"""Retention math and storage reclamation.

srv-rest#23: the hourly and daily rollups used AVG(avg_value), an unweighted
mean of means, while the 5-minute step and the conflict-merge path are
count-weighted. Buckets with unequal counts (partial buckets, offline-buffer
flushes, a changed publish interval) biased long-term history.

srv-rest#24: `PRAGMA incremental_vacuum` is a no-op unless the database is in
auto_vacuum=INCREMENTAL mode, which init_db never sets, and even then a single
execute frees only one page. The nightly "reclaim storage" step did nothing.
Switching modes takes a full VACUUM that stalls every writer, so the nightly
job only does it when a large share of the file is free.
"""

import time

from app.db import get_db
from app.retention.service import (
    _cleanup_old_rollups,
    _rollup_telemetry_hourly,
    _vacuum,
    ensure_incremental_auto_vacuum,
)

DAY = 86400


async def _rollup(resolution, ts, avg, count, node="n1", sensor="temp_f"):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, "
            "avg_value, min_value, max_value, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, node, sensor, resolution, avg, avg, avg, count),
        )
        await db.commit()


async def _only_row(resolution):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM telemetry_rollups WHERE resolution = ?", (resolution,)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    assert len(rows) == 1, rows
    return rows[0]


async def test_hourly_rollup_is_count_weighted():
    hour = int((time.time() - 40 * DAY) // 3600) * 3600
    # One partial bucket (1 reading at 90) + eleven full buckets (5 at 70).
    await _rollup("5min", hour, 90.0, 1)
    for i in range(1, 12):
        await _rollup("5min", hour + i * 300, 70.0, 5)

    await _rollup_telemetry_hourly()

    row = await _only_row("hourly")
    assert row["count"] == 56
    assert abs(row["avg_value"] - (90.0 + 70.0 * 55) / 56) < 1e-9  # 70.357, not 71.67
    assert row["min_value"] == 70.0 and row["max_value"] == 90.0


async def test_daily_rollup_is_count_weighted():
    day = int((time.time() - 400 * DAY) // DAY) * DAY
    await _rollup("hourly", day, 90.0, 1)
    await _rollup("hourly", day + 3600, 70.0, 59)

    await _cleanup_old_rollups()

    row = await _only_row("daily")
    assert row["count"] == 60
    assert abs(row["avg_value"] - (90.0 + 70.0 * 59) / 60) < 1e-9


async def test_rollup_with_null_counts_falls_back_to_plain_mean():
    """Legacy rows without a count must not collapse the average to NULL."""
    hour = int((time.time() - 40 * DAY) // 3600) * 3600
    await _rollup("5min", hour, 80.0, None)
    await _rollup("5min", hour + 300, 60.0, None)

    await _rollup_telemetry_hourly()

    row = await _only_row("hourly")
    assert row["avg_value"] == 70.0


async def _pragma(name):
    async with get_db() as db:
        cursor = await db.execute(f"PRAGMA {name}")
        return (await cursor.fetchone())[0]


async def _bloat_and_delete():
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            [(1000.0 + i, "n1", "x" * 200, float(i)) for i in range(4000)],
        )
        await db.commit()
        await db.execute("DELETE FROM telemetry_readings")
        await db.commit()


async def test_vacuum_actually_reclaims_free_pages():
    # A pre-upgrade DB after a big purge: most of the file is free pages, so
    # the nightly job converts it (one full VACUUM) and hands the space back.
    await _force_no_auto_vacuum()
    await _bloat_and_delete()
    assert await _pragma("freelist_count") > 0

    await _vacuum()

    assert await _pragma("freelist_count") == 0
    # The DB is now in incremental mode, so later nightly runs are cheap.
    assert await _pragma("auto_vacuum") == 2


async def _force_no_auto_vacuum():
    """Put the (tiny) test DB in auto_vacuum=NONE, like a pre-upgrade install."""
    async with get_db() as db:
        await db.execute("PRAGMA auto_vacuum = NONE")
        await db.execute("VACUUM")
    assert await _pragma("auto_vacuum") == 0


async def test_vacuum_second_run_uses_incremental_mode():
    await _force_no_auto_vacuum()
    assert await ensure_incremental_auto_vacuum() is True  # one-time conversion
    assert await _pragma("auto_vacuum") == 2
    assert await ensure_incremental_auto_vacuum() is False  # idempotent

    await _bloat_and_delete()
    assert await _pragma("freelist_count") > 0
    await _vacuum()
    assert await _pragma("freelist_count") == 0


async def test_nightly_vacuum_skips_mode_switch_for_small_freelist():
    """The full VACUUM stalls every writer; a normal night's churn isn't worth it."""
    await _force_no_auto_vacuum()
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            [(1000.0 + i, "n1", "x" * 200, float(i)) for i in range(4000)],
        )
        await db.commit()
        # Free well under a quarter of the file.
        await db.execute("DELETE FROM telemetry_readings WHERE timestamp < 1200")
        await db.commit()
    free_before = await _pragma("freelist_count")
    assert free_before > 0

    await _vacuum()

    assert await _pragma("auto_vacuum") == 0  # no VACUUM ran
    assert await _pragma("freelist_count") == free_before
