"""Grafana driver config schema."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
    TSDB, not in the exporter response. Flip on for diagnostics: it adds
    `sporeprint_node_reading_timestamp_seconds`, the time of each exported
    reading, so a dashboard can show how old each value is.
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
            "Diagnostic: also emit `sporeprint_node_reading_timestamp_seconds`, "
            "the time of each exported reading. Off by default."
        ),
    )

    @field_validator("bearer_token")
    @classmethod
    def _token_is_text(cls, v: str) -> str:
        # JSON can carry an unpaired surrogate ("\ud800"). UTF-8 cannot encode
        # it, so the token could not be stored encrypted, and no scraper could
        # ever send it in an Authorization header.
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("bearer_token must be plain text") from None
        return v
