"""Fohse FohseConnect lighting driver — same shape as Fluence."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import BearerLoginDriver
from .._net import path_segment
from ...telemetry.service import store_readings


_FOHSE_API_BASE = "https://api.fohse.com/v1"


class FohseConfig(BaseModel):
    email: str = Field(default="")
    password: str = Field(default="")
    poll_seconds: int = Field(default=300, ge=60, le=3600)
    request_timeout_seconds: float = Field(default=10.0, ge=2.0, le=60.0)
    fixture_mappings: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Fixture id → SporePrint chamber id. Accepted but not used yet: "
            "readings are stored as fohse:<fixture id> in no chamber."
        ),
    )

    @field_validator("email")
    @classmethod
    def _email_check(cls, v: str) -> str:
        v = v.strip()
        if v and "@" not in v:
            raise ValueError("email looks malformed (missing @)")
        return v


class FohseDriver(BearerLoginDriver):
    name: ClassVar[str] = "fohse"
    config_schema: ClassVar[type[BaseModel]] = FohseConfig
    secret_fields: ClassVar[set[str]] = {"password"}
    vendor_label: ClassVar[str] = "Fohse"
    api_base: ClassVar[str] = _FOHSE_API_BASE

    async def test_connection(self) -> IntegrationHealth:
        cfg: FohseConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            return IntegrationHealth(state="error", last_error="email and password required")
        try:
            await self._login(cfg, retry_rejected=True)
            fixtures = await self._fetch_fixtures(cfg)
        except Exception as exc:  # noqa: BLE001
            return IntegrationHealth(state="error", last_error=str(exc))
        return IntegrationHealth(state="ok", details={"fixtures_seen": len(fixtures)})

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: FohseConfig = self._require_credentials()
        fixtures = await self._fetch_fixtures(cfg)
        readings: list[tuple[float, str, str, float]] = []
        now = time.time()
        for fixture in fixtures:
            fid = str(fixture.get("id", ""))
            if not fid:
                continue
            node_id = f"fohse:{fid}"
            for k, v in [
                ("dimming_percent", fixture.get("intensity_percent")),
                ("power_w", fixture.get("power_w")),
                ("light_temp_c", fixture.get("fixture_temp_c")),
            ]:
                if isinstance(v, (int, float)):
                    readings.append((now, node_id, k, float(v)))
        # One transaction for the whole poll, not a commit per reading.
        rows = await store_readings(readings)
        return rows, {"fixtures": len(fixtures), "rows": rows}

    async def set_dim(self, fixture_id: str, percent: int) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be in [0, 100]")
        segment = path_segment(fixture_id, field="fixture_id")
        cfg: FohseConfig = self._require_credentials()
        resp = await self._authed_request(
            cfg,
            "PUT",
            f"{_FOHSE_API_BASE}/fixtures/{segment}/intensity",
            body={"intensity_percent": percent},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Fohse: HTTP {resp.status_code} on set_dim")
        return {"fixture_id": fixture_id, "percent": percent}

    async def _fetch_fixtures(self, cfg: FohseConfig) -> list[dict[str, Any]]:
        resp = await self._authed_request(cfg, "GET", f"{_FOHSE_API_BASE}/fixtures")
        if resp.status_code >= 400:
            raise RuntimeError(f"Fohse: HTTP {resp.status_code} on /fixtures")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Fohse: non-JSON /fixtures response: {exc}") from exc
        if isinstance(body, list):
            return body
        if isinstance(body, dict) and isinstance(body.get("fixtures"), list):
            return body["fixtures"]
        return []
