"""Tiered data retention: raw → 5min → hourly → daily.

Runs nightly to compress old data and reclaim storage.

Retention policy:
  - Raw telemetry: 7 days
  - 5-minute averages: 30 days
  - Hourly averages: 365 days
  - Daily averages: forever

Same policy for weather data.

Also nightly:
  - automation_firings rows older than 90 days that belong to no session.
    Session-tagged firings are that grow's automation event log (its
    transcript's automation summary counts them), so they stay with it.
  - A vision-frame thinning pass (vision.service.prune_vision_frames), which
    ingest otherwise triggers at most once a day while cameras are posting.

Rollup safety invariant:
  Every raw row deleted must contribute to an aggregate row that was either
  created by this run or merged into an existing row. The previous
  `INSERT OR IGNORE` + `DELETE` could silently drop raw rows whose bucket
  already had a pre-existing rollup from a partial prior run. UPSERTs with
  weighted-merge math preserve that invariant across retries.
"""

import asyncio
import logging
import shutil
import time
from pathlib import Path

from ..config import settings
from ..db import get_db
from ..vision.service import prune_vision_frames

log = logging.getLogger(__name__)

RAW_RETENTION_DAYS = 7
FIVEMIN_RETENTION_DAYS = 30
HOURLY_RETENTION_DAYS = 365
FIRINGS_RETENTION_DAYS = 90

# The one-time conversion VACUUM writes a full copy of the database (a temp
# file, then the new pages through the WAL), so it only runs with room for
# two copies plus this margin left on the database's filesystem.
_VACUUM_FREE_MARGIN_BYTES = 64 * 1024 * 1024

# Coarser rollups (hourly, daily) are built from finer ones, whose buckets hold
# unequal counts (partial buckets, offline-buffer bursts, a changed publish
# interval). They weight each bucket's mean by its count, as the 5-min step and
# the upsert merge do:
#   COALESCE(SUM(avg_value * count) / NULLIF(SUM(count), 0), AVG(avg_value))
# Legacy rows without a count fall back to the plain mean.

# PRAGMA auto_vacuum value for INCREMENTAL mode.
_AUTO_VACUUM_INCREMENTAL = 2
# The nightly job only pays for the one-time mode-switch VACUUM when at least
# this much of the file is free pages (and at least ~1 MB of them).
_CONVERT_MIN_FREE_FRACTION = 0.25
_CONVERT_MIN_FREE_PAGES = 256


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
    await _prune_automation_firings()
    try:
        await prune_vision_frames()
    except Exception as e:
        # Vision storage trouble (a moved or unmounted dir) must not cost the
        # telemetry tiers their vacuum.
        log.warning("Retention: vision frame prune failed: %s", e)
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
                           COALESCE(SUM(avg_value * count) / NULLIF(SUM(count), 0), AVG(avg_value)),
                           MIN(min_value), MAX(max_value), SUM(count)
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
                           COALESCE(SUM(avg_value * count) / NULLIF(SUM(count), 0), AVG(avg_value)),
                           MIN(min_value), MAX(max_value), SUM(count)
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


async def _prune_automation_firings():
    """Delete expired automation firings that belong to no grow session.

    Rows tagged with a session are kept: they are that session's automation
    event log, and its transcript counts them. Rows whose session no longer
    exists (possible only in databases older than the FK pragma) are pruned.
    """
    cutoff = time.time() - FIRINGS_RETENTION_DAYS * 86400
    async with get_db() as db:
        result = await db.execute(
            """DELETE FROM automation_firings
                WHERE timestamp < ?
                  AND (session_id IS NULL
                       OR session_id NOT IN (SELECT id FROM sessions))""",
            (cutoff,),
        )
        await db.commit()
    if result.rowcount > 0:
        log.info("Retention: pruned %d automation firings older than %d days",
                 result.rowcount, FIRINGS_RETENTION_DAYS)


def _vacuum_has_room() -> bool:
    """Enough free disk for a full VACUUM of the database? Logs when not."""
    db_path = Path(settings.database_path)
    try:
        size = db_path.stat().st_size
        free = shutil.disk_usage(db_path.resolve().parent).free
    except OSError as e:
        log.warning("Retention: cannot check disk space for VACUUM: %s", e)
        return False
    needed = 2 * size + _VACUUM_FREE_MARGIN_BYTES
    if free < needed:
        log.warning(
            "Retention: skipping the auto_vacuum conversion VACUUM — %.0f MB free, "
            "%.0f MB needed for a %.0f MB database; free some disk space",
            free / 1e6, needed / 1e6, size / 1e6,
        )
        return False
    return True


async def _pragma_int(db, pragma_sql: str) -> int:
    cursor = await db.execute(pragma_sql)
    return int((await cursor.fetchone())[0])


async def ensure_incremental_auto_vacuum() -> bool:
    """Switch the database to auto_vacuum=INCREMENTAL; True if it converted.

    A database created without auto_vacuum can only change mode through a full
    VACUUM, which rewrites the file (temporary disk up to twice the DB size)
    and holds the write lock throughout. Concurrent writers (MQTT ingest, the
    rules engine) wait out busy_timeout and then fail, so the ideal caller is
    startup, before those tasks run (the main.py lifespan does). A no-op once
    the database is in incremental mode; skipped (False, logged) while the
    disk lacks room for the rewrite.
    """
    async with get_db() as db:
        if await _pragma_int(db, "PRAGMA auto_vacuum") == _AUTO_VACUUM_INCREMENTAL:
            return False
        if not _vacuum_has_room():
            return False
        t0 = time.monotonic()
        log.info("Retention: converting database to auto_vacuum=INCREMENTAL (one-time VACUUM)")
        await db.execute("PRAGMA auto_vacuum = INCREMENTAL")
        await db.execute("VACUUM")
        log.info("Retention: auto_vacuum conversion took %.1fs", time.monotonic() - t0)
        return True


async def _vacuum():
    """Return the pages freed by the rollups to the filesystem.

    `PRAGMA incremental_vacuum` does nothing unless the database is in
    auto_vacuum=INCREMENTAL mode. In that mode it runs every night; it yields
    one row per freed page and stops at the first unread row, so it is drained.

    Otherwise, switching modes takes a full VACUUM that stalls every writer
    while it runs (see ensure_incremental_auto_vacuum), which is not worth it
    here for a normal night's churn: SQLite reuses free pages, so the file does
    not grow. The conversion runs from here only when a large share of the
    file is free (e.g. after a big purge), where handing the space back
    justifies a brief ingest stall.
    """
    async with get_db() as db:
        if await _pragma_int(db, "PRAGMA auto_vacuum") == _AUTO_VACUUM_INCREMENTAL:
            cursor = await db.execute("PRAGMA incremental_vacuum")
            await cursor.fetchall()
            return
        free = await _pragma_int(db, "PRAGMA freelist_count")
        total = await _pragma_int(db, "PRAGMA page_count")
    if free < _CONVERT_MIN_FREE_PAGES or free < total * _CONVERT_MIN_FREE_FRACTION:
        log.info(
            "Retention: %d free pages of %d will be reused; database is not in "
            "auto_vacuum=INCREMENTAL mode, skipping the full VACUUM",
            free, total,
        )
        return
    await ensure_incremental_auto_vacuum()
