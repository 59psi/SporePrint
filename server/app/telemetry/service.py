import math
import time

from ..db import get_db
from ..retention.service import RAW_RETENTION_DAYS

SENSOR_FIELDS = [
    "temp_f", "temp_c", "humidity", "co2_ppm", "lux", "dew_point_f",
    # v4.2 sensor-completeness: HX711 load-cell weight + reed-switch door
    # state, both already on the wire (firmware/src/node/main.cpp), just
    # never persisted to telemetry history until now.
    "weight_g", "door_open",
    # Barometric pressure (hPa) from a BME280 / BMP280 on a climate node —
    # firmware sp_drivers/bme280.cpp, emitted only when one is fitted.
    "pressure_hpa",
]


async def store_reading(node_id: str, sensor: str, value: float, timestamp: float, session_id: int | None = None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) VALUES (?, ?, ?, ?, ?)",
            (timestamp, node_id, sensor, value, session_id),
        )
        await db.commit()


async def store_bulk_readings(node_id: str, readings: dict, timestamp: float, session_id: int | None = None):
    rows = []
    for field in SENSOR_FIELDS:
        if field in readings:
            value = readings[field]
            if isinstance(value, bool):
                # door_open arrives as a JSON true/false over MQTT, but
                # telemetry_readings.value is REAL NOT NULL. Store the
                # established boolean-sensor convention (see
                # integrations/wemo/driver.py and integrations/kasa/driver.py,
                # which store actuator_state as float(state) the same way).
                value = 1.0 if value else 0.0
            rows.append((timestamp, node_id, field, value, session_id))
    if not rows:
        return
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()


# The grow a node's reading belongs to. Chambered sessions can run side by
# side, so this is resolved per node, never "the newest active session":
#   * a node listed in a chamber belongs only to that chamber's active session
#     (never to another chamber's, nor to a chamberless one);
#   * a node in no chamber belongs to the newest active chamberless session
#     (the single-closet default, where no chambers exist at all).
# Sessions that started after the reading (a replayed frame) don't claim it.
# A chamber whose node_ids isn't valid JSON lists no nodes.
_NODE_SESSION_SQL = """
    WITH node_chambers AS (
        SELECT c.id FROM chambers c,
               json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j
         WHERE j.value = :node
    )
    SELECT s.id FROM sessions s
     WHERE s.status = 'active'
       AND COALESCE(s.created_at, 0) <= :ts
       AND CASE WHEN EXISTS (SELECT 1 FROM node_chambers)
                THEN s.chamber_id IN (SELECT id FROM node_chambers)
                ELSE s.chamber_id IS NULL
                     OR s.chamber_id NOT IN (SELECT id FROM chambers)
           END
     ORDER BY s.created_at DESC, s.id DESC
     LIMIT 1
"""


async def active_session_for_node(node_id: str, ts: float) -> int | None:
    """Id of the active session a reading from `node_id` at `ts` belongs to."""
    async with get_db() as db:
        cursor = await db.execute(_NODE_SESSION_SQL, {"node": node_id, "ts": ts})
        row = await cursor.fetchone()
        return row["id"] if row else None


async def latest_node_timestamp(node_id: str) -> float | None:
    """Timestamp of the newest stored reading from `node_id`, or None."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT MAX(timestamp) AS ts FROM telemetry_readings WHERE node_id = ?",
            (node_id,),
        )
        row = await cursor.fetchone()
        return row["ts"] if row else None


async def get_latest(node_id: str | None = None) -> list[dict]:
    query = """
        SELECT node_id, sensor, value, MAX(timestamp) as timestamp
        FROM telemetry_readings
    """
    params = []
    if node_id:
        query += " WHERE node_id = ?"
        params.append(node_id)
    query += " GROUP BY node_id, sensor"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


_RESOLUTION_BUCKETS = {"5min": 300, "hourly": 3600, "daily": 86400}

# Open bounds are passed as 0 / +inf rather than NULL-guarded, so the range
# stays sargable (the (sensor, timestamp) and (timestamp, ...) indexes).
_HISTORY_WINDOW = (
    "node_id = :node AND sensor = :sensor"
    " AND timestamp >= :from_ts AND timestamp <= :to_ts"
)

# Raw points plus rollup rows at their native tier resolution.
_HISTORY_NATIVE_SQL = f"""
    SELECT timestamp, value FROM telemetry_readings WHERE {_HISTORY_WINDOW}
    UNION ALL
    SELECT timestamp, avg_value AS value FROM telemetry_rollups
     WHERE :rollups AND avg_value IS NOT NULL AND {_HISTORY_WINDOW}
    ORDER BY timestamp
"""

# Raw rows and rollup rows re-bucketed together, count-weighted.
_HISTORY_BUCKETED_SQL = f"""
    SELECT CAST(ts / :bucket AS INT) * :bucket AS timestamp,
           SUM(total) / NULLIF(SUM(n), 0) AS value
    FROM (
        SELECT timestamp AS ts, value AS total, 1 AS n
          FROM telemetry_readings WHERE {_HISTORY_WINDOW}
        UNION ALL
        SELECT timestamp, avg_value * COALESCE(count, 1), COALESCE(count, 1)
          FROM telemetry_rollups
         WHERE :rollups AND avg_value IS NOT NULL AND {_HISTORY_WINDOW}
    )
    GROUP BY CAST(ts / :bucket AS INT)
    ORDER BY timestamp
"""


async def get_history(
    node_id: str,
    sensor: str,
    from_ts: float | None = None,
    to_ts: float | None = None,
    resolution: str | None = None,
) -> list[dict]:
    """Time series for one node + sensor, raw and rolled-up.

    Retention MOVES each reading down the tiers (raw for 7 days, 5-min rollups
    to 30 days, hourly to a year, daily after that), so every reading lives in
    exactly one table/tier at a time. When the window reaches past the raw
    cutoff, all rollup tiers are merged in without any double counting.

    With a known `resolution`, raw rows and rollup rows are re-bucketed
    together using a count-weighted average (a bucket that is part raw, part
    rolled-up comes back as one point). Without one, raw points and rollup rows
    are returned at their native resolution, oldest first.
    """
    raw_cutoff = time.time() - RAW_RETENTION_DAYS * 86400
    bucket = _RESOLUTION_BUCKETS.get(resolution)
    params = {
        "node": node_id,
        "sensor": sensor,
        "from_ts": from_ts or 0.0,
        "to_ts": to_ts or math.inf,
        # Rollups only hold data older than the raw window; skip that half of
        # the query when the window can't reach it.
        "rollups": 1 if (not from_ts or from_ts < raw_cutoff) else 0,
        "bucket": bucket,
    }
    query = _HISTORY_BUCKETED_SQL if bucket else _HISTORY_NATIVE_SQL

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
