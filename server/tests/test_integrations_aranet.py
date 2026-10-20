"""The Aranet PRO poller driver.

* base_url is normalised (the API path suffix and a trailing slash cut, a
  host that merely starts with "api" kept) and refused without http(s) or a
  host; the poll interval has a floor.
* The client maps 401 / 404 / 5xx / transport / non-JSON / an unparseable
  shape to an AranetError with operator-readable text (a 502 from Discover,
  an error health from Test), never an unhandled 500; the response model
  tolerates both envelopes, null values, numeric ids and bad entries.
* A poll stores temperature / humidity / CO2 under SporePrint sensor names in
  one batch, skips unmapped types and empty readings, stores a sample once at
  its own time and reports a sample that stops changing as stale.
* Test counts what a poll would store and stores nothing.
* /discover: 400 without config, the sensor list with chamber mappings, 502
  on an Aranet error, and the saved config after a restart.
"""

from __future__ import annotations

import importlib
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations import _registry
from app.integrations._samples import PollResult, SampleTracker
from app.integrations.aranet.client import AranetClient, AranetError
from app.integrations.aranet.config import AranetConfig
from app.integrations.aranet.driver import AranetDriver
from app.integrations.aranet.models import AranetMeasurementsResponse, AranetSensor
from app.integrations.aranet.poller import STALE_FLOOR_SECONDS, run_one_poll
from app.integrations.aranet.router import router as aranet_extra_router
from tests._pi_c1_integrations import (  # noqa: F401 — the fresh_keystore fixture
    fresh_keystore_fixture,
    stored_readings,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def app_client(fresh_keystore, monkeypatch):
    drv = _registry.registered_drivers().get("aranet")
    assert isinstance(drv, AranetDriver)
    # The singleton gets its own state back after the test.
    for attr, value in (("_cfg", AranetConfig()), ("_task", None), ("_last_poll_at", None),
                        ("_last_poll_ok", False), ("_last_error", None)):
        monkeypatch.setattr(drv, attr, value)

    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    app.include_router(aranet_extra_router, prefix="/api/integrations/aranet")
    with TestClient(app) as client:
        yield drv, client


def _aranet_payload(sensors: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sensors": sensors}


# ── Config validation ─────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://apiary.local", "http://api-gw.lan", "https://api.aranet.cloud", "http://10.0.0.5/apiary",
])
def test_config_keeps_api_lookalike_hosts_and_paths(url):
    # Only a whole `api` path segment is the endpoint suffix: a host that
    # starts with "api" used to be cut down to "http:" and rejected.
    assert AranetConfig(base_url=url).base_url == url


@pytest.mark.parametrize("url,expected", [
    ("http://10.0.0.5/api", "http://10.0.0.5"),
    ("http://10.0.0.5/api/v1/measurements", "http://10.0.0.5"),
    ("http://10.0.0.42/api/v1/measurements/last/", "http://10.0.0.42"),
    ("http://apiary.local/api/v1/measurements/last/", "http://apiary.local"),
    ("https://gw.lan/aranet/api/v1", "https://gw.lan/aranet"),
])
def test_config_cuts_the_api_path_suffix(url, expected):
    assert AranetConfig(base_url=url).base_url == expected


@pytest.mark.parametrize("fields,error", [
    ({"base_url": "ftp://10.0.0.42"}, "http://"),
    ({"base_url": "http://"}, "host"),
    ({"poll_seconds": 10}, "greater than or equal"),  # below the 30 s floor
], ids=["scheme", "host", "poll-floor"])
def test_config_refuses_what_the_driver_cannot_poll(fields, error):
    with pytest.raises(ValueError, match=error):
        AranetConfig(**fields)


# ── Response model ────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,ids", [
    (_aranet_payload([{"id": "abc", "measurements": [{"type": "temperature", "value": 23}]}]),
     ["abc"]),
    ({"data": _aranet_payload([{"id": "xyz", "measurements": []}])}, ["xyz"]),
    ({"unexpected": True}, []),
    (["not", "a", "dict"], []),
], ids=["root", "data-envelope", "unknown-shape", "not-a-dict"])
def test_response_reads_either_envelope_and_nothing_else(raw, ids):
    assert [s.id for s in AranetMeasurementsResponse.from_payload(raw).sensors] == ids


def test_response_tolerates_null_values_numeric_ids_and_bad_entries():
    # One sensor with no reading yet, a numeric id, and malformed entries
    # must not fail the whole response (each would have been a
    # ValidationError: a 500 from Test / Discover, and no readings at all).
    raw = _aranet_payload([
        {"id": 4194306, "measurements": [
            {"type": "temperature", "value": None},
            {"type": "humidity", "value": 81.5},
            {"value": 3.0},                            # no type: dropped
            {"type": "co2", "value": "not-a-number"},  # dropped
        ]},
        {"name": "no id"},                             # dropped
        "garbage",                                     # dropped
    ])
    parsed = AranetMeasurementsResponse.from_payload(raw)
    assert [s.id for s in parsed.sensors] == ["4194306"]
    measurements = parsed.sensors[0].measurements
    assert [(m.type, m.value) for m in measurements] == [("temperature", None), ("humidity", 81.5)]


# ── HTTP client ───────────────────────────────────────────────────────


def _connect_refused(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize("reply,error", [
    (lambda r: httpx.Response(401, text="bad key"), "X-API-Key"),
    (lambda r: httpx.Response(404, text="not found"), r"firmware ≥ 2\.0"),
    (lambda r: httpx.Response(503, text="overloaded"), "HTTP 503"),
    (_connect_refused, "transport error"),
    (lambda r: httpx.Response(200, text="<html>login</html>"), "non-JSON"),
], ids=["401", "404", "5xx", "unreachable", "not-json"])
async def test_client_failures_are_aranet_errors_an_operator_can_act_on(monkeypatch, reply, error):
    async def fake_get(self, url, headers):
        return reply(httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(AranetError, match=error):
        await AranetClient("http://10.0.0.42", "key").fetch_latest()


async def test_client_turns_an_unparseable_shape_into_aranet_error(monkeypatch):
    # A payload that still does not validate is an AranetError (502 from
    # /discover, an error health from Test), never an unhandled 500.
    async def fake_get(self, url, headers):
        return httpx.Response(200, json={"sensors": []})

    def _invalid(raw):
        AranetSensor.model_validate({})  # no id: a pydantic ValidationError

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(AranetMeasurementsResponse, "from_payload", staticmethod(_invalid))
    client = AranetClient("http://10.0.0.42", "key")
    with pytest.raises(AranetError, match="unexpected response shape"):
        await client.fetch_latest()


async def test_a_driver_poll_reads_the_pro_with_its_key_and_stores_the_readings(monkeypatch):
    seen = {}

    async def fake_get(self, url, headers):
        seen["url"], seen["key"] = str(url), headers["X-API-Key"]
        return httpx.Response(200, json=_aranet_payload([{
            "id": "s1",
            "name": "Tent A",
            "measurements": [
                {"type": "temperature", "value": 23.4, "unit": "C"},
                {"type": "humidity", "value": 88.0, "unit": "%"},
            ],
        }]))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://10.0.0.42", api_key="key"))
    rows, diag = await drv.poll_once()
    assert (rows, diag["failed"]) == (2, {})
    assert seen == {"url": "http://10.0.0.42/api/v1/measurements/last", "key": "key"}
    assert await stored_readings("aranet:s1") == {("temp_c", 23.4), ("humidity", 88.0)}


# ── Poller ────────────────────────────────────────────────────────────


def _stub_response(*sensors_with_measurements):
    """Sensors as (id, [(type, value) or (type, value, extra fields)])."""
    return AranetMeasurementsResponse(
        sensors=[
            {
                "id": s_id,
                "name": s_id,
                "measurements": [
                    {"type": m[0], "value": m[1], **(m[2] if len(m) > 2 else {})}
                    for m in measurements
                ],
            }
            for s_id, measurements in sensors_with_measurements
        ]
    )


class _StubClient:
    def __init__(self, response):
        self._response = response

    async def fetch_latest(self):
        return self._response


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


async def test_poller_publishes_mapped_measurement_types():
    response = _stub_response(
        ("s1", [("temperature", 23.5), ("humidity", 88.0), ("co2", 870)])
    )
    cfg = AranetConfig(base_url="http://x", api_key="k")
    writer = _Writer()

    result = await run_one_poll(cfg, client=_StubClient(response), writer=writer, now=1_000.0)
    assert result.written == 3
    # One poll is one batch (one transaction), not a commit per reading.
    assert len(writer.batches) == 1
    stored = {(node, sensor, value) for _ts, node, sensor, value in writer.rows}
    assert stored == {
        ("aranet:s1", "temp_c", 23.5),
        ("aranet:s1", "humidity", 88.0),
        ("aranet:s1", "co2_ppm", 870.0),
    }


async def test_poller_skips_unmapped_types():
    response = _stub_response(
        ("s1", [
            ("temperature", 22.0),
            ("atmospheric_pressure", 1012),
            ("radiation_dose_rate", 0.13),
        ])
    )
    cfg = AranetConfig(base_url="http://x", api_key="k")
    writer = _Writer()

    result = await run_one_poll(cfg, client=_StubClient(response), writer=writer)
    assert result.written == 1
    assert [(node, sensor, value) for _ts, node, sensor, value in writer.rows] == [
        ("aranet:s1", "temp_c", 22.0)
    ]


async def test_poller_skips_a_measurement_without_a_value():
    """A sensor with no reading yet must not stop its siblings."""

    response = _stub_response(
        ("good", [("temperature", 21.0)]),
        ("empty", [("temperature", None)]),
    )
    cfg = AranetConfig(base_url="http://x", api_key="k")
    writer = _Writer()

    result = await run_one_poll(cfg, client=_StubClient(response), writer=writer)
    assert result.written == 1
    assert [row[1:] for row in writer.rows] == [("aranet:good", "temp_c", 21.0)]


async def test_poller_converts_a_fahrenheit_temperature():
    response = _stub_response(("s1", [("temperature", 77.0, {"unit": "°F"})]))
    writer = _Writer()
    await run_one_poll(AranetConfig(base_url="http://x", api_key="k"),
                       client=_StubClient(response), writer=writer)
    assert writer.rows[0][2:] == ("temp_c", pytest.approx(25.0))


async def test_a_sample_is_stored_once_at_its_own_time():
    # The PRO keeps serving a sensor's latest sample until the next radio
    # report; every poll used to store it again, stamped with the Pi's clock.
    cfg = AranetConfig(base_url="http://x", api_key="k", poll_seconds=60)
    tracker = SampleTracker(STALE_FLOOR_SECONDS)
    writer = _Writer()
    taken = 1_700_000_000.0
    sample = _stub_response(("s1", [("temperature", 22.0, {"timestamp": taken})]))

    first = await run_one_poll(cfg, client=_StubClient(sample), tracker=tracker,
                               writer=writer, now=taken + 30)
    again = await run_one_poll(cfg, client=_StubClient(sample), tracker=tracker,
                               writer=writer, now=taken + 90)
    assert (first.written, again.written) == (1, 0)
    assert writer.rows == [(taken, "aranet:s1", "temp_c", 22.0)]
    assert again.failed == {}

    newer = _stub_response(("s1", [("temperature", 22.4, {"timestamp": "2023-11-14T22:23:20Z"})]))
    third = await run_one_poll(cfg, client=_StubClient(newer), tracker=tracker,
                               writer=writer, now=taken + 600)
    assert third.written == 1
    assert writer.rows[-1] == (taken + 600, "aranet:s1", "temp_c", 22.4)


async def test_a_sample_that_stops_changing_is_reported_stale():
    cfg = AranetConfig(base_url="http://x", api_key="k", poll_seconds=60)
    tracker = SampleTracker(STALE_FLOOR_SECONDS)
    taken = 1_700_000_000.0
    sample = _stub_response(
        ("dead", [("co2", 900, {"timestamp": taken})]),
        ("live", [("co2", 800, {"timestamp": taken + STALE_FLOOR_SECONDS + 100})]),
    )
    result = await run_one_poll(cfg, client=_StubClient(sample), tracker=tracker,
                                writer=_Writer(), now=taken + STALE_FLOOR_SECONDS + 120)
    # The dead sensor's old sample is not stored as a fresh reading; the
    # live one is, and the poll reports which sensor went quiet.
    assert result.written == 1
    assert list(result.failed) == ["aranet:dead"]
    assert result.devices == 2


async def test_a_sample_without_a_trusted_time_goes_stale_by_the_pi_clock():
    # A naive ISO time (zone unknown) can only tell samples apart.
    cfg = AranetConfig(base_url="http://x", api_key="k", poll_seconds=60)
    tracker = SampleTracker(STALE_FLOOR_SECONDS)
    sample = _stub_response(("s1", [("humidity", 85.0, {"timestamp": "2026-10-18T10:00:00"})]))
    first = await run_one_poll(cfg, client=_StubClient(sample), tracker=tracker,
                               writer=_Writer(), now=5_000.0)
    later = await run_one_poll(cfg, client=_StubClient(sample), tracker=tracker,
                               writer=_Writer(), now=5_000.0 + STALE_FLOOR_SECONDS + 1)
    assert (first.written, first.failed) == (1, {})
    assert (later.written, list(later.failed)) == (0, ["aranet:s1"])


async def test_poll_once_reports_stale_sensors_as_failed_devices(monkeypatch):
    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://x", api_key="k"))
    seen = {}

    async def _fake_run(cfg, *, tracker, **kwargs):
        seen["tracker"] = tracker
        return PollResult(2, 3, {"aranet:s9": "no new reading for over 30 min"})

    # The package binds the driver INSTANCE to `driver`, shadowing the module.
    monkeypatch.setattr(importlib.import_module("app.integrations.aranet.driver"),
                        "run_one_poll", _fake_run)
    rows, diag = await drv.poll_once()
    assert rows == 2
    assert diag["devices"] == 3 and diag["failed"] == {"aranet:s9": "no new reading for over 30 min"}
    assert seen["tracker"] is drv._samples, "the driver's tracker must persist across polls"


# ── Test ──────────────────────────────────────────────────────────────


async def test_test_connection_returns_ok_with_sensor_count_and_stores_nothing(monkeypatch):
    response = _stub_response(("s1", [("temperature", 22.0), ("co2", 900)]))

    async def _fake_fetch(self):
        return response

    monkeypatch.setattr(AranetClient, "fetch_latest", _fake_fetch)
    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://x", api_key="k"))
    health = await drv.test_connection()

    assert health.state == "ok"
    assert health.details == {"sensors_seen": 1, "readings_seen": 2}
    # A Test is a reachability check: it used to run a full poll and write
    # the readings into telemetry history.
    assert await stored_readings() == set()


async def test_test_connection_surfaces_aranet_error(monkeypatch):
    async def _boom(self):
        raise AranetError("401 unauthorized")

    monkeypatch.setattr(AranetClient, "fetch_latest", _boom)

    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://x", api_key="bad"))
    health = await drv.test_connection()
    assert health.state == "error"
    assert "unauthorized" in (health.last_error or "")


# ── /discover route ───────────────────────────────────────────────────


def test_discover_returns_400_without_config(app_client):
    drv, client = app_client
    resp = client.get("/api/integrations/aranet/discover")
    assert resp.status_code == 400


def test_discover_returns_sensor_list(app_client, monkeypatch):
    drv, client = app_client
    drv._cfg = AranetConfig(
        base_url="http://10.0.0.42",
        api_key="k",
        sensor_mappings={"s1": "1"},
    )

    response = _stub_response(
        ("s1", [("temperature", 23.0), ("co2", 900)]),
        ("s2", [("humidity", 88.0)]),
    )

    async def _fake_fetch(self):
        return response

    monkeypatch.setattr(AranetClient, "fetch_latest", _fake_fetch)

    resp = client.get("/api/integrations/aranet/discover")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sensors"]) == 2
    s1 = next(s for s in body["sensors"] if s["id"] == "s1")
    assert set(s1["measurement_types"]) == {"temperature", "co2"}
    assert s1["mapped_to_chamber"] == "1"
    s2 = next(s for s in body["sensors"] if s["id"] == "s2")
    assert s2["mapped_to_chamber"] is None


def test_discover_502_on_aranet_error(app_client, monkeypatch):
    drv, client = app_client
    drv._cfg = AranetConfig(base_url="http://x", api_key="k")

    async def _boom(self):
        raise AranetError("transport error: connection refused")

    monkeypatch.setattr(AranetClient, "fetch_latest", _boom)

    resp = client.get("/api/integrations/aranet/discover")
    assert resp.status_code == 502
    assert "connection refused" in resp.text


def test_discover_after_a_restart_uses_the_saved_config(app_client, monkeypatch):
    drv, client = app_client
    # Saved with the driver left disabled, then a restart: only enabled rows
    # are configured at boot, so the driver holds its constructor defaults.
    resp = client.put("/api/integrations/aranet/config", json={
        "enabled": False, "config": {"base_url": "http://10.0.0.42", "api_key": "k-123"}})
    assert resp.status_code == 200
    drv._cfg = AranetConfig()
    seen = {}

    async def _fake_fetch(self):
        seen["url"], seen["key"] = self._base_url, self._api_key
        return _stub_response(("s1", [("temperature", 21.0)]))

    monkeypatch.setattr(AranetClient, "fetch_latest", _fake_fetch)
    resp = client.get("/api/integrations/aranet/discover")
    assert resp.status_code == 200, resp.text
    assert seen == {"url": "http://10.0.0.42", "key": "k-123"}
