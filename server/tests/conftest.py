import asyncio
import os
import shutil
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

# Since v3.4.7 the server refuses to boot when SPOREPRINT_API_KEY is empty AND
# allow_unauthenticated is false (the new secure-by-default). Tests don't set
# an api_key, so opt into LAN-trust mode for the test process before the
# settings module imports — pydantic-settings reads the env at import time.
# The app imports below must therefore come after this line.
os.environ.setdefault("SPOREPRINT_ALLOW_UNAUTHENTICATED", "true")

import app.automation.engine  # noqa: E402
import app.cloud.service  # noqa: E402
import app.hardware.service  # noqa: E402
import app.main  # noqa: E402
import app.mqtt  # noqa: E402
import app.notifications.service  # noqa: E402
import app.retention.service  # noqa: E402
import app.weather.service  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import init_db  # noqa: E402


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    """One database with the full schema, built once per test session.

    init_db() reads nothing but settings.database_path and keeps no module
    state, so a byte copy of the file it leaves behind is the same database a
    fresh init_db() would build, at a fraction of the cost (the schema plus
    its migrations took ~50 ms per test, most of the suite's runtime).
    """
    path = tmp_path_factory.mktemp("db-template") / "template.db"
    saved = settings.database_path
    settings.database_path = str(path)
    try:
        asyncio.run(init_db())
    finally:
        settings.database_path = saved
    # The last connection closed, so SQLite checkpointed and removed the WAL:
    # the main file holds everything.
    assert not path.with_name(path.name + "-wal").exists()
    return path


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch, _db_template):
    """Provide a fresh SQLite database for each test.

    Monkeypatches settings.database_path to a temp file so every call to
    get_db() connects to the same test database, a copy of the session's
    fully initialised template.
    """
    db_path = tmp_path / "test.db"
    shutil.copyfile(_db_template, db_path)
    monkeypatch.setattr(settings, "database_path", str(db_path))


class _MqttCallsList(list):
    """list subclass that also carries the mock callable (for .mock.return_value)."""


@pytest.fixture()
def mock_mqtt(monkeypatch):
    """Patch mqtt_publish everywhere it's imported. Returns list of (topic, payload) calls.

    Returns True by default so fire-rule status='sent' reflects success. Set
    `mock_mqtt.mock.return_value = False` to simulate an MQTT outage.
    """
    calls = _MqttCallsList()

    class _MockPublish:
        return_value: bool = True

        async def __call__(self, topic, payload):
            calls.append((topic, payload))
            return self.return_value

    fake_publish = _MockPublish()
    calls.mock = fake_publish

    monkeypatch.setattr(app.mqtt, "mqtt_publish", fake_publish)
    monkeypatch.setattr(app.automation.engine, "mqtt_publish", fake_publish)
    # Smart plugs publish raw through app.mqtt._client (mock_mqtt_raw).
    # v3.3.2 refactor: hardware/router imports mqtt_publish via hardware/service
    monkeypatch.setattr(app.hardware.service, "mqtt_publish", fake_publish)
    return calls


@pytest.fixture()
def mock_mqtt_raw(monkeypatch):
    """Capture RAW publishes — the ones that bypass mqtt_publish's json.dumps.

    Smart plugs (Shelly/Tasmota) want a bare `on`/`ON` payload, not JSON, so
    they publish straight through the client. Returns a list of (topic, payload).
    """
    calls: list[tuple[str, str]] = []

    class _FakeClient:
        async def publish(self, topic, payload):
            calls.append((topic, payload))

    monkeypatch.setattr(app.mqtt, "_client", _FakeClient())
    return calls


@pytest.fixture()
def mock_sio():
    """Provide a fake Socket.IO server that records emitted events."""
    return AsyncMock()


@pytest.fixture()
def client(monkeypatch):
    """FastAPI test client with mocked MQTT (no broker needed).

    Triggers the full app lifespan: init_db, seed_builtins, seed_builtin_rules.
    MQTT is stubbed so the background task doesn't try to connect.
    """
    async def _noop_task(sio):
        await asyncio.Event().wait()

    async def _noop_coro():
        await asyncio.Event().wait()

    monkeypatch.setattr(app.mqtt, "start_mqtt", _noop_task)
    monkeypatch.setattr(app.weather.service, "start_weather_polling", _noop_task)
    monkeypatch.setattr(app.retention.service, "start_retention_task", _noop_coro)
    monkeypatch.setattr(app.cloud.service, "start_cloud_connector", _noop_coro)
    monkeypatch.setattr(app.main, "_daily_retrain", _noop_coro)
    monkeypatch.setattr(app.main, "_nightly_weather_aggregate", _noop_coro)
    monkeypatch.setattr(app.main, "_node_liveness_sweeper", _noop_coro)

    with TestClient(app.main.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_engine_state():
    """Clear module-level mutable state in the automation engine between tests."""
    engine = app.automation.engine
    engine._last_fired.clear()
    engine._overrides.clear()
    engine._rule_cache.clear()
    engine._cache_ts = 0
    engine._overrides_loaded = False
    engine._rule_seen.clear()
    engine._alert_last_sent.clear()
    engine._co2_page_undelivered.clear()
    engine._last_off_sent.clear()
    engine._phase_fallback_logged.clear()
    engine._no_node_logged.clear()
    # Each test has its own database: the persisted-watchdog keys reload from it.
    engine._persisted_watchdogs.clear()
    engine._persisted_watchdogs_loaded = False
    for task in list(engine._safety_tasks.values()):
        if not task.done():
            task.cancel()
    engine._safety_tasks.clear()


@pytest.fixture(autouse=True)
def _reset_mqtt_clock_state():
    """Clear the per-node telemetry ordering / clock-skew bookkeeping in mqtt.py
    (a node's newest live ts from one test would make the next test's frames
    look out of order)."""
    mqtt = app.mqtt
    mqtt._node_newest_ts.clear()
    mqtt._node_clock.clear()
    mqtt._skew_logged_at.clear()
    mqtt._reserved_drop_logged.clear()
    # Per-node bookkeeping keyed by node id (the log trim cadence, the CA
    # mismatch warned about): each test's database starts empty.
    mqtt._node_log_since_trim.clear()
    mqtt._ca_mismatch_logged.clear()


@pytest.fixture(autouse=True)
def _reset_notification_state():
    """Clear notification dedup tracking between tests."""
    app.notifications.service._last_sent.clear()


@pytest.fixture(autouse=True)
def _reset_weather_state():
    """Clear weather cache between tests."""
    wsvc = app.weather.service
    wsvc._cache = {}
    wsvc._cache_ts = 0
    wsvc._forecast_cache = []
    wsvc._forecast_cache_ts = 0
