"""The Pulse Grow local-mode transport.

Discovery runs against a fake datagram socket (no real UDP traffic) and the
HTTP polling against a faked httpx client.

* The discovery parser takes a JSON device id (or its id / serial aliases)
  and falls back to the source IP for anything else; explicit device URLs
  skip the scan.
* A local-mode poll reads each device's /api/recent-data and stores the
  readings; a device error, an unreachable device or an unreadable reply is
  a PulseError, and an id outside the discovered set is refused before any
  request.
* Local-mode Test needs no account: it reports the devices it found.

Live-device verification: the discovery reply format is inferred from
secondary sources, so the parser is tolerant by design; growing it is
additive (new branches in ``_parse_discovery_response``).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.integrations.pulse.client import PulseError
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse.driver import PulseDriver
from app.integrations.pulse.local_transport import (
    PulseLocalTransport,
    _parse_discovery_response,
    discover_devices,
)
from app.integrations.pulse.models import PulseDevice, PulseDeviceListResponse
from tests._pi_c1_integrations import stored_readings


# ── Discovery parser ──────────────────────────────────────────────────


@pytest.mark.parametrize("payload,device_id", [
    (json.dumps({"device_id": "abc-123"}).encode(), "abc-123"),
    (json.dumps({"serial": "PULSE-SN-001"}).encode(), "PULSE-SN-001"),
    (b"\x00\x01\x02", "local:10.0.0.42"),
], ids=["device-id", "serial-alias", "unparseable"])
def test_a_discovery_reply_names_its_device_by_id_or_by_source_ip(payload, device_id):
    parsed = _parse_discovery_response(payload, source_ip="10.0.0.42")
    assert (parsed.device_id, parsed.base_url) == (device_id, "http://10.0.0.42")


# ── discover_devices ──────────────────────────────────────────────────


async def test_discover_skips_udp_when_local_device_urls_set():
    cfg = PulseConfig(
        transport="local",
        local_device_urls=["http://10.0.0.5", "http://10.0.0.6/"],
    )
    devices = await discover_devices(cfg, sock_factory=lambda: pytest.fail("no UDP scan"))
    # Trailing / stripped, source URL preserved as the device id token.
    assert [d.base_url for d in devices] == ["http://10.0.0.5", "http://10.0.0.6"]


class _FakeUdpSocket:
    """Stand-in datagram socket; the loop's sock_sendto / sock_recvfrom are
    faked around it."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


async def test_udp_scan_collects_responses_until_the_window_closes(monkeypatch):
    cfg = PulseConfig(
        transport="local",
        local_broadcast_addr="255.255.255.255",
        local_discovery_port=5683,
    # A short window (the config's floor is a whole second): the fake socket
    # goes quiet after two replies and the scan must end on the window.
    ).model_copy(update={"local_discovery_timeout_seconds": 0.05})

    fake_responses = [
        (json.dumps({"device_id": "alpha"}).encode(), "10.0.0.5"),
        (json.dumps({"device_id": "beta"}).encode(), "10.0.0.6"),
    ]
    sock = _FakeUdpSocket()
    sent_packets: list[tuple[bytes, tuple[str, int]]] = []

    async def fake_sendto(s, data, addr):
        sent_packets.append((data, addr))

    async def fake_recvfrom(s, n):
        if not fake_responses:
            await asyncio.Event().wait()  # no more responders
        data, ip = fake_responses.pop(0)
        return data, (ip, cfg.local_discovery_port)

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "sock_sendto", fake_sendto)
    monkeypatch.setattr(loop, "sock_recvfrom", fake_recvfrom)

    devices = await discover_devices(cfg, sock_factory=lambda: sock)
    assert sock.closed
    assert sorted(d.device_id for d in devices) == ["alpha", "beta"]
    # The probe was actually sent to the configured broadcast address.
    assert sent_packets[0][1] == ("255.255.255.255", 5683)


# ── Local-mode polling ────────────────────────────────────────────────


async def test_a_local_mode_poll_reads_each_device_url_and_stores_its_readings(monkeypatch):
    seen: list[str] = []

    async def fake_get(self, url):
        seen.append(str(url))
        return httpx.Response(200, json={"measurements": [
            {"type": "temperature", "value": 22.0},
            {"type": "humidity", "value": 88.0},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    drv = PulseDriver()
    await drv.configure(PulseConfig(transport="local", local_device_urls=["http://10.0.0.5"],
                                    local_http_port=8081))
    rows, diag = await drv.poll_once()
    assert (rows, diag["failed"]) == (2, {})
    assert seen == ["http://10.0.0.5:8081/api/recent-data"]
    assert await stored_readings("pulse:local:http://10.0.0.5") == {
        ("temp_c", 22.0), ("humidity", 88.0)}


def _unreachable(url):
    raise httpx.ConnectError("no route to host", request=httpx.Request("GET", url))


@pytest.mark.parametrize("reply,error", [
    (lambda url: httpx.Response(503, text="overloaded"), "HTTP 503"),
    (_unreachable, "local transport error"),
    (lambda url: httpx.Response(200, text="<html>setup</html>"), "unexpected response"),
], ids=["5xx", "unreachable", "not-json"])
async def test_local_device_failures_are_pulse_errors(monkeypatch, reply, error):
    async def fake_get(self, url):
        return reply(url)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    transport = PulseLocalTransport(PulseConfig(transport="local",
                                                local_device_urls=["http://10.0.0.5"]))
    devices = await transport.list_devices()
    with pytest.raises(PulseError, match=error):
        await transport.recent_data(devices.devices[0].id)


async def test_local_transport_unknown_device_id_raises(monkeypatch):
    async def fake_get(self, url):  # pragma: no cover — should not be called
        raise AssertionError("recent_data should fail before the HTTP call")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    transport = PulseLocalTransport(PulseConfig(transport="local",
                                                local_device_urls=["http://10.0.0.5"]))
    await transport.list_devices()
    with pytest.raises(PulseError, match="not in discovered set"):
        await transport.recent_data("totally-unknown")


# ── Local-mode Test ───────────────────────────────────────────────────


@pytest.mark.parametrize("found", [1, 0], ids=["one-device", "nothing-on-the-lan"])
async def test_local_mode_test_needs_no_account_and_reports_what_it_found(monkeypatch, found):
    async def fake_list_devices(self):
        return PulseDeviceListResponse(devices=[PulseDevice(id="x")] * found)

    monkeypatch.setattr(PulseLocalTransport, "list_devices", fake_list_devices)

    drv = PulseDriver()
    # No email or password: those are cloud-only.
    await drv.configure(PulseConfig(transport="local", local_device_urls=["http://10.0.0.5"]))
    health = await drv.test_connection()
    # Empty discovery is "ok" — there's just nothing on the LAN to find.
    assert health.state == "ok"
    assert health.details["transport"] == "local"
    assert health.details["devices_seen"] == found
