"""System health: the /api/health/detail/* reports and what feeds them.

The background-task statuses themselves are test_task_status.py; MQTT
command signing in the mqtt report is test_mqtt_signing_enforcement.py.
"""

import asyncio
import subprocess
from contextlib import asynccontextmanager

import pytest

import app.health.router as health_router
import app.health.service as health_service
from app.db import get_db
from app.health.service import (
    get_system_metrics,
    get_task_statuses,
    register_task,
    track_client_connect,
    track_client_disconnect,
    update_task,
)


@pytest.fixture
def registries():
    """The client and task registries are module state: start and end empty."""
    health_service._sio_clients.clear()
    health_service._task_registry.clear()
    yield
    health_service._sio_clients.clear()
    health_service._task_registry.clear()


def test_a_task_reports_its_last_status_and_run(registries):
    register_task("test_task", "running")
    update_task("test_task", "error", error="disk full")
    statuses = get_task_statuses()
    assert statuses["test_task"]["status"] == "error"
    assert statuses["test_task"]["error"] == "disk full"
    assert statuses["test_task"]["last_run"] is not None
    # Only registered tasks are reported; an update alone registers nothing.
    update_task("never_registered", "idle")
    assert "never_registered" not in get_task_statuses()


async def test_each_health_detail_route_serves_its_report(client, registries):
    track_client_connect("abc123", {"REMOTE_ADDR": "192.168.1.10"})
    [listed] = client.get("/api/health/detail/clients").json()
    assert (listed["sid"], listed["ip"]) == ("abc123", "192.168.1.10")
    track_client_disconnect("abc123")
    assert client.get("/api/health/detail/clients").json() == []

    assert "command_signing" in client.get("/api/health/detail/mqtt").json()
    # The cloud connector reports itself even when nothing registered it.
    assert "cloud_connector" in client.get("/api/health/detail/tasks").json()


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_system_metrics_sample_cpu_off_the_event_loop(client, monkeypatch):
    calls: list[bool] = []

    def fake_cpu_percent(*args, **kwargs):
        calls.append(_on_event_loop())
        return 12.5

    monkeypatch.setattr(health_service.psutil, "cpu_percent", fake_cpu_percent)
    r = client.get("/api/health/detail/system")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cpu_percent"] == 12.5
    assert {"memory_percent", "disk_percent", "db_size_mb"} <= set(data)
    assert calls == [False], "the 100 ms cpu sample must not block the loop"


def test_clock_runs_chronyc_off_the_event_loop(client, monkeypatch):
    """A blocking subprocess.run (timeout 1.5 s) inside the async
    handler froze MQTT ingest / automation / Socket.IO on every poll."""
    calls: list[bool] = []

    def fake_run(cmd, **kwargs):
        calls.append(_on_event_loop())
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Reference ID    : 0A000001 (10.0.0.1)\nStratum         : 3\n", stderr="",
        )

    monkeypatch.setattr(health_service.subprocess, "run", fake_run)
    r = client.get("/api/health/detail/clock")
    assert r.status_code == 200, r.text
    assert calls == [False], "chronyc must run in a worker thread, not on the loop"
    assert r.json()["chrony"]["available"] is True
    assert r.json()["chrony"]["stratum"] == "3"


def test_the_clock_route_is_a_thin_wrapper():
    """chronyc runs and is parsed in the service (thin-router rule)."""
    assert not hasattr(health_router, "subprocess")
    parsed = health_service._parse_chrony_tracking(
        "Reference ID    : 0A000001 (10.0.0.1)\nLeap status     : Normal\n")
    assert parsed["leap_status"] == "Normal" and parsed["available"] is True


@pytest.mark.parametrize("error,reason", [
    (FileNotFoundError("chronyc"), "chrony not installed"),
    (subprocess.TimeoutExpired("chronyc", 1.5), "chronyc timeout"),
    (PermissionError("socket"), "PermissionError"),
])
async def test_clock_status_without_chrony(monkeypatch, error, reason):
    def fake_run(cmd, **kwargs):
        raise error

    monkeypatch.setattr(health_service.subprocess, "run", fake_run)
    status = await health_service.get_clock_status()
    assert status["chrony"] == {"available": False, "reason": reason}
    assert status["pi_ts"] > 0 and status["pi_iso"].endswith("Z")


# ── table_counts: recounted at most every _TABLE_COUNTS_TTL_SECONDS ──────

@pytest.fixture()
def counting_db(monkeypatch):
    """Count the connections get_system_metrics opens for its row counts."""
    opened = []
    health_service._table_counts_cache.update(at=None, counts={})

    @asynccontextmanager
    async def _counting():
        opened.append(True)
        async with get_db() as db:
            yield db

    monkeypatch.setattr(health_service, "get_db", _counting)
    monkeypatch.setattr(health_service.psutil, "cpu_percent", lambda *a, **k: 1.0)
    yield opened
    health_service._table_counts_cache.update(at=None, counts={})


async def _add_session():
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (name, species_profile_id) VALUES ('s', 'blue_oyster')")
        await db.commit()


async def test_table_counts_are_not_recounted_on_every_poll(counting_db, monkeypatch):
    """Six COUNT(*) scans ran on every 15 s Fleet poll and every 60 s cloud
    heartbeat, for a field no client reads."""
    await _add_session()
    first = await get_system_metrics()
    await _add_session()
    second = await get_system_metrics()
    assert len(counting_db) == 1
    assert first["table_counts"] == second["table_counts"]
    assert first["table_counts"]["sessions"] == 1
    assert set(first["table_counts"]) == set(health_service._COUNTED_TABLES)

    # Past the TTL they are counted again.
    stale = health_service._table_counts_cache["at"] - health_service._TABLE_COUNTS_TTL_SECONDS - 1
    health_service._table_counts_cache["at"] = stale
    third = await get_system_metrics()
    assert len(counting_db) == 2
    assert third["table_counts"]["sessions"] == 2
