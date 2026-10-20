"""Aranet IntegrationDriver implementation.

The poll loop, start/stop and health come from HttpVendorDriver; this
driver supplies one poll (``poller.run_one_poll``) and the Test.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import BaseModel

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from .._samples import SampleTracker
from .client import AranetClient, AranetError
from .config import AranetConfig
from .poller import STALE_FLOOR_SECONDS, mapped_readings, run_one_poll


logger = logging.getLogger(__name__)


class AranetDriver(HttpVendorDriver):
    name: ClassVar[str] = "aranet"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = AranetConfig
    secret_fields: ClassVar[set[str]] = {"api_key"}
    # api_key goes out as X-API-Key to base_url: a new base_url needs the
    # key re-entered.
    secret_bound_fields: ClassVar[frozenset[str]] = frozenset({"base_url"})

    def __init__(self) -> None:
        super().__init__()
        self._cfg: AranetConfig = AranetConfig()
        # The sample each sensor last stored (see _samples.py).
        self._samples = SampleTracker(STALE_FLOOR_SECONDS)

    async def configure(self, config: BaseModel) -> None:
        assert isinstance(config, AranetConfig)
        await super().configure(config)

    async def test_connection(self) -> IntegrationHealth:
        """Fetch once and count what a poll would store; stores nothing."""
        cfg = self._cfg
        if not cfg.base_url or not cfg.api_key:
            return IntegrationHealth(
                state="error",
                last_error="base_url and api_key are required",
            )
        client = AranetClient(
            cfg.base_url, cfg.api_key, timeout_s=cfg.request_timeout_seconds
        )
        try:
            response = await client.fetch_latest()
        except AranetError as exc:
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(
            state="ok",
            details={
                "sensors_seen": len(response.sensors),
                "readings_seen": len(mapped_readings(response)),
            },
        )

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg = self._cfg
        if not cfg.base_url or not cfg.api_key:
            raise RuntimeError("base_url and api_key are required")
        result = await run_one_poll(cfg, tracker=self._samples)
        # A sensor whose sample stopped changing is reported like a failed
        # device: some stale is "degraded", every one stale is an error.
        return result.written, {
            "rows": result.written,
            "devices": result.devices,
            "failed": result.failed,
        }
