"""Tests for the Pulse Grow local-mode transport.

Discovery is exercised against a fake datagram socket so we don't depend
on a real Pulse device or actual UDP traffic. HTTP polling is exercised
against an injected `httpx.AsyncClient`-shaped stub.

Live-device verification: the discovery response parser is tolerant of
JSON, source-IP-only, and unknown payloads — these tests pin that
contract. The exact bytes a real Pulse device emits will be confirmed
against hardware in v4.1.x; if the parser needs to grow new logic, that
will be additive (new branches in `_parse_discovery_response`) rather
than a structural change.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations.pulse import local_transport
from app.integrations.pulse.client import PulseError
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse.driver import PulseDriver
from app.integrations.pulse.local_transport import (
    DiscoveredPulseDevice,
    PulseLocalTransport,
    _parse_discovery_response,
    discover_devices,
)


# ── Discovery parser ──────────────────────────────────────────────────


def test_parse_discovery_handles_plain_json_with_device_id():
    payload = json.dumps({"device_id": "abc-123"}).encode("utf-8")
    parsed = _parse_discovery_response(payload, source_ip="10.0.0.42")
    assert parsed is not None
    assert parsed.device_id == "abc-123"
    assert parsed.base_url == "http://10.0.0.42"


def test_parse_discovery_falls_back_to_source_ip_on_unparseable():
    parsed = _parse_discovery_response(b"\x00\x01\x02", source_ip="10.0.0.99")
    assert parsed is not None
    assert parsed.device_id == "local:10.0.0.99"


def test_parse_discovery_uses_id_or_serial_aliases():
    payload = json.dumps({"serial": "PULSE-SN-001"}).encode("utf-8")
    parsed = _parse_discovery_response(payload, source_ip="10.0.0.5")
    assert parsed is not None
    assert parsed.device_id == "PULSE-SN-001"


# ── discover_devices: explicit URL list bypasses scan ─────────────────


@pytest.mark.asyncio
async def test_discover_skips_udp_when_local_device_urls_set():
    cfg = PulseConfig(
        transport="local",
        local_device_urls=["http://10.0.0.5", "http://10.0.0.6/"],
    )
    devices = await discover_devices(cfg)
    assert len(devices) == 2
    # Trailing / stripped, source URL preserved as the device id token.
    assert all(d.base_url.startswith("http://10.0.0.") for d in devices)
    assert devices[1].base_url == "http://10.0.0.6"


# ── discover_devices: UDP scan with a fake socket ─────────────────────


class _FakeUdpSocket:
    """Stand-in datagram socket that scripts a sequence of recv responses
    then signals end-of-window via TimeoutError on the next recv.
    """

    def __init__(self, responses: list[tuple[bytes, str]]):
        self._responses = list(responses)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def fileno(self) -> int:
        # Not actually used in our async path; keep it cheap.
        return -1

    def setsockopt(self, *args, **kwargs):
        pass

    def setblocking(self, flag: bool):
        pass

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_udp_scan_collects_responses(monkeypatch):
    cfg = PulseConfig(
        transport="local",
        local_broadcast_addr="255.255.255.255",
        local_discovery_port=5683,
        local_discovery_timeout_seconds=1.0,
    )

    fake_responses = [
        (json.dumps({"device_id": "alpha"}).encode(), "10.0.0.5"),
        (json.dumps({"device_id": "beta"}).encode(), "10.0.0.6"),
    ]

    sock = _FakeUdpSocket(fake_responses)
    sent_packets: list[tuple[bytes, tuple[str, int]]] = []
    recv_index = {"i": 0}

    async def fake_sendto(s, data, addr):
        sent_packets.append((data, addr))

    async def fake_recvfrom(s, n):
        i = recv_index["i"]
        if i >= len(fake_responses):
            # Block until the timeout window elapses — emulate "no more
            # responders" without actually sleeping forever.
            await asyncio.sleep(10)
            raise AssertionError("recvfrom should have timed out")
        recv_index["i"] += 1
        data, ip = fake_responses[i]
        return data, (ip, cfg.local_discovery_port)

    loop = asyncio.get_event_loop()
    monkeypatch.setattr(loop, "sock_sendto", fake_sendto)
    monkeypatch.setattr(loop, "sock_recvfrom", fake_recvfrom)

    devices = await discover_devices(cfg, sock_factory=lambda: sock)
    assert sock.closed
    ids = sorted(d.device_id for d in devices)
    assert ids == ["alpha", "beta"]
    # The probe was actually sent to the configured broadcast address.
    assert sent_packets[0][1] == ("255.255.255.255", 5683)


# ── PulseLocalTransport HTTP polling ──────────────────────────────────


@pytest.mark.asyncio
async def test_local_transport_recent_data_calls_per_device_url(monkeypatch):
    cfg = PulseConfig(
        transport="local",
        local_device_urls=["http://10.0.0.5"],
        local_http_port=80,
    )

    captured = {}

    async def fake_get(self, url):
        captured["url"] = url
        return httpx.Response(
            200,
            json={
                "measurements": [
                    {"type": "temperature", "value": 22.0},
                    {"type": "humidity", "value": 88.0},
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    transport = PulseLocalTransport(cfg)
    devices = await transport.list_devices()
    assert len(devices.devices) == 1
    response = await transport.recent_data(devices.devices[0].id)
    assert "10.0.0.5" in captured["url"]
    assert "/api/recent-data" in captured["url"]
    assert len(response.measurements) == 2


@pytest.mark.asyncio
async def test_local_transport_5xx_raises_pulse_error(monkeypatch):
    cfg = PulseConfig(
        transport="local",
        local_device_urls=["http://10.0.0.5"],
    )

    async def fake_get(self, url):
        return httpx.Response(503, text="overloaded")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    transport = PulseLocalTransport(cfg)
    devices = await transport.list_devices()
    with pytest.raises(PulseError, match="HTTP 503"):
        await transport.recent_data(devices.devices[0].id)


@pytest.mark.asyncio
async def test_local_transport_unknown_device_id_raises(monkeypatch):
    cfg = PulseConfig(
        transport="local",
        local_device_urls=["http://10.0.0.5"],
    )

    async def fake_get(self, url):  # pragma: no cover — should not be called
        raise AssertionError("recent_data should fail before the HTTP call")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    transport = PulseLocalTransport(cfg)
    await transport.list_devices()
    with pytest.raises(PulseError, match="not in discovered set"):
        await transport.recent_data("totally-unknown")


# ── Driver routes traffic through local transport ────────────────────


@pytest.mark.asyncio
async def test_driver_test_connection_uses_local_transport_when_configured(
    tmp_path, monkeypatch
):
    from app.config import settings
    from app.integrations._keystore import reset_fernet_cache

    monkeypatch.setattr(
        settings, "integration_key_path", str(tmp_path / ".int-key")
    )
    reset_fernet_cache()

    async def fake_list_devices(self):
        from app.integrations.pulse.models import (
            PulseDevice,
            PulseDeviceListResponse,
        )
        return PulseDeviceListResponse(devices=[PulseDevice(id="x")])

    monkeypatch.setattr(PulseLocalTransport, "list_devices", fake_list_devices)

    drv = PulseDriver()
    await drv.configure(
        PulseConfig(
            transport="local",
            local_device_urls=["http://10.0.0.5"],
        )
    )
    health = await drv.test_connection()
    assert health.state == "ok"
    assert health.details["transport"] == "local"
    assert health.details["devices_seen"] == 1


@pytest.mark.asyncio
async def test_driver_local_mode_does_not_require_email_password(
    tmp_path, monkeypatch
):
    """Local-mode test_connection must not error on missing creds —
    those are cloud-only.
    """
    from app.config import settings
    from app.integrations._keystore import reset_fernet_cache

    monkeypatch.setattr(
        settings, "integration_key_path", str(tmp_path / ".int-key")
    )
    reset_fernet_cache()

    async def fake_list_devices(self):
        from app.integrations.pulse.models import PulseDeviceListResponse
        return PulseDeviceListResponse(devices=[])

    monkeypatch.setattr(PulseLocalTransport, "list_devices", fake_list_devices)

    drv = PulseDriver()
    await drv.configure(
        PulseConfig(transport="local", local_device_urls=["http://10.0.0.5"])
    )
    health = await drv.test_connection()
    # Empty discovery is "ok" — there's just nothing on the LAN to find.
    assert health.state == "ok"


# ── Config ────────────────────────────────────────────────────────────


def test_config_default_transport_is_cloud():
    cfg = PulseConfig()
    assert cfg.transport == "cloud"


def test_config_local_mode_with_explicit_urls():
    cfg = PulseConfig(
        transport="local",
        local_device_urls=["http://10.0.0.5", "http://10.0.0.6"],
    )
    assert cfg.transport == "local"
    assert len(cfg.local_device_urls) == 2


def test_config_local_mode_floor_is_30s():
    """Local has a lower poll floor than cloud (no rate limit), but
    still 30 s minimum for sane device load.
    """
    with pytest.raises(ValueError):
        PulseConfig(transport="local", poll_seconds=10)


def test_config_local_discovery_timeout_bounds():
    cfg = PulseConfig(transport="local", local_discovery_timeout_seconds=5.0)
    assert cfg.local_discovery_timeout_seconds == 5.0
    with pytest.raises(ValueError):
        PulseConfig(transport="local", local_discovery_timeout_seconds=0.5)
