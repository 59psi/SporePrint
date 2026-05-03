"""Grafana exporter driver — wires the registry framework to the route.

Mostly stateless. `start()` flips an `enabled` flag the route reads on
every scrape; there are no asyncio tasks to manage. `health()` returns
``ok`` when configured, ``disabled`` otherwise.
"""

from __future__ import annotations

import time
from typing import ClassVar

from pydantic import BaseModel

from .._base import IntegrationDriver, IntegrationHealth
from .config import GrafanaConfig


class GrafanaDriver(IntegrationDriver):
    name: ClassVar[str] = "grafana"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = GrafanaConfig
    secret_fields: ClassVar[set[str]] = {"bearer_token"}

    def __init__(self) -> None:
        self._cfg: GrafanaConfig = GrafanaConfig()
        self._enabled: bool = False
        self._last_scrape_at: float | None = None
        self._last_scrape_ok: bool = False
        self._last_error: str | None = None

    # ── IntegrationDriver lifecycle ────────────────────────────────────

    async def configure(self, config: BaseModel) -> None:
        assert isinstance(config, GrafanaConfig)
        self._cfg = config

    async def start(self) -> None:
        self._enabled = True

    async def stop(self) -> None:
        self._enabled = False

    async def test_connection(self) -> IntegrationHealth:
        # The "test" for an exporter is "can we render samples?" — we
        # synthesise a render against the live DB. If it errors, surface
        # that to the operator before they wire up Prometheus.
        from .exporter import collect_samples
        try:
            payload = await collect_samples(self._cfg, version="test")
        except Exception as exc:  # noqa: BLE001 — surfaced to operator
            self._last_error = str(exc)
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(
            state="ok",
            details={"sample_bytes": len(payload)},
        )

    async def health(self) -> IntegrationHealth:
        if not self._enabled:
            return IntegrationHealth(state="disabled")
        if self._last_scrape_at is None:
            # Enabled but never scraped — not yet a problem; Prometheus
            # may not be deployed yet.
            return IntegrationHealth(state="ok")
        if not self._last_scrape_ok:
            return IntegrationHealth(state="error", last_error=self._last_error)
        return IntegrationHealth(state="ok")

    # ── Used by the /metrics route handler ─────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def config(self) -> GrafanaConfig:
        return self._cfg

    def record_scrape(self, ok: bool, error: str | None = None) -> None:
        self._last_scrape_at = time.time()
        self._last_scrape_ok = ok
        self._last_error = error
