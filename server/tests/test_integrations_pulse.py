"""The Pulse Grow driver (cloud transport; local mode has its own file).

* Config: a blank config is a valid staged one (cloud transport by
  default), a pasted password is trimmed, and a malformed email, a poll
  interval under the floor or a too-short discovery window is refused.
* Models tolerate the ``{token}`` / ``{data: {token}}`` login envelopes, the
  list / ``{devices}`` / ``{data}`` device envelopes, null values, numeric
  ids and bad entries.
* The client logs in, re-logs in once on a 401 (never in a loop), and maps
  429 / 5xx / transport / non-JSON failures to a PulseError.
* A poll maps temperature / humidity / vpd / dew point / light to SporePrint
  sensors in their units, skips unmapped types, isolates and reports a
  failing device, stores a sample once and reports it stale when it stops
  changing, and reuses one cloud client across polls.
* /devices: 400 without config, the list with chamber mappings, 502 on a
  Pulse error, the saved config after a restart, 409 for a stored password
  that no longer decrypts.
"""

from __future__ import annotations

import importlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.integrations import _registry
from app.integrations._keystore import reset_fernet_cache
from app.integrations._samples import PollResult, SampleTracker
from app.integrations.pulse.client import PulseCloudClient, PulseError
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse.driver import PulseDriver
from app.integrations.pulse.models import (
    PulseDeviceListResponse,
    PulseLoginResponse,
    PulseRecentDataResponse,
)
from app.integrations.pulse.poller import STALE_FLOOR_SECONDS, run_one_poll
from app.integrations.pulse.router import router as pulse_extra_router
from tests._pi_c1_integrations import fresh_keystore_fixture  # noqa: F401 — the fresh_keystore fixture


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def app_client(fresh_keystore, monkeypatch):
    drv = _registry.registered_drivers().get("pulse")
    assert isinstance(drv, PulseDriver)
    # The singleton gets its own state back after the test.
    for attr, value in (("_cfg", PulseConfig()), ("_task", None), ("_last_poll_at", None),
                        ("_last_poll_ok", False), ("_last_error", None)):
        monkeypatch.setattr(drv, attr, value)

    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    app.include_router(pulse_extra_router, prefix="/api/integrations/pulse")
    with TestClient(app) as client:
        yield drv, client


def _login_payload(token="abc123"):
    return {"token": token}


def _device_list_payload(devices):
    return {"devices": devices}


def _recent_data_payload(measurements):
    return {"measurements": measurements}


# ── Config ────────────────────────────────────────────────────────────


def test_a_blank_config_is_a_valid_staged_one_and_a_pasted_password_is_trimmed():
    # Empty fields are how the operator stages a partially-configured driver.
    staged = PulseConfig()
    assert (staged.transport, staged.email, staged.password) == ("cloud", "", "")
    assert PulseConfig(email="b@example.com", password="  secret\n  ").password == "secret"
    assert PulseConfig(local_discovery_timeout_seconds=5.0).local_discovery_timeout_seconds == 5.0


@pytest.mark.parametrize("fields,error", [
    ({"email": "brandon-at-example.com", "password": "x"}, "@"),
    ({"poll_seconds": 10}, "greater than or equal"),
    ({"transport": "local", "local_discovery_timeout_seconds": 0.5}, "greater than or equal"),
], ids=["email", "poll-floor", "discovery-window"])
def test_config_refuses_what_the_driver_cannot_use(fields, error):
    with pytest.raises(ValueError, match=error):
        PulseConfig(**fields)


# ── Models ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload,token", [
    ({"token": "tok"}, "tok"),
    ({"data": {"token": "tok"}}, "tok"),
    ({"weird": True}, None),
], ids=["root", "data-envelope", "unknown-shape"])
def test_login_response_reads_either_envelope(payload, token):
    assert PulseLoginResponse.from_payload(payload).token == token


@pytest.mark.parametrize("payload", [
    [{"id": "a"}, {"id": "b"}],
    {"devices": [{"id": "a"}, {"id": "b"}]},
    {"data": [{"id": "a"}, {"id": "b"}]},
], ids=["array", "devices-envelope", "data-envelope"])
def test_device_list_reads_every_envelope(payload):
    assert [d.id for d in PulseDeviceListResponse.from_payload(payload).devices] == ["a", "b"]


@pytest.mark.parametrize("payload,count", [
    ({"measurements": [{"type": "temperature", "value": 22.0}]}, 1),
    ({"weird": True}, 0),
], ids=["measurements", "unknown-shape"])
def test_recent_data_carries_its_device_id(payload, count):
    parsed = PulseRecentDataResponse.from_payload(payload, device_id="abc")
    assert parsed.device_id == "abc"
    assert len(parsed.measurements) == count


def test_models_tolerate_null_values_numeric_ids_and_bad_entries():
    devices = PulseDeviceListResponse.from_payload([{"id": 1234}, {"name": "no id"}, "junk"])
    assert [d.id for d in devices.devices] == ["1234"]
    data = PulseRecentDataResponse.from_payload(
        {"measurements": [_measurement("temperature", None), _measurement("humidity", 80),
                          {"value": 1}, _measurement("vpd", "n/a")]},
        device_id="1234",
    )
    assert [(m.type, m.value) for m in data.measurements] == [("temperature", None), ("humidity", 80.0)]
    assert PulseRecentDataResponse.from_payload(["not", "a", "dict"], "d").measurements == []


# ── Client ────────────────────────────────────────────────────────────


async def test_client_login_sets_token(monkeypatch):
    async def fake_request(self, method, url, headers, json=None):
        assert "/v2/auth/login" in url
        assert json == {"email": "b@example.com", "password": "pw"}
        return httpx.Response(200, json=_login_payload("tok-1"))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    token = await client.login()
    assert token == "tok-1"
    assert client.has_token


async def test_client_login_with_no_token_in_response_raises(monkeypatch):
    async def fake_request(self, method, url, headers, json=None):
        return httpx.Response(200, json={"unexpected": True})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    with pytest.raises(PulseError, match="no token in response"):
        await client.login()


async def test_client_re_logs_in_on_401(monkeypatch):
    """Token expired → discard, re-login, retry once."""

    calls: list[str] = []

    async def fake_request(self, method, url, headers, json=None):
        calls.append(url)
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("fresh-tok"))
        if "/v2/devices" in url and len(calls) <= 2:
            # First protected call: 401 → forces re-login
            return httpx.Response(401, text="expired")
        # Third call: post-relogin retry
        return httpx.Response(200, json=_device_list_payload([]))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    await client.login()  # cache initial token
    devices = await client.list_devices()
    assert devices.devices == []
    # Sequence: initial login, devices (401), forced login, devices retry.
    assert sum(1 for u in calls if "/v2/auth/login" in u) == 2
    assert sum(1 for u in calls if "/v2/devices" in u) == 2


async def test_client_does_not_loop_re_login(monkeypatch):
    """A persistently-401 protected endpoint must not re-login forever."""

    call_count = {"n": 0}

    async def fake_request(self, method, url, headers, json=None):
        call_count["n"] += 1
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("tok"))
        return httpx.Response(401, text="bad creds")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    with pytest.raises(PulseError, match="unauthorized"):
        await client.list_devices()
    # Bounded calls: initial login + protected 401 + relogin + protected 401 = 4
    assert call_count["n"] <= 4


def _unreachable(url):
    raise httpx.ConnectError("network unreachable", request=httpx.Request("GET", url))


@pytest.mark.parametrize("reply,error", [
    (lambda url: httpx.Response(429, text="slow down"), "rate-limited"),
    (lambda url: httpx.Response(500, text="oops"), "HTTP 500"),
    (_unreachable, "transport error"),
    (lambda url: httpx.Response(200, text="<html>maintenance</html>"), "non-JSON"),
], ids=["429", "5xx", "unreachable", "not-json"])
async def test_client_failures_are_pulse_errors(monkeypatch, reply, error):
    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("t"))
        return reply(url)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    with pytest.raises(PulseError, match=error):
        await client.list_devices()


async def test_client_recent_data_calls_correct_path(monkeypatch):
    captured = {}

    async def fake_request(self, method, url, headers, json=None):
        captured["url"] = url
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("t"))
        return httpx.Response(
            200,
            json=_recent_data_payload(
                [{"type": "temperature", "value": 22.0}]
            ),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    response = await client.recent_data("device-42")
    assert "/v2/devices/device-42/recent-data" in captured["url"]
    assert response.device_id == "device-42"


# ── Poller ────────────────────────────────────────────────────────────


class _StubClient:
    def __init__(self, devices, recent_data_by_id):
        self._devices = devices
        self._data = recent_data_by_id

    async def login(self):
        pass

    async def list_devices(self):
        return PulseDeviceListResponse(devices=self._devices)

    async def recent_data(self, device_id):
        if device_id not in self._data:
            raise PulseError("no data")
        return self._data[device_id]


def _measurement(type_, value, **extra):
    return {"type": type_, "value": value, **extra}


class _Writer:
    """Captures each batch a poll stores, the way store_readings would."""

    def __init__(self):
        self.batches: list[list[tuple]] = []

    async def __call__(self, rows):
        self.batches.append(list(rows))
        return len(rows)

    @property
    def rows(self):
        return [row for batch in self.batches for row in batch]


async def test_poller_publishes_mapped_measurements():
    client = _StubClient(
        devices=[{"id": "d1"}],
        recent_data_by_id={
            "d1": PulseRecentDataResponse.from_payload(
                _recent_data_payload(
                    [
                        _measurement("temperature", 22.5),
                        _measurement("humidity", 86.0),
                        _measurement("vpd", 0.45),
                        _measurement("dew_point", 19.8),
                        _measurement("light", 12000),
                    ]
                ),
                device_id="d1",
            )
        },
    )

    cfg = PulseConfig(email="b@example.com", password="pw")
    writer = _Writer()

    result = await run_one_poll(cfg, client=client, writer=writer)
    assert result.written == 5
    assert len(writer.batches) == 1, "one poll is one transaction"
    rows_by_sensor = {sensor: value for _ts, _node, sensor, value in writer.rows}
    assert rows_by_sensor["temp_c"] == 22.5
    assert rows_by_sensor["humidity"] == 86.0
    assert rows_by_sensor["vpd_kpa"] == 0.45
    # 19.8°C converted at ingest — canonical firmware name + unit
    assert rows_by_sensor["dew_point_f"] == pytest.approx(67.64)
    assert rows_by_sensor["lux"] == 12000


async def test_poller_reads_fahrenheit_units():
    response = PulseRecentDataResponse.from_payload(
        _recent_data_payload([
            _measurement("temperature", 77.0, unit="°F"),
            _measurement("dew_point", 67.6, unit="F"),
        ]),
        device_id="d1",
    )
    client = _StubClient(devices=[{"id": "d1"}], recent_data_by_id={"d1": response})
    writer = _Writer()
    await run_one_poll(PulseConfig(email="b@example.com", password="pw"), client=client, writer=writer)
    rows_by_sensor = {sensor: value for _ts, _node, sensor, value in writer.rows}
    assert rows_by_sensor["temp_c"] == pytest.approx(25.0)
    assert rows_by_sensor["dew_point_f"] == pytest.approx(67.6), "already °F: not converted twice"


async def test_poller_isolates_and_reports_per_device_failures():
    """A failing device fetch must not stop sibling devices."""

    class _PartFailClient(_StubClient):
        async def recent_data(self, device_id):
            if device_id == "broken":
                raise PulseError("device offline")
            return PulseRecentDataResponse.from_payload(
                _recent_data_payload([_measurement("temperature", 21.0)]),
                device_id=device_id,
            )

    client = _PartFailClient(
        devices=[{"id": "ok"}, {"id": "broken"}, {"id": "ok2"}],
        recent_data_by_id={},
    )
    cfg = PulseConfig(email="b@example.com", password="pw")
    writer = _Writer()

    result = await run_one_poll(cfg, client=client, writer=writer)
    assert result.written == 2  # ok + ok2
    assert "pulse:broken" not in {node for _ts, node, _s, _v in writer.rows}
    assert result.devices == 3
    assert result.failed == {"pulse:broken": "device offline"}


async def test_poller_skips_unmapped_types():
    response = PulseRecentDataResponse.from_payload(
        _recent_data_payload(
            [
                _measurement("temperature", 22.0),
                _measurement("co2", 800),  # unmapped
                _measurement("ph", 6.5),  # unmapped
            ]
        ),
        device_id="d1",
    )
    client = _StubClient(devices=[{"id": "d1"}], recent_data_by_id={"d1": response})
    cfg = PulseConfig(email="b@example.com", password="pw")
    writer = _Writer()

    result = await run_one_poll(cfg, client=client, writer=writer)
    assert result.written == 1
    assert [sensor for _ts, _node, sensor, _v in writer.rows] == ["temp_c"]


async def test_poller_stores_a_sample_once_and_reports_it_stale():
    taken = 1_700_000_000.0
    response = PulseRecentDataResponse.from_payload(
        _recent_data_payload([_measurement("humidity", 85.0, timestamp=taken)]),
        device_id="d1",
    )
    client = _StubClient(devices=[{"id": "d1"}], recent_data_by_id={"d1": response})
    cfg = PulseConfig(email="b@example.com", password="pw", poll_seconds=120)
    tracker = SampleTracker(STALE_FLOOR_SECONDS)
    writer = _Writer()

    first = await run_one_poll(cfg, client=client, tracker=tracker, writer=writer, now=taken + 60)
    repeat = await run_one_poll(cfg, client=client, tracker=tracker, writer=writer, now=taken + 180)
    late = await run_one_poll(cfg, client=client, tracker=tracker, writer=writer,
                              now=taken + STALE_FLOOR_SECONDS + 1)
    assert (first.written, repeat.written, late.written) == (1, 0, 0)
    assert writer.rows == [(taken, "pulse:d1", "humidity", 85.0)]
    assert repeat.failed == {}
    assert list(late.failed) == ["pulse:d1"]


async def test_poll_once_reuses_the_cloud_client_and_reports_failures(monkeypatch):
    drv = PulseDriver()
    await drv.configure(PulseConfig(email="b@example.com", password="pw"))
    seen = []

    async def _fake_run(cfg, *, client, tracker, **kwargs):
        seen.append((client, tracker))
        return PollResult(1, 2, {"pulse:x": "device offline"})

    # The package binds the driver INSTANCE to `driver`, shadowing the module.
    monkeypatch.setattr(importlib.import_module("app.integrations.pulse.driver"),
                        "run_one_poll", _fake_run)
    rows, diag = await drv.poll_once()
    await drv.poll_once()
    assert rows == 1 and diag["devices"] == 2 and diag["failed"] == {"pulse:x": "device offline"}
    assert seen[0][0] is seen[1][0] is not None, "one cloud client (one session token) across polls"
    assert seen[0][1] is drv._samples


# ── Test ──────────────────────────────────────────────────────────────


async def test_test_connection_returns_ok_with_device_count(monkeypatch):
    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("t"))
        return httpx.Response(
            200, json=_device_list_payload([{"id": "a"}, {"id": "b"}])
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    drv = PulseDriver()
    await drv.configure(PulseConfig(email="b@example.com", password="pw"))
    health = await drv.test_connection()
    assert health.state == "ok"
    assert health.details["devices_seen"] == 2


async def test_test_connection_surfaces_pulse_error(monkeypatch):
    async def fake_request(self, method, url, headers, json=None):
        return httpx.Response(401, text="bad")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    drv = PulseDriver()
    await drv.configure(PulseConfig(email="b@example.com", password="bad"))
    health = await drv.test_connection()
    assert health.state == "error"
    assert "unauthorized" in (health.last_error or "")


# ── /devices route ────────────────────────────────────────────────────


def test_devices_route_returns_400_without_config(app_client):
    drv, client = app_client
    resp = client.get("/api/integrations/pulse/devices")
    assert resp.status_code == 400


def test_devices_route_returns_list(app_client, monkeypatch):
    drv, client = app_client
    drv._cfg = PulseConfig(
        email="b@example.com",
        password="pw",
        device_mappings={"d-one": "1"},
    )

    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("t"))
        return httpx.Response(
            200,
            json=_device_list_payload(
                [
                    {"id": "d-one", "name": "Pulse One", "type": "pulse_one"},
                    {"id": "d-two", "name": "Pulse Pro", "type": "pulse_pro"},
                ]
            ),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    resp = client.get("/api/integrations/pulse/devices")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["devices"]) == 2
    d1 = next(d for d in body["devices"] if d["id"] == "d-one")
    assert d1["mapped_to_chamber"] == "1"
    d2 = next(d for d in body["devices"] if d["id"] == "d-two")
    assert d2["mapped_to_chamber"] is None


def test_devices_route_502_on_pulse_error(app_client, monkeypatch):
    drv, client = app_client
    drv._cfg = PulseConfig(email="b@example.com", password="pw")

    async def fake_request(self, method, url, headers, json=None):
        return httpx.Response(401, text="bad")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    resp = client.get("/api/integrations/pulse/devices")
    assert resp.status_code == 502


def test_devices_route_after_a_restart_uses_the_saved_config(app_client, monkeypatch):
    # Saved disabled, then a restart: only enabled rows are configured at
    # boot, so the device list used to answer "configure email and password
    # first" for credentials that were saved.
    drv, client = app_client
    assert client.put("/api/integrations/pulse/config", json={
        "enabled": False, "config": {"email": "b@example.com", "password": "pw-1"}}).status_code == 200
    drv._cfg = PulseConfig()
    logins = []

    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            logins.append(json)
            return httpx.Response(200, json=_login_payload("t"))
        return httpx.Response(200, json=_device_list_payload([{"id": "d-one"}]))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    resp = client.get("/api/integrations/pulse/devices")
    assert resp.status_code == 200, resp.text
    assert logins == [{"email": "b@example.com", "password": "pw-1"}]


def test_devices_route_refuses_an_undecryptable_password(app_client, monkeypatch, tmp_path):
    drv, client = app_client
    client.put("/api/integrations/pulse/config", json={
        "enabled": False, "config": {"email": "b@example.com", "password": "pw-1"}})
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".other-key"))
    reset_fernet_cache()
    resp = client.get("/api/integrations/pulse/devices")
    # Not a login with a blank password: the stored one must be re-entered.
    assert resp.status_code == 409
    assert "re-enter" in resp.text
