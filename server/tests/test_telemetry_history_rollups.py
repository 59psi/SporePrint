"""get_history must fall through to whichever rollup tier holds old data.

Retention keeps raw rows for 7 days, 5-minute rollups for 7-30 days, hourly
rollups for 30-365 days and daily rollups beyond that. The old fallthrough
queried a single tier (`resolution or "hourly"`), so a 30-day chart lost days
8-30 (no daily rollups exist for the last year), and an unbucketed query lost
the whole 5-minute tier.
"""

import math
import time

from app.db import get_db
from app.retention.service import _rollup_telemetry_5min, _rollup_telemetry_hourly
from app.telemetry.service import _HISTORY_BUCKETED_SQL, _HISTORY_NATIVE_SQL, get_history

DAY = 86400


async def _raw(node, sensor, value, ts):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            (ts, node, sensor, value),
        )
        await db.commit()


async def _rollup(node, sensor, resolution, ts, avg, count, mn=None, mx=None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, "
            "avg_value, min_value, max_value, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, node, sensor, resolution, avg,
             avg if mn is None else mn, avg if mx is None else mx, count),
        )
        await db.commit()


def _bucket(ts, size):
    return int(ts // size) * size


async def test_daily_chart_includes_5min_and_hourly_tiers():
    now = time.time()
    d10 = _bucket(now - 10 * DAY, 300)   # 5-min tier
    d40 = _bucket(now - 40 * DAY, 3600)  # hourly tier
    await _rollup("n1", "temp_f", "5min", d10, 70.0, 5)
    await _rollup("n1", "temp_f", "hourly", d40, 60.0, 60)
    await _raw("n1", "temp_f", 80.0, now - 60)

    rows = await get_history("n1", "temp_f", from_ts=now - 60 * DAY, to_ts=now,
                             resolution="daily")
    values = sorted(round(r["value"], 1) for r in rows)
    assert values == [60.0, 70.0, 80.0]


async def test_unbucketed_query_includes_every_tier():
    now = time.time()
    await _rollup("n1", "temp_f", "5min", _bucket(now - 10 * DAY, 300), 70.0, 5)
    await _rollup("n1", "temp_f", "hourly", _bucket(now - 40 * DAY, 3600), 60.0, 60)
    await _raw("n1", "temp_f", 80.0, now - 60)

    rows = await get_history("n1", "temp_f", from_ts=now - 60 * DAY, to_ts=now)
    assert [r["value"] for r in rows] == [60.0, 70.0, 80.0]
    assert rows == sorted(rows, key=lambda r: r["timestamp"])


async def test_hourly_request_rebuckets_5min_rollups_weighted():
    now = time.time()
    hour = _bucket(now - 10 * DAY, 3600)
    # Two 5-min buckets in the same hour with unequal counts.
    await _rollup("n1", "temp_f", "5min", hour, 90.0, 1)
    await _rollup("n1", "temp_f", "5min", hour + 300, 70.0, 9)

    rows = await get_history("n1", "temp_f", from_ts=hour - 1, to_ts=hour + 3599,
                             resolution="hourly")
    assert len(rows) == 1
    assert rows[0]["timestamp"] == hour
    assert abs(rows[0]["value"] - 72.0) < 1e-6  # (90*1 + 70*9) / 10


async def test_bucket_straddling_raw_and_rollup_is_merged():
    """A bucket that is part raw, part rolled-up returns ONE point."""
    now = time.time()
    day = _bucket(now - 8 * DAY, DAY)
    await _rollup("n1", "temp_f", "5min", day + 600, 60.0, 4)
    await _raw("n1", "temp_f", 80.0, day + DAY - 10)

    rows = await get_history("n1", "temp_f", from_ts=day, to_ts=day + DAY - 1,
                             resolution="daily")
    assert len(rows) == 1
    assert abs(rows[0]["value"] - 64.0) < 1e-6  # (60*4 + 80*1) / 5


async def test_history_survives_a_real_retention_run():
    """End to end: data rolled 5min -> hourly by retention is still charted."""
    now = time.time()
    # 01:02 UTC on a day 35 days back: the 12 one-minute readings land in
    # three 5-min buckets of unequal size (3, 5, 4) within one hour and day.
    old = _bucket(now - 35 * DAY, DAY) + 3600 + 120
    for i in range(12):
        await _raw("n1", "humidity", 80.0 + (i % 2), old + i * 60)
    await _rollup_telemetry_5min()
    await _rollup_telemetry_hourly()

    rows = await get_history("n1", "humidity", from_ts=now - 40 * DAY, to_ts=now,
                             resolution="daily")
    assert len(rows) == 1
    assert abs(rows[0]["value"] - 80.5) < 1e-6


async def test_other_nodes_and_sensors_excluded():
    now = time.time()
    await _rollup("n1", "temp_f", "5min", _bucket(now - 10 * DAY, 300), 70.0, 5)
    await _rollup("n2", "temp_f", "5min", _bucket(now - 10 * DAY, 300), 99.0, 5)
    await _rollup("n1", "humidity", "5min", _bucket(now - 10 * DAY, 300), 50.0, 5)
    rows = await get_history("n1", "temp_f", from_ts=now - 20 * DAY, to_ts=now)
    assert [r["value"] for r in rows] == [70.0]


async def test_open_bounds_return_everything():
    now = time.time()
    await _rollup("n1", "temp_f", "hourly", _bucket(now - 40 * DAY, 3600), 60.0, 60)
    await _raw("n1", "temp_f", 80.0, now - 60)
    rows = await get_history("n1", "temp_f")
    assert [r["value"] for r in rows] == [60.0, 80.0]


async def test_history_window_uses_indexes_not_table_scans():
    """The time bounds must stay sargable: a chart is served on every page load."""
    params = {"node": "n1", "sensor": "temp_f", "from_ts": time.time() - 30 * DAY,
              "to_ts": math.inf, "rollups": 1, "bucket": 86400}
    async with get_db() as db:
        for sql in (_HISTORY_NATIVE_SQL, _HISTORY_BUCKETED_SQL):
            cursor = await db.execute("EXPLAIN QUERY PLAN " + sql, params)
            plan = " | ".join(r["detail"] for r in await cursor.fetchall())
            assert "SCAN telemetry_readings" not in plan, plan
            assert "SCAN telemetry_rollups" not in plan, plan
            assert "timestamp>?" in plan, plan
