"""Tapo driver — dual-transport (local KLAP / cloud passthrough)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, ClassVar, NoReturn

import httpx
from pydantic import BaseModel

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from .._net import split_host_port, url_host
from ...telemetry.service import store_readings
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

# In-band error codes after which the cached KLAP session is no good: the
# session timed out (9999), the transport is gone (1002), or the device no
# longer accepts its credentials or keys (1003, 1100, 1111, -1005, -1501).
# The next call handshakes again.
_SESSION_ERROR_CODES = frozenset({9999, 1002, 1003, 1100, 1111, -1005, -1501})


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
        # The cloud's answer to a login it refused, kept for the current
        # settings so the poll does not resend a refused password (TP-Link
        # locks accounts after repeated failures).
        self._cloud_rejected: str | None = None
        # Local transport state — per-IP KLAP session cache
        self._sessions: dict[str, KlapSession] = {}
        # One KLAP exchange per plug at a time (see _klap_call).
        self._locks: dict[str, asyncio.Lock] = {}

    def _reset_auth(self) -> None:
        # Credentials changed — sessions/tokens minted for the old ones
        # must not keep being used.
        self._sessions.clear()
        self._cloud_token = None
        self._cloud_rejected = None

    def _clear_login_refusal(self) -> None:
        self._cloud_rejected = None

    def _require_cfg(self) -> TapoConfig:
        cfg: TapoConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            raise TapoError("Tapo is not configured (email and password are required)")
        return cfg

    def _device_lock(self, ip: str) -> asyncio.Lock:
        lock = self._locks.get(ip)
        if lock is None:
            lock = self._locks[ip] = asyncio.Lock()
        return lock

    def _drop_session(self, ip: str, session: KlapSession) -> None:
        if self._sessions.get(ip) is session:
            del self._sessions[ip]

    async def test_connection(self) -> IntegrationHealth:
        cfg: TapoConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.email or not cfg.password:
            return IntegrationHealth(
                state="error", last_error="email and password required"
            )
        try:
            if cfg.transport == "cloud":
                await self._cloud_login(cfg, retry_rejected=True)
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
                        async with self._device_lock(d.ip):
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
        cfg = self._require_cfg()
        if cfg.transport == "cloud":
            # The cloud passthrough is not implemented. Log in at most once
            # (token cached — a credential login every poll risks a TP-Link
            # lockout) and fail the poll loudly so health shows the real
            # state instead of "ok" with zero telemetry.
            if self._cloud_token is None:
                await self._cloud_login(cfg)
            raise TapoError(_CLOUD_TELEMETRY_UNSUPPORTED)
        if not cfg.devices:
            raise TapoError("local transport requires at least one device")

        readings: list[tuple[float, str, str, float]] = []
        failed: dict[str, str] = {}
        now = time.time()
        for i, d in enumerate(cfg.devices):
            try:
                readings.extend(await self._poll_device(cfg, d, now))
            except Exception as exc:  # noqa: BLE001 — one plug must not stop the rest
                # Start this plug over with a fresh handshake next poll.
                self._sessions.pop(d.ip, None)
                failed[d.ip or f"device {i + 1}"] = str(exc)
        # One transaction for the whole poll, not a commit per reading.
        rows = await store_readings(readings)
        return rows, {
            "transport": "local",
            "rows": rows,
            "devices": len(cfg.devices),
            "failed": failed,
        }

    async def _poll_device(
        self, cfg: TapoConfig, d: TapoDeviceMapping, now: float
    ) -> list[tuple[float, str, str, float]]:
        """One plug's (timestamp, node id, sensor, value) readings."""
        if not d.ip:
            raise TapoError("no ip — the local transport needs each plug's LAN address")
        resp = await self._klap_call(cfg, d.ip, {"method": "get_device_info"})
        info = resp.get("result")
        if not isinstance(info, dict):
            info = {}
        readings: list[tuple[float, str, str, float]] = []
        node_id = f"tapo:{d.ip}"
        if isinstance(info.get("device_on"), bool):
            readings.append((now, node_id, "actuator_state", float(info["device_on"])))
        if d.is_dimmer and isinstance(info.get("brightness"), int):
            readings.append((now, node_id, "dimming_percent", float(info["brightness"])))
        if d.has_emeter:
            try:
                energy = await self._klap_call(
                    cfg, d.ip, {"method": "get_current_power"}
                )
            except TapoError:
                # The plug answered; a missing or failing energy meter costs
                # only its power reading.
                return readings
            result = energy.get("result")
            pw = result.get("current_power") if isinstance(result, dict) else None
            # get_current_power reports whole watts (get_energy_usage is the
            # call that reports milliwatts).
            if isinstance(pw, (int, float)) and not isinstance(pw, bool):
                readings.append((now, node_id, "power_w", float(pw)))
        return readings

    # ── Write paths ────────────────────────────────────────────────

    async def set_power(self, ip: str, on: bool) -> dict[str, Any]:
        _require_lan_ip(ip)
        cfg = self._require_cfg()
        await self._klap_call(
            cfg, ip, {"method": "set_device_info", "params": {"device_on": on}}
        )
        return {"ip": ip, "state": "on" if on else "off"}

    async def set_dim(self, ip: str, percent: int) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be in [0, 100]")
        _require_lan_ip(ip)
        cfg = self._require_cfg()
        await self._klap_call(
            cfg,
            ip,
            {"method": "set_device_info", "params": {"brightness": percent}},
        )
        return {"ip": ip, "percent": percent}

    # ── Cloud transport helpers ────────────────────────────────────

    def _reject_cloud(self, cfg: TapoConfig, message: str) -> NoReturn:
        if self._cfg == cfg:
            self._cloud_rejected = message
        raise TapoError(message)

    async def _cloud_login(self, cfg: TapoConfig, *, retry_rejected: bool = False) -> None:
        """Log in to the TP-Link cloud and cache the token.

        A refused login is remembered for these settings and not retried
        until the settings are saved again (changed or not);
        ``retry_rejected`` (the operator's Test) logs in anyway. Network
        errors retry normally.
        """
        if self._cloud_rejected is not None and not retry_rejected:
            raise TapoError(self._cloud_rejected)
        base = _TAPO_CLOUD_BASE_BY_REGION.get(cfg.cloud_region, _TAPO_CLOUD_BASE_BY_REGION["auto"])
        try:
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
        except httpx.HTTPError as exc:
            raise TapoError(f"Tapo cloud login failed: {exc}") from exc
        if resp.status_code in (401, 403):
            self._reject_cloud(
                cfg,
                f"Tapo cloud login HTTP {resp.status_code} — check email + password "
                "(not retried until they are saved again)",
            )
        if resp.status_code >= 400:
            raise TapoError(
                f"Tapo cloud login HTTP {resp.status_code}: {resp.text[:200]!r}"
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise TapoError(f"Tapo cloud login non-JSON: {exc}") from exc
        result = body.get("result") if isinstance(body, dict) else None
        token = result.get("token") if isinstance(result, dict) else None
        if not token:
            code = body.get("error_code") if isinstance(body, dict) else None
            self._reject_cloud(
                cfg,
                f"Tapo cloud login: no token (error_code={code!r}) — check email + "
                "password (not retried until they are saved again)",
            )
        if self._cfg == cfg:
            self._cloud_token = token
            self._cloud_rejected = None

    # ── Local KLAP helpers ─────────────────────────────────────────

    async def _klap_handshake(self, cfg: TapoConfig, ip: str) -> KlapSession:
        """Handshake with one plug; callers hold that plug's _device_lock."""
        local_seed = random_seed()
        base = _device_base(ip)
        url = f"{base}/app/handshake1"
        try:
            async with httpx.AsyncClient(
                timeout=cfg.request_timeout_seconds, follow_redirects=False
            ) as client:
                resp1 = await client.post(url, content=local_seed)
        except httpx.HTTPError as exc:
            raise TapoError(f"Tapo handshake1 with {ip} failed: {exc}") from exc
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
        try:
            async with httpx.AsyncClient(
                timeout=cfg.request_timeout_seconds,
                follow_redirects=False,
                cookies=cookies,
            ) as client:
                resp2 = await client.post(
                    f"{base}/app/handshake2", content=client_hash
                )
        except httpx.HTTPError as exc:
            raise TapoError(f"Tapo handshake2 with {ip} failed: {exc}") from exc
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
        # One exchange per plug at a time, as python-kasa does: a plug may
        # refuse interleaved sequence numbers, and two handshakes at once
        # would replace each other's TP_SESSIONID. (The poll, a REST or cloud
        # action, an automation fire and the safety watchdog's OFF can all
        # reach the same plug together.)
        async with self._device_lock(ip):
            session = self._sessions.get(ip)
            if session is None:
                session = await self._klap_handshake(cfg, ip)
            plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            frame, seq = session.encrypt(plaintext)
            try:
                async with httpx.AsyncClient(
                    timeout=cfg.request_timeout_seconds,
                    follow_redirects=False,
                    cookies=session.cookies,
                ) as client:
                    resp = await client.post(
                        f"{_device_base(ip)}/app/request?seq={seq}", content=frame
                    )
            except httpx.HTTPError as exc:
                raise TapoError(f"Tapo {ip}: request failed: {exc}") from exc
            if resp.status_code == 403:
                # Session expired — drop it; the next call handshakes again.
                self._drop_session(ip, session)
                raise TapoError(f"Tapo {ip}: 403 — session expired, retry")
            if resp.status_code >= 400:
                raise TapoError(
                    f"Tapo {ip}: HTTP {resp.status_code} on /app/request"
                )
            try:
                # The reply is encrypted under THIS request's sequence number.
                cleartext = session.decrypt(resp.content, seq)
            except Exception as exc:  # noqa: BLE001
                raise TapoError(f"Tapo {ip}: decrypt failed: {exc}") from exc
        try:
            reply = json.loads(cleartext)
        except ValueError as exc:  # JSONDecodeError, or UnicodeDecodeError on garbled bytes
            raise TapoError(f"Tapo {ip}: non-JSON response: {exc}") from exc
        if not isinstance(reply, dict):
            raise TapoError(f"Tapo {ip}: unexpected response {cleartext[:100]!r}")
        # The plug reports a refused command in the reply, not the HTTP
        # status. A refused write must not read as delivered (a safety OFF
        # counted as sent is never retried); a missing code is success.
        code = reply.get("error_code")
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            if code in _SESSION_ERROR_CODES:
                self._drop_session(ip, session)
            raise TapoError(
                f"Tapo {ip}: {payload.get('method')} refused (error_code {code})"
            )
        return reply
