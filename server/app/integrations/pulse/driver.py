"""Pulse Grow IntegrationDriver implementation (dual transport).

The driver itself is registered as ``free`` because the lowest tier it
can run in (local transport — UDP discovery + LAN HTTP polling) does
not touch our cloud. The cloud-web settings UI is responsible for
hiding the cloud-transport option from free-tier users since cloud mode
holds the operator's Pulse credentials and refreshes tokens against
api.pulsegrow.com (premium per ``feedback_tier_model``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import ClassVar

from pydantic import BaseModel

from .._base import IntegrationDriver, IntegrationHealth
from .client import PulseCloudClient, PulseError
from .config import PulseConfig
from .poller import poll_loop, run_one_poll


logger = logging.getLogger(__name__)


class PulseDriver(IntegrationDriver):
    name: ClassVar[str] = "pulse"
    # Lowest tier the driver can run in: free (local transport). Cloud
    # mode is gated by the cloud-web settings UI, not the driver.
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = PulseConfig
    secret_fields: ClassVar[set[str]] = {"password"}

    def __init__(self) -> None:
        self._cfg: PulseConfig = PulseConfig()
        self._task: asyncio.Task | None = None
        self._last_poll_at: float | None = None
        self._last_poll_ok: bool = False
        self._last_error: str | None = None

    async def configure(self, config: BaseModel) -> None:
        assert isinstance(config, PulseConfig)
        self._cfg = config

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
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
        if self._cfg.transport == "local":
            from .local_transport import PulseLocalTransport
            client = PulseLocalTransport(self._cfg)
            try:
                devices = await client.list_devices()
            except PulseError as exc:
                return IntegrationHealth(state="error", last_error=str(exc))
            return IntegrationHealth(
                state="ok",
                details={
                    "transport": "local",
                    "devices_seen": len(devices.devices),
                },
            )

        # Cloud transport
        if not self._cfg.email or not self._cfg.password:
            return IntegrationHealth(
                state="error",
                last_error="email and password are required for cloud transport",
            )
        client = PulseCloudClient(
            self._cfg.email,
            self._cfg.password,
            timeout_s=self._cfg.request_timeout_seconds,
        )
        try:
            await client.login()
            devices = await client.list_devices()
        except PulseError as exc:
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(
            state="ok",
            details={
                "transport": "cloud",
                "devices_seen": len(devices.devices),
            },
        )

    async def health(self) -> IntegrationHealth:
        if self._task is None:
            return IntegrationHealth(state="disabled")
        if self._last_poll_at is None:
            return IntegrationHealth(state="ok")
        if not self._last_poll_ok:
            return IntegrationHealth(state="error", last_error=self._last_error)
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

    def _record_outcome(self, ok: bool, error: str | None) -> None:
        self._last_poll_at = time.time()
        self._last_poll_ok = ok
        self._last_error = error

    @property
    def config(self) -> PulseConfig:
        return self._cfg

    @property
    def is_polling(self) -> bool:
        return self._task is not None and not self._task.done()
