"""Tests for tiered data retention and rollup logic."""

import time

from app.db import get_db
from app.retention.service import (
    FIRINGS_RETENTION_DAYS,
    _rollup_telemetry_5min,
    _rollup_telemetry_hourly,
    _rollup_weather_hourly,
    run_retention,
)
from app.telemetry.service import store_reading


async def _insert_old_reading(node_id: str, sensor: str, value: float, ts: float):
    """Insert a telemetry reading with a specific timestamp."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            (ts, node_id, sensor, value),
        )
        await db.commit()


async def _insert_old_weather(temp_f: float, humidity: float, ts: float):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO weather_readings (timestamp, temp_f, humidity) VALUES (?, ?, ?)",
            (ts, temp_f, humidity),
        )
        await db.commit()


async def test_rollup_telemetry_5min():
    # Insert readings 10 days ago (older than 7-day raw retention)
    # All within one 5-min bucket (300s)
    old_ts = time.time() - 10 * 86400
    for i in range(6):
        await _insert_old_reading("node-01", "temp_f", 70.0 + i, old_ts + i * 30)

    await _rollup_telemetry_5min()

    # Raw readings should be deleted
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM telemetry_readings")
        assert (await cursor.fetchone())["cnt"] == 0

        # Rollups should exist
        cursor = await db.execute(
            "SELECT * FROM telemetry_rollups WHERE resolution = '5min'"
        )
        rows = await cursor.fetchall()
        assert len(rows) >= 1
        rollup = dict(rows[0])
        assert rollup["sensor"] == "temp_f"
        assert rollup["count"] >= 1  # at least one bucket


async def test_rollup_preserves_recent():
    # Insert a reading from today (within 7-day window)
    await store_reading("node-01", "temp_f", 75.0, time.time())

    await _rollup_telemetry_5min()

    # Recent reading should NOT be deleted
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM telemetry_readings")
        assert (await cursor.fetchone())["cnt"] == 1


async def test_rollup_weather_hourly():
    # Insert weather readings 35 days ago (older than 30-day retention)
    old_ts = time.time() - 35 * 86400
    for i in range(10):
        await _insert_old_weather(80.0 + i, 50.0, old_ts + i * 600)

    await _rollup_weather_hourly()

    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM weather_readings")
        assert (await cursor.fetchone())["cnt"] == 0

        cursor = await db.execute("SELECT * FROM weather_rollups WHERE resolution = 'hourly'")
        rows = await cursor.fetchall()
        assert len(rows) >= 1


async def test_full_retention_run():
    """run_retention() should complete without errors even with empty tables."""
    await run_retention()


# ── automation_firings pruning (srv-auto#18) ───────────────────────────────

async def _firing(ts: float, session_id: int | None = None, *, fk: bool = True) -> None:
    async with get_db() as db:
        if not fk:  # an orphan left by a pre-FK database
            await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute(
            "INSERT INTO automation_firings (rule_id, rule_name, timestamp, session_id) "
            "VALUES (1, 'Humidity Boost', ?, ?)",
            (ts, session_id),
        )
        await db.commit()


async def _session() -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO sessions (name, species_profile_id) VALUES ('grow', 'blue_oyster')")
        await db.commit()
        return cursor.lastrowid


async def test_retention_prunes_old_firings_that_belong_to_no_session():
    now = time.time()
    old = now - (FIRINGS_RETENTION_DAYS + 5) * 86400
    sid = await _session()
    await _firing(old)                        # no session, expired  -> pruned
    await _firing(old, 9999, fk=False)        # orphaned session id  -> pruned
    await _firing(old, sid)                   # a grow's event log   -> kept
    await _firing(now - 10 * 86400)           # recent               -> kept

    await run_retention()

    async with get_db() as db:
        rows = [dict(r) for r in await (await db.execute(
            "SELECT timestamp, session_id FROM automation_firings ORDER BY timestamp")).fetchall()]
    # Session-tagged rows feed that session's transcript automation summary
    # (transcript.export_json), so they are kept for the life of the record.
    assert rows == [
        {"timestamp": old, "session_id": sid},
        {"timestamp": now - 10 * 86400, "session_id": None},
    ]


# ── vision frames get a nightly prune pass (notify-vision-weather 4) ──────

async def test_retention_runs_the_vision_frame_prune(monkeypatch):
    calls = []

    async def _prune():
        calls.append(time.time())
        return {"frames_deleted": 0, "bytes_freed": 0, "frames_kept_outside_storage": 0}

    monkeypatch.setattr("app.retention.service.prune_vision_frames", _prune)
    await run_retention()
    assert len(calls) == 1


async def test_a_failing_vision_prune_does_not_abort_retention(monkeypatch):
    async def _boom():
        raise OSError("vision storage unavailable")

    monkeypatch.setattr("app.retention.service.prune_vision_frames", _boom)
    vacuumed = []

    async def _vacuum_spy():
        vacuumed.append(True)

    monkeypatch.setattr("app.retention.service._vacuum", _vacuum_spy)
    await run_retention()
    assert vacuumed == [True]


# ── the one-time auto_vacuum conversion needs disk headroom ────────────────

async def test_auto_vacuum_conversion_is_skipped_without_disk_headroom(monkeypatch):
    """A full VACUUM writes a copy of the DB (temp file + WAL); running out of
    disk mid-way would starve the broker and ntfy on the same card."""
    import collections

    from app.retention import service as retention

    async with get_db() as db:
        await db.execute("PRAGMA auto_vacuum = NONE")
        await db.execute("VACUUM")
    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(retention.shutil, "disk_usage",
                        lambda _path: Usage(10**9, 10**9 - 1024, 1024))

    assert await retention.ensure_incremental_auto_vacuum() is False
    async with get_db() as db:
        mode = (await (await db.execute("PRAGMA auto_vacuum")).fetchone())[0]
    assert mode == 0
