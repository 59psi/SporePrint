"""Shared scaffolding for v4.1.1 lighting/HVAC vendor drivers.

Each new vendor in the v4.1.1 batch (Trane / BIOS / Fluence / Quest /
Anden / Fohse / Agrowtek) follows the same shape: an HTTP poller that
hits a vendor REST endpoint on a schedule, normalises the response into
the SporePrint telemetry pipeline. The infrastructure for that
(config + lifespan + tier gate + secret encryption) is already in
place via :mod:`app.integrations._base` and :mod:`._registry` — this
module just provides a thin base class that drivers extend so we don't
re-implement the asyncio task boilerplate seven times.

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
from typing import Any, Awaitable, Callable, ClassVar

from pydantic import BaseModel

from ._base import IntegrationDriver, IntegrationHealth


logger = logging.getLogger(__name__)


class HttpVendorDriver(IntegrationDriver):
    """Base class for "poll vendor REST API on a schedule" drivers.

    Subclasses override :meth:`poll_once` (one HTTP cycle, returns
    rows-written count + diagnostic dict). The base class handles
    asyncio task lifecycle, idempotent start/stop, and the
    `disabled → ok → degraded → error` health transitions.
    """

    name: ClassVar[str]
    tier_required: ClassVar[str] = "premium"
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

    # ── IntegrationDriver lifecycle ────────────────────────────────────

    async def configure(self, config: BaseModel) -> None:
        self._cfg = config

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
        if not self._last_poll_ok:
            return IntegrationHealth(state="error", last_error=self._last_error)
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
        return IntegrationHealth(state="ok")

    # ── Subclass extension points ─────────────────────────────────────

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        """Override: run one HTTP cycle. Return (rows_written,
        diagnostic_dict). Raise on transport / parse errors so the
        loop can record outcome.
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
                await self.poll_once()
                self._record_outcome(True, None)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s poll failed: %s", self.name, exc)
                self._record_outcome(False, str(exc))
            await asyncio.sleep(poll_seconds)

    def _record_outcome(self, ok: bool, error: str | None) -> None:
        self._last_poll_at = time.time()
        self._last_poll_ok = ok
        self._last_error = error

    @property
    def config(self):
        return self._cfg

    @property
    def is_polling(self) -> bool:
        return self._task is not None and not self._task.done()
