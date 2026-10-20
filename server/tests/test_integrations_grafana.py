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
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import token_matches
from app.cloud.version import server_version
from app.db import get_db
from app.integrations import _registry
from app.integrations.grafana import GrafanaDriver
from app.integrations.grafana.driver import GrafanaDriver as GrafanaDriverCls
from app.integrations.grafana.config import GrafanaConfig
from app.integrations.grafana.router import router as grafana_metrics_router
from app.integrations._keystore import reset_fernet_cache
from app.integrations._settings_store import secret_preview
from app.integrations.trane.driver import TraneConfig
from app.main import app as server_app
from app.mqtt import _handle_message
from app.retention.service import RAW_RETENTION_DAYS, _prune_actuator_events


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
        # An actuator event, with the lifetime total the MQTT ingest keeps
        # beside it (the exporter's counter reads the total).
        await db.execute(
            "INSERT INTO actuator_events (timestamp, node_id, channel, action, trigger) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), "climate-01", "humidifier", "on", "rule"),
        )
        await db.execute(
            "INSERT INTO actuator_event_counts (node_id, channel, action, n) "
            "VALUES (?, ?, ?, ?)",
            ("climate-01", "humidifier", "on", 1),
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
    # The token must be redacted, never exposed in plaintext — not even its
    # last characters.
    preview = grafana_row["config"]["bearer_token"]
    assert preview == secret_preview("abcdefghij")
    assert "ghij" not in preview


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


# ── Freshness, chamber map, counters, token and version ──────────────


async def _reading(node_id: str, sensor: str, value: float, *, age_s: float) -> float:
    taken = time.time() - age_s
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) "
            "VALUES (?, ?, ?, ?)",
            (taken, node_id, sensor, value),
        )
        await db.commit()
    return taken


def _sample(body: str, metric: str, **labels: str) -> float | None:
    """One sample's value from a Prometheus exposition, or None."""
    for line in body.splitlines():
        if line.startswith(metric + "{") and all(
            f'{k}="{v}"' in line for k, v in labels.items()
        ):
            return float(line.rsplit(" ", 1)[1])
    return None


def _enable(client, **config) -> None:
    resp = client.put(
        "/api/integrations/grafana/config", json={"enabled": True, "config": config}
    )
    assert resp.status_code == 200, resp.text


async def test_node_gone_quiet_is_not_exported_as_a_live_gauge(app_client):
    drv, client = app_client
    await _reading("climate-01", "temp_c", 23.5, age_s=60)
    await _reading("climate-02", "temp_c", 19.0, age_s=2 * 3600)
    _enable(client)
    body = client.get("/metrics").text
    temp = "sporeprint_node_temperature_celsius"
    assert _sample(body, temp, node_id="climate-01") == 23.5
    assert _sample(body, temp, node_id="climate-02") is None


async def test_vendor_sample_taken_minutes_ago_is_still_current(app_client):
    # An Aranet4 radios a sample every 1-10 minutes and the Pi stores it at
    # the time the sensor took it, so its latest reading is often minutes old.
    drv, client = app_client
    await _reading("aranet:s1", "co2_ppm", 900.0, age_s=20 * 60)
    await _reading("climate-04", "co2_ppm", 950.0, age_s=20 * 60)
    _enable(client)
    body = client.get("/metrics").text
    assert _sample(body, "sporeprint_node_co2_ppm", node_id="aranet:s1") == 900.0
    assert _sample(body, "sporeprint_node_co2_ppm", node_id="climate-04") is None


async def test_slow_vendor_reading_stays_current_for_three_polls(app_client, monkeypatch):
    drv, client = app_client
    trane = _registry.registered_drivers()["trane"]
    monkeypatch.setattr(trane, "_cfg", TraneConfig(poll_seconds=3600))
    await _reading("trane:t1", "temp_c", 21.0, age_s=2 * 3600)  # within 3 hourly polls
    await _reading("trane:t2", "temp_c", 22.0, age_s=4 * 3600)  # past them
    _enable(client)
    body = client.get("/metrics").text
    temp = "sporeprint_node_temperature_celsius"
    assert _sample(body, temp, node_id="trane:t1") == 21.0
    assert _sample(body, temp, node_id="trane:t2") is None


async def test_sensor_history_flag_adds_each_readings_timestamp(app_client):
    drv, client = app_client
    taken = await _reading("climate-01", "humidity", 88.0, age_s=120)
    _enable(client)
    assert "sporeprint_node_reading_timestamp_seconds" not in client.get("/metrics").text
    _enable(client, include_sensor_history=True)
    body = client.get("/metrics").text
    stamp = _sample(
        body, "sporeprint_node_reading_timestamp_seconds",
        node_id="climate-01", sensor="humidity",
    )
    assert stamp == pytest.approx(taken, abs=1.0)


async def test_chamber_with_non_list_node_ids_does_not_break_the_scrape(app_client):
    drv, client = app_client
    async with get_db() as db:
        await db.execute(
            "INSERT INTO chambers (id, name, node_ids) VALUES (?, ?, ?)", (2, "Odd", "5")
        )
        await db.execute(
            "INSERT INTO chambers (id, name, node_ids) VALUES (?, ?, ?)",
            (3, "Tent B", json.dumps(["climate-03"])),
        )
        await db.commit()
    await _reading("climate-03", "temp_c", 20.0, age_s=30)
    _enable(client)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert _sample(
        resp.text, "sporeprint_node_temperature_celsius",
        node_id="climate-03", chamber_id="3",
    ) == 20.0


async def test_actuator_counter_counts_reports_and_survives_retention(app_client):
    """Every switch report the ingest stores is counted, and the nightly
    prune of old rows never lowers the counter (a reset to Prometheus)."""
    drv, client = app_client
    for state in ("on", "on", "off"):
        await _handle_message(
            AsyncMock(),
            "sporeprint/relay-01/telemetry/fan",
            {"channel": "fan", "state": state, "pwm": 255, "trigger": "report"},
        )
    _enable(client)
    counter = "sporeprint_actuator_event_count_total"
    body = client.get("/metrics").text
    assert _sample(body, counter, node_id="relay-01", channel="fan", action="on") == 2.0
    assert _sample(body, counter, node_id="relay-01", channel="fan", action="off") == 1.0

    async with get_db() as db:
        await db.execute(
            "UPDATE actuator_events SET timestamp = timestamp - ?",
            ((RAW_RETENTION_DAYS + 1) * 86400,),
        )
        await db.commit()
    await _prune_actuator_events()
    async with get_db() as db:
        left = (await (await db.execute("SELECT COUNT(*) FROM actuator_events")).fetchone())[0]
    assert left == 0
    body = client.get("/metrics").text
    assert _sample(body, counter, node_id="relay-01", channel="fan", action="on") == 2.0
    assert _sample(body, counter, node_id="relay-01", channel="fan", action="off") == 1.0


async def test_actuator_prune_keeps_recent_reports(app_client):
    await _handle_message(
        AsyncMock(),
        "sporeprint/relay-01/telemetry/aux",
        {"channel": "aux", "state": "off", "pwm": 0, "trigger": "report"},
    )
    await _prune_actuator_events()
    async with get_db() as db:
        left = (await (await db.execute("SELECT COUNT(*) FROM actuator_events")).fetchone())[0]
    assert left == 1


def test_bearer_token_that_cannot_be_text_is_refused_by_the_config():
    with pytest.raises(ValidationError):
        GrafanaConfig(bearer_token="\ud800abc")


def test_scrape_against_an_odd_configured_token_is_a_401_not_a_500(app_client):
    drv, client = app_client
    _enable(client)
    # A token that reached the driver without the config's validation.
    drv._cfg = GrafanaConfig.model_construct(
        bearer_token="\ud800abc",
        include_actuator_state=True,
        include_contamination_metrics=True,
        include_sensor_history=False,
    )
    assert client.get("/metrics").status_code == 401
    resp = client.get("/metrics", headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 401


def test_token_comparison_handles_unpaired_surrogates_on_either_side():
    assert token_matches("\ud800x", "\ud800x") is True
    assert token_matches("abc", "\ud800x") is False
    assert token_matches(None, "abc") is False
    assert token_matches("", "") is False


def test_build_info_reports_the_running_server_version(app_client):
    drv, client = app_client
    _enable(client)
    version = server_version()
    assert version != "unknown"
    assert version == server_app.version  # bump.sh moves both
    body = client.get("/metrics").text
    assert f'sporeprint_build_info{{version="{version}"}} 1.0' in body
