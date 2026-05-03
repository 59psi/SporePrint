"""Tests for the v4.1 Aranet PRO poller driver.

Covers:
  - Driver auto-registers on import
  - Config validation (URL normalisation, scheme check)
  - HTTP client maps 401/404/5xx to AranetError with operator-readable text
  - Response model tolerates both `{sensors:[]}` and `{data:{sensors:[]}}` shapes
  - Poller maps temperature/humidity/co2 → SporePrint sensor names and
    publishes via the injected publisher
  - Poller skips unmapped measurement types without crashing the cycle
  - Driver lifecycle: start/stop is idempotent, polling state surfaces in health
  - test_connection returns ok with sensor count, error on transport
  - /discover endpoint shape
  - 400 when discover called without config
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations import _registry
from app.integrations._keystore import reset_fernet_cache
from app.integrations.aranet import driver as aranet_driver_mod
from app.integrations.aranet.client import AranetClient, AranetError
from app.integrations.aranet.config import AranetConfig
from app.integrations.aranet.driver import AranetDriver
from app.integrations.aranet.models import AranetMeasurementsResponse
from app.integrations.aranet.poller import (
    _TYPE_MAP,
    poll_loop,
    run_one_poll,
)
from app.integrations.aranet.router import router as aranet_extra_router


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


@pytest.fixture
def app_client(fresh_keystore):
    drv = _registry.registered_drivers().get("aranet")
    assert isinstance(drv, AranetDriver)
    drv._cfg = AranetConfig()
    drv._task = None
    drv._last_poll_at = None
    drv._last_poll_ok = False
    drv._last_error = None

    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    app.include_router(aranet_extra_router, prefix="/api/integrations/aranet")
    with TestClient(app) as client:
        yield drv, client


def _aranet_payload(sensors: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sensors": sensors}


# ── Registration ──────────────────────────────────────────────────────


def test_driver_auto_registers_on_import():
    assert "aranet" in _registry.registered_drivers()


def test_secret_fields_marks_api_key():
    drv = _registry.registered_drivers()["aranet"]
    assert drv.secret_fields == {"api_key"}


def test_tier_is_free():
    drv = _registry.registered_drivers()["aranet"]
    assert drv.tier_required == "free"


# ── Config validation ─────────────────────────────────────────────────


def test_config_strips_trailing_slash_and_api_path():
    c = AranetConfig(base_url="http://10.0.0.42/api/v1/measurements/last/")
    assert c.base_url == "http://10.0.0.42"


def test_config_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http://"):
        AranetConfig(base_url="ftp://10.0.0.42")


def test_config_rejects_missing_host():
    with pytest.raises(ValueError, match="host"):
        AranetConfig(base_url="http://")


def test_config_accepts_mdns_host():
    c = AranetConfig(base_url="http://aranet-pro.local")
    assert c.base_url == "http://aranet-pro.local"


def test_config_floors_poll_seconds():
    with pytest.raises(ValueError):
        AranetConfig(poll_seconds=10)  # below the 30 s floor


# ── Response model ────────────────────────────────────────────────────


def test_response_handles_root_sensors_shape():
    raw = _aranet_payload([
        {"id": "abc", "measurements": [{"type": "temperature", "value": 23}]}
    ])
    parsed = AranetMeasurementsResponse.from_payload(raw)
    assert len(parsed.sensors) == 1
    assert parsed.sensors[0].id == "abc"


def test_response_handles_data_envelope_shape():
    raw = {"data": _aranet_payload([{"id": "xyz", "measurements": []}])}
    parsed = AranetMeasurementsResponse.from_payload(raw)
    assert parsed.sensors[0].id == "xyz"


def test_response_unknown_shape_returns_empty():
    parsed = AranetMeasurementsResponse.from_payload({"unexpected": True})
    assert parsed.sensors == []


# ── HTTP client ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_maps_401_to_clear_error(monkeypatch):
    async def fake_get(self, url, headers):
        return httpx.Response(401, text="bad key")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = AranetClient("http://10.0.0.42", "wrong")
    with pytest.raises(AranetError, match="X-API-Key"):
        await client.fetch_latest()


@pytest.mark.asyncio
async def test_client_maps_404_to_firmware_hint(monkeypatch):
    async def fake_get(self, url, headers):
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = AranetClient("http://10.0.0.42", "key")
    with pytest.raises(AranetError, match=r"firmware ≥ 2\.0"):
        await client.fetch_latest()


@pytest.mark.asyncio
async def test_client_maps_5xx_to_includes_status(monkeypatch):
    async def fake_get(self, url, headers):
        return httpx.Response(503, text="overloaded")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = AranetClient("http://10.0.0.42", "key")
    with pytest.raises(AranetError, match="HTTP 503"):
        await client.fetch_latest()


@pytest.mark.asyncio
async def test_client_returns_parsed_response(monkeypatch):
    async def fake_get(self, url, headers):
        assert headers["X-API-Key"] == "key"
        return httpx.Response(200, json=_aranet_payload([
            {
                "id": "s1",
                "name": "Tent A",
                "measurements": [
                    {"type": "temperature", "value": 23.4, "unit": "C"},
                    {"type": "humidity", "value": 88.0, "unit": "%"},
                ],
            }
        ]))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = AranetClient("http://10.0.0.42", "key")
    response = await client.fetch_latest()
    assert len(response.sensors) == 1
    assert len(response.sensors[0].measurements) == 2


# ── Poller ────────────────────────────────────────────────────────────


def _stub_response(*sensors_with_measurements):
    return AranetMeasurementsResponse(
        sensors=[
            {
                "id": s_id,
                "name": s_id,
                "measurements": [
                    {"type": m_type, "value": m_val} for m_type, m_val in measurements
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


@pytest.mark.asyncio
async def test_poller_publishes_mapped_measurement_types():
    response = _stub_response(
        ("s1", [("temperature", 23.5), ("humidity", 88.0), ("co2", 870)])
    )
    cfg = AranetConfig(base_url="http://x", api_key="k", sensor_mappings={"s1": "1"})
    written_rows = []

    async def _publish(node_id, sensor, value, ts):
        written_rows.append((node_id, sensor, value))

    written, _ = await run_one_poll(
        cfg, client=_StubClient(response), publisher=_publish
    )
    assert written == 3
    assert ("aranet:s1", "temp_c", 23.5) in written_rows
    assert ("aranet:s1", "humidity", 88.0) in written_rows
    assert ("aranet:s1", "co2_ppm", 870.0) in written_rows


@pytest.mark.asyncio
async def test_poller_skips_unmapped_types():
    response = _stub_response(
        ("s1", [
            ("temperature", 22.0),
            ("atmospheric_pressure", 1012),
            ("radiation_dose_rate", 0.13),
        ])
    )
    cfg = AranetConfig(base_url="http://x", api_key="k")
    written_rows = []

    async def _publish(node_id, sensor, value, ts):
        written_rows.append((node_id, sensor, value))

    written, _ = await run_one_poll(
        cfg, client=_StubClient(response), publisher=_publish
    )
    assert written == 1
    assert ("aranet:s1", "temp_c", 22.0) in written_rows


@pytest.mark.asyncio
async def test_poller_isolates_per_measurement_failure():
    """One sensor's bad measurement must not stop sibling sensors."""

    response = _stub_response(
        ("good", [("temperature", 21.0)]),
        ("boom", [("temperature", 99.0)]),
    )
    cfg = AranetConfig(base_url="http://x", api_key="k")
    written_rows = []

    async def _publish(node_id, sensor, value, ts):
        if node_id == "aranet:boom":
            raise RuntimeError("disk full")
        written_rows.append((node_id, sensor, value))

    written, _ = await run_one_poll(
        cfg, client=_StubClient(response), publisher=_publish
    )
    # Sibling 'good' still got persisted.
    assert ("aranet:good", "temp_c", 21.0) in written_rows
    assert written == 1


def test_type_map_covers_documented_aranet_types():
    """Lock the contract — adding/removing entries should require updating
    the README + dashboard. Tripwire so a silent contract change is loud."""
    assert _TYPE_MAP == {
        "temperature": "temp_c",
        "humidity": "humidity",
        "co2": "co2_ppm",
    }


@pytest.mark.asyncio
async def test_poll_loop_records_outcome_and_respects_cancel():
    cfg = AranetConfig(base_url="http://x", api_key="k", poll_seconds=30)
    outcomes = []

    sleep_calls = []

    async def _sleep(seconds):
        sleep_calls.append(seconds)
        # Cancel the task on the very first sleep so the test exits.
        raise asyncio.CancelledError()

    def _record(ok, err):
        outcomes.append((ok, err))

    async def _publish(*args, **kwargs):
        pass

    # Patch the run_one_poll the loop calls so we don't make real HTTP.
    import app.integrations.aranet.poller as poller_mod
    original = poller_mod.run_one_poll

    async def _fake_run(_cfg, **kwargs):
        return 1, _stub_response(("s1", []))

    poller_mod.run_one_poll = _fake_run
    try:
        with pytest.raises(asyncio.CancelledError):
            await poll_loop(
                lambda: cfg, record_outcome=_record, sleep=_sleep
            )
    finally:
        poller_mod.run_one_poll = original

    assert outcomes == [(True, None)]
    assert sleep_calls == [30]


# ── Driver lifecycle ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_is_idempotent(fresh_keystore):
    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://x", api_key="k"))
    await drv.start()
    first_task = drv._task
    await drv.start()
    assert drv._task is first_task
    await drv.stop()
    assert drv._task is None


@pytest.mark.asyncio
async def test_stop_is_idempotent(fresh_keystore):
    drv = AranetDriver()
    await drv.stop()  # never started — must not raise
    await drv.configure(AranetConfig(base_url="http://x", api_key="k"))
    await drv.start()
    await drv.stop()
    await drv.stop()  # already stopped — must not raise


@pytest.mark.asyncio
async def test_test_connection_requires_creds(fresh_keystore):
    drv = AranetDriver()
    health = await drv.test_connection()
    assert health.state == "error"
    assert "required" in (health.last_error or "")


@pytest.mark.asyncio
async def test_test_connection_returns_ok_with_sensor_count(
    fresh_keystore, monkeypatch
):
    response = _stub_response(("s1", [("temperature", 22.0)]))

    async def _fake_fetch(self):
        return response

    monkeypatch.setattr(AranetClient, "fetch_latest", _fake_fetch)

    async def _publish(*args, **kwargs):
        pass

    # Patch run_one_poll's default publisher path so it doesn't call the
    # real DB.
    import app.integrations.aranet.poller as poller_mod
    original_run = poller_mod.run_one_poll

    async def _wrapper(cfg, *, client=None, publisher=None):
        return await original_run(
            cfg, client=client, publisher=publisher or _publish
        )

    poller_mod.run_one_poll = _wrapper
    try:
        drv = AranetDriver()
        await drv.configure(AranetConfig(base_url="http://x", api_key="k"))
        health = await drv.test_connection()
    finally:
        poller_mod.run_one_poll = original_run

    assert health.state == "ok"
    assert health.details["sensors_seen"] == 1
    assert health.details["rows_written"] == 1


@pytest.mark.asyncio
async def test_test_connection_surfaces_aranet_error(
    fresh_keystore, monkeypatch
):
    async def _boom(self):
        raise AranetError("401 unauthorized")

    monkeypatch.setattr(AranetClient, "fetch_latest", _boom)

    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://x", api_key="bad"))
    health = await drv.test_connection()
    assert health.state == "error"
    assert "unauthorized" in (health.last_error or "")


@pytest.mark.asyncio
async def test_health_degraded_when_polls_go_stale(fresh_keystore):
    drv = AranetDriver()
    await drv.configure(AranetConfig(base_url="http://x", api_key="k", poll_seconds=30))
    await drv.start()
    drv._record_outcome(True, None)
    # Pretend the last successful poll was 200 s ago — > 3 × 30 = 90 s.
    drv._last_poll_at = time.time() - 200
    health = await drv.health()
    assert health.state == "degraded"
    await drv.stop()


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


# ── Bearer-token redaction (inherited from scaffolding) ────────────────


def test_api_key_redacts_to_last4_in_listing(app_client):
    drv, client = app_client
    client.put(
        "/api/integrations/aranet/config",
        json={
            "enabled": False,  # don't actually start the polling task
            "config": {
                "base_url": "http://10.0.0.42",
                "api_key": "abcdefghij",
            },
        },
    )
    listing = client.get("/api/integrations").json()
    aranet_row = next(r for r in listing if r["slug"] == "aranet")
    assert aranet_row["config"]["api_key"] == "••••ghij"
    assert aranet_row["config"]["base_url"] == "http://10.0.0.42"
