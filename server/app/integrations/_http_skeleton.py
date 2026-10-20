"""Shared scaffolding for the polling vendor drivers.

Every driver that polls a vendor on a schedule (Aranet, Pulse, the
lighting/HVAC batch — Trane / BIOS / Fluence / Quest / Anden / Fohse /
Agrowtek — and the Wemo / Kasa / Tapo plugs) follows the same shape: a
poller that reads the vendor's devices and stores the readings in
telemetry history. The infrastructure for that (config + lifespan +
secret encryption) is already in place via :mod:`app.integrations._base`
and :mod:`._registry` — this module provides the one base class they
extend for the poll loop, start/stop and health, so a fix there reaches
every one of them.

⚠ **Live-device verification needed.** Every driver in the v4.1.1
batch has been written against vendor documentation only. Tolerant
pydantic models accept payload-shape variance, ``test_connection``
surfaces transport errors verbatim, and the parsing layer degrades to
empty rather than crashing the poll. Refinements based on real
hardware will be additive — the framework's stable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar, NoReturn

import httpx
from pydantic import BaseModel

from ._base import IntegrationDriver, IntegrationHealth


logger = logging.getLogger(__name__)

# Longest per-device failure summary kept for health(): it is shown under the
# status pill and forwarded to the cloud with the health transition.
_MAX_FAILURE_SUMMARY = 500


def _failure_summary(failed: dict[str, str], total: int) -> str:
    """``"2 of 3 devices failed: 10.0.0.5: refused; …"``, truncated."""
    text = f"{len(failed)} of {total} devices failed: " + "; ".join(
        f"{device}: {error}" for device, error in failed.items()
    )
    if len(text) > _MAX_FAILURE_SUMMARY:
        text = text[: _MAX_FAILURE_SUMMARY - 1] + "…"
    return text


class HttpVendorDriver(IntegrationDriver):
    """Base class for "poll vendor REST API on a schedule" drivers.

    Subclasses override :meth:`poll_once` (one HTTP cycle, returns
    rows-written count + diagnostic dict). The base class handles
    asyncio task lifecycle, idempotent start/stop, and the
    `disabled → ok → degraded → error` health transitions, including the
    per-device outcome a multi-device poll reports (see :meth:`poll_once`).
    """

    name: ClassVar[str]
    # The Pi has no paygate: every driver runs free on it, including the ones
    # that talk to a vendor's cloud with the operator's own credentials.
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]]
    secret_fields: ClassVar[set[str]] = set()
    # Subclasses can override the stale-after multiplier if their poll
    # cadence is more or less variable than 3× interval.
    stale_after_multiplier: ClassVar[float] = 3.0

    def __init__(self) -> None:
        self._cfg: BaseModel | None = None
        self._task: asyncio.Task | None = None
        self._last_poll_at: float | None = None
        self._last_poll_ok: bool = False
        self._last_error: str | None = None
        # Devices that failed in the last poll, {device: error}. Some of them
        # failing makes health "degraded"; all of them failing is an error.
        self._failed_devices: dict[str, str] = {}

    # ── IntegrationDriver lifecycle ────────────────────────────────────

    async def configure(self, config: BaseModel) -> None:
        previous = self._cfg
        self._cfg = config
        if previous is not None and previous != config:
            # Settings changed (possibly a different account / rotated
            # password): never keep acting with auth minted for the old one.
            self._reset_auth()
        # Every save (and the saved config applied before a Test) is the
        # operator's go-ahead to try the credentials again, changed or not.
        self._clear_login_refusal()

    def _reset_auth(self) -> None:
        """Hook: drop cached vendor auth (bearer tokens, sessions) after a
        config change. Drivers that cache auth state override this."""

    def _clear_login_refusal(self) -> None:
        """Hook: forget a remembered login refusal (see BearerLoginDriver).
        Drivers that stop retrying refused credentials override this."""

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def health(self) -> IntegrationHealth:
        if self._task is None:
            return IntegrationHealth(state="disabled")
        if self._last_poll_at is None:
            return IntegrationHealth(state="ok")
        details: dict[str, Any] = (
            {"failed": dict(self._failed_devices)} if self._failed_devices else {}
        )
        if not self._last_poll_ok:
            return IntegrationHealth(
                state="error", last_error=self._last_error, details=details
            )
        if self._cfg is not None:
            poll_seconds = getattr(self._cfg, "poll_seconds", 60)
            stale_after = poll_seconds * self.stale_after_multiplier
            if (time.time() - self._last_poll_at) > stale_after:
                return IntegrationHealth(
                    state="degraded",
                    last_error=(
                        f"no successful poll in {stale_after:.0f}s "
                        "(loop may be hung; restart the driver)"
                    ),
                )
        if self._failed_devices:
            return IntegrationHealth(
                state="degraded", last_error=self._last_error, details=details
            )
        return IntegrationHealth(state="ok")

    # ── Subclass extension points ─────────────────────────────────────

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        """Override: run one HTTP cycle. Return (rows_written,
        diagnostic_dict). Raise on transport / parse errors — and when
        the driver is enabled without the settings it needs to poll — so
        the loop can record outcome.

        A driver that polls several devices keeps going past a device
        that fails and reports it instead: ``diag["failed"]`` maps each
        failed device to its error and ``diag["devices"]`` is how many it
        polled. The loop records the poll as an error when every device
        failed and as ``degraded`` when only some did, so an unplugged
        plug shows up in health (and in the cloud's health alerts)
        instead of the poll reporting ``ok``.
        """
        raise NotImplementedError

    # ── Internals ──────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while True:
            cfg = self._cfg
            if cfg is None:
                await asyncio.sleep(60)
                continue
            poll_seconds = getattr(cfg, "poll_seconds", 60)
            try:
                _rows, diag = await self.poll_once()
                self._record_poll(diag)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s poll failed: %s", self.name, exc)
                self._record_outcome(False, str(exc))
            await asyncio.sleep(poll_seconds)

    def _record_poll(self, diag: Any) -> None:
        """Record a poll that returned, from its per-device outcome."""
        failed = diag.get("failed") if isinstance(diag, dict) else None
        if not failed:
            self._record_outcome(True, None)
            return
        total = max(int(diag.get("devices") or 0), len(failed))
        summary = _failure_summary(failed, total)
        logger.warning("%s poll: %s", self.name, summary)
        self._record_outcome(len(failed) < total, summary, failed=failed)

    def _record_outcome(
        self, ok: bool, error: str | None, failed: dict[str, str] | None = None
    ) -> None:
        self._last_poll_at = time.time()
        self._last_poll_ok = ok
        self._last_error = error
        self._failed_devices = dict(failed or {})

    @property
    def config(self):
        return self._cfg

    @property
    def is_polling(self) -> bool:
        return self._task is not None and not self._task.done()


class CredentialsRejected(RuntimeError):
    """The vendor refused the configured credentials.

    Remembered until the settings are saved again (or a Test logs in), so
    the driver does not keep sending a password the vendor has refused.
    """


class BearerLoginDriver(HttpVendorDriver):
    """HttpVendorDriver for a vendor cloud that trades the operator's email
    and password for a bearer token (``POST {api_base}/auth/login``):
    Trane, Fluence and Fohse.

    * A request that gets 401 (the token expired) drops the token, logs in
      once more and repeats the request once, so a token expiry costs
      neither a poll nor a write.
    * A login the vendor refuses (401, or a reply without a token) is
      remembered for the current settings: polls and writes then fail at
      once with the vendor's answer instead of sending the same password
      every poll, which can lock the vendor account. Saving the settings
      again (changed or not) clears it, and a Test always logs in.
    * A login that started before the settings changed never installs its
      token afterwards (an equal re-save keeps the token).

    The config schema must have ``email``, ``password`` and
    ``request_timeout_seconds``.
    """

    vendor_label: ClassVar[str]
    api_base: ClassVar[str]

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None
        self._auth_rejected: str | None = None

    def _reset_auth(self) -> None:
        self._token = None
        self._auth_rejected = None

    def _clear_login_refusal(self) -> None:
        self._auth_rejected = None

    def _require_credentials(self) -> Any:
        """The current config, or a RuntimeError when it lacks credentials."""
        cfg = self._cfg
        if cfg is None or not getattr(cfg, "email", "") or not getattr(cfg, "password", ""):
            raise RuntimeError(f"{self.vendor_label}: email and password are required")
        return cfg

    def _reject(self, cfg: Any, message: str) -> NoReturn:
        if self._cfg == cfg:
            self._auth_rejected = message
        raise CredentialsRejected(message)

    async def _login(self, cfg: Any, *, retry_rejected: bool = False) -> str:
        """Log in with ``cfg``'s credentials and return the token.

        ``retry_rejected`` (an operator's Test) logs in even after the
        vendor refused these credentials; nothing else does.
        """
        if self._auth_rejected is not None and not retry_rejected:
            raise CredentialsRejected(self._auth_rejected)
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.post(
                f"{self.api_base}/auth/login",
                json={"email": cfg.email, "password": cfg.password},
            )
        if resp.status_code == 401:
            self._reject(
                cfg,
                f"{self.vendor_label}: 401 unauthorized — check email + password "
                "(not retried until they are saved again)",
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"{self.vendor_label}: HTTP {resp.status_code} on login")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{self.vendor_label}: non-JSON login response: {exc}"
            ) from exc
        token = (body.get("token") or body.get("access_token")) if isinstance(body, dict) else None
        if not token or not isinstance(token, str):
            self._reject(
                cfg,
                f"{self.vendor_label}: login succeeded but no token in response "
                "(not retried until the credentials are saved again)",
            )
        if self._cfg == cfg:
            self._token = token
            self._auth_rejected = None
        return token

    async def _authed_request(
        self, cfg: Any, method: str, url: str, *, body: Any = None
    ) -> httpx.Response:
        """``GET``/``PUT`` ``url`` with the bearer token, logging in first if
        there is none; on 401 log in again and repeat the request once."""
        token = self._token or await self._login(cfg)
        resp = await self._send(cfg, method, url, token, body)
        if resp.status_code != 401:
            return resp
        if self._token == token:
            self._token = None
        token = await self._login(cfg)
        resp = await self._send(cfg, method, url, token, body)
        if resp.status_code == 401:
            raise RuntimeError(
                f"{self.vendor_label}: 401 on {method} {httpx.URL(url).path} "
                "right after a fresh login"
            )
        return resp

    @staticmethod
    async def _send(
        cfg: Any, method: str, url: str, token: str, body: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            if method == "GET":
                return await client.get(url, headers=headers)
            if method == "PUT":
                return await client.put(url, headers=headers, json=body)
        raise ValueError(f"unsupported method {method!r}")
