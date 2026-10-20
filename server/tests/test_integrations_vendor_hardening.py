"""Vendor-driver correctness and safety.

* String booleans ("false"/"off"/"0") never switch a plug ON, and the cloud
  automation pause never reads "false" as truthy.
* Caller-supplied device ids and IPs cannot rewrite the request URL (path
  traversal with the operator's vendor bearer token, arbitrary
  host/port/path POSTs).
* Pulse cloud polling reuses its session token instead of an email+password
  login every cycle, until the credentials change.
* Wemo finds a plug whose UPnP port moved off 49153.
* The Tapo cloud transport does not log in every poll while reporting "ok"
  with zero telemetry, and cloud-only (ip-less) writes fail clearly.
* Kasa reads the whole length-prefixed frame, not one TCP segment, and
  refuses a frame header claiming more than any plug sends.
* A credential change drops cached vendor tokens and KLAP sessions.
"""

from __future__ import annotations

import importlib
import json
import struct
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

import app.automation.engine as engine
from app.cloud import service
from app.integrations import _actions
from app.integrations.fluence.driver import FluenceConfig, FluenceDriver
from app.integrations.fohse.driver import FohseConfig, FohseDriver
from app.integrations.kasa.driver import KasaConfig, KasaDriver, KasaError
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse.driver import PulseDriver
from app.integrations.tapo.config import TapoConfig
from app.integrations.tapo.driver import _TAPO_CLOUD_BASE_BY_REGION, TapoDriver, TapoError
from app.integrations.trane.driver import TraneConfig, TraneDriver
from app.integrations.wemo.driver import WemoConfig, WemoDriver
from tests._pi_c1_integrations import use_drivers

# The vendor packages bind a driver INSTANCE to the name `driver`, shadowing
# the submodule attribute — resolve the modules themselves.
kasa_mod = importlib.import_module("app.integrations.kasa.driver")
wemo_mod = importlib.import_module("app.integrations.wemo.driver")


@pytest.fixture
def drivers(monkeypatch):
    """Fresh Kasa, Wemo and Fohse drivers behind the dispatcher."""
    found = SimpleNamespace(kasa=KasaDriver(), wemo=WemoDriver(), fohse=FohseDriver())
    use_drivers(monkeypatch, found.kasa, found.wemo, found.fohse)
    return found


# ── String booleans ──────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected_state", [
    ("false", 0), ("off", 0), ("0", 0), (0, 0), (False, 0),
    ("true", 1), ("on", 1), (1, 1), (True, 1),
])
async def test_kasa_set_power_coerces_string_booleans(drivers, monkeypatch, raw, expected_state):
    sent: list[dict] = []

    async def fake_query(ip, payload, timeout):
        sent.append(payload)
        return {}

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    await _actions.dispatch("kasa", "set_power", {"ip": "10.0.0.20", "on": raw})
    assert sent == [{"system": {"set_relay_state": {"state": expected_state}}}]


async def test_kasa_set_power_rejects_ambiguous_boolean(drivers, monkeypatch):
    async def fake_query(ip, payload, timeout):  # pragma: no cover — must not run
        raise AssertionError("device must not be actuated on an ambiguous value")

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("kasa", "set_power", {"ip": "10.0.0.20", "on": "maybe"})
    assert exc.value.status_code == 400


@pytest.mark.parametrize("raw,outcome", [("false", [False]), ("sometimes", None)],
                         ids=["string-false-resumes", "garbage-is-refused"])
async def test_cloud_automation_pause_reads_a_lax_bool(monkeypatch, raw, outcome):
    seen: list[bool] = []

    async def fake_set_paused(value):
        seen.append(value)

    monkeypatch.setattr(engine, "set_paused", fake_set_paused)
    ok, err = await service._dispatch_system_command("automation", {"paused": raw})
    if outcome is None:
        assert ok is False and "paused" in err
        assert seen == []  # never toggled on an ambiguous value
    else:
        assert ok is True, err
        assert seen == outcome


# ── IDs / IPs can't rewrite the request URL ──────────────────────────


async def test_fohse_fixture_id_path_traversal_rejected(drivers, monkeypatch):
    await drivers.fohse.configure(FohseConfig(email="a@b.co", password="pw"))
    drivers.fohse._token = "operator-bearer"
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

    # A numeric id is still one path segment.
    await _actions.dispatch("fohse", "set_dim", {"fixture_id": 42, "percent": 10})
    assert len(urls) == 1 and urls[0].endswith("/fixtures/42/intensity")


async def test_wemo_ip_url_injection_rejected(drivers, monkeypatch):
    posted: list[str] = []

    async def fake_post(self, url, **kw):
        posted.append(str(url))
        return httpx.Response(200, text="<BinaryState>1</BinaryState>")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("wemo", "set_power", {"ip": "10.0.0.5:80/latest#", "on": False})
    assert exc.value.status_code == 400
    assert posted == []


@pytest.mark.parametrize("cfg_cls,ip", [
    (WemoConfig, "10.0.0.5:80/latest#"),
    (KasaConfig, "10.0.0.5/x?y"),
    (TapoConfig, "user@10.0.0.5"),
], ids=["wemo", "kasa", "tapo"])
def test_a_device_ip_that_is_a_url_is_refused_on_save(cfg_cls, ip):
    with pytest.raises(ValueError):
        cfg_cls.model_validate({"devices": [{"ip": ip}]})


# ── Wemo port discovery ──────────────────────────────────────────────


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


# ── Kasa full-frame read ─────────────────────────────────────────────


class _SegmentedReader:
    """A plug reply arriving in TCP segments of at most ``segment`` bytes:
    ``read(n)`` returns one segment, ``readexactly(n)`` waits for n bytes
    (asyncio.StreamReader's own semantics)."""

    def __init__(self, data: bytes, segment: int = 1000):
        self._buf = data
        self._segment = segment

    async def read(self, n: int = -1) -> bytes:
        take = min(n if n >= 0 else len(self._buf), self._segment)
        chunk, self._buf = self._buf[:take], self._buf[take:]
        return chunk

    async def readexactly(self, n: int) -> bytes:
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk


class _Writer:
    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def _plug_replying(monkeypatch, wire: bytes) -> None:
    async def fake_open(host, port):
        return _SegmentedReader(wire), _Writer()

    monkeypatch.setattr(kasa_mod.asyncio, "open_connection", fake_open)


async def test_kasa_reads_frame_split_across_segments(monkeypatch):
    big = {"system": {"get_sysinfo": {"relay_state": 1, "pad": "x" * 6000}}}
    _plug_replying(monkeypatch, kasa_mod._encrypt(json.dumps(big)))
    resp = await kasa_mod._kasa_query("10.0.0.20", {"system": {"get_sysinfo": {}}}, 2.0)
    assert resp["system"]["get_sysinfo"]["relay_state"] == 1


async def test_kasa_refuses_a_frame_larger_than_any_plug_sends(monkeypatch):
    # A header claiming a huge body is not buffered (a LAN device cannot make
    # the Pi allocate gigabytes).
    _plug_replying(monkeypatch, struct.pack("!I", kasa_mod._MAX_FRAME_BYTES + 1) + b"x" * 64)
    with pytest.raises(KasaError, match="too large"):
        await kasa_mod._kasa_query("10.0.0.20", {"system": {"get_sysinfo": {}}}, 2.0)


# ── Credential change drops cached auth ──────────────────────────────


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


# ── Tapo cloud transport ─────────────────────────────────────────────


async def test_tapo_cloud_poll_logs_in_once_and_reports_unimplemented(monkeypatch):
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


# ── Pulse cloud token reuse ──────────────────────────────────────────


async def test_pulse_cloud_reuses_its_token_until_the_credentials_change(monkeypatch):
    calls: list[tuple[str, dict | None, str | None]] = []

    async def fake_request(self, method, url, headers, json=None):
        calls.append((url, json, headers.get("Authorization")))
        if "/v2/auth/login" in url:
            return httpx.Response(200, json={"token": f"tok-{json['password']}"})
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    drv = PulseDriver()
    await drv.configure(PulseConfig(transport="cloud", email="a@x.co", password="pw"))
    for _ in range(3):
        await drv.poll_once()
    # A password change must not keep using the old account's session.
    await drv.configure(PulseConfig(transport="cloud", email="a@x.co", password="other"))
    await drv.poll_once()

    assert [body["password"] for url, body, _ in calls if "/v2/auth/login" in url] == ["pw", "other"]
    device_lists = [auth for url, _, auth in calls if url.endswith("/v2/devices")]
    assert device_lists == ["Bearer tok-pw"] * 3 + ["Bearer tok-other"]
