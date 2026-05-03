"""Wemo SOAP driver — on/off + Insight power monitoring."""

from __future__ import annotations

import re
import time
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from .._base import IntegrationHealth
from .._http_skeleton import HttpVendorDriver
from ...telemetry.service import store_reading


# Wemo plugs respond on either port; we hit basicevent1 first then
# fall back. The Insight ALSO exposes /upnp/control/insight1 for power
# stats which we attempt only when the device replies as an Insight.
_WEMO_PORT = 49153

_GET_STATE_BODY = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body><u:GetBinaryState xmlns:u="urn:Belkin:service:basicevent:1"/></s:Body>
</s:Envelope>"""

_SET_STATE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body>
  <u:SetBinaryState xmlns:u="urn:Belkin:service:basicevent:1">
    <BinaryState>{state}</BinaryState>
  </u:SetBinaryState>
</s:Body>
</s:Envelope>"""

_GET_INSIGHT_BODY = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body><u:GetInsightParams xmlns:u="urn:Belkin:service:insight:1"/></s:Body>
</s:Envelope>"""


class WemoDeviceMapping(BaseModel):
    ip: str
    chamber_id: str = ""
    actuator: str = "wemo"
    is_insight: bool = False


class WemoConfig(BaseModel):
    devices: list[WemoDeviceMapping] = Field(default_factory=list)
    poll_seconds: int = Field(default=60, ge=15, le=3600)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)

    @field_validator("devices")
    @classmethod
    def _check_ips(cls, devices: list[WemoDeviceMapping]) -> list[WemoDeviceMapping]:
        for d in devices:
            if not d.ip:
                continue
            parsed = urlparse(f"//{d.ip}")
            if not parsed.hostname:
                raise ValueError(f"invalid ip in devices: {d.ip!r}")
        return devices


class WemoError(RuntimeError):
    pass


class WemoDriver(HttpVendorDriver):
    name: ClassVar[str] = "wemo"
    tier_required: ClassVar[str] = "free"
    config_schema: ClassVar[type[BaseModel]] = WemoConfig
    secret_fields: ClassVar[set[str]] = set()

    async def test_connection(self) -> IntegrationHealth:
        cfg: WemoConfig | None = self._cfg  # type: ignore[assignment]
        if cfg is None or not cfg.devices:
            return IntegrationHealth(state="error", last_error="no devices configured")
        ok = 0
        errors: list[str] = []
        for d in cfg.devices:
            try:
                await self._get_state(d.ip, cfg.request_timeout_seconds)
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
        cfg: WemoConfig = self._cfg  # type: ignore[assignment]
        if not cfg.devices:
            return 0, {"reason": "no devices"}
        rows = 0
        now = time.time()
        for d in cfg.devices:
            try:
                state = await self._get_state(d.ip, cfg.request_timeout_seconds)
            except WemoError:
                continue
            node_id = f"wemo:{d.ip}"
            await store_reading(node_id, "actuator_state", float(state), now)
            rows += 1
            if d.is_insight:
                try:
                    power_w = await self._get_insight_power(d.ip, cfg.request_timeout_seconds)
                except WemoError:
                    power_w = None
                if power_w is not None:
                    await store_reading(node_id, "power_w", power_w, now)
                    rows += 1
        return rows, {"rows": rows, "devices": len(cfg.devices)}

    # ── Write paths ────────────────────────────────────────────────

    async def set_power(self, ip: str, on: bool) -> dict[str, Any]:
        cfg: WemoConfig = self._cfg  # type: ignore[assignment]
        timeout = cfg.request_timeout_seconds if cfg else 5.0
        body = _SET_STATE_TEMPLATE.format(state=1 if on else 0)
        await self._soap_post(
            ip,
            "/upnp/control/basicevent1",
            "urn:Belkin:service:basicevent:1#SetBinaryState",
            body,
            timeout,
        )
        return {"ip": ip, "state": "on" if on else "off"}

    # ── Helpers ────────────────────────────────────────────────────

    async def _get_state(self, ip: str, timeout: float) -> int:
        text = await self._soap_post(
            ip,
            "/upnp/control/basicevent1",
            "urn:Belkin:service:basicevent:1#GetBinaryState",
            _GET_STATE_BODY,
            timeout,
        )
        m = re.search(r"<BinaryState>([01])</BinaryState>", text)
        if m is None:
            raise WemoError(f"unexpected GetBinaryState response: {text[:200]!r}")
        return int(m.group(1))

    async def _get_insight_power(self, ip: str, timeout: float) -> float | None:
        try:
            text = await self._soap_post(
                ip,
                "/upnp/control/insight1",
                "urn:Belkin:service:insight:1#GetInsightParams",
                _GET_INSIGHT_BODY,
                timeout,
            )
        except WemoError:
            return None
        m = re.search(r"<InsightParams>([^<]+)</InsightParams>", text)
        if m is None:
            return None
        # Field 8 of the pipe-delimited string is current-mW.
        parts = m.group(1).split("|")
        if len(parts) < 8:
            return None
        try:
            return float(parts[7]) / 1000.0  # mW → W
        except (ValueError, IndexError):
            return None

    async def _soap_post(
        self,
        ip: str,
        path: str,
        action: str,
        body: str,
        timeout: float,
    ) -> str:
        url = f"http://{ip}:{_WEMO_PORT}{path}"
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPACTION": f'"{action}"',
                },
            )
        if resp.status_code >= 400:
            raise WemoError(f"HTTP {resp.status_code} from {ip}: {resp.text[:200]!r}")
        return resp.text
