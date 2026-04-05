"""Tests for tiered data retention and rollup logic."""

import time

from app.db import get_db
from app.retention.service import (
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
