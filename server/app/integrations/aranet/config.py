"""Aranet driver config schema."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class AranetConfig(BaseModel):
    """Connection config for the Aranet PRO poller.

    `base_url` is the LAN HTTP/HTTPS root of the PRO base station — e.g.
    ``http://10.0.0.42`` or ``http://aranet-pro.local``. Trailing slashes
    and `/api/v1/...` suffixes are stripped on save so the driver builds
    request URLs from a normalised root.

    `api_key` is minted in the PRO web UI under Admin → API. The driver
    sends it as ``X-API-Key: <key>`` on every request.

    Every sensor's readings are stored under the node id
    ``aranet:<sensor id>`` (the ids the PRO returns under ``sensors[].id``),
    in no chamber. `sensor_mappings` (sensor id → chamber id) is accepted
    but not used yet: to show a sensor in a chamber, add its node id to
    that chamber's ``node_ids``.

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
            "Aranet sensor id → SporePrint chamber id. Accepted but not "
            "used yet: every sensor is stored as aranet:<sensor id> in no "
            "chamber; add that node id to a chamber's node_ids instead."
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
        # Validate scheme + host now so bad input fails on save, not on
        # first poll. We don't validate that the host is RFC1918 because
        # users may legitimately use an mDNS or Tailscale hostname.
        parsed = urlparse(v.strip().rstrip("/"))
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must start with http:// or https://")
        if not parsed.netloc:
            raise ValueError("base_url must include a host")
        # Cut the path at its first `api` segment so users can paste either
        # the root or the example endpoint URL from the PRO docs. Only a
        # whole path segment counts: neither a host such as api-gw.lan nor
        # a path such as /apiary is an /api suffix.
        segments = parsed.path.split("/")
        if "api" in segments:
            segments = segments[: segments.index("api")]
        return f"{parsed.scheme}://{parsed.netloc}" + "/".join(segments).rstrip("/")
