"""Tests for v4.1.2 vendor write paths + Wemo + Kasa drivers."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations import _actions, _registry
from app.integrations._keystore import reset_fernet_cache


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


# ── Wemo + Kasa register ─────────────────────────────────────────────


@pytest.mark.parametrize("slug", ["wemo", "kasa"])
def test_smart_plug_drivers_registered(slug):
    drv = _registry.registered_drivers().get(slug)
    assert drv is not None
    assert drv.tier_required == "free"


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
    }
    actual = {slug: set(actions.keys()) for slug, actions in _actions.VENDOR_ACTIONS.items()}
    assert actual == expected


@pytest.mark.asyncio
async def test_dispatch_unknown_vendor_raises_404(fresh_keystore):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await _actions.dispatch("unknown", "set_dim", {})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_unsupported_action_raises_404(fresh_keystore):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await _actions.dispatch("fluence", "nuke_fixture", {})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_filters_unknown_kwargs(fresh_keystore, monkeypatch):
    """Stray fields in the payload must not blow up the call —
    dispatch should only forward kwargs the method actually accepts.
    """
    drv = _registry.registered_drivers()["bios"]
    captured: dict[str, Any] = {}

    async def fake_set_dim(self, fixture_id: str, percent: int):
        captured["fixture_id"] = fixture_id
        captured["percent"] = percent
        return {"ok": True}

    monkeypatch.setattr(type(drv), "set_dim", fake_set_dim)
    result = await _actions.dispatch(
        "bios",
        "set_dim",
        {"fixture_id": "f1", "percent": 75, "extra": "ignored", "another": 42},
    )
    assert result == {"ok": True}
    assert captured == {"fixture_id": "f1", "percent": 75}


@pytest.mark.asyncio
async def test_dispatch_value_error_becomes_400(fresh_keystore, monkeypatch):
    from fastapi import HTTPException
    drv = _registry.registered_drivers()["fluence"]

    async def explode(self, **kwargs):
        raise ValueError("percent must be in [0, 100]")

    monkeypatch.setattr(type(drv), "set_dim", explode)
    with pytest.raises(HTTPException) as exc_info:
        await _actions.dispatch("fluence", "set_dim", {"percent": 150})
    assert exc_info.value.status_code == 400
    assert "[0, 100]" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_dispatch_runtime_error_becomes_502(fresh_keystore, monkeypatch):
    from fastapi import HTTPException
    drv = _registry.registered_drivers()["wemo"]

    async def explode(self, **kwargs):
        raise RuntimeError("device unreachable")

    monkeypatch.setattr(type(drv), "set_power", explode)
    with pytest.raises(HTTPException) as exc_info:
        await _actions.dispatch("wemo", "set_power", {"ip": "10.0.0.1", "on": True})
    assert exc_info.value.status_code == 502


# ── Wemo SOAP cipher of state values ─────────────────────────────────


@pytest.mark.asyncio
async def test_wemo_set_power_emits_correct_soap(fresh_keystore, monkeypatch):
    from app.integrations.wemo.driver import WemoDriver, WemoConfig

    captured: dict[str, Any] = {}

    async def fake_post(self, url, content=None, headers=None):
        captured["url"] = url
        captured["body"] = content
        captured["headers"] = headers
        return httpx.Response(200, text="<Envelope/>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.10"}]))
    await drv.set_power("10.0.0.10", True)
    assert "<BinaryState>1</BinaryState>" in captured["body"]
    assert "10.0.0.10" in captured["url"]
    await drv.set_power("10.0.0.10", False)
    assert "<BinaryState>0</BinaryState>" in captured["body"]


@pytest.mark.asyncio
async def test_wemo_get_state_parses_response(fresh_keystore, monkeypatch):
    from app.integrations.wemo.driver import WemoDriver, WemoConfig

    async def fake_post(self, url, content=None, headers=None):
        return httpx.Response(
            200,
            text="<Envelope><Body><GetBinaryStateResponse><BinaryState>1</BinaryState></GetBinaryStateResponse></Body></Envelope>",
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.10"}]))
    health = await drv.test_connection()
    assert health.state == "ok"


@pytest.mark.asyncio
async def test_wemo_5xx_surfaces_as_error(fresh_keystore, monkeypatch):
    from app.integrations.wemo.driver import WemoDriver, WemoConfig

    async def fake_post(self, url, content=None, headers=None):
        return httpx.Response(503)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.10"}]))
    health = await drv.test_connection()
    assert health.state == "error"


# ── Kasa cipher round-trip ───────────────────────────────────────────


def test_kasa_xor_cipher_round_trip():
    from app.integrations.kasa.driver import _decrypt, _encrypt
    payload = json.dumps({"system": {"get_sysinfo": {}}})
    enc = _encrypt(payload)
    dec = _decrypt(enc)
    assert dec == payload


def test_kasa_decrypt_short_buffer_raises():
    from app.integrations.kasa.driver import _decrypt
    with pytest.raises(ValueError, match="length prefix"):
        _decrypt(b"\x00")


@pytest.mark.asyncio
async def test_kasa_test_connection_no_devices_returns_error(fresh_keystore):
    from app.integrations.kasa.driver import KasaDriver, KasaConfig
    drv = KasaDriver()
    await drv.configure(KasaConfig())
    health = await drv.test_connection()
    assert health.state == "error"


@pytest.mark.asyncio
async def test_kasa_query_writes_correct_command(fresh_keystore, monkeypatch):
    """The ON command sent over the wire must decrypt to the documented
    JSON body — protects against accidental cipher-key drift.
    """
    from app.integrations.kasa.driver import _decrypt, _encrypt, KasaDriver, KasaConfig

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
        async def read(self, n):
            return _encrypt(json.dumps({"system": {"set_relay_state": {"err_code": 0}}}))

    async def fake_open_connection(host, port):
        captured["host"] = host
        captured["port"] = port
        writer = FakeWriter()
        captured["writer"] = writer
        return FakeReader(), writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)

    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.20"}]))
    await drv.set_power("10.0.0.20", True)
    assert captured["host"] == "10.0.0.20"
    assert captured["port"] == 9999
    sent = bytes(captured["writer"].buffer)
    decoded = _decrypt(sent)
    assert json.loads(decoded) == {"system": {"set_relay_state": {"state": 1}}}


@pytest.mark.asyncio
async def test_kasa_set_dim_validates_percent(fresh_keystore):
    from app.integrations.kasa.driver import KasaDriver, KasaConfig
    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.20"}]))
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        await drv.set_dim("10.0.0.20", 150)


# ── set_dim validation across lighting drivers ──────────────────────


@pytest.mark.parametrize("slug", ["fluence", "fohse", "bios"])
@pytest.mark.asyncio
async def test_set_dim_rejects_out_of_range(fresh_keystore, slug):
    drv = _registry.registered_drivers()[slug]
    cfg = drv.config_schema()
    if hasattr(cfg, "email"):
        cfg = drv.config_schema(email="b@example.com", password="x")
    elif hasattr(cfg, "base_url"):
        cfg = drv.config_schema(base_url="http://10.0.0.1")
    await drv.configure(cfg)
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        await drv.set_dim("f1", 150)


# ── Cloud-bound RPC handler honours vendor_action ───────────────────


@pytest.mark.asyncio
async def test_rpc_vendor_action_dispatches(fresh_keystore, monkeypatch):
    """The cloud-bound RPC handler should accept action='vendor_action'
    and forward the inner action to the dispatcher."""
    from app.cloud import integrations_proxy

    class FakeSio:
        def __init__(self):
            self.emits = []

        async def emit(self, event, data):
            self.emits.append((event, data))

    fake_dispatch = AsyncMock(return_value={"ok": True, "fixture_id": "f1"})
    monkeypatch.setattr(integrations_proxy._vendor_actions, "dispatch", fake_dispatch)

    sio = FakeSio()
    await integrations_proxy.handle_request(
        sio,
        {
            "id": "x",
            "action": "vendor_action",
            "slug": "bios",
            "payload": {"action": "set_dim", "fixture_id": "f1", "percent": 80},
        },
    )
    fake_dispatch.assert_awaited_once_with(
        "bios", "set_dim", {"fixture_id": "f1", "percent": 80}
    )
    assert sio.emits[0][1]["success"] is True


@pytest.mark.asyncio
async def test_rpc_vendor_action_without_inner_action_returns_400(
    fresh_keystore,
):
    from app.cloud import integrations_proxy

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
