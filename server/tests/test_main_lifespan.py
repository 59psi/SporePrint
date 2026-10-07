"""Boot-time wiring in app.main's lifespan and its periodic tasks.

* A small existing database is converted to auto_vacuum=INCREMENTAL at
  startup, so the nightly retention job never needs the writer-stalling
  VACUUM. The conversion runs only AFTER MQTT (the rules engine) has started
  and the persisted safety watchdogs are re-armed, and a database too big to
  rewrite quickly is left to the nightly retention window.
* Overdue-phase INFO reminders (sessions.check_phase_reminders) run daily.
* The coredump directory is created up front, so an unwritable data volume is
  reported at boot rather than when a node's first panic dump is lost.
"""

import asyncio
import datetime as dt
import logging

import aiosqlite
import pytest
from fastapi.testclient import TestClient

import app.automation.engine
import app.cloud.service
import app.mqtt
import app.retention.service
import app.weather.service
from app import main
from app.config import settings
from app.db import get_db


async def _pragma(name):
    async with aiosqlite.connect(settings.database_path) as db:
        return (await (await db.execute(f"PRAGMA {name}")).fetchone())[0]


# ── auto_vacuum conversion at boot (ingest-telemetry cross-need 4a) ────────

@pytest.fixture()
async def legacy_db():
    """The test DB as a pre-upgrade install left it: auto_vacuum=NONE."""
    async with get_db() as db:
        await db.execute("PRAGMA auto_vacuum = NONE")
        await db.execute("VACUUM")
    assert await _pragma("auto_vacuum") == 0


async def test_boot_converts_an_existing_database_to_incremental(legacy_db, client):
    assert client.get("/api/health").status_code == 200
    assert await _pragma("auto_vacuum") == 2


@pytest.fixture()
def failing_conversion(monkeypatch):
    calls = []

    async def _boom():
        calls.append(True)
        raise OSError("database or disk is full")

    monkeypatch.setattr("app.retention.service.ensure_incremental_auto_vacuum", _boom)
    return calls


async def test_a_failed_conversion_never_blocks_boot(failing_conversion, client):
    assert failing_conversion == [True]
    assert client.get("/api/health").status_code == 200


async def _forever(*_args):
    await asyncio.Event().wait()


@pytest.fixture()
def boot_order(monkeypatch):
    """Boot the real lifespan, recording when each safety-relevant step ran."""
    order: list[str] = []

    def _start_mqtt(sio):
        order.append("mqtt")
        return _forever()

    async def _rehydrate():
        order.append("rehydrate_watchdogs")
        return 0

    async def _start_integrations():
        order.append("integrations")

    async def _convert():
        order.append("auto_vacuum")
        return False

    monkeypatch.setattr(app.mqtt, "start_mqtt", _start_mqtt)
    monkeypatch.setattr(app.weather.service, "start_weather_polling", _forever)
    monkeypatch.setattr(app.retention.service, "start_retention_task", _forever)
    monkeypatch.setattr(app.cloud.service, "start_cloud_connector", _forever)
    monkeypatch.setattr(main, "_daily_retrain", _forever)
    monkeypatch.setattr(main, "_nightly_weather_aggregate", _forever)
    monkeypatch.setattr(main, "_node_liveness_sweeper", _forever)
    monkeypatch.setattr(app.automation.engine, "rehydrate_safety_watchdogs", _rehydrate)
    monkeypatch.setattr(main, "_start_enabled_integrations", _start_integrations)
    monkeypatch.setattr(app.retention.service, "ensure_incremental_auto_vacuum", _convert)
    return order


def test_conversion_runs_after_mqtt_and_the_safety_watchdogs(boot_order):
    """The one-time VACUUM can take minutes on an SD card. Before, it ran
    first, so for that whole time the rules engine was down and a persisted
    safety ceiling (a smart-plug heater held ON, no firmware backstop) was
    neither re-armed nor tripped."""
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
    assert "auto_vacuum" in boot_order
    converted_at = boot_order.index("auto_vacuum")
    for step in ("mqtt", "rehydrate_watchdogs", "integrations"):
        assert boot_order.index(step) < converted_at, boot_order


async def test_a_big_legacy_database_is_left_to_the_nightly_window(
        legacy_db, monkeypatch, main_log, client_factory):
    monkeypatch.setattr(main, "_BOOT_AUTO_VACUUM_MAX_BYTES", 1)
    with client_factory() as client:
        assert client.get("/api/health").status_code == 200
    assert await _pragma("auto_vacuum") == 0
    assert any("nightly" in m for m in main_log), main_log


async def test_a_converted_big_database_logs_nothing(monkeypatch, main_log, client_factory):
    assert await _pragma("auto_vacuum") == 2
    monkeypatch.setattr(main, "_BOOT_AUTO_VACUUM_MAX_BYTES", 1)
    with client_factory():
        pass
    assert not any("auto_vacuum" in m for m in main_log), main_log


@pytest.fixture()
def main_log():
    """Messages app.main logs. caplog cannot see them: the lifespan's
    configure_logging() replaces the root handlers."""
    messages: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Collect(level=logging.INFO)
    logger = logging.getLogger("app.main")
    logger.addHandler(handler)
    yield messages
    logger.removeHandler(handler)


@pytest.fixture()
def client_factory(monkeypatch):
    """Like conftest's `client`, but the test decides when to boot."""
    monkeypatch.setattr(app.mqtt, "start_mqtt", _forever)
    monkeypatch.setattr(app.weather.service, "start_weather_polling", _forever)
    monkeypatch.setattr(app.retention.service, "start_retention_task", _forever)
    monkeypatch.setattr(app.cloud.service, "start_cloud_connector", _forever)
    monkeypatch.setattr(main, "_daily_retrain", _forever)
    monkeypatch.setattr(main, "_nightly_weather_aggregate", _forever)
    monkeypatch.setattr(main, "_node_liveness_sweeper", _forever)
    return lambda: TestClient(main.app, raise_server_exceptions=False)


# ── daily phase reminders (sessions-species cross-need 1, srv-rest#13) ─────

def test_next_phase_reminder_is_the_next_local_reminder_hour():
    hour = main._PHASE_REMINDER_LOCAL_HOUR
    before = dt.datetime(2026, 9, 27, hour - 1, 0, 0).timestamp()
    assert main._seconds_until_next_phase_reminder(before) == pytest.approx(3600)
    after = dt.datetime(2026, 9, 27, hour, 30, 0).timestamp()
    assert main._seconds_until_next_phase_reminder(after) == pytest.approx(23.5 * 3600)


async def test_phase_reminder_loop_runs_the_check_repeatedly(monkeypatch):
    calls = []
    done = asyncio.Event()

    async def _check():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("profile lookup failed")  # must not kill the loop
        done.set()
        return 1

    monkeypatch.setattr(main, "check_phase_reminders", _check)
    monkeypatch.setattr(main, "_seconds_until_next_phase_reminder", lambda now=None: 0.0)
    task = asyncio.create_task(main._phase_reminder_loop())
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(calls) == 2


async def test_phase_reminder_task_is_started_and_registered(client):
    resp = client.get("/api/health/detail/tasks")
    assert resp.status_code == 200
    assert "phase_reminders" in resp.json()


# ── coredump directory (deps-platform cross-need 6) ────────────────────────

async def test_boot_creates_the_coredump_directory(client):
    from app.hardware.coredumps import coredump_dir

    assert coredump_dir().is_dir()


async def test_boot_discards_half_written_coredumps(tmp_path, monkeypatch, client_factory):
    # A crash mid-write leaves <name>.elf.part; that upload was never
    # acknowledged, so the node still holds the dump and sends it again.
    from app.hardware import coredumps

    dumps = tmp_path / "dumps"
    dumps.mkdir()
    (dumps / "node-1-20261005T000000Z.elf.part").write_bytes(b"half")
    (dumps / "node-1-20261004T000000Z.elf").write_bytes(b"whole")
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", dumps)
    with client_factory():
        pass
    assert sorted(p.name for p in dumps.iterdir()) == ["node-1-20261004T000000Z.elf"]
