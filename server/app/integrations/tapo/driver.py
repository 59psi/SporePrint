"""Tapo driver — dual-transport (local KLAP / cloud passthrough)."""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading
from .config import TapoConfig, TapoDeviceMapping
from .klap import KlapSession, auth_hash, derive_session, random_seed


_TAPO_CLOUD_BASE_BY_REGION: dict[str, str] = {
    "auto": "https://wap.tplinkcloud.com",
    "us": "https://aps1-wap.tplinkcloud.com",
    "eu": "https://eu-wap.tplinkcloud.com",
    "aps": "https://aps1-wap.tplinkcloud.com",
}


class TapoError(RuntimeError):
    pass


class TapoDriver(HttpVendorDriver):
    name: ClassVar[str] = "tapo"
    # Lowest tier the driver runs in is local (free). The cloud
    # transport is gated by the cloud-web settings UI for free users.
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = TapoConfig
    secret_fields: ClassVar[set[str]] = {"password"}

    def __init__(self) -> None:
        super().__init__()
        # Cloud transport state
        self._cloud_token: str | None = None
        # Local transport state — per-IP KLAP session cache
        self._sessions: dict[str, KlapSession] = {}

    async def test_connection(self) -> IntegrationHealth:
        cfg: TapoConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            return IntegrationHealth(
                state="error", last_error="email and password required"
            )
        try:
            if cfg.transport == "cloud":
                await self._cloud_login(cfg)
                return IntegrationHealth(
                    state="ok", details={"transport": "cloud", "logged_in": True}
                )
            else:
                if not cfg.devices:
                    return IntegrationHealth(
                        state="error",
                        last_error="local transport requires at least one device",
                    )
                ok = 0
                errors: list[str] = []
                for d in cfg.devices:
                    try:
                        await self._klap_handshake(cfg, d.ip)
                        ok += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{d.ip}: {exc}")
                if ok == 0:
                    return IntegrationHealth(
                        state="error",
                        last_error="; ".join(errors) or "no devices reachable",
                    )
                return IntegrationHealth(
                    state="ok",
                    details={
                        "transport": "local",
                        "reachable": ok,
                        "total": len(cfg.devices),
                        "errors": errors,
                    },
                )
        except TapoError as exc:
            return IntegrationHealth(state="error", last_error=str(exc))

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: TapoConfig = self._cfg  # type: ignore[assignment]
        if not cfg.email or not cfg.password:
            return 0, {"reason": "missing creds"}
        rows = 0
        now = time.time()
        if cfg.transport == "cloud":
            # Skeleton: the cloud passthrough surface is documented but
            # vendor-payload-shape variance is high; record raw shapes
            # we observe so the parser can be refined incrementally.
            await self._cloud_login(cfg)
            return rows, {"transport": "cloud", "rows": rows}

        for d in cfg.devices:
            try:
                resp = await self._klap_call(
                    cfg, d.ip, {"method": "get_device_info"}
                )
            except TapoError:
                # Reset session and try again next poll.
                self._sessions.pop(d.ip, None)
                continue
            info = resp.get("result", {}) or {}
            node_id = f"tapo:{d.ip}"
            if isinstance(info.get("device_on"), bool):
                await store_reading(
                    node_id, "actuator_state", float(info["device_on"]), now
                )
                rows += 1
            if d.is_dimmer and isinstance(info.get("brightness"), int):
                await store_reading(
                    node_id, "dimming_percent", float(info["brightness"]), now
                )
                rows += 1
            if d.has_emeter:
                try:
                    energy = await self._klap_call(
                        cfg, d.ip, {"method": "get_current_power"}
                    )
                    pw = (energy.get("result", {}) or {}).get("current_power")
                    if isinstance(pw, (int, float)):
                        await store_reading(node_id, "power_w", float(pw) / 1000.0, now)
                        rows += 1
                except TapoError:
                    pass
        return rows, {"transport": "local", "rows": rows, "devices": len(cfg.devices)}

    # ── Write paths ────────────────────────────────────────────────

    async def set_power(self, ip: str, on: bool) -> dict[str, Any]:
        cfg: TapoConfig = self._cfg  # type: ignore[assignment]
        await self._klap_call(
            cfg, ip, {"method": "set_device_info", "params": {"device_on": on}}
        )
        return {"ip": ip, "state": "on" if on else "off"}

    async def set_dim(self, ip: str, percent: int) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be in [0, 100]")
        cfg: TapoConfig = self._cfg  # type: ignore[assignment]
        await self._klap_call(
            cfg,
            ip,
            {"method": "set_device_info", "params": {"brightness": percent}},
        )
        return {"ip": ip, "percent": percent}

    # ── Cloud transport helpers ────────────────────────────────────

    async def _cloud_login(self, cfg: TapoConfig) -> None:
        base = _TAPO_CLOUD_BASE_BY_REGION.get(cfg.cloud_region, _TAPO_CLOUD_BASE_BY_REGION["auto"])
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.post(
                f"{base}/app",
                json={
                    "method": "login",
                    "params": {
                        "appType": "Tapo_Android",
                        "cloudUserName": cfg.email,
                        "cloudPassword": cfg.password,
                        "terminalUUID": "sporeprint",
                    },
                },
            )
        if resp.status_code >= 400:
            raise TapoError(
                f"Tapo cloud login HTTP {resp.status_code}: {resp.text[:200]!r}"
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise TapoError(f"Tapo cloud login non-JSON: {exc}") from exc
        token = (body.get("result") or {}).get("token")
        if not token:
            raise TapoError(
                f"Tapo cloud login: no token (error_code={body.get('error_code')!r})"
            )
        self._cloud_token = token

    # ── Local KLAP helpers ─────────────────────────────────────────

    async def _klap_handshake(self, cfg: TapoConfig, ip: str) -> KlapSession:
        local_seed = random_seed()
        url = f"http://{ip}/app/handshake1"
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp1 = await client.post(url, content=local_seed)
        if resp1.status_code >= 400:
            raise TapoError(
                f"Tapo handshake1 HTTP {resp1.status_code} from {ip}"
            )
        body1 = resp1.content
        if len(body1) < 16 + 32:
            raise TapoError(
                f"Tapo handshake1 short response from {ip} ({len(body1)}b)"
            )
        remote_seed = body1[:16]
        server_hash = body1[16:48]
        expected_hash = auth_hash(local_seed, remote_seed, cfg.email, cfg.password)
        if server_hash != expected_hash:
            raise TapoError(
                f"Tapo handshake1 auth_hash mismatch from {ip} — bad credentials?"
            )
        # Handshake2: post sha256(remote_seed || local_seed || user_hash).
        client_hash = auth_hash(remote_seed, local_seed, cfg.email, cfg.password)
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp2 = await client.post(
                f"http://{ip}/app/handshake2", content=client_hash
            )
        if resp2.status_code >= 400:
            raise TapoError(
                f"Tapo handshake2 HTTP {resp2.status_code} from {ip}"
            )
        session = derive_session(local_seed, remote_seed, cfg.email, cfg.password)
        self._sessions[ip] = session
        return session

    async def _klap_call(
        self, cfg: TapoConfig, ip: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        session = self._sessions.get(ip)
        if session is None:
            session = await self._klap_handshake(cfg, ip)
        plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        frame, seq = session.encrypt(plaintext)
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds, follow_redirects=False
        ) as client:
            resp = await client.post(
                f"http://{ip}/app/request?seq={seq}", content=frame
            )
        if resp.status_code == 403:
            # Session expired — drop it and let the caller retry once.
            self._sessions.pop(ip, None)
            raise TapoError(f"Tapo {ip}: 403 — session expired, retry")
        if resp.status_code >= 400:
            raise TapoError(
                f"Tapo {ip}: HTTP {resp.status_code} on /app/request"
            )
        try:
            cleartext = session.decrypt(resp.content)
        except Exception as exc:  # noqa: BLE001
            raise TapoError(f"Tapo {ip}: decrypt failed: {exc}") from exc
        try:
            return json.loads(cleartext)
        except json.JSONDecodeError as exc:
            raise TapoError(f"Tapo {ip}: non-JSON response: {exc}") from exc
