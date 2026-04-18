import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
async def _db(tmp_path, monkeypatch):
    """Provide a fresh SQLite database for each test.

    Monkeypatches settings.database_path to a temp file so every call to
    get_db() connects to the same test database. Runs init_db() to apply
    the full schema.
    """
    db_path = str(tmp_path / "test.db")

    from app.config import settings
    monkeypatch.setattr(settings, "database_path", db_path)

    from app.db import init_db
    await init_db()


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

    import app.mqtt
    import app.automation.engine
    import app.automation.smart_plugs
    import app.hardware.service
    monkeypatch.setattr(app.mqtt, "mqtt_publish", fake_publish)
    monkeypatch.setattr(app.automation.engine, "mqtt_publish", fake_publish)
    monkeypatch.setattr(app.automation.smart_plugs, "mqtt_publish", fake_publish)
    # v3.3.2 refactor: hardware/router imports mqtt_publish via hardware/service
    monkeypatch.setattr(app.hardware.service, "mqtt_publish", fake_publish)
    return calls


@pytest.fixture()
def mock_sio():
    """Provide a fake Socket.IO server that records emitted events."""
    from unittest.mock import AsyncMock
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

    import app.mqtt
    import app.weather.service
    import app.retention.service
    import app.cloud.service
    import app.main
    monkeypatch.setattr(app.mqtt, "start_mqtt", _noop_task)
    monkeypatch.setattr(app.weather.service, "start_weather_polling", _noop_task)
    monkeypatch.setattr(app.retention.service, "start_retention_task", _noop_coro)
    monkeypatch.setattr(app.cloud.service, "start_cloud_connector", _noop_coro)
    monkeypatch.setattr(app.main, "_daily_retrain", _noop_coro)
    monkeypatch.setattr(app.main, "_nightly_weather_aggregate", _noop_coro)
    monkeypatch.setattr(app.main, "_node_liveness_sweeper", _noop_coro)

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_engine_state():
    """Clear module-level mutable state in the automation engine between tests."""
    import app.automation.engine as engine
    engine._last_fired.clear()
    engine._overrides.clear()
    engine._rule_cache.clear()
    engine._cache_ts = 0
    engine._overrides_loaded = False
    for task in list(engine._safety_tasks.values()):
        if not task.done():
            task.cancel()
    engine._safety_tasks.clear()


@pytest.fixture(autouse=True)
def _reset_notification_state():
    """Clear notification dedup tracking between tests."""
    import app.notifications.service as svc
    svc._last_sent.clear()


@pytest.fixture(autouse=True)
def _reset_weather_state():
    """Clear weather cache between tests."""
    import app.weather.service as wsvc
    wsvc._cache = {}
    wsvc._cache_ts = 0
    wsvc._forecast_cache = []
    wsvc._forecast_cache_ts = 0
