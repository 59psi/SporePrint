"""The background-task registry (GET /api/health/detail/tasks) tells the truth.

weather_polling, retention and node_liveness_sweeper were registered as
"running" at boot and never updated, so a nightly retention that failed every
night still read "running"; main.py's cloud_connector registration was dead
(cloud.service's own status always replaced it). Each loop now reports
running / idle / error (with the error) itself. The sweeper's reporting is in
test_node_liveness.py.
"""

import asyncio

import pytest

import app.retention.service as retention_service
import app.weather.service as weather_service
from app.config import settings
from app.health.service import _task_registry, register_task


@pytest.fixture(autouse=True)
def _registry():
    _task_registry.clear()
    yield
    _task_registry.clear()


async def _until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


async def _run(loop_coro, until) -> None:
    task = asyncio.create_task(loop_coro)
    try:
        await _until(until)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ── nightly retention ─────────────────────────────────────────────────────

class _JustBefore3am:
    """Stands in for retention's `time` module: 10 ms before 3 AM."""

    def time(self) -> float:
        return 86400 * 20_000 + 3 * 3600 - 0.01


@pytest.fixture()
def retention_now(monkeypatch):
    monkeypatch.setattr(retention_service, "time", _JustBefore3am())
    register_task("retention", "idle")


async def test_a_failing_retention_run_shows_as_an_error(monkeypatch, retention_now):
    async def _fail():
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(retention_service, "run_retention", _fail)
    await _run(retention_service.start_retention_task(),
               lambda: _task_registry["retention"]["status"] == "error")
    assert "disk is full" in _task_registry["retention"]["error"]


async def test_a_good_retention_run_shows_as_idle(monkeypatch, retention_now):
    runs = []

    async def _ok():
        runs.append(_task_registry["retention"]["status"])

    monkeypatch.setattr(retention_service, "run_retention", _ok)
    await _run(retention_service.start_retention_task(), lambda: bool(runs) and
               _task_registry["retention"]["status"] == "idle")
    assert runs == ["running"]
    assert _task_registry["retention"]["last_run"] is not None


# ── weather polling ───────────────────────────────────────────────────────

class _Provider:
    name = "fake"

    def __init__(self, current=None, forecast=None, error=None):
        self._current, self._forecast, self._error = current, forecast, error

    async def fetch_current(self, lat, lon):
        if self._error:
            raise self._error
        return self._current

    async def fetch_forecast(self, lat, lon):
        if self._error:
            raise self._error
        return self._forecast


@pytest.fixture()
def weather_configured(monkeypatch):
    monkeypatch.setattr(settings, "weather_lat", "45.5")
    monkeypatch.setattr(settings, "weather_lon", "-122.6")
    register_task("weather_polling", "idle")

    async def _no_alerts(current, forecast):
        return None

    monkeypatch.setattr(weather_service, "_check_forecast_alerts", _no_alerts)


def _not_running(name):
    return lambda: _task_registry[name]["last_run"] is not None and \
        _task_registry[name]["status"] != "running"


async def test_a_poll_every_provider_failed_is_an_error(monkeypatch, weather_configured):
    monkeypatch.setattr(weather_service, "_get_providers",
                        lambda: [_Provider(error=TimeoutError("no route"))])
    await _run(weather_service.start_weather_polling(None), _not_running("weather_polling"))
    assert _task_registry["weather_polling"]["status"] == "error"
    assert "provider" in _task_registry["weather_polling"]["error"]


async def test_a_good_poll_is_idle(monkeypatch, weather_configured):
    forecast = [{"timestamp": 0, "temp_f": 60.0}]
    monkeypatch.setattr(weather_service, "_get_providers",
                        lambda: [_Provider(current=None, forecast=forecast)])
    await _run(weather_service.start_weather_polling(None), _not_running("weather_polling"))
    assert _task_registry["weather_polling"]["status"] == "idle"
    assert _task_registry["weather_polling"]["error"] is None


async def test_a_crashing_poll_is_an_error(monkeypatch, weather_configured):
    def _broken():
        raise ValueError("bad provider config")

    monkeypatch.setattr(weather_service, "_get_providers", _broken)
    await _run(weather_service.start_weather_polling(None), _not_running("weather_polling"))
    assert _task_registry["weather_polling"]["status"] == "error"
    assert "bad provider config" in _task_registry["weather_polling"]["error"]


# ── registration at boot ──────────────────────────────────────────────────

def test_boot_registers_the_nightly_and_periodic_jobs_as_idle(client):
    tasks = client.get("/api/health/detail/tasks").json()
    for name in ("retention", "weather_polling", "node_liveness_sweeper"):
        assert tasks[name]["status"] == "idle", (name, tasks[name])
    # Still reported, by the connector itself.
    assert "cloud_connector" in tasks
