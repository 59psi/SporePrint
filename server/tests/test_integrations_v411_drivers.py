"""The HTTP vendor drivers, and the skeleton every polling driver runs on.

* Every shipped driver registers itself, free on the Pi (it has no paygate),
  with the config fields it keeps encrypted at rest.
* Agrowtek, Quest, Anden and BIOS (LAN controllers) and Trane, Fluence and
  Fohse (vendor clouds behind an email/password login) are written against
  vendor documentation. The tables pin what each poll reads and stores and
  what each write sends. A vendor error or an unreadable reply fails the poll
  or the write (an error in health, a 502), never an empty "ok"; a reply of
  a shape the driver does not know stores nothing.
* A level a device cannot take is the caller's 400 and reaches no device.
* HttpVendorDriver: start/stop are idempotent, and health follows the last
  poll (ok; error; degraded when some devices failed or the polls stopped).
"""

from __future__ import annotations

import asyncio
import importlib
import json

import httpx
import pytest
from fastapi import HTTPException

from app.integrations import _actions, _registry
from app.integrations._base import IntegrationHealth
from app.integrations._http_skeleton import HttpVendorDriver
from app.integrations.agrowtek.driver import AgrowtekConfig, AgrowtekDriver
from app.integrations.anden.driver import AndenConfig, AndenDriver
from app.integrations.bios.driver import BiosConfig, BiosDriver
from app.integrations.fluence.driver import FluenceConfig, FluenceDriver
from app.integrations.fohse.driver import FohseConfig, FohseDriver
from app.integrations.kasa.driver import KasaConfig, KasaDriver
from app.integrations.quest.driver import QuestConfig, QuestDriver
from app.integrations.tapo.driver import TapoDriver
from app.integrations.trane.driver import TraneConfig, TraneDriver
from tests._pi_c1_integrations import route_httpx, stored_readings, tapo_cfg, use_drivers

# The vendor packages bind a driver INSTANCE to the name `driver`, shadowing
# the submodule attribute — resolve the module itself.
kasa_mod = importlib.import_module("app.integrations.kasa.driver")

_LAN = "http://10.0.0.30"
_KEY = "lan-api-key"
_TOKEN = "cloud-token"


def _cloud(cfg_cls, **extra):
    return cfg_cls(email="grower@example.com", password="pw", **extra)


class _Vendor:
    """A vendor API: a login answers with a token, ``read_path`` with
    ``reads`` (bytes are sent raw), every PUT with ``put_status``. Records
    every request."""

    def __init__(self, read_path=None, reads=None, *, read_status=200, put_status=200):
        self.read_path = read_path
        self.reads = reads
        self.read_status = read_status
        self.put_status = put_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": _TOKEN})
        if request.method == "GET" and request.url.path == self.read_path:
            if isinstance(self.reads, bytes):
                return httpx.Response(self.read_status, content=self.reads)
            return httpx.Response(self.read_status, json=self.reads)
        if request.method == "PUT":
            return httpx.Response(self.put_status, json={})
        return httpx.Response(404)

    def calls(self, method: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method
                and not r.url.path.endswith("/auth/login")]


# ── Registration ─────────────────────────────────────────────────────


def test_every_shipped_driver_is_registered_free_with_its_secret_fields():
    drivers = _registry.registered_drivers()
    assert {slug: drv.secret_fields for slug, drv in drivers.items()} == {
        "grafana": {"bearer_token"},
        "aranet": {"api_key"},
        "pulse": {"password"},
        "agrowtek": {"api_key"},
        "trane": {"password"},
        "fluence": {"password"},
        "quest": set(),
        "anden": set(),
        "fohse": {"password"},
        "bios": {"api_key"},
        "wemo": set(),
        "kasa": set(),
        "tapo": {"password"},
    }
    # The Pi has no paygate: a "premium" chip on a driver that runs free
    # (the vendor-cloud ones included) told operators they needed a plan.
    assert {drv.tier_required for drv in drivers.values()} == {"free"}


@pytest.mark.parametrize("cfg_cls,fields,error", [
    (AgrowtekConfig, {"base_url": "ftp://10.0.0.30"}, "http"),
    (AgrowtekConfig, {"base_url": "http://"}, "host"),
    (TraneConfig, {"email": "not-an-email"}, "@"),
    (QuestConfig, {"poll_seconds": 10}, "greater than or equal"),
], ids=["scheme", "host", "email", "poll-floor"])
def test_a_config_the_driver_cannot_use_is_refused_on_save(cfg_cls, fields, error):
    with pytest.raises(ValueError, match=error):
        cfg_cls(**fields)


# ── What a poll reads and stores ─────────────────────────────────────

_SENSORS = [
    {"id": "s1", "measurements": {"temperature": 22.5, "rh": 88, "co2": 900,
                                  "ph": 6.1, "vpd": "n/a"}},
    {"measurements": {"temp_c": 30.0}},  # no id: skipped
]
_BIOS = [{"id": "f1", "dim": 80, "watts": 600, "temp_c": 41.5}, {"dim": 10}]
_FLUENCE = [{"id": "f1", "dimming": 70, "power_watts": 500, "temperature_c": 38.0}]
_FOHSE = [{"id": "f2", "intensity_percent": 60, "power_w": 450, "fixture_temp_c": 36.5}]
_HOUSES = [{"thermostats": [
    {"id": "t1", "current_temperature": 21.5, "current_humidity": 45},
    {"current_temperature": 30.0},  # no id: skipped
]}]

# (driver, config, read path, the reply in each envelope the vendor may use,
#  the Authorization the read carries, the readings stored)
_POLLS = [
    pytest.param(
        AgrowtekDriver, AgrowtekConfig(base_url=_LAN, api_key=_KEY), "/api/sensors",
        [_SENSORS, {"sensors": _SENSORS}],
        f"Bearer {_KEY}",
        {("agrowtek:s1", "temp_c", 22.5), ("agrowtek:s1", "humidity", 88.0),
         ("agrowtek:s1", "co2_ppm", 900.0)},
        id="agrowtek"),
    pytest.param(
        QuestDriver, QuestConfig(base_url=_LAN), "/api/status",
        [{"temp_c": 21.0, "humidity": 55, "setpoint_humidity": 60, "fan": "auto"}],
        None,
        {("quest:10.0.0.30", "temp_c", 21.0), ("quest:10.0.0.30", "humidity", 55.0),
         ("quest:10.0.0.30", "setpoint_humidity", 60.0)},
        id="quest"),
    pytest.param(
        AndenDriver, AndenConfig(base_url=_LAN), "/api/status",
        [{"temp_c": 20.0, "humidity": 58, "setpoint_humidity": 55, "power_w": 410}],
        None,
        {("anden:10.0.0.30", "temp_c", 20.0), ("anden:10.0.0.30", "humidity", 58.0),
         ("anden:10.0.0.30", "setpoint_humidity", 55.0), ("anden:10.0.0.30", "power_w", 410.0)},
        id="anden"),
    pytest.param(
        # The API key is optional on BIOS firmware: none set, none sent.
        BiosDriver, BiosConfig(base_url=_LAN), "/api/fixtures",
        [_BIOS, {"fixtures": _BIOS}],
        None,
        {("bios:f1", "dimming_percent", 80.0), ("bios:f1", "power_w", 600.0),
         ("bios:f1", "light_temp_c", 41.5)},
        id="bios"),
    pytest.param(
        FluenceDriver, _cloud(FluenceConfig), "/v1/fixtures",
        [_FLUENCE, {"fixtures": _FLUENCE}],
        f"Bearer {_TOKEN}",
        {("fluence:f1", "dimming_percent", 70.0), ("fluence:f1", "power_w", 500.0),
         ("fluence:f1", "light_temp_c", 38.0)},
        id="fluence"),
    pytest.param(
        FohseDriver, _cloud(FohseConfig), "/v1/fixtures",
        [_FOHSE, {"fixtures": _FOHSE}],
        f"Bearer {_TOKEN}",
        {("fohse:f2", "dimming_percent", 60.0), ("fohse:f2", "power_w", 450.0),
         ("fohse:f2", "light_temp_c", 36.5)},
        id="fohse"),
    pytest.param(
        TraneDriver, _cloud(TraneConfig), "/api/houses",
        [_HOUSES, {"houses": _HOUSES}, _HOUSES[0]],  # a list, an envelope, one house
        f"Bearer {_TOKEN}",
        {("trane:t1", "temp_c", 21.5), ("trane:t1", "humidity", 45.0)},
        id="trane"),
]


@pytest.mark.parametrize("drv_cls,cfg,read_path,replies,auth,expected", _POLLS)
async def test_a_poll_stores_the_vendors_readings_under_its_node_ids(
    monkeypatch, drv_cls, cfg, read_path, replies, auth, expected,
):
    drv = drv_cls()
    await drv.configure(cfg)
    for reply in replies:
        vendor = _Vendor(read_path, reply)
        route_httpx(monkeypatch, vendor)

        rows, _diag = await drv.poll_once()

        assert rows == len(expected)
        assert await stored_readings() == expected
        [read] = vendor.calls("GET")
        assert read.url.path == read_path
        assert read.headers.get("authorization") == auth
    health = await drv.test_connection()
    assert health.state == "ok", health.last_error


@pytest.mark.parametrize("drv_cls,cfg,read_path,replies,auth,expected", _POLLS)
async def test_a_vendor_error_or_unreadable_reply_fails_the_poll(
    monkeypatch, drv_cls, cfg, read_path, replies, auth, expected,
):
    drv = drv_cls()
    await drv.configure(cfg)
    for status, body, error in ((503, {"error": "overloaded"}, "503"),
                                (200, b"<html>maintenance</html>", "non-JSON")):
        route_httpx(monkeypatch, _Vendor(read_path, body, read_status=status))
        with pytest.raises(RuntimeError, match=error):
            await drv.poll_once()
        health = await drv.test_connection()
        assert health.state == "error" and error in health.last_error

    # A JSON reply of a shape the driver does not know stores nothing.
    route_httpx(monkeypatch, _Vendor(read_path, "maintenance"))
    assert (await drv.poll_once())[0] == 0
    assert await stored_readings() == set()


# ── What a write sends ───────────────────────────────────────────────

_WRITES = [
    pytest.param(
        AgrowtekDriver, AgrowtekConfig(base_url=_LAN, api_key=_KEY), "set_output",
        {"output_id": "o1", "value": "on"}, "/api/outputs/o1", {"value": True},
        f"Bearer {_KEY}", {"output_id": "o1", "value": True}, id="agrowtek"),
    pytest.param(
        QuestDriver, QuestConfig(base_url=_LAN), "set_setpoint",
        {"humidity_pct": "55"}, "/api/setpoint", {"humidity": 55},
        None, {"humidity_pct": 55}, id="quest"),
    pytest.param(
        AndenDriver, AndenConfig(base_url=_LAN), "set_setpoint",
        {"humidity_pct": 50}, "/api/setpoint", {"humidity": 50},
        None, {"humidity_pct": 50}, id="anden"),
    pytest.param(
        BiosDriver, BiosConfig(base_url=_LAN, api_key=_KEY), "set_dim",
        {"fixture_id": "f1", "percent": 40}, "/api/fixtures/f1/dim", {"dim": 40},
        f"Bearer {_KEY}", {"fixture_id": "f1", "percent": 40}, id="bios"),
    pytest.param(
        FluenceDriver, _cloud(FluenceConfig), "set_dim",
        {"fixture_id": "f1", "percent": 40}, "/v1/fixtures/f1/dimming", {"dimming": 40},
        f"Bearer {_TOKEN}", {"fixture_id": "f1", "percent": 40}, id="fluence"),
    pytest.param(
        FohseDriver, _cloud(FohseConfig), "set_dim",
        {"fixture_id": "f1", "percent": 40}, "/v1/fixtures/f1/intensity",
        {"intensity_percent": 40},
        f"Bearer {_TOKEN}", {"fixture_id": "f1", "percent": 40}, id="fohse"),
    pytest.param(
        TraneDriver, _cloud(TraneConfig), "set_setpoint",
        {"thermostat_id": "t1", "target_c": 21.5, "mode": "heat"},
        "/api/thermostats/t1/setpoint", {"target_c": 21.5, "mode": "heat"},
        f"Bearer {_TOKEN}", {"thermostat_id": "t1", "target_c": 21.5, "mode": "heat"},
        id="trane"),
]


@pytest.mark.parametrize("drv_cls,cfg,action,params,path,body,auth,result", _WRITES)
async def test_a_write_sends_its_command_and_a_refused_one_is_a_502(
    monkeypatch, drv_cls, cfg, action, params, path, body, auth, result,
):
    drv = drv_cls()
    await drv.configure(cfg)
    use_drivers(monkeypatch, drv)
    vendor = _Vendor(put_status=503)
    route_httpx(monkeypatch, vendor)
    # A field the action does not take is dropped, not a TypeError.
    payload = {**params, "stray": "ignored"}

    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch(drv.name, action, payload)
    assert exc.value.status_code == 502
    assert "503" in exc.value.detail

    vendor.put_status = 200
    assert await _actions.dispatch(drv.name, action, payload) == result
    sent = vendor.calls("PUT")[-1]
    assert (sent.url.path, json.loads(sent.content)) == (path, body)
    assert sent.headers.get("authorization") == auth


async def _no_kasa_call(ip, payload, timeout):  # pragma: no cover — must not run
    raise AssertionError("a refused level must not reach the plug")


@pytest.mark.parametrize("drv_cls,cfg,action,params", [
    (BiosDriver, BiosConfig(base_url=_LAN), "set_dim", {"fixture_id": "f1", "percent": 150}),
    (FluenceDriver, _cloud(FluenceConfig), "set_dim", {"fixture_id": "f1", "percent": 150}),
    (FohseDriver, _cloud(FohseConfig), "set_dim", {"fixture_id": "f1", "percent": 150}),
    (QuestDriver, QuestConfig(base_url=_LAN), "set_setpoint", {"humidity_pct": 101}),
    (AndenDriver, AndenConfig(base_url=_LAN), "set_setpoint", {"humidity_pct": -1}),
    (KasaDriver, KasaConfig(devices=[{"ip": "10.0.0.20"}]), "set_dim",
     {"ip": "10.0.0.20", "percent": 150}),
    (TapoDriver, tapo_cfg("10.0.0.30"), "set_dim", {"ip": "10.0.0.30", "percent": 200}),
], ids=["bios", "fluence", "fohse", "quest", "anden", "kasa", "tapo"])
async def test_an_out_of_range_level_is_a_400_that_reaches_no_device(
    monkeypatch, drv_cls, cfg, action, params,
):
    drv = drv_cls()
    await drv.configure(cfg)
    use_drivers(monkeypatch, drv)
    vendor = _Vendor()
    route_httpx(monkeypatch, vendor)
    monkeypatch.setattr(kasa_mod, "_kasa_query", _no_kasa_call)

    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch(drv.name, action, params)
    assert exc.value.status_code == 400
    assert "[0, 100]" in exc.value.detail
    assert vendor.requests == []


# ── The polling skeleton ─────────────────────────────────────────────


class _Scripted(HttpVendorDriver):
    """A polling driver whose next poll returns (or raises) ``next``."""

    name = "scripted"
    config_schema = QuestConfig

    def __init__(self) -> None:
        super().__init__()
        self.next: tuple | Exception = (0, {})

    async def poll_once(self):
        if isinstance(self.next, Exception):
            raise self.next
        return self.next

    async def test_connection(self) -> IntegrationHealth:
        return IntegrationHealth(state="ok")


async def _poll(drv: _Scripted, outcome) -> None:
    """One cycle of the real poll loop with ``outcome`` as the poll's result.
    The loop is left running, asleep until its next poll."""
    await drv.stop()
    drv.next = outcome
    drv._last_poll_at = None
    await drv.start()
    for _ in range(300):
        if drv._last_poll_at is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the poll loop never polled")


async def test_start_and_stop_are_idempotent():
    drv = _Scripted()
    await drv.configure(QuestConfig())
    await drv.stop()  # never started: must not raise
    await drv.start()
    task = drv._task
    await drv.start()
    assert drv._task is task and drv.is_polling
    await drv.stop()
    await drv.stop()  # already stopped: must not raise
    assert drv._task is None and not drv.is_polling


async def test_health_follows_the_last_poll():
    drv = _Scripted()
    await drv.configure(QuestConfig(poll_seconds=60))
    assert (await drv.health()).state == "disabled"
    await drv.start()
    # Enabled but not yet polled is no news, not an error.
    assert (await drv.health()).state == "ok"
    try:
        await _poll(drv, (3, {"devices": 2, "failed": {}}))
        assert await drv.health() == IntegrationHealth(state="ok")

        # No successful poll for three intervals: the loop may be hung.
        drv._last_poll_at -= 3 * 60 + 1
        stale = await drv.health()
        assert stale.state == "degraded"
        assert "no successful poll" in stale.last_error

        # Some devices failing is degraded, every device failing an error,
        # and both name the devices (the summary is cut at 500 characters).
        await _poll(drv, (1, {"devices": 2, "failed": {"10.0.0.5": "refused"}}))
        some = await drv.health()
        assert (some.state, some.details) == ("degraded", {"failed": {"10.0.0.5": "refused"}})
        assert some.last_error == "1 of 2 devices failed: 10.0.0.5: refused"
        await _poll(drv, (0, {"devices": 2,
                              "failed": {"10.0.0.5": "x" * 300, "10.0.0.6": "y" * 300}}))
        every = await drv.health()
        assert every.state == "error"
        assert len(every.last_error) == 500 and every.last_error.endswith("…")

        # A poll that raises is an error carrying the exception's text.
        await _poll(drv, RuntimeError("vendor cloud unreachable"))
        failed = await drv.health()
        assert (failed.state, failed.last_error, failed.details) == (
            "error", "vendor cloud unreachable", {})
    finally:
        await drv.stop()
