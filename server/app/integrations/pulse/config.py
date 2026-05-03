"""Pulse Grow driver config schema (cloud transport)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PulseConfig(BaseModel):
    """Cloud-mode credentials + per-device chamber mapping.

    `email` + `password` are exchanged for a session token on first
    poll; the token is held in process memory and refreshed
    transparently when the Pulse API returns 401.

    `device_mappings` maps Pulse device id → SporePrint chamber id so
    readings get tagged with the chamber for downstream UI. Devices not
    listed here are still polled and stored, just with chamber ``""``.

    `poll_seconds` floor is 60 s — Pulse's cloud rate limit is roughly
    1 req/sec per token across all devices, so a household with one
    Pulse device is fine but a 4-device account would saturate the
    limit at sub-minute intervals.
    """

    email: str = Field(
        default="",
        description="Pulse account email. Empty = driver stays disabled.",
    )
    password: str = Field(
        default="",
        description=(
            "Pulse account password. Stored encrypted at rest via the "
            "integrations Fernet key. Exchanged for a session token on "
            "first poll; never sent to anyone but api.pulsegrow.com."
        ),
    )
    poll_seconds: int = Field(
        default=120,
        ge=60,
        le=3600,
        description=(
            "Poll interval. Floor 60 s (Pulse cloud rate limit ~1 req/s "
            "across all devices on a token). Ceiling 1 h."
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
