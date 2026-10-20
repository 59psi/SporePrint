"""The vendor-action dispatcher's surface and the Wemo / Kasa write wire formats.

* VENDOR_ACTIONS is the whole write surface the cloud-web UI can reach; an
  unknown vendor or action is a 404. (What each vendor's write sends, and
  that a caller's mistake is a 400 and a vendor's failure a 502, is pinned
  per vendor in test_integrations_v411_drivers.py.)
* Wemo switches a plug with a SOAP SetBinaryState; Kasa sends the documented
  JSON, XOR-ciphered, to port 9999.
* The actions routes list a vendor's controls, and a manual write reaches
  the device and then every vendor-write listener (the safety ceiling's
  bookkeeping), none of which can fail a write that already went out.
* The cloud's vendor_action RPC needs the inner action.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.cloud import integrations_proxy
from app.config import settings
from app.integrations import _actions
from app.integrations.bios.driver import BiosConfig, BiosDriver
from app.integrations.kasa.driver import KasaConfig, KasaDriver, _decrypt, _encrypt
from app.integrations.wemo.driver import WemoConfig, WemoDriver
from tests._pi_c1_integrations import route_httpx, use_drivers


# ── Vendor-actions dispatcher ────────────────────────────────────────


def test_vendor_actions_map_covers_every_writable_vendor():
    """Tripwire: every vendor with a writable action shows up in
    VENDOR_ACTIONS exactly once. Adding a write method without
    advertising it here means the cloud-web UI can't reach it."""
    expected = {
        "fluence": {"set_dim"},
        "fohse": {"set_dim"},
        "bios": {"set_dim"},
        "trane": {"set_setpoint"},
        "agrowtek": {"set_output"},
        "quest": {"set_setpoint"},
        "anden": {"set_setpoint"},
        "wemo": {"set_power"},
        "kasa": {"set_power", "set_dim"},
        "tapo": {"set_power", "set_dim"},
    }
    actual = {slug: set(actions.keys()) for slug, actions in _actions.VENDOR_ACTIONS.items()}
    assert actual == expected


@pytest.mark.parametrize("slug,action", [("unknown", "set_dim"), ("fluence", "nuke_fixture")],
                         ids=["unknown-vendor", "unsupported-action"])
async def test_an_unknown_vendor_or_action_is_a_404(slug, action):
    with pytest.raises(HTTPException) as exc_info:
        await _actions.dispatch(slug, action, {})
    assert exc_info.value.status_code == 404


def test_the_actions_routes_list_controls_and_send_a_manual_write_to_every_listener(monkeypatch):
    drv = BiosDriver()
    asyncio.run(drv.configure(BiosConfig(base_url="http://10.0.0.55")))
    use_drivers(monkeypatch, drv)
    sent: list[tuple[str, dict]] = []

    def vendor(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    route_httpx(monkeypatch, vendor)
    heard: list[tuple] = []

    async def listener(slug, action, params, *, sent_at):
        heard.append((slug, action, params, sent_at))

    async def broken(slug, action, params, *, sent_at):
        raise RuntimeError("listener bug")

    # The engine's own listener (the safety ceiling) stays registered.
    monkeypatch.setattr(_actions, "_write_listeners", [broken, *_actions._write_listeners, listener])
    app = FastAPI()
    app.include_router(_actions.router, prefix="/api/integrations")
    with TestClient(app) as client:
        assert client.get("/api/integrations/bios/actions").json() == {
            "slug": "bios", "actions": ["set_dim"]}
        assert client.get("/api/integrations/nope/actions").json() == {
            "slug": "nope", "actions": []}
        before = time.time()
        resp = client.post("/api/integrations/bios/actions/set_dim",
                           json={"fixture_id": "f1", "percent": "40"})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"fixture_id": "f1", "percent": 40}
    assert sent == [("/api/fixtures/f1/dim", {"dim": 40})]
    # Told after the write went out, with the parsed params and the time it
    # was sent; the listener that raised did not turn the write into an error.
    [(slug, action, params, sent_at)] = heard
    assert (slug, action, params) == ("bios", "set_dim", {"fixture_id": "f1", "percent": 40})
    assert before <= sent_at <= time.time()


# ── Wemo SOAP ────────────────────────────────────────────────────────


async def test_wemo_set_power_emits_correct_soap(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_post(self, url, content=None, headers=None):
        captured["url"] = url
        captured["body"] = content
        return httpx.Response(200, text="<Envelope/>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.10"}]))
    await drv.set_power("10.0.0.10", True)
    assert "<BinaryState>1</BinaryState>" in captured["body"]
    assert "10.0.0.10" in captured["url"]
    await drv.set_power("10.0.0.10", False)
    assert "<BinaryState>0</BinaryState>" in captured["body"]


@pytest.mark.parametrize("status,state", [(200, "ok"), (503, "error")])
async def test_wemo_test_reports_whether_the_plug_answered(monkeypatch, status, state):
    async def fake_post(self, url, content=None, headers=None):
        return httpx.Response(
            status,
            text="<Envelope><Body><GetBinaryStateResponse><BinaryState>1</BinaryState>"
                 "</GetBinaryStateResponse></Body></Envelope>",
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.10"}]))
    assert (await drv.test_connection()).state == state


# ── Kasa wire format ─────────────────────────────────────────────────


def test_kasa_decrypt_short_buffer_raises():
    with pytest.raises(ValueError, match="length prefix"):
        _decrypt(b"\x00")


async def test_kasa_query_writes_correct_command(monkeypatch):
    """The ON command sent over the wire must decrypt to the documented
    JSON body — protects against accidental cipher-key drift."""
    captured: dict[str, Any] = {}

    class FakeWriter:
        def __init__(self) -> None:
            self.buffer = bytearray()

        def write(self, data: bytes) -> None:
            self.buffer.extend(data)

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    class FakeReader:
        # The driver reads the 4-byte length header, then exactly that many
        # body bytes (a reply can span several TCP segments).
        def __init__(self):
            self._buf = _encrypt(json.dumps({"system": {"set_relay_state": {"err_code": 0}}}))

        async def readexactly(self, n):
            chunk, self._buf = self._buf[:n], self._buf[n:]
            return chunk

    async def fake_open_connection(host, port):
        captured["host"] = host
        captured["port"] = port
        writer = FakeWriter()
        captured["writer"] = writer
        return FakeReader(), writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.20"}]))
    assert await drv.set_power("10.0.0.20", True) == {"ip": "10.0.0.20", "state": "on"}
    assert captured["host"] == "10.0.0.20"
    assert captured["port"] == 9999
    sent = bytes(captured["writer"].buffer)
    assert json.loads(_decrypt(sent)) == {"system": {"set_relay_state": {"state": 1}}}


# ── Cloud-bound RPC ──────────────────────────────────────────────────


async def test_rpc_vendor_action_without_inner_action_returns_400(monkeypatch):
    # An unsigned frame with strict signing off (the gate has its own suite,
    # test_cloud_integrations_signing.py).
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)

    class FakeSio:
        def __init__(self):
            self.emits = []

        async def emit(self, event, data):
            self.emits.append((event, data))

    sio = FakeSio()
    await integrations_proxy.handle_request(
        sio,
        {
            "id": "x",
            "action": "vendor_action",
            "slug": "bios",
            "payload": {"fixture_id": "f1"},  # missing inner action
        },
    )
    payload = sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 400
