"""Tiered data retention: raw → 5min → hourly → daily.

Runs nightly to compress old data and reclaim storage.

Retention policy:
  - Raw telemetry: 7 days
  - 5-minute averages: 30 days
  - Hourly averages: 365 days
  - Daily averages: forever

Same policy for weather data.
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
            # Sleep until next 3 AM
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
            await asyncio.sleep(3600)  # retry in 1 hour


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
        await db.execute(
            """INSERT OR IGNORE INTO telemetry_rollups (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
               SELECT CAST(timestamp / 300 AS INT) * 300, node_id, sensor, '5min',
                      AVG(value), MIN(value), MAX(value), COUNT(*)
               FROM telemetry_readings
               WHERE timestamp < ?
               GROUP BY CAST(timestamp / 300 AS INT), node_id, sensor""",
            (cutoff,),
        )
        result = await db.execute("DELETE FROM telemetry_readings WHERE timestamp < ?", (cutoff,))
        await db.commit()
        log.info("Retention: 5min telemetry rollup — deleted %d raw rows", result.rowcount)


async def _rollup_telemetry_hourly():
    """Aggregate 5-min rollups older than 30 days into hourly rollups, then delete 5-min."""
    cutoff = time.time() - FIVEMIN_RETENTION_DAYS * 86400
    async with get_db() as db:
        await db.execute(
            """INSERT OR IGNORE INTO telemetry_rollups (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
               SELECT CAST(timestamp / 3600 AS INT) * 3600, node_id, sensor, 'hourly',
                      AVG(avg_value), MIN(min_value), MAX(max_value), SUM(count)
               FROM telemetry_rollups
               WHERE resolution = '5min' AND timestamp < ?
               GROUP BY CAST(timestamp / 3600 AS INT), node_id, sensor""",
            (cutoff,),
        )
        result = await db.execute(
            "DELETE FROM telemetry_rollups WHERE resolution = '5min' AND timestamp < ?",
            (cutoff,),
        )
        await db.commit()
        log.info("Retention: hourly telemetry rollup — deleted %d 5min rows", result.rowcount)


async def _rollup_weather_hourly():
    """Aggregate raw weather readings older than 30 days into hourly rollups, then delete raw."""
    cutoff = time.time() - FIVEMIN_RETENTION_DAYS * 86400
    async with get_db() as db:
        await db.execute(
            """INSERT OR IGNORE INTO weather_rollups (timestamp, resolution, avg_temp_f, min_temp_f, max_temp_f, avg_humidity, count)
               SELECT CAST(timestamp / 3600 AS INT) * 3600, 'hourly',
                      AVG(temp_f), MIN(temp_f), MAX(temp_f), AVG(humidity), COUNT(*)
               FROM weather_readings
               WHERE timestamp < ?
               GROUP BY CAST(timestamp / 3600 AS INT)""",
            (cutoff,),
        )
        result = await db.execute("DELETE FROM weather_readings WHERE timestamp < ?", (cutoff,))
        await db.commit()
        log.info("Retention: hourly weather rollup — deleted %d raw rows", result.rowcount)


async def _cleanup_old_rollups():
    """Remove hourly rollups older than 365 days (daily rollups kept forever)."""
    cutoff = time.time() - HOURLY_RETENTION_DAYS * 86400
    async with get_db() as db:
        # Aggregate hourly → daily before deleting
        await db.execute(
            """INSERT OR IGNORE INTO telemetry_rollups (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
               SELECT CAST(timestamp / 86400 AS INT) * 86400, node_id, sensor, 'daily',
                      AVG(avg_value), MIN(min_value), MAX(max_value), SUM(count)
               FROM telemetry_rollups
               WHERE resolution = 'hourly' AND timestamp < ?
               GROUP BY CAST(timestamp / 86400 AS INT), node_id, sensor""",
            (cutoff,),
        )
        result = await db.execute(
            "DELETE FROM telemetry_rollups WHERE resolution = 'hourly' AND timestamp < ?",
            (cutoff,),
        )
        await db.commit()
        if result.rowcount > 0:
            log.info("Retention: daily rollup — deleted %d hourly rows", result.rowcount)


async def _vacuum():
    """Reclaim disk space."""
    async with get_db() as db:
        await db.execute("PRAGMA incremental_vacuum")
