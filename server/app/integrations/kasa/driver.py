"""TP-Link Kasa driver — local TCP encrypted JSON protocol.

Cipher (TP-Link's "Smart" protocol): each byte XOR'd with a rolling
key seeded at 0xAB; decryption is the same operation in reverse. The
on-wire frame is a 4-byte big-endian length prefix followed by the
ciphertext.

Live-device-tested protocol, but firmware revisions vary in the JSON
shape — the parser is tolerant.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from typing import Any, ClassVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


_KASA_PORT = 9999
_KEY_SEED = 0xAB


def _encrypt(plaintext: str) -> bytes:
    """Kasa's XOR cipher with a 4-byte length prefix (`!I` packed)."""
    key = _KEY_SEED
    out = bytearray()
    for byte in plaintext.encode("utf-8"):
        key = key ^ byte
        out.append(key)
    return struct.pack("!I", len(out)) + bytes(out)


def _decrypt(buf: bytes) -> str:
    """Reverse of _encrypt. Strips the 4-byte length header first."""
    if len(buf) < 4:
        raise ValueError("kasa frame shorter than length prefix")
    expected_len = struct.unpack("!I", buf[:4])[0]
    body = buf[4 : 4 + expected_len]
    key = _KEY_SEED
    out = bytearray()
    for cipher_byte in body:
        out.append(key ^ cipher_byte)
        key = cipher_byte
    return out.decode("utf-8", errors="replace")


class KasaDeviceMapping(BaseModel):
    ip: str
    chamber_id: str = ""
    actuator: str = "kasa"
    is_dimmer: bool = False
    has_emeter: bool = False

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        if not v:
            return v
        parsed = urlparse(f"//{v}")
        if not parsed.hostname:
            raise ValueError(f"invalid ip {v!r}")
        return v


class KasaConfig(BaseModel):
    devices: list[KasaDeviceMapping] = Field(default_factory=list)
    poll_seconds: int = Field(default=60, ge=15, le=3600)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)


class KasaError(RuntimeError):
    pass


async def _kasa_query(ip: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Send one JSON request, await one response. Connection per call —
    Kasa devices accept this fine and it keeps state minimal."""
    text = json.dumps(payload, separators=(",", ":"))
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, _KASA_PORT), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise KasaError(f"connect to {ip}:{_KASA_PORT} failed: {exc}") from exc
    try:
        writer.write(_encrypt(text))
        await writer.drain()
        try:
            buf = await asyncio.wait_for(reader.read(8192), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise KasaError(f"read from {ip} timed out") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
    raw = _decrypt(buf)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KasaError(f"non-JSON response from {ip}: {exc}") from exc


class KasaDriver(HttpVendorDriver):
    name: ClassVar[str] = "kasa"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = KasaConfig
    secret_fields: ClassVar[set[str]] = set()

    async def test_connection(self) -> IntegrationHealth:
        cfg: KasaConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.devices:
            return IntegrationHealth(state="error", last_error="no devices configured")
        ok = 0
        errors: list[str] = []
        for d in cfg.devices:
            try:
                await _kasa_query(
                    d.ip, {"system": {"get_sysinfo": {}}}, cfg.request_timeout_seconds
                )
                ok += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{d.ip}: {exc}")
        if ok == 0:
            return IntegrationHealth(
                state="error", last_error="; ".join(errors) or "no devices reachable"
            )
        return IntegrationHealth(
            state="ok",
            details={"reachable": ok, "total": len(cfg.devices), "errors": errors},
        )

    async def poll_once(self) -> tuple[int, dict[str, Any]]:
        cfg: KasaConfig = self._cfg  # type: ignore[assignment]
        if not cfg.devices:
            return 0, {"reason": "no devices"}
        rows = 0
        now = time.time()
        for d in cfg.devices:
            try:
                sysinfo_resp = await _kasa_query(
                    d.ip, {"system": {"get_sysinfo": {}}}, cfg.request_timeout_seconds
                )
            except KasaError:
                continue
            sysinfo = (
                sysinfo_resp.get("system", {}).get("get_sysinfo", {}) or {}
            )
            relay_state = sysinfo.get("relay_state")
            brightness = sysinfo.get("brightness")
            node_id = f"kasa:{d.ip}"
            if isinstance(relay_state, int):
                await store_reading(node_id, "actuator_state", float(relay_state), now)
                rows += 1
            if d.is_dimmer and isinstance(brightness, int):
                await store_reading(node_id, "dimming_percent", float(brightness), now)
                rows += 1
            if d.has_emeter:
                try:
                    emeter_resp = await _kasa_query(
                        d.ip,
                        {"emeter": {"get_realtime": {}}},
                        cfg.request_timeout_seconds,
                    )
                    realtime = emeter_resp.get("emeter", {}).get("get_realtime", {}) or {}
                    power_mw = realtime.get("power_mw")
                    power_w = realtime.get("power")
                    if isinstance(power_mw, (int, float)):
                        await store_reading(node_id, "power_w", float(power_mw) / 1000.0, now)
                        rows += 1
                    elif isinstance(power_w, (int, float)):
                        await store_reading(node_id, "power_w", float(power_w), now)
                        rows += 1
                except KasaError:
                    pass
        return rows, {"rows": rows, "devices": len(cfg.devices)}

    # ── Write paths ────────────────────────────────────────────────

    async def set_power(self, ip: str, on: bool) -> dict[str, Any]:
        cfg: KasaConfig = self._cfg  # type: ignore[assignment]
        timeout = cfg.request_timeout_seconds if cfg else 5.0
        await _kasa_query(
            ip, {"system": {"set_relay_state": {"state": 1 if on else 0}}}, timeout
        )
        return {"ip": ip, "state": "on" if on else "off"}

    async def set_dim(self, ip: str, percent: int) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be in [0, 100]")
        cfg: KasaConfig = self._cfg  # type: ignore[assignment]
        timeout = cfg.request_timeout_seconds if cfg else 5.0
        await _kasa_query(
            ip,
            {"smartlife.iot.dimmer": {"set_brightness": {"brightness": percent}}},
            timeout,
        )
        return {"ip": ip, "percent": percent}
