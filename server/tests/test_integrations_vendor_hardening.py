"""Vendor-driver correctness/safety regressions from the v5 audit.

* #6  string booleans ("false"/"off"/"0") must not switch a plug ON, and the
      cloud automation pause must not treat "false" as truthy.
* #7  caller-supplied device IDs / IPs must not be able to rewrite the
      request URL (path traversal with the operator's vendor bearer token,
      arbitrary host/port/path POSTs).
* #14 Pulse cloud polling must reuse its session token instead of a fresh
      email+password login every cycle.
* #15 Wemo must find a plug whose UPnP port moved off 49153.
* #16 Tapo cloud transport must not log in every poll while reporting "ok"
      with zero telemetry, and cloud-only (ip-less) writes must fail clearly.
* #18 Kasa must read the whole length-prefixed frame, not one TCP segment.
* #19 A credential change must drop cached vendor tokens / KLAP sessions.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import struct

import httpx
import pytest
from fastapi import HTTPException

import app.automation.engine as engine
from app.cloud import service
from app.config import settings
from app.integrations import _actions
from app.integrations._keystore import reset_fernet_cache
from app.integrations.fluence.driver import FluenceConfig, FluenceDriver
from app.integrations.fohse.driver import FohseConfig, FohseDriver
from app.integrations.kasa.driver import KasaConfig, KasaDriver
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse import poller
from app.integrations.pulse.driver import PulseDriver
from app.integrations.tapo.config import TapoConfig
from app.integrations.tapo.driver import _TAPO_CLOUD_BASE_BY_REGION, TapoDriver, TapoError
from app.integrations.trane.driver import TraneConfig, TraneDriver
from app.integrations.wemo.driver import WemoConfig, WemoDriver

# The vendor packages bind a driver INSTANCE to the name `driver`, shadowing
# the submodule attribute — resolve the modules themselves.
kasa_mod = importlib.import_module("app.integrations.kasa.driver")
wemo_mod = importlib.import_module("app.integrations.wemo.driver")


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


@pytest.fixture
def kasa_driver(monkeypatch):
    drv = KasaDriver()
    monkeypatch.setattr(
        _actions._registry, "registered_drivers", lambda: {"kasa": drv, "wemo": _WEMO, "fohse": _FOHSE}
    )
    return drv


_WEMO = WemoDriver()
_FOHSE = FohseDriver()


# ── #6 string booleans ───────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected_state", [
    ("false", 0), ("off", 0), ("0", 0), (0, 0), (False, 0),
    ("true", 1), ("on", 1), (1, 1), (True, 1),
])
async def test_kasa_set_power_coerces_string_booleans(kasa_driver, monkeypatch, raw, expected_state):
    sent: list[dict] = []

    async def fake_query(ip, payload, timeout):
        sent.append(payload)
        return {}

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    await _actions.dispatch("kasa", "set_power", {"ip": "10.0.0.20", "on": raw})
    assert sent == [{"system": {"set_relay_state": {"state": expected_state}}}]


async def test_kasa_set_power_rejects_ambiguous_boolean(kasa_driver, monkeypatch):
    async def fake_query(ip, payload, timeout):  # pragma: no cover — must not run
        raise AssertionError("device must not be actuated on an ambiguous value")

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("kasa", "set_power", {"ip": "10.0.0.20", "on": "maybe"})
    assert exc.value.status_code == 400


async def test_cloud_automation_pause_string_false_resumes(monkeypatch):
    seen: list[bool] = []

    async def fake_set_paused(value):
        seen.append(value)

    monkeypatch.setattr(engine, "set_paused", fake_set_paused)
    ok, err = await service._dispatch_system_command("automation", {"paused": "false"})
    assert ok is True, err
    assert seen == [False]


async def test_cloud_automation_pause_rejects_garbage(monkeypatch):
    async def fake_set_paused(value):  # pragma: no cover
        raise AssertionError("must not toggle on an ambiguous value")

    monkeypatch.setattr(engine, "set_paused", fake_set_paused)
    ok, err = await service._dispatch_system_command("automation", {"paused": "sometimes"})
    assert ok is False
    assert "paused" in err


# ── #7 IDs / IPs can't rewrite the request URL ───────────────────────


async def test_fohse_fixture_id_path_traversal_rejected(kasa_driver, monkeypatch):
    await _FOHSE.configure(FohseConfig(email="a@b.co", password="pw"))
    _FOHSE._token = "operator-bearer"
    urls: list[str] = []

    async def fake_put(self, url, **kw):
        urls.append(str(url))
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncClient, "put", fake_put)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch(
            "fohse", "set_dim", {"fixture_id": "../../admin/users?x=", "percent": 10}
        )
    assert exc.value.status_code == 400
    assert urls == []


async def test_fohse_numeric_fixture_id_still_works(kasa_driver, monkeypatch):
    await _FOHSE.configure(FohseConfig(email="a@b.co", password="pw"))
    _FOHSE._token = "operator-bearer"
    urls: list[str] = []

    async def fake_put(self, url, **kw):
        urls.append(str(url))
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncClient, "put", fake_put)
    await _actions.dispatch("fohse", "set_dim", {"fixture_id": 42, "percent": 10})
    assert urls and urls[0].endswith("/fixtures/42/intensity")


async def test_wemo_ip_url_injection_rejected(kasa_driver, monkeypatch):
    posted: list[str] = []

    async def fake_post(self, url, **kw):
        posted.append(str(url))
        return httpx.Response(200, text="<BinaryState>1</BinaryState>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("wemo", "set_power", {"ip": "10.0.0.5:80/latest#", "on": False})
    assert exc.value.status_code == 400
    assert posted == []


def test_wemo_config_rejects_url_in_ip():
    with pytest.raises(ValueError):
        WemoConfig.model_validate({"devices": [{"ip": "10.0.0.5:80/latest#"}]})


def test_kasa_and_tapo_config_reject_url_in_ip():
    with pytest.raises(ValueError):
        KasaConfig.model_validate({"devices": [{"ip": "10.0.0.5/x?y"}]})
    with pytest.raises(ValueError):
        TapoConfig.model_validate({"devices": [{"ip": "user@10.0.0.5"}]})


# ── #15 Wemo port discovery ──────────────────────────────────────────


async def test_wemo_falls_back_to_other_upnp_ports_and_caches(monkeypatch):
    attempts: list[str] = []

    async def fake_post(self, url, **kw):
        attempts.append(str(url))
        if ":49154/" not in str(url):
            raise httpx.ConnectError("refused")
        return httpx.Response(200, text="<BinaryState>1</BinaryState>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    await drv.configure(WemoConfig(devices=[{"ip": "10.0.0.5"}]))
    assert await drv._get_state("10.0.0.5", 1.0) == 1
    assert any(":49153/" in u for u in attempts), "should try the default port first"
    attempts.clear()
    await drv.set_power("10.0.0.5", False)
    assert all(":49154/" in u for u in attempts), "working port should be cached"


async def test_wemo_explicit_port_is_honoured(monkeypatch):
    attempts: list[str] = []

    async def fake_post(self, url, **kw):
        attempts.append(str(url))
        return httpx.Response(200, text="<BinaryState>0</BinaryState>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    assert await drv._get_state("10.0.0.5:49155", 1.0) == 0
    assert attempts == ["http://10.0.0.5:49155/upnp/control/basicevent1"]


async def test_wemo_all_ports_down_raises_wemo_error(monkeypatch):
    async def fake_post(self, url, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    with pytest.raises(wemo_mod.WemoError):
        await drv._get_state("10.0.0.5", 1.0)


async def test_wemo_unreachable_host_does_not_probe_every_port(monkeypatch):
    """A connect timeout means the host is down — don't multiply the delay
    (this path also carries safety-OFF retries) by probing four more ports."""
    attempts: list[str] = []

    async def fake_post(self, url, **kw):
        attempts.append(str(url))
        raise httpx.ConnectTimeout("no route")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = WemoDriver()
    with pytest.raises(wemo_mod.WemoError):
        await drv._get_state("10.0.0.5", 1.0)
    assert len(attempts) == 1


# ── #18 Kasa full-frame read ─────────────────────────────────────────


async def test_kasa_reads_frame_split_across_segments(monkeypatch):
    big = {"system": {"get_sysinfo": {"relay_state": 1, "pad": "x" * 6000}}}
    body = kasa_mod._encrypt(json.dumps(big))

    async def handle(reader, writer):
        hdr = await reader.readexactly(4)
        await reader.readexactly(struct.unpack("!I", hdr)[0])
        writer.write(body[:1000])
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.write(body[1000:])
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(kasa_mod, "_KASA_PORT", port)
    try:
        resp = await kasa_mod._kasa_query("127.0.0.1", {"system": {"get_sysinfo": {}}}, 2.0)
    finally:
        server.close()
        await server.wait_closed()
    assert resp["system"]["get_sysinfo"]["relay_state"] == 1


# ── #19 credential change drops cached auth ──────────────────────────


@pytest.mark.parametrize("drv_cls,cfg_cls", [
    (FluenceDriver, FluenceConfig), (FohseDriver, FohseConfig), (TraneDriver, TraneConfig),
])
async def test_credential_change_drops_cached_token(drv_cls, cfg_cls):
    drv = drv_cls()
    await drv.configure(cfg_cls(email="old@x.co", password="old"))
    drv._token = "old-account-token"
    await drv.configure(cfg_cls(email="new@x.co", password="new"))
    assert drv._token is None


async def test_tapo_credential_change_drops_sessions_and_cloud_token():
    drv = TapoDriver()
    await drv.configure(TapoConfig(email="a@x.co", password="old"))
    drv._sessions["10.0.0.30"] = object()  # type: ignore[assignment]
    drv._cloud_token = "old"
    await drv.configure(TapoConfig(email="a@x.co", password="new"))
    assert drv._sessions == {}
    assert drv._cloud_token is None


# ── #16 Tapo cloud transport ─────────────────────────────────────────


async def test_tapo_cloud_poll_logs_in_once_and_reports_unimplemented(fresh_keystore, monkeypatch):
    logins: list[str] = []

    async def fake_post(self, url, json=None, **kw):
        logins.append(str(url))
        return httpx.Response(200, json={"result": {"token": "tok"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    drv = TapoDriver()
    await drv.configure(TapoConfig(transport="cloud", email="a@x.co", password="pw"))
    for _ in range(3):
        with pytest.raises(TapoError, match="cloud transport"):
            await drv.poll_once()
    assert len(logins) == 1, "cloud token must be reused across polls"


async def test_tapo_write_without_ip_fails_clearly():
    drv = TapoDriver()
    await drv.configure(TapoConfig(transport="cloud", email="a@x.co", password="pw"))
    with pytest.raises(ValueError, match="ip"):
        await drv.set_power("", True)


def test_tapo_us_region_is_not_the_apac_host():
    assert "aps1" not in _TAPO_CLOUD_BASE_BY_REGION["us"]


# ── #14 Pulse cloud token reuse ──────────────────────────────────────


async def test_pulse_cloud_poll_reuses_session_token(monkeypatch):
    calls: list[str] = []

    async def fake_request(self, method, url, headers, json=None):
        calls.append(url)
        if "/v2/auth/login" in url:
            return httpx.Response(200, json={"token": "tok-1"})
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    drv = PulseDriver()
    await drv.configure(PulseConfig(transport="cloud", email="a@x.co", password="pw"))

    polls = 0

    async def fake_sleep(_s):
        nonlocal polls
        polls += 1
        if polls >= 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await poller.poll_loop(
            lambda: drv._cfg,
            record_outcome=drv._record_outcome,
            sleep=fake_sleep,
            client_provider=drv._client_for,
        )
    assert sum(1 for u in calls if "/v2/auth/login" in u) == 1
    assert sum(1 for u in calls if u.endswith("/v2/devices")) == 3


async def test_pulse_client_rebuilt_when_credentials_change():
    drv = PulseDriver()
    cfg1 = PulseConfig(transport="cloud", email="a@x.co", password="pw")
    await drv.configure(cfg1)
    c1 = drv._client_for(cfg1)
    assert drv._client_for(cfg1) is c1
    cfg2 = PulseConfig(transport="cloud", email="a@x.co", password="other")
    await drv.configure(cfg2)
    assert drv._client_for(cfg2) is not c1
    assert drv._client_for(PulseConfig(transport="local")) is None
