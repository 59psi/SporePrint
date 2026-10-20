"""Trane Nexia / BAS HVAC driver — read-only telemetry sync."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import BearerLoginDriver
from .._net import path_segment
from ...telemetry.service import store_readings


_TRANE_API_BASE = "https://www.mynexia.com/api"


class TraneConfig(BaseModel):
    email: str = Field(default="", description="Nexia account email")
    password: str = Field(default="", description="Nexia account password (encrypted at rest)")
    house_id: str = Field(default="", description="Optional: limit reads to one house id")
    poll_seconds: int = Field(default=300, ge=60, le=3600)
    request_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    device_mappings: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Thermostat id → SporePrint chamber id. Accepted but not used yet: "
            "readings are stored as trane:<thermostat id> in no chamber."
        ),
    )

    @field_validator("email")
    @classmethod
    def _email_check(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email looks malformed (missing @)")
        return v

    @field_validator("house_id")
    @classmethod
    def _house_id_is_one_segment(cls, v: str) -> str:
        # Interpolated into the request that carries the Nexia bearer token,
        # so it must be exactly one path segment ("../x?y=" would rewrite it).
        v = v.strip()
        return path_segment(v, field="house_id") if v else ""


class TraneDriver(BearerLoginDriver):
    name: ClassVar[str] = "trane"
    config_schema: ClassVar[type[BaseModel]] = TraneConfig
    secret_fields: ClassVar[set[str]] = {"password"}
    vendor_label: ClassVar[str] = "Trane"
    api_base: ClassVar[str] = _TRANE_API_BASE

    async def test_connection(self) -> IntegrationHealth:
        cfg: TraneConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            return IntegrationHealth(
                state="error", last_error="email and password are required"
            )
        try:
            await self._login(cfg, retry_rejected=True)
            houses = await self._fetch_houses(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"houses_seen": len(houses)})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: TraneConfig = self._require_credentials()
        houses = await self._fetch_houses(cfg)
        readings: list[tuple[float, str, str, float]] = []
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
                    readings.append((now, node_id, "temp_c", float(indoor_temp)))
                if isinstance(indoor_rh, (int, float)):
                    readings.append((now, node_id, "humidity", float(indoor_rh)))
        # One transaction for the whole poll, not a commit per reading.
        rows = await store_readings(readings)
        return rows, {"houses": len(houses), "rows": rows}

    async def set_setpoint(
        self, thermostat_id: str, target_c: float, mode: str | None = None
    ) -> dict[str, Any]:
        segment = path_segment(thermostat_id, field="thermostat_id")
        cfg: TraneConfig = self._require_credentials()
        body: dict[str, Any] = {"target_c": target_c}
        if mode:
            body["mode"] = mode
        resp = await self._authed_request(
            cfg, "PUT", f"{_TRANE_API_BASE}/thermostats/{segment}/setpoint", body=body
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Trane: HTTP {resp.status_code} on set_setpoint")
        return {"thermostat_id": thermostat_id, "target_c": target_c, "mode": mode}

    async def _fetch_houses(self, cfg: TraneConfig) -> list[dict[str, Any]]:
        url = f"{_TRANE_API_BASE}/houses"
        if cfg.house_id:
            # Checked again at use: a value saved before the config validated
            # it fails the poll instead of reaching the vendor with the token.
            url = f"{url}/{path_segment(cfg.house_id, field='house_id')}"
        resp = await self._authed_request(cfg, "GET", url)
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
