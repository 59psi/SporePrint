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

from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from .._net import split_host_port
from ...telemetry.service import store_readings


_KASA_PORT = 9999
_KEY_SEED = 0xAB
# Upper bound on one response frame. Multi-outlet strips (HS300/KP303) return
# a few KB of sysinfo; anything this large is not a Kasa reply.
_MAX_FRAME_BYTES = 256 * 1024


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
    # Accepted but not used yet: readings are stored as kasa:<ip> in no chamber.
    chamber_id: str = ""
    actuator: str = "kasa"
    is_dimmer: bool = False
    has_emeter: bool = False

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        if not v:
            return v
        split_host_port(v)
        return v


class KasaConfig(BaseModel):
    devices: list[KasaDeviceMapping] = Field(default_factory=list)
    poll_seconds: int = Field(default=60, ge=15, le=3600)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)


class KasaError(RuntimeError):
    pass


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read one complete length-prefixed frame (header + body).

    A single ``read()`` returns whatever one TCP segment delivered; replies
    larger than ~1460 bytes (multi-outlet sysinfo) arrive in several, and the
    device keeps the socket open, so read exactly the advertised length.
    """
    header = await reader.readexactly(4)
    length = struct.unpack("!I", header)[0]
    if length > _MAX_FRAME_BYTES:
        raise KasaError(f"kasa frame too large ({length} bytes)")
    return header + await reader.readexactly(length)


async def _kasa_query(ip: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Send one JSON request, await one response. Connection per call —
    Kasa devices accept this fine and it keeps state minimal."""
    host, port = split_host_port(ip)
    port = port or _KASA_PORT
    text = json.dumps(payload, separators=(",", ":"))
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise KasaError(f"connect to {host}:{port} failed: {exc}") from exc
    try:
        writer.write(_encrypt(text))
        await writer.drain()
        buf = await asyncio.wait_for(_read_frame(reader), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise KasaError(f"read from {ip} timed out") from exc
    except asyncio.IncompleteReadError as exc:
        raise KasaError(f"{ip} closed the connection mid-frame") from exc
    except OSError as exc:
        # A reset or broken pipe mid-exchange (TimeoutError, also an OSError,
        # is handled above for its message): the device failed, not the poll.
        raise KasaError(f"{ip}: connection failed mid-exchange: {exc}") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
    raw = _decrypt(buf)
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KasaError(f"non-JSON response from {ip}: {exc}") from exc
    if not isinstance(reply, dict):
        raise KasaError(f"unexpected response from {ip}: {raw[:200]!r}")
    return reply


def _raise_for_err_code(obj: dict[str, Any], ip: str, where: str) -> None:
    code = obj.get("err_code")
    if isinstance(code, int) and not isinstance(code, bool) and code != 0:
        msg = obj.get("err_msg")
        detail = f": {msg}" if msg else ""
        raise KasaError(f"{ip}: {where} refused (err_code {code}{detail})")


def _module_reply(
    resp: dict[str, Any], module: str, method: str, ip: str
) -> dict[str, Any]:
    """``resp[module][method]``, raising KasaError when the device refused.

    A Kasa device reports a refused command inside the reply, not on the
    transport: a non-zero ``err_code`` next to the method's result, or one
    at module level with no method key at all (``{"smartlife.iot.dimmer":
    {"err_code": -1, "err_msg": "module not support"}}`` from a plug that is
    not a dimmer). A reply without a code is success.
    """
    mod = resp.get(module)
    if not isinstance(mod, dict):
        return {}
    _raise_for_err_code(mod, ip, module)
    body = mod.get(method)
    if not isinstance(body, dict):
        return {}
    _raise_for_err_code(body, ip, f"{module}.{method}")
    return body


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
                _module_reply(
                    await _kasa_query(
                        d.ip, {"system": {"get_sysinfo": {}}}, cfg.request_timeout_seconds
                    ),
                    "system", "get_sysinfo", d.ip,
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
            raise KasaError("no devices configured")
        readings: list[tuple[float, str, str, float]] = []
        failed: dict[str, str] = {}
        now = time.time()
        for i, d in enumerate(cfg.devices):
            try:
                readings.extend(await self._poll_device(cfg, d, now))
            except Exception as exc:  # noqa: BLE001 — one plug must not stop the rest
                failed[d.ip or f"device {i + 1}"] = str(exc)
        # One transaction for the whole poll, not a commit per reading.
        rows = await store_readings(readings)
        return rows, {"rows": rows, "devices": len(cfg.devices), "failed": failed}

    async def _poll_device(
        self, cfg: KasaConfig, d: KasaDeviceMapping, now: float
    ) -> list[tuple[float, str, str, float]]:
        """One plug's (timestamp, node id, sensor, value) readings."""
        sysinfo = _module_reply(
            await _kasa_query(
                d.ip, {"system": {"get_sysinfo": {}}}, cfg.request_timeout_seconds
            ),
            "system", "get_sysinfo", d.ip,
        )
        readings: list[tuple[float, str, str, float]] = []
        relay_state = sysinfo.get("relay_state")
        brightness = sysinfo.get("brightness")
        node_id = f"kasa:{d.ip}"
        if isinstance(relay_state, int):
            readings.append((now, node_id, "actuator_state", float(relay_state)))
        if d.is_dimmer and isinstance(brightness, int):
            readings.append((now, node_id, "dimming_percent", float(brightness)))
        if d.has_emeter:
            try:
                realtime = _module_reply(
                    await _kasa_query(
                        d.ip,
                        {"emeter": {"get_realtime": {}}},
                        cfg.request_timeout_seconds,
                    ),
                    "emeter", "get_realtime", d.ip,
                )
            except KasaError:
                # The plug answered; a missing or failing energy meter costs
                # only its power reading.
                return readings
            power_mw = realtime.get("power_mw")
            power_w = realtime.get("power")
            if isinstance(power_mw, (int, float)):
                readings.append((now, node_id, "power_w", float(power_mw) / 1000.0))
            elif isinstance(power_w, (int, float)):
                readings.append((now, node_id, "power_w", float(power_w)))
        return readings

    # ── Write paths ────────────────────────────────────────────────

    async def set_power(self, ip: str, on: bool) -> dict[str, Any]:
        cfg: KasaConfig = self._cfg  # type: ignore[assignment]
        timeout = cfg.request_timeout_seconds if cfg else 5.0
        resp = await _kasa_query(
            ip, {"system": {"set_relay_state": {"state": 1 if on else 0}}}, timeout
        )
        # A refused command must fail the write (dispatch → 502), never read
        # as delivered: a safety OFF counted as sent stops being retried.
        _module_reply(resp, "system", "set_relay_state", ip)
        return {"ip": ip, "state": "on" if on else "off"}

    async def set_dim(self, ip: str, percent: int) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be in [0, 100]")
        cfg: KasaConfig = self._cfg  # type: ignore[assignment]
        timeout = cfg.request_timeout_seconds if cfg else 5.0
        resp = await _kasa_query(
            ip,
            {"smartlife.iot.dimmer": {"set_brightness": {"brightness": percent}}},
            timeout,
        )
        _module_reply(resp, "smartlife.iot.dimmer", "set_brightness", ip)
        return {"ip": ip, "percent": percent}
