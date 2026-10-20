"""Pulse Grow IntegrationDriver implementation (dual transport).

Both transports run free on the Pi: local polls the devices on the LAN,
cloud logs in to api.pulsegrow.com with the operator's own Pulse account
(the password stays on the Pi, encrypted at rest). The poll loop,
start/stop and health come from HttpVendorDriver; this driver supplies one
poll (``poller.run_one_poll``) and the Test.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import BaseModel

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from .._samples import SampleTracker
from .client import PulseCloudClient, PulseError
from .config import PulseConfig
from .local_transport import PulseLocalTransport
from .poller import STALE_FLOOR_SECONDS, run_one_poll


logger = logging.getLogger(__name__)


class PulseDriver(HttpVendorDriver):
    name: ClassVar[str] = "pulse"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = PulseConfig
    secret_fields: ClassVar[set[str]] = {"password"}

    def __init__(self) -> None:
        super().__init__()
        self._cfg: PulseConfig = PulseConfig()
        # Long-lived cloud client (holds the session token between polls).
        self._cloud_client: PulseCloudClient | None = None
        self._cloud_client_key: tuple | None = None
        # The sample each device sensor last stored (see _samples.py).
        self._samples = SampleTracker(STALE_FLOOR_SECONDS)

    def _client_for(self, cfg: PulseConfig) -> PulseCloudClient | None:
        """Cloud transport: reuse one client (and so one session token)
        across polls, rebuilding it only when the credentials change.
        Local transport: None (the poller builds its LAN transport)."""
        if cfg.transport != "cloud" or not cfg.email or not cfg.password:
            return None
        key = (cfg.email, cfg.password, cfg.request_timeout_seconds)
        if self._cloud_client is None or self._cloud_client_key != key:
            self._cloud_client = PulseCloudClient(
                cfg.email, cfg.password, timeout_s=cfg.request_timeout_seconds,
            )
            self._cloud_client_key = key
        return self._cloud_client

    async def configure(self, config: BaseModel) -> None:
        assert isinstance(config, PulseConfig)
        await super().configure(config)

    def _clear_login_refusal(self) -> None:
        # A save of the same credentials keeps the cloud client (and its
        # session token) but lets it try a refused login once more.
        if self._cloud_client is not None:
            self._cloud_client.clear_login_refusal()

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg = self._cfg
        # Local transport can run on its defaults (discovery finds the
        # devices); cloud transport cannot log in without credentials.
        if cfg.transport == "cloud" and (not cfg.email or not cfg.password):
            raise PulseError("email and password are required for cloud transport")
        result = await run_one_poll(cfg, client=self._client_for(cfg), tracker=self._samples)
        # A device whose fetch failed, or whose sample stopped changing, is a
        # failed device: some failing is "degraded", all of them an error.
        return result.written, {
            "rows": result.written,
            "devices": result.devices,
            "failed": result.failed,
        }

    async def test_connection(self) -> IntegrationHealth:
        if self._cfg.transport == "local":
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
