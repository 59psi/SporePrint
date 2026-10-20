"""Vendor drivers: per-device poll outcome, refused commands, transport
errors, KLAP request pairing, power units and vendor logins.

* A multi-device poll keeps going past a device that fails and reports it:
  health is "degraded" when some devices fail and "error" when all do, so an
  unplugged plug reaches the health alerts instead of the poll reading "ok".
* Kasa and Tapo report a refused command inside the reply (err_code /
  error_code); a refused write is a 502, never a delivered command.
* Transport errors (a reset socket, an unreachable plug, a dead cloud) fail
  the one device or the one call, not the poll.
* A Tapo reply decrypts under its own request's sequence number, and calls
  to one plug are serialized.
* Bearer-token clouds (Trane, Fluence, Fohse) renew an expired token and
  retry once; a refused login is not resent every poll (Tapo cloud and Pulse
  too) until the settings are saved again.
"""

from __future__ import annotations

import asyncio
import importlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.cloud.service as cloud_service
from app.config import settings
from app.db import get_db
from app.integrations import _actions, _health_sweeper, _registry
from app.integrations._keystore import reset_fernet_cache
from app.integrations.agrowtek.driver import AgrowtekDriver
from app.integrations.anden.driver import AndenDriver
from app.integrations.aranet.client import AranetClient
from app.integrations.aranet.models import AranetMeasurementsResponse
from app.integrations.aranet.router import router as aranet_router
from app.integrations.bios.driver import BiosDriver
from app.integrations.fluence.driver import FluenceConfig, FluenceDriver
from app.integrations.fohse.driver import FohseConfig, FohseDriver
from app.integrations.kasa.driver import KasaConfig, KasaDriver, KasaError
from app.integrations.pulse.client import PulseError
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse.driver import PulseDriver
from app.integrations.pulse.local_transport import PulseLocalTransport
from app.integrations.pulse.router import router as pulse_router
from app.integrations.quest.driver import QuestConfig, QuestDriver
from app.integrations.tapo import klap
from app.integrations.tapo.config import TapoConfig
from app.integrations.tapo.driver import TapoDriver, TapoError
from app.integrations.trane.driver import TraneConfig, TraneDriver
from app.integrations.wemo.driver import WemoConfig, WemoDriver

# The vendor packages bind a driver INSTANCE to the name `driver`, shadowing
# the submodule attribute — resolve the module itself.
kasa_mod = importlib.import_module("app.integrations.kasa.driver")


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


def _route_httpx(monkeypatch, handler) -> None:
    """Send every httpx.AsyncClient the drivers build to ``handler``."""
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, **{**k, "transport": transport})
    )


async def _readings(node_id: str) -> set[tuple[str, float]]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT sensor, value FROM telemetry_readings WHERE node_id = ?", (node_id,)
        )
        return {(r["sensor"], r["value"]) for r in await cursor.fetchall()}


async def _health_after_one_poll(drv):
    """Run the driver's real poll loop for one cycle and read its health."""
    await drv.start()
    try:
        for _ in range(300):
            if drv._last_poll_at is not None:
                break
            await asyncio.sleep(0.01)
        return await drv.health()
    finally:
        await drv.stop()


# ── Per-device poll outcome ──────────────────────────────────────────


async def test_kasa_one_unreachable_plug_is_degraded_and_the_rest_are_polled(monkeypatch):
    async def fake_query(ip, payload, timeout):
        if ip == "10.0.0.31":
            raise KasaError("connect to 10.0.0.31:9999 failed: refused")
        return {"system": {"get_sysinfo": {"relay_state": 1, "err_code": 0}}}

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.31"}, {"ip": "10.0.0.32"}]))
    health = await _health_after_one_poll(drv)
    assert health.state == "degraded"
    assert set(health.details["failed"]) == {"10.0.0.31"}
    assert health.last_error.startswith("1 of 2 devices failed")
    assert await _readings("kasa:10.0.0.32") == {("actuator_state", 1.0)}


async def test_kasa_every_plug_down_is_an_error_and_alerts_once(monkeypatch):
    async def fake_query(ip, payload, timeout):
        raise KasaError(f"connect to {ip}:9999 failed: refused")

    sent: list[tuple[str, dict]] = []

    async def fake_forward(event, data, *, confirm=False):
        sent.append((event, data))
        return True

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    monkeypatch.setattr(cloud_service, "forward_event", fake_forward)
    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.31"}, {"ip": "10.0.0.32"}]))
    monkeypatch.setattr(_health_sweeper._registry, "registered_drivers", lambda: {"kasa": drv})
    _health_sweeper._last_state.clear()
    # Enabled (health reads a running task) but polled by hand, so the
    # sweeps see exactly: not yet polled, then the failed poll.
    drv._task = asyncio.get_running_loop().create_future()
    try:
        await _health_sweeper._sweep_once()  # baseline: enabled, not yet polled
        _rows, diag = await drv.poll_once()
        drv._record_poll(diag)
        health = await drv.health()
        assert health.state == "error"
        assert set(health.details["failed"]) == {"10.0.0.31", "10.0.0.32"}
        await _health_sweeper._sweep_once()
        await _health_sweeper._sweep_once()
    finally:
        drv._task.cancel()
        drv._task = None
        _health_sweeper._last_state.clear()
    degraded = [data for event, data in sent if event == "vendor_health_degraded"]
    assert len(degraded) == 1
    assert degraded[0]["state"] == "error" and degraded[0]["resolved"] is False


@pytest.mark.parametrize("cfg", [KasaConfig(), WemoConfig()])
async def test_enabled_plug_driver_without_devices_is_an_error(cfg):
    drv = KasaDriver() if isinstance(cfg, KasaConfig) else WemoDriver()
    await drv.configure(cfg)
    health = await _health_after_one_poll(drv)
    assert health.state == "error"
    assert "no devices" in health.last_error


@pytest.mark.parametrize("drv_cls,needs", [
    (FluenceDriver, "email and password"),
    (FohseDriver, "email and password"),
    (TraneDriver, "email and password"),
    (AgrowtekDriver, "base_url and api_key"),
    (QuestDriver, "base_url"),
    (AndenDriver, "base_url"),
    (BiosDriver, "base_url"),
])
async def test_enabled_driver_missing_its_settings_is_an_error(drv_cls, needs):
    drv = drv_cls()
    await drv.configure(drv.config_schema())
    health = await _health_after_one_poll(drv)
    assert health.state == "error"
    assert needs in health.last_error


async def test_kasa_blank_ip_row_fails_alone(monkeypatch):
    real_query = kasa_mod._kasa_query

    async def fake_query(ip, payload, timeout):
        if not ip:
            return await real_query(ip, payload, timeout)  # ValueError: ip is required
        return {"system": {"get_sysinfo": {"relay_state": 0}}}

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": ""}, {"ip": "10.0.0.32"}]))
    rows, diag = await drv.poll_once()
    assert rows == 1
    assert "ip is required" in diag["failed"]["device 1"]


# ── Kasa transport errors and in-band refusals ───────────────────────


class _Writer:
    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


class _ResetReader:
    async def readexactly(self, n):
        raise ConnectionResetError(54, "Connection reset by peer")


class _ReplyReader:
    def __init__(self, reply: dict):
        self._buf = kasa_mod._encrypt(json.dumps(reply))

    async def readexactly(self, n):
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk


async def test_kasa_connection_reset_is_a_kasa_error_and_spares_the_other_plugs(monkeypatch):
    async def fake_open(host, port):
        if host == "10.0.0.31":
            return _ResetReader(), _Writer()
        return _ReplyReader({"system": {"get_sysinfo": {"relay_state": 1}}}), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    with pytest.raises(KasaError, match="mid-exchange"):
        await kasa_mod._kasa_query("10.0.0.31", {"system": {"get_sysinfo": {}}}, 1.0)

    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.31"}, {"ip": "10.0.0.32"}]))
    rows, diag = await drv.poll_once()
    assert rows == 1
    assert set(diag["failed"]) == {"10.0.0.31"}
    assert await _readings("kasa:10.0.0.32") == {("actuator_state", 1.0)}


@pytest.mark.parametrize("action,params,reply", [
    # A plug that is not a dimmer answers at module level, with no method key.
    ("set_dim", {"ip": "10.0.0.20", "percent": 40},
     {"smartlife.iot.dimmer": {"err_code": -1, "err_msg": "module not support"}}),
    ("set_power", {"ip": "10.0.0.20", "on": False},
     {"system": {"set_relay_state": {"err_code": -3, "err_msg": "invalid argument"}}}),
])
async def test_kasa_refused_write_is_a_502(monkeypatch, action, params, reply):
    async def fake_query(ip, payload, timeout):
        return reply

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    drv = KasaDriver()
    await drv.configure(KasaConfig(devices=[{"ip": "10.0.0.20"}]))
    monkeypatch.setattr(_actions._registry, "registered_drivers", lambda: {"kasa": drv})
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("kasa", action, params)
    assert exc.value.status_code == 502
    assert "refused" in str(exc.value.detail)


async def test_kasa_accepted_write_still_succeeds(monkeypatch):
    async def fake_query(ip, payload, timeout):
        return {"system": {"set_relay_state": {"err_code": 0}}}

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    drv = KasaDriver()
    assert await drv.set_power("10.0.0.20", True) == {"ip": "10.0.0.20", "state": "on"}


# ── Wemo BinaryState ─────────────────────────────────────────────────


@pytest.mark.parametrize("state_text,expected", [
    ("8", 1),                          # Insight: on, load idle
    ("1|1611092839|0|0|0|0", 1),       # pipe-delimited
    ("0", 0),
])
async def test_wemo_reads_every_binary_state_form(monkeypatch, state_text, expected):
    async def fake_post(self, url, content=None, headers=None):
        return httpx.Response(200, text=f"<u:R><BinaryState>{state_text}</BinaryState></u:R>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await WemoDriver()._get_state("10.0.0.5:49153", 1.0) == expected


async def test_wemo_insight_in_standby_is_polled_with_its_power(monkeypatch):
    insight = "8|1611092839|0|0|0|0|0|1500000|0|0|8000"  # field 8: current mW

    async def fake_post(self, url, content=None, headers=None):
        if "/insight1" in url:
            return httpx.Response(200, text=f"<InsightParams>{insight}</InsightParams>")
        return httpx.Response(200, text="<BinaryState>8</BinaryState>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.5:49153", "is_insight": True}]))
    rows, diag = await drv.poll_once()
    assert rows == 2 and diag["failed"] == {}
    assert await _readings("wemo:10.0.0.5:49153") == {
        ("actuator_state", 1.0), ("power_w", 1500.0),
    }


# ── Tapo: a fake KLAP v2 plug ────────────────────────────────────────


EMAIL, PASSWORD = "user@example.com", "hunter2"
REMOTE = bytes(range(16, 32))


def _encrypt_reply(local: bytes, seq: int, body: dict) -> bytes:
    session = klap.derive_session(local, REMOTE, EMAIL, PASSWORD)
    iv = session.iv_prefix + seq.to_bytes(4, "big", signed=True)
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(session.encrypt_key), modes.CBC(iv)).encryptor()
    plain = json.dumps(body).encode()
    return b"\x00" * 32 + enc.update(padder.update(plain) + padder.finalize()) + enc.finalize()


class FakePlugs:
    """KLAP v2 plugs behind an httpx MockTransport, keyed by host.

    ``answer(host, request_json)`` returns the reply body; hosts in ``down``
    refuse connections; ``slow`` delays one method's reply.
    """

    def __init__(self, answer, *, down=(), slow=None):
        self.answer = answer
        self.down = set(down)
        self.slow = slow or {}
        self.local: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/app/handshake1":
            local = request.content
            self.local[host] = local
            proof = klap.auth_hash(local, REMOTE, EMAIL, PASSWORD)
            return httpx.Response(
                200, content=REMOTE + proof,
                headers={"Set-Cookie": "TP_SESSIONID=s1;TIMEOUT=86400"},
            )
        if path == "/app/handshake2":
            return httpx.Response(200)
        if path == "/app/request":
            seq = int(request.url.params["seq"])
            session = klap.derive_session(self.local[host], REMOTE, EMAIL, PASSWORD)
            body = json.loads(session.decrypt(request.content, seq))
            self.calls.append((host, body["method"]))
            delay = self.slow.get(body["method"])
            if delay:
                await asyncio.sleep(delay)
            reply = self.answer(host, body)
            return httpx.Response(200, content=_encrypt_reply(self.local[host], seq, reply))
        return httpx.Response(404)


def _ok(result: dict | None = None) -> dict:
    return {"error_code": 0, "result": result or {}}


def _tapo_cfg(*ips: str, **device) -> TapoConfig:
    return TapoConfig(email=EMAIL, password=PASSWORD,
                      devices=[{"ip": ip, **device} for ip in ips])


async def test_tapo_unreachable_plug_does_not_stop_the_poll(monkeypatch):
    plugs = FakePlugs(lambda host, body: _ok({"device_on": True}), down={"10.0.0.31"})
    _route_httpx(monkeypatch, plugs)
    drv = TapoDriver()
    await drv.configure(_tapo_cfg("10.0.0.31", "10.0.0.32"))
    rows, diag = await drv.poll_once()
    assert rows == 1
    assert set(diag["failed"]) == {"10.0.0.31"}
    assert "10.0.0.31" not in drv._sessions
    assert await _readings("tapo:10.0.0.32") == {("actuator_state", 1.0)}


async def test_tapo_plug_row_without_ip_fails_alone(monkeypatch):
    _route_httpx(monkeypatch, FakePlugs(lambda host, body: _ok({"device_on": False})))
    drv = TapoDriver()
    await drv.configure(TapoConfig(email=EMAIL, password=PASSWORD,
                                   devices=[{"ip": ""}, {"ip": "10.0.0.32"}]))
    rows, diag = await drv.poll_once()
    assert rows == 1
    assert "no ip" in diag["failed"]["device 1"]


async def test_tapo_power_is_stored_in_watts(monkeypatch):
    def answer(host, body):
        if body["method"] == "get_current_power":
            return _ok({"current_power": 1500})  # already watts
        return _ok({"device_on": True})

    _route_httpx(monkeypatch, FakePlugs(answer))
    drv = TapoDriver()
    await drv.configure(_tapo_cfg("10.0.0.30", has_emeter=True))
    await drv.poll_once()
    assert ("power_w", 1500.0) in await _readings("tapo:10.0.0.30")


async def test_tapo_cloud_test_with_a_dead_network_is_an_error_not_a_500(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("network unreachable", request=request)

    _route_httpx(monkeypatch, handler)
    drv = TapoDriver()
    await drv.configure(TapoConfig(transport="cloud", email=EMAIL, password=PASSWORD))
    health = await drv.test_connection()
    assert health.state == "error"
    assert "cloud login failed" in health.last_error


async def test_tapo_write_before_configuration_is_a_clear_502(monkeypatch):
    drv = TapoDriver()  # never configured
    monkeypatch.setattr(_actions._registry, "registered_drivers", lambda: {"tapo": drv})
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("tapo", "set_power", {"ip": "10.0.0.30", "on": False})
    assert exc.value.status_code == 502
    assert "not configured" in str(exc.value.detail)


async def test_tapo_refused_write_is_a_502_and_keeps_the_session(monkeypatch):
    def answer(host, body):
        if body["method"] == "set_device_info":
            return {"error_code": -1008}  # PARAMS_ERROR
        return _ok({"device_on": True})

    _route_httpx(monkeypatch, FakePlugs(answer))
    drv = TapoDriver()
    await drv.configure(_tapo_cfg("10.0.0.30"))
    monkeypatch.setattr(_actions._registry, "registered_drivers", lambda: {"tapo": drv})
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("tapo", "set_power", {"ip": "10.0.0.30", "on": False})
    assert exc.value.status_code == 502
    assert "error_code -1008" in str(exc.value.detail)
    assert "10.0.0.30" in drv._sessions  # a refused command is not a dead session


async def test_tapo_session_error_code_drops_the_session(monkeypatch):
    _route_httpx(monkeypatch, FakePlugs(lambda host, body: {"error_code": 9999}))
    drv = TapoDriver()
    await drv.configure(_tapo_cfg("10.0.0.30"))
    with pytest.raises(TapoError, match="error_code 9999"):
        await drv.set_power("10.0.0.30", True)
    assert "10.0.0.30" not in drv._sessions  # the next call handshakes again


async def test_tapo_poll_with_an_in_band_error_is_a_failed_plug(monkeypatch):
    _route_httpx(monkeypatch, FakePlugs(lambda host, body: {"error_code": -1501}))
    drv = TapoDriver()
    await drv.configure(_tapo_cfg("10.0.0.30"))
    rows, diag = await drv.poll_once()
    assert rows == 0
    assert "error_code -1501" in diag["failed"]["10.0.0.30"]


async def test_tapo_concurrent_calls_to_one_plug_each_get_their_own_reply(monkeypatch):
    """A safety OFF in flight while the poll reads the same plug: each reply
    must decrypt under its own request's sequence number."""
    def answer(host, body):
        if body["method"] == "set_device_info":
            return _ok({"applied": body["params"]})
        return _ok({"device_on": False})

    plugs = FakePlugs(answer, slow={"set_device_info": 0.2})
    _route_httpx(monkeypatch, plugs)
    drv = TapoDriver()
    cfg = _tapo_cfg("10.0.0.30")
    await drv.configure(cfg)
    await drv._klap_call(cfg, "10.0.0.30", {"method": "get_device_info"})  # session up

    write = asyncio.create_task(drv.set_power("10.0.0.30", False))
    await asyncio.sleep(0.05)  # the write is waiting for its (slow) reply
    read = await drv._klap_call(cfg, "10.0.0.30", {"method": "get_device_info"})
    assert await write == {"ip": "10.0.0.30", "state": "off"}
    assert read["result"] == {"device_on": False}
    # The plug saw one exchange at a time, in order.
    assert [m for _h, m in plugs.calls] == ["get_device_info", "set_device_info", "get_device_info"]


# ── Bearer-token vendor clouds: Trane, Fluence, Fohse ────────────────


_BEARER = [
    pytest.param(TraneDriver, TraneConfig, "/houses", id="trane"),
    pytest.param(FluenceDriver, FluenceConfig, "/fixtures", id="fluence"),
    pytest.param(FohseDriver, FohseConfig, "/fixtures", id="fohse"),
]

_WRITES = [
    pytest.param(TraneDriver, TraneConfig, "set_setpoint",
                 {"thermostat_id": "t1", "target_c": 21.0}, id="trane"),
    pytest.param(FluenceDriver, FluenceConfig, "set_dim",
                 {"fixture_id": "f1", "percent": 40}, id="fluence"),
    pytest.param(FohseDriver, FohseConfig, "set_dim",
                 {"fixture_id": "f1", "percent": 40}, id="fohse"),
]


def _logins(calls: list[httpx.Request]) -> list[str]:
    return [json.loads(r.content)["password"] for r in calls if r.url.path.endswith("/auth/login")]


@pytest.mark.parametrize("drv_cls,cfg_cls,read_path", _BEARER)
async def test_expired_token_is_renewed_and_the_poll_succeeds(monkeypatch, drv_cls, cfg_cls, read_path):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "fresh"})
        if request.headers["authorization"] != "Bearer fresh":
            return httpx.Response(401, text="token expired")
        return httpx.Response(200, json=[])

    _route_httpx(monkeypatch, handler)
    drv = drv_cls()
    await drv.configure(cfg_cls(email="a@x.co", password="pw"))
    drv._token = "expired"  # an earlier login's token
    await drv.poll_once()
    assert _logins(calls) == ["pw"]
    assert drv._token == "fresh"
    assert sum(1 for r in calls if r.url.path.endswith(read_path)) == 2


@pytest.mark.parametrize("drv_cls,cfg_cls,action,params", _WRITES)
async def test_write_after_token_expiry_is_retried_once(monkeypatch, drv_cls, cfg_cls, action, params):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "fresh"})
        if request.headers["authorization"] != "Bearer fresh":
            return httpx.Response(401)
        return httpx.Response(200, json={})

    _route_httpx(monkeypatch, handler)
    drv = drv_cls()
    await drv.configure(cfg_cls(email="a@x.co", password="pw"))
    drv._token = "expired"
    await getattr(drv, action)(**params)
    assert _logins(calls) == ["pw"]
    assert sum(1 for r in calls if r.method == "PUT") == 2


@pytest.mark.parametrize("drv_cls,cfg_cls,read_path", _BEARER)
async def test_refused_login_is_not_resent_every_poll(monkeypatch, drv_cls, cfg_cls, read_path):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(401, text="bad credentials")
        raise AssertionError("no data request without a token")

    _route_httpx(monkeypatch, handler)
    drv = drv_cls()
    await drv.configure(cfg_cls(email="a@x.co", password="wrong"))
    for _ in range(3):
        with pytest.raises(RuntimeError, match="401"):
            await drv.poll_once()
    assert _logins(calls) == ["wrong"]

    # New credentials log in again; so does saving the same ones again
    # (after unlocking the account, say), and an explicit Test.
    await drv.configure(cfg_cls(email="a@x.co", password="right"))
    with pytest.raises(RuntimeError):
        await drv.poll_once()
    await drv.configure(cfg_cls(email="a@x.co", password="right"))
    with pytest.raises(RuntimeError):
        await drv.poll_once()
    with pytest.raises(RuntimeError):
        await drv.poll_once()
    health = await drv.test_connection()
    assert health.state == "error" and "401" in health.last_error
    assert _logins(calls) == ["wrong", "right", "right", "right"]


@pytest.mark.parametrize("drv_cls,cfg_cls,read_path", _BEARER)
async def test_network_errors_are_retried_every_poll(monkeypatch, drv_cls, cfg_cls, read_path):
    attempts = []

    def handler(request):
        attempts.append(request.url.path)
        raise httpx.ConnectError("network unreachable", request=request)

    _route_httpx(monkeypatch, handler)
    drv = drv_cls()
    await drv.configure(cfg_cls(email="a@x.co", password="pw"))
    for _ in range(3):
        with pytest.raises(httpx.ConnectError):
            await drv.poll_once()
    assert len(attempts) == 3


async def test_login_that_finishes_after_a_config_change_installs_no_token(monkeypatch):
    release = asyncio.Event()

    async def handler(request):
        await release.wait()
        return httpx.Response(200, json={"token": "old-account-token"})

    _route_httpx(monkeypatch, handler)
    drv = FluenceDriver()
    old = FluenceConfig(email="old@x.co", password="pw")
    await drv.configure(old)
    login = asyncio.create_task(drv._login(old))
    await asyncio.sleep(0.05)
    await drv.configure(FluenceConfig(email="new@x.co", password="pw2"))
    release.set()
    assert await login == "old-account-token"
    assert drv._token is None


def test_trane_house_id_must_be_one_path_segment():
    for bad in ("../x?y=", "a/b", "x#frag", "."):
        with pytest.raises(ValidationError):
            TraneConfig(house_id=bad)
    assert TraneConfig(house_id=" 12345 ").house_id == "12345"


async def test_trane_reads_the_configured_house(monkeypatch):
    paths: list[str] = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(200, json={"thermostats": []})

    _route_httpx(monkeypatch, handler)
    drv = TraneDriver()
    await drv.configure(TraneConfig(email="a@x.co", password="pw", house_id="12345"))
    await drv.poll_once()
    assert paths[-1] == "/api/houses/12345"


async def test_trane_house_id_saved_before_validation_never_reaches_the_vendor(monkeypatch):
    def handler(request):  # pragma: no cover — must not be called
        raise AssertionError(f"request sent: {request.url}")

    _route_httpx(monkeypatch, handler)
    drv = TraneDriver()
    await drv.configure(TraneConfig.model_construct(
        email="a@x.co", password="pw", house_id="../admin?x=",
        poll_seconds=300, request_timeout_seconds=15.0, device_mappings={},
    ))
    drv._token = "t"
    with pytest.raises(ValueError, match="house_id"):
        await drv.poll_once()


# ── Tapo cloud and Pulse logins ──────────────────────────────────────


async def test_tapo_refused_cloud_login_is_not_resent_every_poll(monkeypatch):
    logins: list[str] = []

    def handler(request):
        logins.append(json.loads(request.content)["params"]["cloudPassword"])
        return httpx.Response(200, json={"error_code": -20601, "msg": "Incorrect email or password"})

    _route_httpx(monkeypatch, handler)
    drv = TapoDriver()
    await drv.configure(TapoConfig(transport="cloud", email=EMAIL, password="wrong"))
    for _ in range(3):
        with pytest.raises(TapoError, match="no token"):
            await drv.poll_once()
    assert logins == ["wrong"]
    await drv.configure(TapoConfig(transport="cloud", email=EMAIL, password="right"))
    with pytest.raises(TapoError):
        await drv.poll_once()
    assert logins == ["wrong", "right"]


async def test_pulse_refused_login_is_not_resent_every_poll(monkeypatch):
    logins: list[str] = []

    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            logins.append(json["password"])
            return httpx.Response(401, text="bad credentials")
        raise AssertionError("no data request without a token")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    drv = PulseDriver()
    await drv.configure(PulseConfig(transport="cloud", email="a@x.co", password="wrong"))
    for _ in range(3):
        with pytest.raises(PulseError, match="401"):
            await drv.poll_once()
    assert logins == ["wrong"]
    # Saving the same credentials again (account unlocked) allows one more try.
    await drv.configure(PulseConfig(transport="cloud", email="a@x.co", password="wrong"))
    with pytest.raises(PulseError):
        await drv.poll_once()
    await drv.configure(PulseConfig(transport="cloud", email="a@x.co", password="right"))
    with pytest.raises(PulseError):
        await drv.poll_once()
    assert logins == ["wrong", "wrong", "right"]


# ── Pulse local transport URLs ───────────────────────────────────────


async def test_pulse_local_url_with_its_own_port_polls_that_port(monkeypatch):
    seen: list[str] = []

    async def fake_get(self, url):
        seen.append(str(url))
        return httpx.Response(200, json={"measurements": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    cfg = PulseConfig(transport="local",
                      local_device_urls=["http://10.0.0.5:8080/", "http://10.0.0.6"],
                      local_http_port=81)
    transport = PulseLocalTransport(cfg)
    for device in (await transport.list_devices()).devices:
        await transport.recent_data(device.id)
    assert seen == [
        "http://10.0.0.5:8080/api/recent-data",
        "http://10.0.0.6:81/api/recent-data",
    ]


def test_pulse_local_urls_are_checked_on_save():
    for bad in ("http://10.0.0.5:8080:80", "ftp://10.0.0.5", "http://10.0.0.5/api/x",
                "http://user@10.0.0.5", "10.0.0.5", "http://10.0.0.5?x=1"):
        with pytest.raises(ValidationError):
            PulseConfig(local_device_urls=[bad])
    assert PulseConfig(local_device_urls=["http://pulse.local:81/"]).local_device_urls == [
        "http://pulse.local:81"
    ]


async def test_pulse_local_unusable_url_is_a_pulse_error(monkeypatch):
    async def fake_get(self, url):  # pragma: no cover — must not be called
        raise AssertionError("no request for an unusable URL")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # A list saved before the URLs were checked.
    cfg = PulseConfig.model_construct(transport="local",
                                      local_device_urls=["http://h:8080:80"])
    transport = PulseLocalTransport(cfg)
    devices = await transport.list_devices()
    with pytest.raises(PulseError, match="bad local device URL"):
        await transport.recent_data(devices.devices[0].id)


# ── Saved config is used after a restart ─────────────────────────────


@pytest.fixture
def routes_client(fresh_keystore):
    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    app.include_router(aranet_router, prefix="/api/integrations/aranet")
    app.include_router(pulse_router, prefix="/api/integrations/pulse")
    with TestClient(app) as client:
        yield client


def test_discover_uses_the_saved_config_after_a_restart(routes_client, monkeypatch):
    drv = _registry.registered_drivers()["aranet"]
    saved = routes_client.put(
        "/api/integrations/aranet/config",
        json={"enabled": False, "config": {"base_url": "http://10.0.0.42", "api_key": "k"}},
    )
    assert saved.status_code == 200
    seen: dict = {}

    async def fake_fetch(self):
        seen["base_url"] = self._base_url
        return AranetMeasurementsResponse(sensors=[])

    monkeypatch.setattr(AranetClient, "fetch_latest", fake_fetch)
    # A restart: disabled drivers are not configured at boot.
    drv._cfg = drv.config_schema()
    resp = routes_client.get("/api/integrations/aranet/discover")
    assert resp.status_code == 200, resp.text
    assert seen["base_url"] == "http://10.0.0.42"


def test_pulse_devices_uses_the_saved_config_after_a_restart(routes_client, monkeypatch):
    drv = _registry.registered_drivers()["pulse"]
    saved = routes_client.put(
        "/api/integrations/pulse/config",
        json={"enabled": False, "config": {"email": "a@x.co", "password": "pw"}},
    )
    assert saved.status_code == 200

    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(200, json=[{"id": "d1", "name": "Pulse One"}])

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    drv._cfg = drv.config_schema()
    resp = routes_client.get("/api/integrations/pulse/devices")
    assert resp.status_code == 200, resp.text
    assert [d["id"] for d in resp.json()["devices"]] == ["d1"]


def test_test_uses_the_saved_config_after_a_restart(routes_client, monkeypatch):
    drv = _registry.registered_drivers()["quest"]
    saved = routes_client.put(
        "/api/integrations/quest/config",
        json={"enabled": False, "config": {"base_url": "http://10.0.0.40"}},
    )
    assert saved.status_code == 200
    urls: list[str] = []

    async def fake_get(self, url):
        urls.append(str(url))
        return httpx.Response(200, json={"humidity": 55.0})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    drv._cfg = QuestConfig()
    resp = routes_client.post("/api/integrations/quest/test")
    assert resp.status_code == 200
    assert resp.json()["state"] == "ok"
    assert urls == ["http://10.0.0.40/api/status"]
