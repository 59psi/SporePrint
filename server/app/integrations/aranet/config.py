"""Aranet driver config schema."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class AranetConfig(BaseModel):
    """Connection + sensor-mapping config for the Aranet PRO poller.

    `base_url` is the LAN HTTP/HTTPS root of the PRO base station — e.g.
    ``http://10.0.0.42`` or ``http://aranet-pro.local``. Trailing slashes
    and `/api/v1/...` suffixes are stripped on save so the driver builds
    request URLs from a normalised root.

    `api_key` is minted in the PRO web UI under Admin → API. The driver
    sends it as ``X-API-Key: <key>`` on every request.

    `sensor_mappings` maps each Aranet sensor's ID (UUID-ish strings the
    PRO returns under ``sensors[].id``) to a chamber id (string). Mapped
    sensors get their readings published into the SporePrint telemetry
    pipeline as if they came from a native node ``aranet:<sensor_id>``.
    Unmapped sensors are still polled but their readings are tagged with
    chamber ``""`` and skipped by automation rules.

    `poll_seconds` — Aranet sensors radio every ~10 minutes anyway, so
    polling faster than ~60s wastes Pi cycles. Default 60 s; floor 30 s
    to leave headroom for the PRO's own internal API rate limits.
    """

    base_url: str = Field(
        default="",
        description=(
            "LAN HTTP root of the Aranet PRO base station. Empty = driver "
            "stays disabled. Example: http://10.0.0.42"
        ),
    )
    api_key: str = Field(
        default="",
        description=(
            "API key from the PRO admin UI. Sent as X-API-Key header. "
            "Empty = driver stays disabled."
        ),
    )
    poll_seconds: int = Field(
        default=60,
        ge=30,
        le=3600,
        description=(
            "How often to poll the PRO. Floor 30 s (PRO rate limits); "
            "ceiling 1 h."
        ),
    )
    sensor_mappings: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Aranet sensor id → SporePrint chamber id. Sensors not "
            "mapped here are polled but tagged with chamber ''."
        ),
    )
    request_timeout_seconds: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="HTTP request timeout per poll.",
    )

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, v: str) -> str:
        if not v:
            return ""
        v = v.strip().rstrip("/")
        # Strip a trailing /api/... so users can paste either the root or
        # the example endpoint URL from the PRO docs.
        if "/api" in v:
            v = v.split("/api", 1)[0]
        # Validate scheme + host now so bad input fails on save, not on
        # first poll. We don't validate that the host is RFC1918 because
        # users may legitimately use an mDNS or Tailscale hostname.
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must start with http:// or https://")
        if not parsed.netloc:
            raise ValueError("base_url must include a host")
        return v
