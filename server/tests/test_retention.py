"""Tiered data retention: the rollup steps, the rollup safety invariant, and
the nightly prunes.

Rollup safety invariant (retention/service.py): every raw row deleted must
contribute to an aggregate row, created by this run or merged count-weighted
into an existing one (a partial earlier run), and a step that fails deletes
nothing.
"""

import collections
import sqlite3
import time

import aiosqlite
import pytest

from app.db import get_db
from app.retention import service as retention
from app.retention.service import (
    FIRINGS_RETENTION_DAYS,
    _cleanup_old_rollups,
    _rollup_telemetry_5min,
    _rollup_telemetry_hourly,
    _rollup_weather_hourly,
    run_retention,
)

DAY = 86400


def _bucket(ts: float, width: int) -> int:
    return int(ts // width) * width


async def _raw(node_id: str, sensor: str, value: float, ts: float):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            (ts, node_id, sensor, value),
        )
        await db.commit()


async def _rollup(resolution, ts, avg, mn, mx, count, node="n1", sensor="temp_f"):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, "
            "avg_value, min_value, max_value, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, node, sensor, resolution, avg, mn, mx, count),
        )
        await db.commit()


async def _rows(sql: str, params=()) -> list[tuple]:
    async with get_db() as db:
        return [tuple(r) for r in await (await db.execute(sql, params)).fetchall()]


_ROLLUPS = ("SELECT timestamp, resolution, avg_value, min_value, max_value, count "
            "FROM telemetry_rollups ORDER BY resolution, timestamp")


async def test_raw_readings_past_seven_days_roll_into_5min_buckets():
    now = time.time()
    b = _bucket(now - 10 * DAY, 300)
    for i in range(6):
        await _raw("node-01", "temp_f", 70.0 + i, b + i * 30)
    await _raw("node-01", "temp_f", 75.0, now)  # inside the raw window: stays raw

    await _rollup_telemetry_5min()

    assert await _rows("SELECT value FROM telemetry_readings") == [(75.0,)]
    assert await _rows(_ROLLUPS) == [(b, "5min", 72.5, 70.0, 75.0, 6)]


# One source tier per step. Each case's source rows hold 6 readings inside one
# bucket of the target tier: one at 90 and five at 70, so their count-weighted
# mean is 73.33 (an unweighted mean of two rollup rows would read 80).
async def _raw_source(bucket):
    for i, value in enumerate((90.0, 70.0, 70.0, 70.0, 70.0, 70.0)):
        await _raw("n1", "temp_f", value, bucket + i * 30)


def _rollup_source(resolution, width):
    async def _put(bucket):
        await _rollup(resolution, bucket, 90.0, 90.0, 90.0, 1)
        await _rollup(resolution, bucket + width, 70.0, 70.0, 70.0, 5)
    return _put


_STEPS = {
    # target tier: (step, age of the data, target width, source rows, source table/tier)
    "5min": (_rollup_telemetry_5min, 10 * DAY, 300, _raw_source,
             "SELECT COUNT(*) FROM telemetry_readings"),
    "hourly": (_rollup_telemetry_hourly, 40 * DAY, 3600, _rollup_source("5min", 300),
               "SELECT COUNT(*) FROM telemetry_rollups WHERE resolution = '5min'"),
    "daily": (_cleanup_old_rollups, 400 * DAY, DAY, _rollup_source("hourly", 3600),
              "SELECT COUNT(*) FROM telemetry_rollups WHERE resolution = 'hourly'"),
}


@pytest.mark.parametrize("tier", list(_STEPS))
async def test_a_rerun_merges_count_weighted_into_an_existing_rollup(tier):
    """A bucket already rolled up by a partial earlier run is merged into,
    never skipped (INSERT OR IGNORE + DELETE silently dropped its rows), and
    coarser tiers weight each finer bucket's mean by its count (partial
    buckets, offline-buffer flushes)."""
    step, age, width, put_source, source_count = _STEPS[tier]
    bucket = _bucket(time.time() - age, width)
    await _rollup(tier, bucket, 60.0, 55.0, 65.0, 4)  # the earlier run's row
    await put_source(bucket)

    await step()

    assert await _rows(source_count) == [(0,)]
    ((ts, resolution, avg, mn, mx, count),) = [
        r for r in await _rows(_ROLLUPS) if r[1] == tier]
    assert (ts, mn, mx, count) == (bucket, 55.0, 90.0, 10)
    assert avg == pytest.approx((60.0 * 4 + 90.0 + 70.0 * 5) / 10)  # 68.0


@pytest.mark.parametrize("tier", list(_STEPS))
async def test_a_failed_rollup_step_deletes_nothing(monkeypatch, tier):
    step, age, width, put_source, source_count = _STEPS[tier]
    await put_source(_bucket(time.time() - age, width))
    (before,) = await _rows(source_count)
    real_execute = aiosqlite.Connection.execute

    async def _execute(self, sql, *args, **kwargs):
        if sql.lstrip().startswith("DELETE"):
            raise sqlite3.OperationalError("disk I/O error")
        return await real_execute(self, sql, *args, **kwargs)

    with monkeypatch.context() as m, pytest.raises(sqlite3.OperationalError):
        m.setattr(aiosqlite.Connection, "execute", _execute)
        await step()

    assert await _rows(source_count) == [before]
    assert [r for r in await _rows(_ROLLUPS) if r[1] == tier] == []


async def test_weather_older_than_30_days_merges_into_hourly_rollups():
    hour = _bucket(time.time() - 35 * DAY, 3600)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO weather_rollups (timestamp, resolution, avg_temp_f, min_temp_f, "
            "max_temp_f, avg_humidity, count) VALUES (?, 'hourly', 60, 55, 65, 40, 4)", (hour,))
        await db.executemany(
            "INSERT INTO weather_readings (timestamp, temp_f, humidity) VALUES (?, ?, 50)",
            [(hour + i * 600, 70.0 + i) for i in range(6)])
        await db.commit()

    await _rollup_weather_hourly()

    assert await _rows("SELECT COUNT(*) FROM weather_readings") == [(0,)]
    ((avg_t, mn, mx, avg_h, count),) = await _rows(
        "SELECT avg_temp_f, min_temp_f, max_temp_f, avg_humidity, count FROM weather_rollups")
    assert (mn, mx, count) == (55.0, 75.0, 10)
    assert avg_t == pytest.approx(67.5) and avg_h == pytest.approx(46.0)


# ── automation_firings pruning ─────────────────────────────────────────────

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


# ── vision frames get a nightly prune pass ─────────────────────────────────

@pytest.mark.parametrize("prune_fails", [False, True], ids=["prune-ok", "prune-fails"])
async def test_retention_prunes_vision_frames_and_still_vacuums_if_that_fails(
        monkeypatch, prune_fails):
    """Vision storage trouble (a moved or unmounted dir) must not cost the
    telemetry tiers their vacuum."""
    pruned, vacuumed = [], []

    async def _prune():
        pruned.append(True)
        if prune_fails:
            raise OSError("vision storage unavailable")
        return {"frames_deleted": 0, "bytes_freed": 0, "frames_kept_outside_storage": 0}

    async def _vacuum_spy():
        vacuumed.append(True)

    monkeypatch.setattr("app.retention.service.prune_vision_frames", _prune)
    monkeypatch.setattr("app.retention.service._vacuum", _vacuum_spy)
    await run_retention()
    assert pruned == [True] and vacuumed == [True]


# ── the one-time auto_vacuum conversion needs disk headroom ────────────────

async def test_auto_vacuum_conversion_is_skipped_without_disk_headroom(monkeypatch):
    """A full VACUUM writes a copy of the DB (temp file + WAL); running out of
    disk mid-way would starve the broker and ntfy on the same card."""
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
