"""Fluence FluenceID lighting driver."""

from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


_FLUENCE_API_BASE = "https://api.fluencebioengineering.com/v1"


class FluenceConfig(BaseModel):
    email: str = Field(default="")
    password: str = Field(default="")
    poll_seconds: int = Field(default=300, ge=60, le=3600)
    request_timeout_seconds: float = Field(default=10.0, ge=2.0, le=60.0)
    fixture_mappings: dict[str, str] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def _email_check(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email looks malformed (missing @)")
        return v


class FluenceDriver(HttpVendorDriver):
    name: ClassVar[str] = "fluence"
    config_schema: ClassVar[type[BaseModel]] = FluenceConfig
    secret_fields: ClassVar[set[str]] = {"password"}

    def __init__(self) -> None:
        super().__init__()
        self._token: str | None = None

    async def test_connection(self) -> IntegrationHealth:
        cfg: FluenceConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            return IntegrationHealth(state="error", last_error="email and password required")
        try:
            await self._login(cfg)
            fixtures = await self._fetch_fixtures(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"fixtures_seen": len(fixtures)})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: FluenceConfig = self._cfg  # type: ignore[assignment]
        if not cfg.email or not cfg.password:
            return 0, {"reason": "missing creds"}
        if self._token is None:
            await self._login(cfg)
        fixtures = await self._fetch_fixtures(cfg)
        rows = 0
        now = time.time()
        for fixture in fixtures:
            fid = str(fixture.get("id", ""))
            if not fid:
                continue
            node_id = f"fluence:{fid}"
            for k, v in [
                ("dimming_percent", fixture.get("dimming")),
                ("power_w", fixture.get("power_watts")),
                ("light_temp_c", fixture.get("temperature_c")),
            ]:
                if isinstance(v, (int, float)):
                    await store_reading(node_id, k, float(v), now)
                    rows += 1
        return rows, {"fixtures": len(fixtures), "rows": rows}

    async def _login(self, cfg: FluenceConfig) -> None:
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.post(
                f"{_FLUENCE_API_BASE}/auth/login",
                json={"email": cfg.email, "password": cfg.password},
            )
        if resp.status_code == 401:
            raise RuntimeError("Fluence: 401 unauthorized — check email + password")
        if resp.status_code >= 400:
            raise RuntimeError(f"Fluence: HTTP {resp.status_code} on login")
        body = resp.json()
        token = body.get("token") or body.get("access_token")
        if not token:
            raise RuntimeError("Fluence: login succeeded but no token in response")
        self._token = token

    async def _fetch_fixtures(self, cfg: FluenceConfig) -> list[dict[str, Any]]:
        if self._token is None:
            await self._login(cfg)
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.get(
                f"{_FLUENCE_API_BASE}/fixtures",
                headers={"Authorization": f"Bearer {self._token}"},
            )
        if resp.status_code == 401:
            self._token = None
            raise RuntimeError("Fluence: token expired")
        if resp.status_code >= 400:
            raise RuntimeError(f"Fluence: HTTP {resp.status_code} on /fixtures")
        body = resp.json()
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("fixtures"), list):
            return body["fixtures"]
        return []
