"""Tapo driver — dual-transport (local KLAP / cloud passthrough)."""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from .._net import split_host_port, url_host
from ...telemetry.service import store_reading
from .config import TapoConfig, TapoDeviceMapping
from .klap import KlapSession, auth_hash, derive_session, random_seed


# "us" used to point at the APAC (aps1) host. The global endpoint serves US
# accounts, so "us" now shares it with "auto".
_TAPO_CLOUD_BASE_BY_REGION: dict[str, str] = {
    "auto": "https://wap.tplinkcloud.com",
    "us": "https://wap.tplinkcloud.com",
    "eu": "https://eu-wap.tplinkcloud.com",
    "aps": "https://aps1-wap.tplinkcloud.com",
}

# Handshake1 sets this cookie; the device rejects handshake2 and every
# encrypted request that doesn't present it.
_SESSION_COOKIE = "TP_SESSIONID"

_CLOUD_TELEMETRY_UNSUPPORTED = (
    "Tapo cloud transport does not collect telemetry yet — switch to "
    "transport=local with the plugs' LAN IPs"
)


def _session_cookies(resp: httpx.Response) -> dict[str, str]:
    """Extract TP_SESSIONID from handshake1's Set-Cookie header(s).

    Parsed from the raw header (Tapo sends ``TP_SESSIONID=…;TIMEOUT=86400``)
    rather than ``resp.cookies`` so it works for any response object.
    """
    for header in resp.headers.get_list("set-cookie"):
        for part in header.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name == _SESSION_COOKIE:
                return {_SESSION_COOKIE: value}
    return {}


def _device_base(ip: str) -> str:
    host, port = split_host_port(ip)
    return f"http://{url_host(host)}" + (f":{port}" if port else "")


class TapoError(RuntimeError):
    pass


def _require_lan_ip(ip: object) -> None:
    """Writes always go over local KLAP (cloud passthrough is not
    implemented), so a device ip is mandatory — including for
    transport="cloud" configs."""
    if not isinstance(ip, str) or not ip.strip():
        raise ValueError(
            "ip is required: Tapo writes use the local KLAP transport "
            "(cloud passthrough is not supported)"
        )
    split_host_port(ip)


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

    def _reset_auth(self) -> None:
        # Credentials changed — sessions/tokens minted for the old ones
        # must not keep being used.
        self._sessions.clear()
        self._cloud_token = None

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
            # The cloud passthrough is not implemented. Log in at most once
            # (token cached — a credential login every poll risks a TP-Link
            # lockout) and fail the poll loudly so health shows the real
            # state instead of "ok" with zero telemetry.
            if self._cloud_token is None:
                await self._cloud_login(cfg)
            raise TapoError(_CLOUD_TELEMETRY_UNSUPPORTED)

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
        _require_lan_ip(ip)
        cfg: TapoConfig = self._cfg  # type: ignore[assignment]
        await self._klap_call(
            cfg, ip, {"method": "set_device_info", "params": {"device_on": on}}
        )
        return {"ip": ip, "state": "on" if on else "off"}

    async def set_dim(self, ip: str, percent: int) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be in [0, 100]")
        _require_lan_ip(ip)
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
        base = _device_base(ip)
        url = f"{base}/app/handshake1"
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
        cookies = _session_cookies(resp1)
        # Handshake2: post sha256(remote_seed || local_seed || user_hash),
        # presenting handshake1's session cookie.
        client_hash = auth_hash(remote_seed, local_seed, cfg.email, cfg.password)
        async with httpx.AsyncClient(
            timeout=cfg.request_timeout_seconds,
            follow_redirects=False,
            cookies=cookies,
        ) as client:
            resp2 = await client.post(
                f"{base}/app/handshake2", content=client_hash
            )
        if resp2.status_code >= 400:
            raise TapoError(
                f"Tapo handshake2 HTTP {resp2.status_code} from {ip}"
            )
        session = derive_session(local_seed, remote_seed, cfg.email, cfg.password)
        session.cookies = cookies
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
            timeout=cfg.request_timeout_seconds,
            follow_redirects=False,
            cookies=session.cookies,
        ) as client:
            resp = await client.post(
                f"{_device_base(ip)}/app/request?seq={seq}", content=frame
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
