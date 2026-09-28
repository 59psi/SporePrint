"""Boot-time wiring in app.main's lifespan and its periodic tasks.

* The database is converted to auto_vacuum=INCREMENTAL at startup, before any
  writer task exists (the conversion is a full VACUUM holding the write lock),
  so the nightly retention job never needs the writer-stalling VACUUM.
* Overdue-phase INFO reminders (sessions.check_phase_reminders) run daily.
* The coredump directory is created up front, so an unwritable data volume is
  reported at boot rather than when a node's first panic dump is lost.
"""

import asyncio
import datetime as dt

import aiosqlite
import pytest

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
