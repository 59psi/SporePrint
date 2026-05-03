"""Grafana driver config schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GrafanaConfig(BaseModel):
    """Knobs for the Prometheus exporter.

    Both fields are optional — the default config exposes `/metrics`
    unauthenticated on the LAN, which matches Prometheus convention and
    works out-of-the-box for users running Grafana Cloud → LAN-Pi via
    Prometheus's `scrape_configs` with a self-hosted scraper.

    Set `bearer_token` to require an `Authorization: Bearer <token>` header
    on each scrape. Useful when the Pi is reachable through Tailscale or
    similar mesh and the operator wants a defence-in-depth check on top of
    network-layer scoping.

    `include_sensor_history` is off by default because Prometheus is built
    for instantaneous gauge samples — historical scrape lag belongs in the
    TSDB, not in the exporter response. Flip on for diagnostics only.
    """

    bearer_token: str = Field(
        default="",
        description=(
            "Optional bearer token. When non-empty, scrapes without a "
            "matching `Authorization: Bearer <token>` header receive a 401."
        ),
    )
    include_actuator_state: bool = Field(
        default=True,
        description="Emit `sporeprint_actuator_event_count` counters.",
    )
    include_contamination_metrics: bool = Field(
        default=True,
        description="Emit `sporeprint_contamination_events_total` counters.",
    )
    include_sensor_history: bool = Field(
        default=False,
        description=(
            "Diagnostic: also emit oldest-fresh-reading age. Off by default."
        ),
    )
