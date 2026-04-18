"""Tiered data retention: raw → 5min → hourly → daily.

Runs nightly to compress old data and reclaim storage.

Retention policy:
  - Raw telemetry: 7 days
  - 5-minute averages: 30 days
  - Hourly averages: 365 days
  - Daily averages: forever

Same policy for weather data.

Rollup safety invariant:
  Every raw row deleted must contribute to an aggregate row that was either
  created by this run or merged into an existing row. The previous
  `INSERT OR IGNORE` + `DELETE` could silently drop raw rows whose bucket
  already had a pre-existing rollup from a partial prior run. UPSERTs with
  weighted-merge math preserve that invariant across retries.
"""

import asyncio
import logging
import time

from ..db import get_db

log = logging.getLogger(__name__)

RAW_RETENTION_DAYS = 7
FIVEMIN_RETENTION_DAYS = 30
HOURLY_RETENTION_DAYS = 365


async def start_retention_task():
    """Background task: run retention at 3 AM daily."""
    while True:
        try:
            now = time.time()
            today_3am = now - (now % 86400) + 3 * 3600
            if today_3am <= now:
                today_3am += 86400
            wait = today_3am - now
            log.info("Retention: next run in %.1f hours", wait / 3600)
            await asyncio.sleep(wait)

            await run_retention()

        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error("Retention task failed: %s", e)
            await asyncio.sleep(3600)


async def run_retention():
    """Execute all retention steps."""
    log.info("Retention: starting data compression run")
    t0 = time.time()

    await _rollup_telemetry_5min()
    await _rollup_telemetry_hourly()
    await _rollup_weather_hourly()
    await _cleanup_old_rollups()
    await _vacuum()

    elapsed = time.time() - t0
    log.info("Retention: completed in %.1fs", elapsed)


async def _rollup_telemetry_5min():
    """Aggregate raw telemetry older than 7 days into 5-minute rollups, then delete raw."""
    cutoff = time.time() - RAW_RETENTION_DAYS * 86400
    async with get_db() as db:
        await db.execute("BEGIN")
        try:
            await db.execute(
                """INSERT INTO telemetry_rollups
                      (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
                    SELECT CAST(timestamp / 300 AS INT) * 300, node_id, sensor, '5min',
                           AVG(value), MIN(value), MAX(value), COUNT(*)
                      FROM telemetry_readings
                     WHERE timestamp < ?
                     GROUP BY CAST(timestamp / 300 AS INT), node_id, sensor
                    ON CONFLICT(timestamp, node_id, sensor, resolution) DO UPDATE SET
                      avg_value = (
                        COALESCE(telemetry_rollups.avg_value, 0) * COALESCE(telemetry_rollups.count, 0)
                        + excluded.avg_value * excluded.count
                      ) / NULLIF(COALESCE(telemetry_rollups.count, 0) + excluded.count, 0),
                      min_value = MIN(telemetry_rollups.min_value, excluded.min_value),
                      max_value = MAX(telemetry_rollups.max_value, excluded.max_value),
                      count = COALESCE(telemetry_rollups.count, 0) + excluded.count""",
                (cutoff,),
            )
            result = await db.execute(
                "DELETE FROM telemetry_readings WHERE timestamp < ?", (cutoff,)
            )
            await db.commit()
            log.info("Retention: 5min telemetry rollup — deleted %d raw rows", result.rowcount)
        except Exception:
            await db.rollback()
            raise


async def _rollup_telemetry_hourly():
    """Aggregate 5-min rollups older than 30 days into hourly rollups, then delete 5-min."""
    cutoff = time.time() - FIVEMIN_RETENTION_DAYS * 86400
    async with get_db() as db:
        await db.execute("BEGIN")
        try:
            await db.execute(
                """INSERT INTO telemetry_rollups
                      (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
                    SELECT CAST(timestamp / 3600 AS INT) * 3600, node_id, sensor, 'hourly',
                           AVG(avg_value), MIN(min_value), MAX(max_value), SUM(count)
                      FROM telemetry_rollups
                     WHERE resolution = '5min' AND timestamp < ?
                     GROUP BY CAST(timestamp / 3600 AS INT), node_id, sensor
                    ON CONFLICT(timestamp, node_id, sensor, resolution) DO UPDATE SET
                      avg_value = (
                        COALESCE(telemetry_rollups.avg_value, 0) * COALESCE(telemetry_rollups.count, 0)
                        + excluded.avg_value * excluded.count
                      ) / NULLIF(COALESCE(telemetry_rollups.count, 0) + excluded.count, 0),
                      min_value = MIN(telemetry_rollups.min_value, excluded.min_value),
                      max_value = MAX(telemetry_rollups.max_value, excluded.max_value),
                      count = COALESCE(telemetry_rollups.count, 0) + excluded.count""",
                (cutoff,),
            )
            result = await db.execute(
                "DELETE FROM telemetry_rollups WHERE resolution = '5min' AND timestamp < ?",
                (cutoff,),
            )
            await db.commit()
            log.info("Retention: hourly telemetry rollup — deleted %d 5min rows", result.rowcount)
        except Exception:
            await db.rollback()
            raise


async def _rollup_weather_hourly():
    """Aggregate raw weather readings older than 30 days into hourly rollups, then delete raw."""
    cutoff = time.time() - FIVEMIN_RETENTION_DAYS * 86400
    async with get_db() as db:
        await db.execute("BEGIN")
        try:
            await db.execute(
                """INSERT INTO weather_rollups
                      (timestamp, resolution, avg_temp_f, min_temp_f, max_temp_f, avg_humidity, count)
                    SELECT CAST(timestamp / 3600 AS INT) * 3600, 'hourly',
                           AVG(temp_f), MIN(temp_f), MAX(temp_f), AVG(humidity), COUNT(*)
                      FROM weather_readings
                     WHERE timestamp < ?
                     GROUP BY CAST(timestamp / 3600 AS INT)
                    ON CONFLICT(timestamp, resolution) DO UPDATE SET
                      avg_temp_f = (
                        COALESCE(weather_rollups.avg_temp_f, 0) * COALESCE(weather_rollups.count, 0)
                        + excluded.avg_temp_f * excluded.count
                      ) / NULLIF(COALESCE(weather_rollups.count, 0) + excluded.count, 0),
                      min_temp_f = MIN(weather_rollups.min_temp_f, excluded.min_temp_f),
                      max_temp_f = MAX(weather_rollups.max_temp_f, excluded.max_temp_f),
                      avg_humidity = (
                        COALESCE(weather_rollups.avg_humidity, 0) * COALESCE(weather_rollups.count, 0)
                        + excluded.avg_humidity * excluded.count
                      ) / NULLIF(COALESCE(weather_rollups.count, 0) + excluded.count, 0),
                      count = COALESCE(weather_rollups.count, 0) + excluded.count""",
                (cutoff,),
            )
            result = await db.execute(
                "DELETE FROM weather_readings WHERE timestamp < ?", (cutoff,)
            )
            await db.commit()
            log.info("Retention: hourly weather rollup — deleted %d raw rows", result.rowcount)
        except Exception:
            await db.rollback()
            raise


async def _cleanup_old_rollups():
    """Aggregate hourly rollups older than 365 days into daily, then delete hourly."""
    cutoff = time.time() - HOURLY_RETENTION_DAYS * 86400
    async with get_db() as db:
        await db.execute("BEGIN")
        try:
            await db.execute(
                """INSERT INTO telemetry_rollups
                      (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
                    SELECT CAST(timestamp / 86400 AS INT) * 86400, node_id, sensor, 'daily',
                           AVG(avg_value), MIN(min_value), MAX(max_value), SUM(count)
                      FROM telemetry_rollups
                     WHERE resolution = 'hourly' AND timestamp < ?
                     GROUP BY CAST(timestamp / 86400 AS INT), node_id, sensor
                    ON CONFLICT(timestamp, node_id, sensor, resolution) DO UPDATE SET
                      avg_value = (
                        COALESCE(telemetry_rollups.avg_value, 0) * COALESCE(telemetry_rollups.count, 0)
                        + excluded.avg_value * excluded.count
                      ) / NULLIF(COALESCE(telemetry_rollups.count, 0) + excluded.count, 0),
                      min_value = MIN(telemetry_rollups.min_value, excluded.min_value),
                      max_value = MAX(telemetry_rollups.max_value, excluded.max_value),
                      count = COALESCE(telemetry_rollups.count, 0) + excluded.count""",
                (cutoff,),
            )
            result = await db.execute(
                "DELETE FROM telemetry_rollups WHERE resolution = 'hourly' AND timestamp < ?",
                (cutoff,),
            )
            await db.commit()
            if result.rowcount > 0:
                log.info("Retention: daily rollup — deleted %d hourly rows", result.rowcount)
        except Exception:
            await db.rollback()
            raise


async def _vacuum():
    """Reclaim disk space."""
    async with get_db() as db:
        await db.execute("PRAGMA incremental_vacuum")
