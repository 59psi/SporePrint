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


router = APIRouter()


# ── Listing ────────────────────────────────────────────────────────────


@router.get("")
async def list_integrations() -> list[dict[str, Any]]:
    """One row per registered driver with its persisted state.

    Drivers that have never been configured show `enabled=False` and an
    empty config; the UI renders them as "not yet set up." Secret-field
    values are redacted to a `••••last4` preview.
    """
    stored = {row.slug: row for row in await store.list_all(_secret_fields_map())}
    out: list[dict[str, Any]] = []
    for slug, driver in _drivers.items():
        row = stored.get(slug)
        config = (
            store.redact_for_response(row.config, driver.secret_fields)
            if row is not None
            else {}
        )
        out.append(
            {
                "slug": slug,
                "tier_required": driver.tier_required,
                "enabled": row.enabled if row else False,
                "config": config,
                "health": {
                    "state": row.last_health_state if row else "disabled",
                    "last_error": row.last_error if row else None,
                    "last_checked_at": row.last_health_at if row else None,
                },
            }
        )
    return out


# ── Per-driver config ──────────────────────────────────────────────────


@router.get("/{slug}/config")
async def get_config(slug: str) -> dict[str, Any]:
    driver = _get_driver_or_404(slug)
    row = await store.load(slug, driver.secret_fields)
    config = (
        store.redact_for_response(row.config, driver.secret_fields)
        if row is not None
        else {}
    )
    return {
        "slug": slug,
        "enabled": row.enabled if row else False,
        "config": config,
        "schema": driver.config_schema.model_json_schema(),
    }


@router.put("/{slug}/config")
async def put_config(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist, and apply config in one round-trip.

    Body shape: ``{"enabled": bool, "config": {...}}``.

    - Validates ``config`` against the driver's pydantic schema (400 on
      ValidationError).
    - Calls ``driver.configure()`` with the validated model. A
      ``DriverConfigError`` from the driver also surfaces as 400.
    - Persists encrypted-at-rest.
    - Starts/stops the driver to match ``enabled``.
    """
    driver = _get_driver_or_404(slug)
    enabled = bool(payload.get("enabled", False))
    raw_config = payload.get("config") or {}

    try:
        validated: BaseModel = driver.config_schema.model_validate(raw_config)
    except ValidationError as exc:
        raise HTTPException(400, exc.errors())

    try:
        await driver.configure(validated)
    except DriverConfigError as exc:
        raise HTTPException(400, str(exc))

    await store.save(slug, enabled, validated.model_dump(), driver.secret_fields)

    if enabled:
        await driver.start()
    else:
        await driver.stop()

    return {"slug": slug, "enabled": enabled, "ok": True}


# ── Test + lifecycle ───────────────────────────────────────────────────


@router.post("/{slug}/test")
async def test_connection(slug: str) -> IntegrationHealth:
    driver = _get_driver_or_404(slug)
    health = await driver.test_connection()
    await store.update_health(slug, health)
    return health


@router.post("/{slug}/enable")
async def enable(slug: str) -> dict[str, Any]:
    driver = _get_driver_or_404(slug)
    row = await store.load(slug, driver.secret_fields)
    if row is None:
        raise HTTPException(409, "configure before enabling")
    await store.save(slug, True, row.config, driver.secret_fields)
    await driver.start()
    return {"slug": slug, "enabled": True}


@router.post("/{slug}/disable")
async def disable(slug: str) -> dict[str, Any]:
    driver = _get_driver_or_404(slug)
    row = await store.load(slug, driver.secret_fields)
    if row is not None:
        await store.save(slug, False, row.config, driver.secret_fields)
    await driver.stop()
    return {"slug": slug, "enabled": False}


# ── Lifespan helpers ───────────────────────────────────────────────────


async def start_enabled_drivers() -> None:
    """Boot every driver that is persisted as enabled. Called from
    `main.py`'s lifespan after `init_db()` has run.
    """
    for slug, driver in _drivers.items():
        try:
            row = await store.load(slug, driver.secret_fields)
        except Exception:
            logger.exception("integrations: failed to load %s during startup", slug)
            continue
        if row is None or not row.enabled:
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
