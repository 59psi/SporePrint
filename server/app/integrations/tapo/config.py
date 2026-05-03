"""Tapo dual-transport config (local KLAP / cloud passthrough)."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


TapoTransport = Literal["local", "cloud"]


class TapoDeviceMapping(BaseModel):
    ip: str = ""
    device_id: str = ""
    chamber_id: str = ""
    actuator: str = "tapo"
    is_dimmer: bool = False
    has_emeter: bool = False

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        if not v:
            return v
        parsed = urlparse(f"//{v}")
        if not parsed.hostname:
            raise ValueError(f"invalid ip {v!r}")
        return v


class TapoConfig(BaseModel):
    transport: TapoTransport = Field(default="local")

    # Auth — required for both transports. Tapo's local KLAP also needs
    # the operator's TP-Link account password (not a separate per-device
    # secret), because the auth_hash is derived from username + password.
    email: str = Field(default="")
    password: str = Field(default="")

    # Local transport — list of devices on the LAN. Either populate
    # `devices` directly or rely on the operator setting up devices in
    # the Tapo app (no LAN auto-discovery in this skeleton; mDNS-style
    # discovery is v4.1.x roadmap).
    devices: list[TapoDeviceMapping] = Field(default_factory=list)

    # Cloud transport — region routes. tplinkcloud.com auto-redirects
    # but explicit region speeds up the OAuth flow. Default is "auto".
    cloud_region: str = Field(default="auto", description="auto / us / eu / aps")

    poll_seconds: int = Field(default=60, ge=15, le=3600)
    request_timeout_seconds: float = Field(default=10.0, ge=2.0, le=60.0)

    @field_validator("email")
    @classmethod
    def _email_check(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email looks malformed (missing @)")
        return v

    @field_validator("password")
    @classmethod
    def _strip_password(cls, v: str) -> str:
        return v.strip()
