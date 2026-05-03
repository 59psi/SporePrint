"""Pulse Grow driver config schema (dual-transport: cloud + local)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


PulseTransport = Literal["cloud", "local"]


class PulseConfig(BaseModel):
    """Dual-transport config — cloud (premium, account-mediated) or local
    (free, LAN-only).

    Cloud mode: ``email`` + ``password`` exchanged for a session token on
    first poll; the token is held in process memory and refreshed
    transparently when the Pulse API returns 401.

    Local mode: UDP discovery on the LAN broadcast address (port 5683,
    CoAP convention) followed by per-device HTTP polling on a configured
    port. **Local-mode endpoint shape needs verification on a paired
    Pulse device** — the parsing layer is tolerant by design but the
    discovery probe has not been exercised against live hardware. If
    your Pulse fleet is reachable at known LAN IPs, set
    ``local_device_urls`` to skip discovery entirely.

    `device_mappings` maps Pulse device id → SporePrint chamber id so
    readings get tagged with the chamber for downstream UI. Devices not
    listed here are still polled and stored, just with chamber ``""``.

    `poll_seconds` floor is 60 s for cloud (Pulse's cloud rate limit is
    roughly 1 req/sec per token); 30 s for local (no remote rate limit
    to worry about, but 30 s gives the device time to refresh).
    """

    transport: PulseTransport = Field(
        default="cloud",
        description=(
            "cloud = api.pulsegrow.com (premium); "
            "local = LAN UDP discovery + HTTP poll (free)."
        ),
    )

    # ── Cloud transport fields ──────────────────────────────────────
    email: str = Field(
        default="",
        description="Pulse account email. Cloud transport only.",
    )
    password: str = Field(
        default="",
        description=(
            "Pulse account password. Cloud transport only. Stored "
            "encrypted at rest via the integrations Fernet key. Exchanged "
            "for a session token on first poll; never sent to anyone "
            "but api.pulsegrow.com."
        ),
    )

    # ── Local transport fields ──────────────────────────────────────
    local_broadcast_addr: str = Field(
        default="255.255.255.255",
        description=(
            "UDP broadcast address used for local discovery. Default "
            "limited-broadcast; set to your subnet broadcast (e.g. "
            "10.0.0.255) if your router blocks limited-broadcast."
        ),
    )
    local_discovery_port: int = Field(
        default=5683,
        ge=1,
        le=65535,
        description="UDP discovery port (CoAP convention).",
    )
    local_http_port: int = Field(
        default=80,
        ge=1,
        le=65535,
        description="Per-device HTTP port for local polling.",
    )
    local_device_urls: list[str] = Field(
        default_factory=list,
        description=(
            "Optional list of explicit per-device URLs (e.g. "
            "['http://10.0.0.5', 'http://10.0.0.6']). When non-empty, "
            "discovery is skipped and these URLs are polled directly."
        ),
    )
    local_discovery_timeout_seconds: float = Field(
        default=3.0,
        ge=1.0,
        le=30.0,
        description="UDP discovery scan timeout.",
    )

    # ── Common fields ───────────────────────────────────────────────
    poll_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description=(
            "Poll interval. Cloud transport: 60 s floor recommended "
            "(Pulse cloud rate limit ~1 req/s). Local transport: 30 s "
            "minimum, default 120 s."
        ),
    )
    device_mappings: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Pulse device id → SporePrint chamber id. Devices not listed "
            "are still polled but tagged with chamber ''."
        ),
    )
    request_timeout_seconds: float = Field(
        default=10.0,
        ge=2.0,
        le=60.0,
        description="HTTP request timeout per call.",
    )

    @field_validator("email")
    @classmethod
    def _check_email_shape(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            # Sanity check rather than RFC 5322 pedantry — we just want
            # to catch the obvious "you forgot to fill this in" case
            # before the first request to api.pulsegrow.com.
            raise ValueError("email looks malformed (missing @)")
        return v

    @field_validator("password")
    @classmethod
    def _strip_password(cls, v: str) -> str:
        # Trim whitespace to catch the common copy-paste-with-newline
        # mistake. Empty after strip is treated identically to empty.
        return v.strip()
