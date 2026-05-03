"""Tests for the v4.1 Grafana / Prometheus exporter driver.

Covers:
  - Driver auto-registers on import
  - `/metrics` returns 404 when disabled (default state)
  - Enabling via PUT /api/integrations/grafana/config flips on the route
  - Sample exposition includes node + chamber + session metrics
  - Bearer-token gate works when configured
  - Unit conversion (dew_point F → C in metric name)
  - Counters reflect database row counts
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations import _registry
from app.integrations.grafana import GrafanaDriver
from app.integrations.grafana.driver import GrafanaDriver as GrafanaDriverCls
from app.integrations.grafana.config import GrafanaConfig
from app.integrations.grafana.router import router as grafana_metrics_router
from app.integrations._keystore import reset_fernet_cache


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
    """Build a FastAPI app with both the integrations router and the
    Grafana `/metrics` route mounted, mimicking production wiring.
    """
    # Reset the driver to a known-disabled state. The grafana driver
    # auto-registers at import time, so we look it up rather than
    # constructing fresh.
    drv = _registry.registered_drivers().get("grafana")
    assert isinstance(drv, GrafanaDriverCls), "grafana driver should auto-register"
    drv._enabled = False
    drv._cfg = GrafanaConfig()
    drv._last_scrape_at = None
    drv._last_scrape_ok = False
    drv._last_error = None

    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    app.include_router(grafana_metrics_router)
    with TestClient(app) as client:
        yield drv, client


@pytest.fixture
async def telemetry_seed():
    """Seed a chamber, a node mapping, and a few telemetry rows."""
    from app.db import get_db
    async with get_db() as db:
        await db.execute(
            "INSERT INTO chambers (id, name, node_ids) VALUES (?, ?, ?)",
            (1, "Tent A", json.dumps(["climate-01"])),
        )
        for sensor, value in [
            ("temp_c", 23.5),
            ("humidity", 91.2),
            ("co2_ppm", 870.0),
            ("dew_point_f", 71.6),  # → ~22.0°C
            ("lux", 12.0),
        ]:
            await db.execute(
                "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) "
                "VALUES (?, ?, ?, ?)",
                (time.time(), "climate-01", sensor, value),
            )
        # Active session in the chamber
        await db.execute(
            "INSERT INTO sessions (id, name, species_profile_id, chamber_id, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (10, "test grow", "lions-mane", 1, "active"),
        )
        # An actuator event
        await db.execute(
            "INSERT INTO actuator_events (timestamp, node_id, channel, action, trigger) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), "climate-01", "humidifier", "on", "rule"),
        )
        # A contaminated session in same chamber
        await db.execute(
            "INSERT INTO sessions (id, name, species_profile_id, chamber_id, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (11, "old grow", "lions-mane", 1, "contaminated"),
        )
        await db.commit()


# ── Registration ──────────────────────────────────────────────────────


def test_driver_auto_registers_on_import():
    """The package's __init__ side-effect must register the driver."""
    assert "grafana" in _registry.registered_drivers()


def test_secret_fields_marks_bearer_token():
    drv = _registry.registered_drivers()["grafana"]
    assert "bearer_token" in drv.secret_fields


def test_tier_is_free():
    drv = _registry.registered_drivers()["grafana"]
    assert drv.tier_required == "free"


# ── /metrics route ────────────────────────────────────────────────────


def test_metrics_returns_404_when_disabled(app_client):
    _, client = app_client
    resp = client.get("/metrics")
    assert resp.status_code == 404


def test_put_config_enables_metrics_route(app_client):
    drv, client = app_client
    resp = client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    assert resp.status_code == 200
    assert drv.enabled is True

    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "sporeprint_build_info" in body
    assert resp.headers["content-type"].startswith(
        "text/plain; version=0.0.4"
    )


def test_metrics_emits_sensor_samples(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    body = client.get("/metrics").text
    assert "sporeprint_node_temperature_celsius" in body
    assert 'node_id="climate-01"' in body
    assert 'chamber_id="1"' in body
    assert "23.5" in body  # temp_c value
    assert "91.2" in body  # humidity
    assert "870" in body   # co2


def test_metrics_converts_dew_point_to_celsius(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    body = client.get("/metrics").text
    # 71.6 F → 22.0 C exactly
    assert "sporeprint_node_dewpoint_celsius" in body
    # Find the dewpoint sample line — value should be ~22.0
    for line in body.split("\n"):
        if line.startswith("sporeprint_node_dewpoint_celsius{") and 'node_id="climate-01"' in line:
            value = float(line.rsplit(" ", 1)[1])
            assert 21.99 < value < 22.01
            break
    else:
        raise AssertionError("dewpoint sample not found")


def test_metrics_emits_session_active(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    body = client.get("/metrics").text
    assert "sporeprint_chamber_session_active" in body
    assert 'species_profile_id="lions-mane"' in body
    assert 'chamber_id="1"' in body


def test_metrics_emits_contamination_counter(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    body = client.get("/metrics").text
    assert "sporeprint_contamination_events_total" in body
    # One contaminated session exists in chamber 1.
    assert 'chamber_id="1"' in body


def test_metrics_emits_actuator_counter(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    body = client.get("/metrics").text
    assert "sporeprint_actuator_event_count" in body
    assert 'channel="humidifier"' in body


def test_actuator_metric_can_be_disabled_via_config(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {"include_actuator_state": False}},
    )
    body = client.get("/metrics").text
    assert "sporeprint_actuator_event_count" not in body


def test_metrics_records_scrape(app_client, telemetry_seed):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={"enabled": True, "config": {}},
    )
    assert drv._last_scrape_at is None
    client.get("/metrics")
    assert drv._last_scrape_at is not None
    assert drv._last_scrape_ok is True


# ── Bearer-token gate ─────────────────────────────────────────────────


def test_bearer_token_required_when_set(app_client):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={
            "enabled": True,
            "config": {"bearer_token": "secret-prom-token"},
        },
    )
    # No header → 401
    assert client.get("/metrics").status_code == 401
    # Wrong header → 401
    assert (
        client.get(
            "/metrics", headers={"Authorization": "Bearer nope"}
        ).status_code
        == 401
    )
    # Correct header → 200
    assert (
        client.get(
            "/metrics", headers={"Authorization": "Bearer secret-prom-token"}
        ).status_code
        == 200
    )


def test_bearer_token_is_secret_field_in_listing(app_client):
    drv, client = app_client
    client.put(
        "/api/integrations/grafana/config",
        json={
            "enabled": True,
            "config": {"bearer_token": "abcdefghij"},
        },
    )
    listing = client.get("/api/integrations").json()
    grafana_row = next(r for r in listing if r["slug"] == "grafana")
    # The token must be redacted, never exposed in plaintext.
    assert grafana_row["config"]["bearer_token"] == "••••ghij"


# ── Driver lifecycle ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_connection_returns_ok_against_live_db(fresh_keystore):
    drv = GrafanaDriverCls()
    await drv.configure(GrafanaConfig())
    health = await drv.test_connection()
    assert health.state == "ok"
    assert health.details.get("sample_bytes", 0) > 0


@pytest.mark.asyncio
async def test_health_disabled_until_started(fresh_keystore):
    drv = GrafanaDriverCls()
    await drv.configure(GrafanaConfig())
    h = await drv.health()
    assert h.state == "disabled"
    await drv.start()
    h = await drv.health()
    # Started but never scraped — `ok` (Prometheus may not be deployed yet).
    assert h.state == "ok"


@pytest.mark.asyncio
async def test_health_reports_error_after_failed_scrape(fresh_keystore):
    drv = GrafanaDriverCls()
    await drv.configure(GrafanaConfig())
    await drv.start()
    drv.record_scrape(False, "boom")
    h = await drv.health()
    assert h.state == "error"
    assert h.last_error == "boom"
