"""Aranet IntegrationDriver implementation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import ClassVar

from pydantic import BaseModel

from .._base import IntegrationDriver, IntegrationHealth
from .client import AranetClient, AranetError
from .config import AranetConfig
from .poller import poll_loop, run_one_poll


logger = logging.getLogger(__name__)


class AranetDriver(IntegrationDriver):
    name: ClassVar[str] = "aranet"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = AranetConfig
    secret_fields: ClassVar[set[str]] = {"api_key"}

    def __init__(self) -> None:
        self._cfg: AranetConfig = AranetConfig()
        self._task: asyncio.Task | None = None
        self._last_poll_at: float | None = None
        self._last_poll_ok: bool = False
        self._last_error: str | None = None

    async def configure(self, config: BaseModel) -> None:
        assert isinstance(config, AranetConfig)
        self._cfg = config

    async def start(self) -> None:
        # Idempotent — calling start() twice doesn't spawn a second task.
        if self._task is not None and not self._task.done():
            return
        if not self._cfg.base_url or not self._cfg.api_key:
            # Persisted-enabled but no creds yet (UI flow: enable first,
            # then PUT config). Start a noop loop that picks up creds on
            # the next config write.
            pass
        self._task = asyncio.create_task(
            poll_loop(
                lambda: self._cfg,
                record_outcome=self._record_outcome,
            )
        )

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

    async def test_connection(self) -> IntegrationHealth:
        if not self._cfg.base_url or not self._cfg.api_key:
            return IntegrationHealth(
                state="error",
                last_error="base_url and api_key are required",
            )
        client = AranetClient(
            self._cfg.base_url,
            self._cfg.api_key,
            timeout_s=self._cfg.request_timeout_seconds,
        )
        try:
            written, response = await run_one_poll(
                self._cfg, client=client
            )
        except AranetError as exc:
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(
            state="ok",
            details={
                "sensors_seen": len(response.sensors),
                "rows_written": written,
            },
        )

    async def health(self) -> IntegrationHealth:
        if self._task is None:
            return IntegrationHealth(state="disabled")
        if self._last_poll_at is None:
            return IntegrationHealth(state="ok")
        if not self._last_poll_ok:
            return IntegrationHealth(state="error", last_error=self._last_error)
        # Stale freshness check: if the last successful poll is older
        # than 3× the configured interval, surface ``degraded`` so the
        # operator notices a silent task hang.
        stale_after = self._cfg.poll_seconds * 3
        if (time.time() - self._last_poll_at) > stale_after:
            return IntegrationHealth(
                state="degraded",
                last_error=(
                    f"no successful poll in {stale_after}s "
                    "(loop may be hung; restart the driver)"
                ),
            )
        return IntegrationHealth(state="ok")

    # ── Internal ───────────────────────────────────────────────────────

    def _record_outcome(self, ok: bool, error: str | None) -> None:
        self._last_poll_at = time.time()
        self._last_poll_ok = ok
        self._last_error = error

    @property
    def config(self) -> AranetConfig:
        return self._cfg

    @property
    def is_polling(self) -> bool:
        return self._task is not None and not self._task.done()
