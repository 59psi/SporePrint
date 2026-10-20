"""The Grafana / Prometheus exporter driver.

* `/metrics` is a 404 until the exporter is enabled, then serves the
  Prometheus text format with the running server's version.
* The exposition carries the latest live reading per node and sensor (dew
  point in Celsius) with its chamber, each active grow, and the lifetime
  actuator counter, which survives the nightly prune; a node or vendor gone
  quiet is not exported as a live gauge.
* An optional bearer token gates the scrape; a missing, wrong or odd token
  is a 401, never a 500.
* Health: disabled until started, ok before the first scrape, and an error
  while the last scrape failed. (Contamination counts:
  test_integrations_grafana_contamination.py.)
"""

from __future__ import annotations

import importlib
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
from app.integrations.grafana.config import GrafanaConfig
from app.integrations.grafana.driver import GrafanaDriver
from app.integrations.grafana.router import router as grafana_metrics_router
from app.integrations.trane.driver import TraneConfig
from app.main import app as server_app
from app.mqtt import _handle_message
from app.retention.service import RAW_RETENTION_DAYS, _prune_actuator_events

grafana_router_mod = importlib.import_module("app.integrations.grafana.router")


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def app_client(monkeypatch):
    """The integrations router and the Grafana `/metrics` route, mounted as
    in production, with the registered exporter reset to disabled (and given
    its own state back after the test)."""
    drv = _registry.registered_drivers().get("grafana")
    assert isinstance(drv, GrafanaDriver), "grafana driver should auto-register"
    for attr, value in (("_enabled", False), ("_cfg", GrafanaConfig()), ("_last_scrape_at", None),
                        ("_last_scrape_ok", False), ("_last_error", None)):
        monkeypatch.setattr(drv, attr, value)

    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    app.include_router(grafana_metrics_router)
    with TestClient(app) as client:
        yield drv, client


@pytest.fixture
async def telemetry_seed():
    """A chamber, a node in it with a few fresh readings, an active grow and
    one recorded actuator switch."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO chambers (id, name, node_ids) VALUES (?, ?, ?)",
            (1, "Tent A", json.dumps(["climate-01"])),
        )
        for sensor, value in [
            ("temp_c", 23.5),
            ("humidity", 91.2),
            ("co2_ppm", 870.0),
            ("dew_point_f", 71.6),  # → 22.0°C
            ("lux", 12.0),
        ]:
            await db.execute(
                "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) "
                "VALUES (?, ?, ?, ?)",
                (time.time(), "climate-01", sensor, value),
            )
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
        await db.commit()


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


# ── /metrics ──────────────────────────────────────────────────────────


def test_metrics_is_a_404_until_enabled_then_prometheus_text_with_the_version(app_client):
    drv, client = app_client
    assert client.get("/metrics").status_code == 404

    _enable(client)
    assert drv.enabled is True
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain; version=0.0.4")
    version = server_version()
    assert version != "unknown"
    assert version == server_app.version  # bump.sh moves both
    assert f'sporeprint_build_info{{version="{version}"}} 1.0' in resp.text


def test_metrics_exports_the_live_readings_grows_and_actuator_counts(app_client, telemetry_seed):
    drv, client = app_client
    _enable(client)
    body = client.get("/metrics").text
    node = {"node_id": "climate-01", "chamber_id": "1"}
    assert _sample(body, "sporeprint_node_temperature_celsius", **node) == 23.5
    assert _sample(body, "sporeprint_node_humidity_percent", **node) == 91.2
    assert _sample(body, "sporeprint_node_co2_ppm", **node) == 870.0
    assert _sample(body, "sporeprint_node_lux", **node) == 12.0
    # Stored in °F (the firmware's unit), exported in °C: 71.6 °F is 22.0 °C.
    assert _sample(body, "sporeprint_node_dewpoint_celsius", **node) == pytest.approx(22.0)
    assert _sample(body, "sporeprint_chamber_session_active",
                   chamber_id="1", species_profile_id="lions-mane") == 1.0
    assert _sample(body, "sporeprint_actuator_event_count_total",
                   node_id="climate-01", channel="humidifier", action="on") == 1.0


def test_actuator_metric_can_be_disabled_via_config(app_client, telemetry_seed):
    drv, client = app_client
    _enable(client, include_actuator_state=False)
    body = client.get("/metrics").text
    assert "sporeprint_actuator_event_count" not in body


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


# ── Bearer-token gate ─────────────────────────────────────────────────


def test_bearer_token_required_when_set(app_client):
    drv, client = app_client
    _enable(client, bearer_token="secret-prom-token")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(
        "/metrics", headers={"Authorization": "Bearer secret-prom-token"}
    ).status_code == 200


def test_bearer_token_that_cannot_be_text_is_refused_by_the_config():
    with pytest.raises(ValidationError):
        GrafanaConfig(bearer_token="\ud800abc")


@pytest.mark.parametrize("configured", ["tök€n", "\ud800abc"],
                         ids=["non-ascii", "unpaired-surrogate"])
def test_scrape_against_an_odd_configured_token_is_a_401_not_a_500(app_client, configured):
    drv, client = app_client
    _enable(client)
    # A token that reached the driver without the config's validation (a
    # surrogate) or that compare_digest cannot take as str (non-ASCII).
    drv._cfg = GrafanaConfig.model_construct(
        bearer_token=configured,
        include_actuator_state=True,
        include_contamination_metrics=True,
        include_sensor_history=False,
    )
    assert client.get("/metrics").status_code == 401
    resp = client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_token_comparison_handles_unpaired_surrogates_on_either_side():
    assert token_matches("\ud800x", "\ud800x") is True
    assert token_matches("abc", "\ud800x") is False
    assert token_matches(None, "abc") is False
    assert token_matches("", "") is False


# ── Driver lifecycle and health ───────────────────────────────────────


async def test_test_connection_returns_ok_against_live_db():
    drv = GrafanaDriver()
    await drv.configure(GrafanaConfig())
    health = await drv.test_connection()
    assert health.state == "ok"
    assert health.details.get("sample_bytes", 0) > 0


async def test_health_disabled_until_started():
    drv = GrafanaDriver()
    await drv.configure(GrafanaConfig())
    assert (await drv.health()).state == "disabled"
    await drv.start()
    # Started but never scraped — `ok` (Prometheus may not be deployed yet).
    assert (await drv.health()).state == "ok"


def test_a_failed_scrape_is_a_500_and_an_error_health_until_one_succeeds(app_client, monkeypatch):
    drv, client = app_client
    _enable(client)

    async def broken(cfg, *, version):
        raise RuntimeError("database is locked")

    with monkeypatch.context() as m:
        m.setattr(grafana_router_mod, "collect_samples", broken)
        resp = client.get("/metrics")
    assert resp.status_code == 500
    assert "database is locked" in resp.text
    health = client.get("/api/integrations").json()
    grafana = next(r for r in health if r["slug"] == "grafana")["health"]
    assert (grafana["state"], grafana["last_error"]) == ("error", "database is locked")

    assert client.get("/metrics").status_code == 200
    health = client.get("/api/integrations").json()
    assert next(r for r in health if r["slug"] == "grafana")["health"]["state"] == "ok"
