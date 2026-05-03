"""BIOS Lighting LAN driver."""

from __future__ import annotations

import time
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


class BiosConfig(BaseModel):
    base_url: str = Field(default="", description="LAN HTTP root of the BIOS controller")
    api_key: str = Field(default="", description="Optional API key (newer firmware)")
    poll_seconds: int = Field(default=60, ge=30, le=3600)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    fixture_mappings: dict[str, str] = Field(default_factory=dict)

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


class BiosDriver(HttpVendorDriver):
    name: ClassVar[str] = "bios"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = BiosConfig
    secret_fields: ClassVar[set[str]] = {"api_key"}

    async def test_connection(self) -> IntegrationHealth:
        cfg: BiosConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.base_url:
            return IntegrationHealth(state="error", last_error="base_url required")
        try:
            fixtures = await self._fetch_fixtures(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"fixtures_seen": len(fixtures)})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: BiosConfig = self._cfg  # type: ignore[assignment]
        if not cfg.base_url:
            return 0, {"reason": "missing base_url"}
        fixtures = await self._fetch_fixtures(cfg)
        rows = 0
        now = time.time()
        for fixture in fixtures:
            fid = str(fixture.get("id", ""))
            if not fid:
                continue
            node_id = f"bios:{fid}"
            for k, v in [
                ("dimming_percent", fixture.get("dim")),
                ("power_w", fixture.get("watts")),
                ("light_temp_c", fixture.get("temp_c")),
            ]:
                if isinstance(v, (int, float)):
                    await store_reading(node_id, k, float(v), now)
                    rows += 1
        return rows, {"fixtures": len(fixtures), "rows": rows}

    async def _fetch_fixtures(self, cfg: BiosConfig) -> list[dict[str, Any]]:
        headers = {}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.get(f"{cfg.base_url}/api/fixtures", headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"BIOS: HTTP {resp.status_code}: {resp.text[:200]!r}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"BIOS: non-JSON response: {exc}") from exc
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("fixtures"), list):
            return body["fixtures"]
        return []
