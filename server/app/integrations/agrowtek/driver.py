"""Agrowtek GCX controller driver."""

from __future__ import annotations

import time
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


# Mapping known GCX measurement names → SporePrint sensor names.
_TYPE_MAP: dict[str, str] = {
    "temp_c": "temp_c",
    "temperature": "temp_c",
    "humidity": "humidity",
    "rh": "humidity",
    "co2": "co2_ppm",
    "co2_ppm": "co2_ppm",
    "vpd": "vpd_kpa",
    "light": "lux",
}


class AgrowtekConfig(BaseModel):
    base_url: str = Field(default="", description="LAN HTTP root, e.g. http://10.0.0.30")
    api_key: str = Field(default="", description="API key from GCX admin UI")
    poll_seconds: int = Field(default=60, ge=30, le=3600)
    sensor_mappings: dict[str, str] = Field(default_factory=dict)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)

    @field_validator("base_url")
    @classmethod
    def _norm(cls, v: str) -> str:
        if not v:
            return ""
        v = v.strip().rstrip("/")
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must start with http:// or https://")
        if not parsed.netloc:
            raise ValueError("base_url must include a host")
        return v


class AgrowtekDriver(HttpVendorDriver):
    name: ClassVar[str] = "agrowtek"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = AgrowtekConfig
    secret_fields: ClassVar[set[str]] = {"api_key"}

    async def test_connection(self) -> IntegrationHealth:
        cfg: AgrowtekConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.base_url or not cfg.api_key:
            return IntegrationHealth(state="error", last_error="base_url and api_key are required")
        try:
            sensors = await self._fetch_sensors(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"sensors_seen": len(sensors)})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: AgrowtekConfig = self._cfg  # type: ignore[assignment]
        if not cfg.base_url or not cfg.api_key:
            return 0, {"reason": "missing creds"}
        sensors = await self._fetch_sensors(cfg)
        rows = 0
        now = time.time()
        for sensor in sensors:
            sensor_id = str(sensor.get("id", ""))
            if not sensor_id:
                continue
            node_id = f"agrowtek:{sensor_id}"
            for k, v in sensor.get("measurements", {}).items():
                sp_sensor = _TYPE_MAP.get(k)
                if sp_sensor is None or not isinstance(v, (int, float)):
                    continue
                await store_reading(node_id, sp_sensor, float(v), now)
                rows += 1
        return rows, {"sensors": len(sensors), "rows": rows}

    async def set_output(
        self, output_id: str, value: float | bool
    ) -> dict[str, Any]:
        cfg: AgrowtekConfig = self._cfg  # type: ignore[assignment]
        if not cfg or not cfg.base_url or not cfg.api_key:
            raise RuntimeError("agrowtek not configured")
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.put(
                f"{cfg.base_url}/api/outputs/{output_id}",
                headers={"Authorization": f"Bearer {cfg.api_key}"},
                json={"value": value},
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Agrowtek: HTTP {resp.status_code} on set_output: {resp.text[:200]!r}"
            )
        return {"output_id": output_id, "value": value}

    async def _fetch_sensors(self, cfg: AgrowtekConfig) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.get(
                f"{cfg.base_url}/api/sensors",
                headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} from /api/sensors: {resp.text[:200]!r}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"non-JSON response: {exc}") from exc
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("sensors"), list):
            return payload["sensors"]
        return []
