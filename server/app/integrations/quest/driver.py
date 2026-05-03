"""Quest networked dehumidifier driver."""

from __future__ import annotations

import time
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


class QuestConfig(BaseModel):
    base_url: str = Field(default="", description="LAN HTTP root, e.g. http://10.0.0.40")
    poll_seconds: int = Field(default=60, ge=30, le=3600)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    chamber_id: str = Field(default="", description="SporePrint chamber id this Quest serves")

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


class QuestDriver(HttpVendorDriver):
    name: ClassVar[str] = "quest"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = QuestConfig

    async def test_connection(self) -> IntegrationHealth:
        cfg: QuestConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.base_url:
            return IntegrationHealth(state="error", last_error="base_url required")
        try:
            data = await self._fetch_status(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"reachable": True, "fields": list(data.keys())})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: QuestConfig = self._cfg  # type: ignore[assignment]
        if not cfg.base_url:
            return 0, {"reason": "missing base_url"}
        data = await self._fetch_status(cfg)
        node_id = f"quest:{urlparse(cfg.base_url).netloc}"
        rows = 0
        now = time.time()
        for k, sp in [("temp_c", "temp_c"), ("humidity", "humidity"), ("setpoint_humidity", "setpoint_humidity")]:
            v = data.get(k)
            if isinstance(v, (int, float)):
                await store_reading(node_id, sp, float(v), now)
                rows += 1
        return rows, {"rows": rows}

    async def set_setpoint(self, humidity_pct: int) -> dict[str, Any]:
        if not 0 <= humidity_pct <= 100:
            raise ValueError("humidity_pct must be in [0, 100]")
        cfg: QuestConfig = self._cfg  # type: ignore[assignment]
        if not cfg or not cfg.base_url:
            raise RuntimeError("quest not configured")
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.put(
                f"{cfg.base_url}/api/setpoint",
                json={"humidity": humidity_pct},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Quest: HTTP {resp.status_code} on set_setpoint")
        return {"humidity_pct": humidity_pct}

    async def _fetch_status(self, cfg: QuestConfig) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.get(f"{cfg.base_url}/api/status")
        if resp.status_code >= 400:
            raise RuntimeError(f"Quest: HTTP {resp.status_code}: {resp.text[:200]!r}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Quest: non-JSON response: {exc}") from exc
        return body if isinstance(body, dict) else {}
