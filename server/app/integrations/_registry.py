"""Driver registry + the unified `/api/integrations/*` HTTP surface.

Drivers register themselves at import time via `register(DriverCls)`; the
v4.1 `app/integrations/__init__.py` aggregator walks the per-vendor
sub-packages so a fresh process boots with every shipped driver in the
table. The router mounts in `main.py` under `/api/integrations`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from . import _settings_store as store
from ._base import (
    DriverConfigError,
    IntegrationDriver,
    IntegrationHealth,
)


logger = logging.getLogger(__name__)


# Slug → driver instance. Each driver is a singleton inside one Pi process.
_drivers: dict[str, IntegrationDriver] = {}


def register(driver: IntegrationDriver) -> None:
    """Register a driver instance under its `name` slug.

    Called at module-import time by each vendor sub-package. Re-registering
    the same slug raises — drivers must not be silently shadowed.
    """
    slug = driver.name
    if slug in _drivers:
        raise RuntimeError(f"integration driver {slug!r} already registered")
    _drivers[slug] = driver
    logger.debug("integrations: registered driver %s", slug)


def registered_drivers() -> dict[str, IntegrationDriver]:
    """Read-only view of the slug → driver map (for tests + lifespan)."""
    return dict(_drivers)


def _get_driver_or_404(slug: str) -> IntegrationDriver:
    driver = _drivers.get(slug)
    if driver is None:
        raise HTTPException(404, f"integration {slug!r} not registered")
    return driver


def _secret_fields_map() -> dict[str, set[str]]:
    return {slug: drv.secret_fields for slug, drv in _drivers.items()}


def _merge_unchanged_secrets(
    raw_config: dict[str, Any],
    stored_config: dict[str, Any],
    secret_fields: set[str],
    unreadable: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], set[str], frozenset[str]]:
    """Resolve "unchanged" secret values in an incoming config against the
    stored (decrypted) config.

    GET redacts secrets to a ``••••<fingerprint>`` preview; a form that PUTs
    the whole config back (or a cloud-web get_config → put_config round-trip)
    must not store that preview as the credential. Rules per secret field:

    - omitted              → keep the stored value
    - the preview of the stored value → keep the stored value
    - a secret that no longer decrypts, omitted or sent back as GET shows it
      (``••••``) → keep its stored ciphertext as it is
    - any other ``••••…`` value → 400 (stale preview of a different secret)
    - ``""``               → explicit clear
    - anything else        → the new secret

    Returns the merged config, the names of the secrets that were kept from
    storage (the caller checks those against secret_bound_fields), and the
    kept ones whose ciphertext no longer decrypts (store.save preserves it;
    the merged config holds ``""`` for them).
    """
    merged = dict(raw_config)
    kept: set[str] = set()
    preserved: set[str] = set()
    for name in secret_fields:
        stored = stored_config.get(name)
        value = merged.get(name)
        if name in unreadable and (
            name not in merged or value == store.UNREADABLE_SECRET_PLACEHOLDER
        ):
            merged[name] = ""
            kept.add(name)
            preserved.add(name)
            continue
        if name not in merged:
            if stored not in (None, ""):
                merged[name] = stored
                kept.add(name)
            continue
        if isinstance(value, str) and value.startswith(store.REDACTED_PREFIX):
            stored_preview = (
                store.secret_preview(stored)
                if isinstance(stored, str) and stored
                else None
            )
            if stored_preview is None or value != stored_preview:
                raise HTTPException(
                    400,
                    f"{name}: the masked value does not match the stored secret — "
                    "re-enter it",
                )
            merged[name] = stored
            kept.add(name)
    return merged, kept, frozenset(preserved)


def _bound_values(driver: IntegrationDriver, config: dict[str, Any]) -> dict[str, Any]:
    """The driver's secret_bound_fields as the schema normalises them.

    A stored row is re-validated so one saved before a normaliser existed
    (e.g. base_url with a trailing slash) still compares equal; a row that no
    longer validates is compared as stored.
    """
    try:
        config = driver.config_schema.model_validate(config).model_dump()
    except ValidationError:
        pass
    return {name: config.get(name) for name in driver.secret_bound_fields}


def _refuse_rebound_secrets(
    driver: IntegrationDriver,
    validated: BaseModel,
    stored_config: dict[str, Any],
    kept: set[str],
) -> None:
    """422 when a kept (not re-entered) secret would go to a new destination.

    Only a non-empty new value counts: a blank base_url sends the secret
    nowhere, and the next non-blank one is compared against that blank.
    """
    if not kept or not driver.secret_bound_fields:
        return
    old = _bound_values(driver, stored_config)
    new = _bound_values(driver, validated.model_dump())
    changed = sorted(name for name in new if new[name] and new[name] != old[name])
    if changed:
        secrets = ", ".join(sorted(kept))
        fields = ", ".join(changed)
        raise HTTPException(
            422,
            f"re-enter {secrets} to change {fields}: a stored secret is only "
            f"reused for the {fields} it was entered for, never sent to a new one",
        )


def _refuse_unstorable_secrets(config: dict[str, Any], secret_fields: set[str]) -> None:
    """400 for a secret UTF-8 cannot encode.

    JSON can carry an unpaired surrogate ("\\ud800"). Such a secret cannot be
    encrypted for storage, so the save failed only after the driver had been
    handed the new config: refuse it before the driver sees anything.
    """
    for name in sorted(secret_fields):
        value = config.get(name)
        if not isinstance(value, str):
            continue
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(
                400, f"{name} must be plain text: it contains characters that cannot be stored"
            ) from None


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """A ValidationError's errors as JSON-safe dicts for a 400 detail.

    A custom validator's ValueError rides in each error's ``ctx``, which the
    JSON response cannot serialize: every such rejection (a base_url without
    a scheme, a malformed email or device ip) was a 500 instead of the 400
    carrying its message, which ``msg`` keeps. The input is left out too, so
    a rejected config's values (secrets included) are not echoed back.
    """
    return exc.errors(include_url=False, include_context=False, include_input=False)


def _validate_config(driver: IntegrationDriver, raw_config: Any) -> BaseModel:
    """Validate ``raw_config`` against the driver schema (400 on error)."""
    try:
        return driver.config_schema.model_validate(raw_config)
    except ValidationError as exc:
        raise HTTPException(400, _validation_errors(exc))


async def _configure(driver: IntegrationDriver, validated: BaseModel) -> None:
    """Push a validated config into the driver (DriverConfigError → 400)."""
    try:
        await driver.configure(validated)
    except DriverConfigError as exc:
        raise HTTPException(400, str(exc))


async def _apply_config(driver: IntegrationDriver, raw_config: Any) -> BaseModel:
    """Validate ``raw_config`` against the driver schema and push it into the
    driver. ValidationError / DriverConfigError surface as HTTP 400."""
    validated = _validate_config(driver, raw_config)
    await _configure(driver, validated)
    return validated


router = APIRouter()


# ── Listing ────────────────────────────────────────────────────────────


async def _current_health(
    driver: IntegrationDriver, row: store.StoredSettings | None,
) -> dict[str, Any]:
    """The health a listing shows: the driver's own (live) state.

    The persisted last_health_* is only the last Test's result, so it never
    showed a poll failing after a good Test, nor a disabled driver as
    disabled. It still wins in two cases the driver cannot see: a stored
    secret that no longer decrypts, and a row saved as enabled whose driver
    is not running (it failed to start at boot). last_checked_at stays the
    time of the last Test.
    """
    try:
        live = await driver.health()
    except Exception:  # noqa: BLE001 — a listing must not fail on one driver
        logger.exception("integrations: %s.health() raised", driver.name)
        live = None
    state = live.state if live is not None else None
    last_error = live.last_error if live is not None else None
    if row is not None and row.unreadable_secrets:
        state, last_error = "error", store.UNREADABLE_SECRET_ERROR
    elif row is not None and row.enabled and state in (None, "disabled"):
        state = "error"
        last_error = "saved as enabled but not running — save the settings again to start it"
    elif state is None:
        state = row.last_health_state if row else "disabled"
        last_error = row.last_error if row else None
    return {
        "state": state,
        "last_error": last_error,
        "last_checked_at": row.last_health_at if row else None,
    }


@router.get("")
async def list_integrations() -> list[dict[str, Any]]:
    """One row per registered driver with its persisted config and live
    health.

    Drivers that have never been configured show `enabled=False` and an
    empty config; the UI renders them as "not yet set up." Secret-field
    values are redacted to a ``••••<fingerprint>`` preview.
    """
    stored = {row.slug: row for row in await store.list_all(_secret_fields_map())}
    out: list[dict[str, Any]] = []
    for slug, driver in _drivers.items():
        row = stored.get(slug)
        config = (
            store.redact_for_response(row.config, driver.secret_fields, row.unreadable_secrets)
            if row is not None
            else {}
        )
        out.append(
            {
                "slug": slug,
                "tier_required": driver.tier_required,
                "enabled": row.enabled if row else False,
                "config": config,
                "health": await _current_health(driver, row),
            }
        )
    return out


# ── Per-driver config ──────────────────────────────────────────────────


@router.get("/{slug}/config")
async def get_config(slug: str) -> dict[str, Any]:
    driver = _get_driver_or_404(slug)
    row = await store.load(slug, driver.secret_fields)
    config = (
        store.redact_for_response(row.config, driver.secret_fields, row.unreadable_secrets)
        if row is not None
        else {}
    )
    return {
        "slug": slug,
        "enabled": row.enabled if row else False,
        "config": config,
        "schema": driver.config_schema.model_json_schema(),
    }


class _ConfigBody(BaseModel):
    """PUT /{slug}/config body.

    ``enabled`` is a lax bool (true/false, on/off, 1/0, also as strings);
    anything else is a 400 — ``bool("false")`` used to read the string
    "false" as true. An omitted ``enabled`` or ``config`` keeps what is
    stored, rather than disabling the driver or resetting every field to
    its default.
    """

    enabled: bool | None = None
    config: dict[str, Any] | None = None


@router.put("/{slug}/config")
async def put_config(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist, and apply config in one round-trip.

    Body shape: ``{"enabled": bool, "config": {...}}`` (see _ConfigBody).

    - Validates ``config`` against the driver's pydantic schema (400 on
      ValidationError), and refuses a secret that cannot be stored (400).
    - Keeps an omitted / masked secret only while the driver's
      ``secret_bound_fields`` are unchanged (422 otherwise), checked before
      the driver sees the config. A kept secret that no longer decrypts
      keeps its ciphertext, and the driver is not started without it (409).
    - Calls ``driver.configure()`` with the validated model. A
      ``DriverConfigError`` from the driver also surfaces as 400.
    - Persists encrypted-at-rest. If that fails, the driver goes back to
      the config it had, so it never runs settings that were not saved.
    - Starts/stops the driver to match ``enabled``.
    """
    driver = _get_driver_or_404(slug)
    try:
        body = _ConfigBody.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(400, _validation_errors(exc))

    existing = await store.load(slug, driver.secret_fields)
    stored_config = existing.config if existing else {}
    unreadable = existing.unreadable_secrets if existing else frozenset()
    enabled = body.enabled if body.enabled is not None else bool(existing and existing.enabled)
    if body.config is not None:
        raw_config = body.config
    else:
        # Keep the stored config; its secrets count as omitted (kept).
        raw_config = {k: v for k, v in stored_config.items() if k not in driver.secret_fields}

    kept: set[str] = set()
    preserve: frozenset[str] = frozenset()
    if driver.secret_fields:
        raw_config, kept, preserve = _merge_unchanged_secrets(
            raw_config, stored_config, driver.secret_fields, unreadable,
        )

    validated = _validate_config(driver, raw_config)
    _refuse_unstorable_secrets(validated.model_dump(), driver.secret_fields)
    _refuse_rebound_secrets(driver, validated, stored_config, kept)
    if enabled and preserve:
        raise HTTPException(
            409,
            f"{', '.join(sorted(preserve))}: {store.UNREADABLE_SECRET_ERROR} "
            "before enabling",
        )
    previous = getattr(driver, "config", None)
    await _configure(driver, validated)

    try:
        await store.save(
            slug, enabled, validated.model_dump(), driver.secret_fields, preserve=preserve,
        )
    except Exception:
        if previous is not None:
            try:
                await driver.configure(previous)
            except Exception:  # noqa: BLE001 — the save error is the one to report
                logger.exception("integrations: %s could not go back to its config", slug)
        raise

    if enabled:
        await driver.start()
    else:
        await driver.stop()

    await _push_state_snapshot_safe()
    return {"slug": slug, "enabled": enabled, "ok": True}


# ── Test + lifecycle ───────────────────────────────────────────────────


async def apply_stored_config(slug: str) -> None:
    """Push the stored config into the driver before a one-shot call.

    Only enabled rows are configured at boot, so after a restart a driver
    saved as disabled still holds its constructor defaults: Test, Aranet
    Discover and the Pulse device list then ran against an empty config
    ("base_url required" for a saved base_url, and Test persisted that).
    Nothing stored leaves the driver as it is; a stored secret that no
    longer decrypts is a 409 (the call would run without it).
    """
    driver = _get_driver_or_404(slug)
    row = await store.load(slug, driver.secret_fields)
    if row is None:
        return
    if row.unreadable_secrets:
        raise HTTPException(409, store.UNREADABLE_SECRET_ERROR)
    await _apply_config(driver, row.config)


@router.post("/{slug}/test")
async def test_connection(slug: str) -> IntegrationHealth:
    driver = _get_driver_or_404(slug)
    await apply_stored_config(slug)
    health = await driver.test_connection()
    await store.update_health(slug, health)
    return health


@router.post("/{slug}/enable")
async def enable(slug: str) -> dict[str, Any]:
    driver = _get_driver_or_404(slug)
    row = await store.load(slug, driver.secret_fields)
    if row is None:
        raise HTTPException(409, "configure before enabling")
    if row.unreadable_secrets:
        # Fail closed: started with the secret blanked, Grafana would serve
        # /metrics with no bearer check at all.
        raise HTTPException(409, store.UNREADABLE_SECRET_ERROR)
    # Apply the STORED config before starting. After a restart a driver that
    # was persisted disabled still holds its constructor defaults (only
    # enabled rows are configured at boot), so starting it bare would serve
    # e.g. Grafana /metrics without its bearer token, or poll an empty URL.
    await _apply_config(driver, row.config)
    # Only the flag: re-saving the config would rewrite every secret.
    await store.set_enabled(slug, True)
    await driver.start()
    await _push_state_snapshot_safe()
    return {"slug": slug, "enabled": True}


@router.post("/{slug}/disable")
async def disable(slug: str) -> dict[str, Any]:
    driver = _get_driver_or_404(slug)
    # Only the flag: a secret that no longer decrypts keeps its ciphertext,
    # so it is still there if the original key file comes back.
    await store.set_enabled(slug, False)
    await driver.stop()
    await _push_state_snapshot_safe()
    return {"slug": slug, "enabled": False}


async def _push_state_snapshot_safe() -> None:
    """Best-effort snapshot push. Imported lazily so the registry
    doesn't depend on the sweeper at import time (the sweeper depends
    on the registry — avoiding a cycle).
    """
    try:
        from ._health_sweeper import push_state_snapshot
        await push_state_snapshot()
    except Exception:
        # Cloud connector may not be configured; that's fine.
        pass


# ── Lifespan helpers ───────────────────────────────────────────────────


async def start_enabled_drivers() -> None:
    """Boot every driver that is persisted as enabled. Called from
    `main.py`'s lifespan after `init_db()` has run.

    A driver with a stored secret that no longer decrypts (integration key
    lost or replaced) stays down until the secret is re-entered: started
    with it blanked, Grafana would serve /metrics with no bearer check.
    """
    for slug, driver in _drivers.items():
        try:
            row = await store.load(slug, driver.secret_fields)
        except Exception:
            logger.exception("integrations: failed to load %s during startup", slug)
            continue
        if row is None or not row.enabled:
            continue
        if row.unreadable_secrets:
            # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure — logs field names only, never a secret value
            logger.error(
                "integrations: %s not started — stored secret(s) %s could not be "
                "decrypted; re-enter them",
                slug, sorted(row.unreadable_secrets),
            )
            continue
        try:
            validated = driver.config_schema.model_validate(row.config)
            await driver.configure(validated)
            await driver.start()
        except Exception:
            logger.exception(
                "integrations: %s failed to start; staying down until re-saved",
                slug,
            )


async def stop_all_drivers() -> None:
    for slug, driver in _drivers.items():
        try:
            await driver.stop()
        except Exception:
            logger.exception("integrations: %s failed to stop cleanly", slug)
