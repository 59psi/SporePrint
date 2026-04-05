import pytest


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


@pytest.fixture()
def mock_mqtt(monkeypatch):
    """Patch mqtt_publish everywhere it's imported. Returns list of (topic, payload) calls."""
    calls: list[tuple[str, dict]] = []

    async def fake_publish(topic, payload):
        calls.append((topic, payload))

    import app.mqtt
    import app.automation.engine
    monkeypatch.setattr(app.mqtt, "mqtt_publish", fake_publish)
    monkeypatch.setattr(app.automation.engine, "mqtt_publish", fake_publish)
    return calls


@pytest.fixture()
def mock_sio():
    """Provide a fake Socket.IO server that records emitted events."""
    from unittest.mock import AsyncMock
    return AsyncMock()


@pytest.fixture(autouse=True)
def _reset_engine_state():
    """Clear module-level mutable state in the automation engine between tests."""
    import app.automation.engine as engine
    engine._last_fired.clear()
    engine._overrides.clear()
    engine._rule_cache.clear()
    engine._cache_ts = 0


@pytest.fixture(autouse=True)
def _reset_notification_state():
    """Clear notification dedup tracking between tests."""
    import app.notifications.service as svc
    svc._last_sent.clear()
