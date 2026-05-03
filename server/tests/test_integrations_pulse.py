"""Tests for the v4.1 Pulse Grow cloud-API driver.

Covers:
  - Driver auto-registers; tier="premium"; secret_fields={"password"}
  - Config validation (email shape, poll interval bounds, password trim)
  - Models tolerate `{token: …}` and `{data: {token: …}}` envelopes;
    handle list / `{devices:[…]}` / `{data:[…]}` shapes for devices
  - Client login / list_devices / recent_data round-trip
  - Client transparently re-logs in on 401 once and only once
  - Client maps 429 → "rate-limited" hint, ≥400 → status + body
  - Poller maps temperature / humidity / vpd / dew_point / light to the
    SporePrint sensor name space; skips unmapped types; isolates
    per-device failures; persists via injected publisher
  - Driver lifecycle: idempotent start/stop; test_connection requires
    creds; surfaces PulseError; health transitions disabled→ok→degraded
  - /devices route shape (200 / 400 / 502)
  - password redacts to ••••last4 in /api/integrations listing
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
from app.integrations.pulse.client import (
    PULSE_API_BASE,
    PulseCloudClient,
    PulseError,
)
from app.integrations.pulse.config import PulseConfig
from app.integrations.pulse.driver import PulseDriver
from app.integrations.pulse.models import (
    PulseDeviceListResponse,
    PulseLoginResponse,
    PulseRecentDataResponse,
)
from app.integrations.pulse.poller import _TYPE_MAP, run_one_poll
from app.integrations.pulse.router import router as pulse_extra_router


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
    drv = _registry.registered_drivers().get("pulse")
    assert isinstance(drv, PulseDriver)
    drv._cfg = PulseConfig()
    drv._task = None
    drv._last_poll_at = None
    drv._last_poll_ok = False
    drv._last_error = None

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


# ── Registration ──────────────────────────────────────────────────────


def test_driver_auto_registers_on_import():
    assert "pulse" in _registry.registered_drivers()


def test_tier_is_premium():
    drv = _registry.registered_drivers()["pulse"]
    assert drv.tier_required == "premium"


def test_password_in_secret_fields():
    drv = _registry.registered_drivers()["pulse"]
    assert drv.secret_fields == {"password"}


# ── Config ────────────────────────────────────────────────────────────


def test_config_rejects_obviously_malformed_email():
    with pytest.raises(ValueError, match="@"):
        PulseConfig(email="brandon-at-example.com", password="x")


def test_config_strips_password_whitespace():
    c = PulseConfig(email="b@example.com", password="  secret\n  ")
    assert c.password == "secret"


def test_config_floors_poll_seconds():
    with pytest.raises(ValueError):
        PulseConfig(poll_seconds=10)


def test_config_empty_email_is_allowed():
    """Empty fields are how the operator stages a partially-configured
    driver — they shouldn't trip validation just for being unset.
    """
    c = PulseConfig()
    assert c.email == ""
    assert c.password == ""


# ── Models ────────────────────────────────────────────────────────────


def test_login_response_handles_root_token_shape():
    parsed = PulseLoginResponse.from_payload({"token": "tok"})
    assert parsed.token == "tok"


def test_login_response_handles_data_envelope():
    parsed = PulseLoginResponse.from_payload({"data": {"token": "tok"}})
    assert parsed.token == "tok"


def test_login_response_unknown_shape_returns_none():
    parsed = PulseLoginResponse.from_payload({"weird": True})
    assert parsed.token is None


def test_device_list_handles_array_shape():
    parsed = PulseDeviceListResponse.from_payload(
        [{"id": "a"}, {"id": "b"}]
    )
    assert [d.id for d in parsed.devices] == ["a", "b"]


def test_device_list_handles_data_envelope():
    parsed = PulseDeviceListResponse.from_payload(
        {"data": [{"id": "x"}, {"id": "y"}]}
    )
    assert [d.id for d in parsed.devices] == ["x", "y"]


def test_recent_data_attaches_device_id():
    parsed = PulseRecentDataResponse.from_payload(
        {"measurements": [{"type": "temperature", "value": 22.0}]},
        device_id="abc",
    )
    assert parsed.device_id == "abc"
    assert len(parsed.measurements) == 1


def test_recent_data_unknown_shape_returns_empty():
    parsed = PulseRecentDataResponse.from_payload(
        {"weird": True}, device_id="abc"
    )
    assert parsed.device_id == "abc"
    assert parsed.measurements == []


# ── Client ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_client_login_with_no_token_in_response_raises(monkeypatch):
    async def fake_request(self, method, url, headers, json=None):
        return httpx.Response(200, json={"unexpected": True})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    with pytest.raises(PulseError, match="no token in response"):
        await client.login()


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_client_maps_429_to_rate_limited(monkeypatch):
    async def fake_request(self, method, url, headers, json=None):
        if "/v2/auth/login" in url:
            return httpx.Response(200, json=_login_payload("t"))
        return httpx.Response(429, text="slow down")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = PulseCloudClient("b@example.com", "pw")
    with pytest.raises(PulseError, match="rate-limited"):
        await client.list_devices()


@pytest.mark.asyncio
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


def test_type_map_covers_documented_pulse_types():
    """Tripwire — keep _TYPE_MAP in sync with the README + Grafana
    exporter's metric family list."""
    assert _TYPE_MAP == {
        "temperature": "temp_c",
        "humidity": "humidity",
        "vpd": "vpd_kpa",
        "dew_point": "dew_point_c",
        "light": "lux",
    }


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


def _measurement(type_, value):
    return {"type": type_, "value": value}


@pytest.mark.asyncio
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
    written_rows = []

    async def _publish(node_id, sensor, value, ts):
        written_rows.append((node_id, sensor, value))

    written, _ = await run_one_poll(cfg, client=client, publisher=_publish)
    assert written == 5
    rows_by_sensor = {sensor: value for _, sensor, value in written_rows}
    assert rows_by_sensor["temp_c"] == 22.5
    assert rows_by_sensor["humidity"] == 86.0
    assert rows_by_sensor["vpd_kpa"] == 0.45
    assert rows_by_sensor["dew_point_c"] == 19.8
    assert rows_by_sensor["lux"] == 12000


@pytest.mark.asyncio
async def test_poller_isolates_per_device_failures():
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
    written_rows = []

    async def _publish(node_id, sensor, value, ts):
        written_rows.append(node_id)

    written, responses = await run_one_poll(
        cfg, client=client, publisher=_publish
    )
    assert written == 2  # ok + ok2
    assert "pulse:broken" not in written_rows


@pytest.mark.asyncio
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
    written_rows = []

    async def _publish(node_id, sensor, value, ts):
        written_rows.append(sensor)

    written, _ = await run_one_poll(cfg, client=client, publisher=_publish)
    assert written == 1
    assert written_rows == ["temp_c"]


# ── Driver lifecycle ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_is_idempotent(fresh_keystore):
    drv = PulseDriver()
    await drv.configure(PulseConfig(email="b@example.com", password="pw"))
    await drv.start()
    first_task = drv._task
    await drv.start()
    assert drv._task is first_task
    await drv.stop()


@pytest.mark.asyncio
async def test_stop_is_safe_when_never_started(fresh_keystore):
    drv = PulseDriver()
    await drv.stop()  # must not raise


@pytest.mark.asyncio
async def test_test_connection_requires_creds(fresh_keystore):
    drv = PulseDriver()
    health = await drv.test_connection()
    assert health.state == "error"
    assert "required" in (health.last_error or "")


@pytest.mark.asyncio
async def test_test_connection_returns_ok_with_device_count(
    fresh_keystore, monkeypatch
):
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


@pytest.mark.asyncio
async def test_test_connection_surfaces_pulse_error(
    fresh_keystore, monkeypatch
):
    async def fake_request(self, method, url, headers, json=None):
        return httpx.Response(401, text="bad")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    drv = PulseDriver()
    await drv.configure(PulseConfig(email="b@example.com", password="bad"))
    health = await drv.test_connection()
    assert health.state == "error"
    assert "unauthorized" in (health.last_error or "")


@pytest.mark.asyncio
async def test_health_degraded_when_polls_go_stale(fresh_keystore):
    drv = PulseDriver()
    await drv.configure(
        PulseConfig(email="b@example.com", password="pw", poll_seconds=60)
    )
    await drv.start()
    drv._record_outcome(True, None)
    drv._last_poll_at = time.time() - 500  # > 3 × 60
    health = await drv.health()
    assert health.state == "degraded"
    await drv.stop()


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


# ── Secret-field redaction ────────────────────────────────────────────


def test_password_redacts_to_last4_in_listing(app_client):
    drv, client = app_client
    client.put(
        "/api/integrations/pulse/config",
        json={
            "enabled": False,
            "config": {
                "email": "b@example.com",
                "password": "supersecret-1234",
            },
        },
    )
    listing = client.get("/api/integrations").json()
    pulse_row = next(r for r in listing if r["slug"] == "pulse")
    assert pulse_row["config"]["password"] == "••••1234"
    assert pulse_row["config"]["email"] == "b@example.com"
