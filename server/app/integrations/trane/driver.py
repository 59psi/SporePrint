"""Trane Nexia / BAS HVAC driver — read-only telemetry sync."""

from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


_TRANE_API_BASE = "https://www.mynexia.com/api"


class TraneConfig(BaseModel):
    email: str = Field(default="", description="Nexia account email")
    password: str = Field(default="", description="Nexia account password (encrypted at rest)")
    house_id: str = Field(default="", description="Optional: limit reads to one house id")
    poll_seconds: int = Field(default=300, ge=60, le=3600)
    request_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    device_mappings: dict[str, str] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def _email_check(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email looks malformed (missing @)")
        return v


class TraneDriver(HttpVendorDriver):
    name: ClassVar[str] = "trane"
    config_schema: ClassVar[type[BaseModel]] = TraneConfig
    secret_fields: ClassVar[set[str]] = {"password"}

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None

    async def test_connection(self) -> IntegrationHealth:
        cfg: TraneConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            return IntegrationHealth(
                state="error", last_error="email and password are required"
            )
        try:
            await self._login(cfg)
            houses = await self._fetch_houses(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"houses_seen": len(houses)})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: TraneConfig = self._cfg  # type: ignore[assignment]
        if not cfg.email or not cfg.password:
            return 0, {"reason": "missing creds"}
        if self._token is None:
            await self._login(cfg)
        houses = await self._fetch_houses(cfg)
        rows = 0
        now = time.time()
        for house in houses:
            for thermostat in house.get("thermostats", []) or []:
                tid = str(thermostat.get("id", ""))
                if not tid:
                    continue
                node_id = f"trane:{tid}"
                indoor_temp = thermostat.get("current_temperature")
                indoor_rh = thermostat.get("current_humidity")
                if isinstance(indoor_temp, (int, float)):
                    await store_reading(node_id, "temp_c", float(indoor_temp), now)
                    rows += 1
                if isinstance(indoor_rh, (int, float)):
                    await store_reading(node_id, "humidity", float(indoor_rh), now)
                    rows += 1
        return rows, {"houses": len(houses), "rows": rows}

    async def _login(self, cfg: TraneConfig) -> None:
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.post(
                f"{_TRANE_API_BASE}/auth/login",
                json={"email": cfg.email, "password": cfg.password},
            )
        if resp.status_code == 401:
            raise RuntimeError("Trane: 401 unauthorized — check email + password")
        if resp.status_code >= 400:
            raise RuntimeError(f"Trane: HTTP {resp.status_code} on login")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Trane: non-JSON login response: {exc}") from exc
        token = body.get("token") or body.get("access_token")
        if not token:
            raise RuntimeError("Trane: login succeeded but no token in response")
        self._token = token

    async def _fetch_houses(self, cfg: TraneConfig) -> list[dict[str, Any]]:
        if self._token is None:
            await self._login(cfg)
        url = f"{_TRANE_API_BASE}/houses"
        if cfg.house_id:
            url = f"{_TRANE_API_BASE}/houses/{cfg.house_id}"
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {self._token}"}
            )
        if resp.status_code == 401:
            self._token = None  # force re-login on next call
            raise RuntimeError("Trane: 401 — token expired, retry")
        if resp.status_code >= 400:
            raise RuntimeError(f"Trane: HTTP {resp.status_code} on /houses")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Trane: non-JSON houses response: {exc}") from exc
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and "houses" in body:
            return body["houses"] if isinstance(body["houses"], list) else []
        return [body] if isinstance(body, dict) else []
