"""Tests for system health endpoints."""

import asyncio
import subprocess

import app.health.router as health_router
import app.health.service as health_service
from app.health.service import (
    track_client_connect,
    track_client_disconnect,
    get_client_list,
    register_task,
    update_task,
    get_task_statuses,
    _sio_clients,
    _task_registry,
)


def _reset():
    _sio_clients.clear()
    _task_registry.clear()


def test_client_tracking():
    _reset()
    track_client_connect("abc123", {"REMOTE_ADDR": "192.168.1.10"})
    clients = get_client_list()
    assert len(clients) == 1
    assert clients[0]["sid"] == "abc123"
    assert clients[0]["ip"] == "192.168.1.10"

    track_client_disconnect("abc123")
    assert len(get_client_list()) == 0


def test_task_registry():
    _reset()
    register_task("test_task", "running")
    update_task("test_task", "completed")
    statuses = get_task_statuses()
    assert "test_task" in statuses
    assert statuses["test_task"]["status"] == "completed"
    assert statuses["test_task"]["last_run"] is not None


async def test_system_health_api(client):
    r = client.get("/api/health/detail/system")
    assert r.status_code == 200
    data = r.json()
    assert "cpu_percent" in data
    assert "memory_percent" in data
    assert "disk_percent" in data
    assert "db_size_mb" in data


async def test_mqtt_health_api(client):
    r = client.get("/api/health/detail/mqtt")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


async def test_clients_api(client):
    r = client.get("/api/health/detail/clients")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_tasks_api(client):
    r = client.get("/api/health/detail/tasks")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_clock_runs_chronyc_off_the_event_loop(client, monkeypatch):
    """srv-rest#36: a blocking subprocess.run (timeout 1.5 s) inside the async
    handler froze MQTT ingest / automation / Socket.IO on every poll."""
    calls: list[bool] = []

    def fake_run(cmd, **kwargs):
        calls.append(_on_event_loop())
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Reference ID    : 0A000001 (10.0.0.1)\nStratum         : 3\n", stderr="",
        )

    monkeypatch.setattr(health_router.subprocess, "run", fake_run)
    r = client.get("/api/health/detail/clock")
    assert r.status_code == 200, r.text
    assert calls == [False], "chronyc must run in a worker thread, not on the loop"
    assert r.json()["chrony"]["available"] is True
    assert r.json()["chrony"]["stratum"] == "3"


def test_system_metrics_sample_cpu_off_the_event_loop(client, monkeypatch):
    calls: list[bool] = []

    def fake_cpu_percent(*args, **kwargs):
        calls.append(_on_event_loop())
        return 12.5

    monkeypatch.setattr(health_service.psutil, "cpu_percent", fake_cpu_percent)
    r = client.get("/api/health/detail/system")
    assert r.status_code == 200, r.text
    assert r.json()["cpu_percent"] == 12.5
    assert calls == [False], "the 100 ms cpu sample must not block the loop"
