import logging
import math
import time

from ..db import get_db
from ..retention.service import RAW_RETENTION_DAYS, RESOLUTION_BUCKETS

log = logging.getLogger(__name__)

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


_INSERT_READING_SQL = (
    "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) "
    "VALUES (?, ?, ?, ?, ?)"
)

# Frame fields skipped because their value was not a finite number (see
# reading_rows); reported under reliability in GET /api/health/detail/system.
_skipped_value_count = 0


def skipped_value_count() -> int:
    return _skipped_value_count


def _stored_value(value) -> float | None:
    """A reading's stored value, or None when it is not a finite number.

    door_open arrives as a JSON true/false, and telemetry_readings.value is
    REAL NOT NULL, so a bool is stored as 1.0 / 0.0 (the boolean-sensor
    convention integrations/wemo and kasa use for actuator_state). A null
    (ArduinoJson writes a NaN reading, e.g. a dew point from RH 0, as null),
    a NaN, an infinity, a string or an integer too large for a REAL is not a
    reading.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def reading_rows(node_id: str, readings: dict, timestamp: float,
                 session_id: int | None = None) -> list[tuple]:
    """telemetry_readings rows for a frame's SENSOR_FIELDS values.

    A field whose value is not a finite number is skipped, not stored:
    value is REAL NOT NULL, and one such value used to fail the whole
    insert, losing every other reading in the frame with it.
    """
    global _skipped_value_count
    rows = []
    for field in SENSOR_FIELDS:
        if field not in readings:
            continue
        value = _stored_value(readings[field])
        if value is None:
            _skipped_value_count += 1
            log.debug("skipping %s=%r from %s: not a finite number",
                      field, readings[field], node_id)
            continue
        rows.append((timestamp, node_id, field, value, session_id))
    return rows


async def insert_readings(db, rows: list[tuple]) -> None:
    """Insert reading_rows inside the caller's open transaction.

    Under a savepoint: a failed insert (a session deleted under it, say) is
    rolled back on its own and re-raised, and the caller's other writes in
    the transaction still commit.
    """
    if not rows:
        return
    await db.execute("SAVEPOINT readings")
    try:
        await db.executemany(_INSERT_READING_SQL, rows)
    except Exception:
        await db.execute("ROLLBACK TO readings")
        await db.execute("RELEASE readings")
        raise
    await db.execute("RELEASE readings")


async def store_bulk_readings(node_id: str, readings: dict, timestamp: float, session_id: int | None = None):
    rows = reading_rows(node_id, readings, timestamp, session_id)
    if not rows:
        return
    async with get_db() as db:
        await db.executemany(_INSERT_READING_SQL, rows)
        await db.commit()


async def store_readings(rows: list[tuple[float, str, str, float]]) -> int:
    """Store (timestamp, node_id, sensor, value) readings in one transaction.

    For the integration pollers, which read many devices and sensors per poll:
    one connection and one commit for the whole poll, not one per reading.
    A non-finite value is dropped (value is REAL NOT NULL, so a vendor's NaN
    would fail the whole batch). Returns how many rows were written.
    """
    batch = [
        (ts, node_id, sensor, float(value), None)
        for ts, node_id, sensor, value in rows
        if math.isfinite(value)
    ]
    if not batch:
        return 0
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) VALUES (?, ?, ?, ?, ?)",
            batch,
        )
        await db.commit()
    return len(batch)


async def active_session_for_node(node_id: str, ts: float) -> int | None:
    """Id of the active session a reading from `node_id` at `ts` belongs to.

    The per-node session rule the rules engine drives the node's grow by
    (sessions.service.get_active_session_for_node), not counting sessions
    started after `ts` (a replayed reading). A second, stricter copy of the
    rule used to leave a grow the engine managed (a chamberless session on a
    chambered node, a legacy chamber link) with no readings of its own.
    """
    # Late import: sessions.service imports mqtt, which imports this module.
    from ..sessions.service import get_active_session_for_node

    session = await get_active_session_for_node(node_id, before_ts=ts)
    return session["id"] if session else None


# The newest reading of each sensor without a scan of the node's whole raw
# history: the distinct (node, sensor) pairs are walked one index seek at a
# time on idx_telemetry_node_sensor_time, then each pair's newest row is one
# more seek. A GROUP BY with MAX(timestamp) read every raw row (7 days of
# them) on every dashboard load.
_LATEST_PAIRS_ALL = """
    nodes(node_id) AS (
        SELECT MIN(node_id) FROM telemetry_readings
        UNION ALL
        SELECT (SELECT MIN(node_id) FROM telemetry_readings WHERE node_id > nodes.node_id)
          FROM nodes WHERE nodes.node_id IS NOT NULL
    ),
    pairs(node_id, sensor) AS (
        SELECT node_id, (SELECT MIN(sensor) FROM telemetry_readings t
                          WHERE t.node_id = nodes.node_id)
          FROM nodes WHERE nodes.node_id IS NOT NULL
        UNION ALL
        SELECT node_id, (SELECT MIN(sensor) FROM telemetry_readings t
                          WHERE t.node_id = pairs.node_id AND t.sensor > pairs.sensor)
          FROM pairs WHERE pairs.sensor IS NOT NULL
    )
"""
_LATEST_PAIRS_NODE = """
    pairs(node_id, sensor) AS (
        SELECT :node, (SELECT MIN(sensor) FROM telemetry_readings WHERE node_id = :node)
        UNION ALL
        SELECT node_id, (SELECT MIN(sensor) FROM telemetry_readings t
                          WHERE t.node_id = pairs.node_id AND t.sensor > pairs.sensor)
          FROM pairs WHERE pairs.sensor IS NOT NULL
    )
"""
_LATEST_ROWS = """
    SELECT r.node_id, r.sensor, r.value, r.timestamp
      FROM pairs p
      JOIN telemetry_readings r ON r.id = (
            SELECT id FROM telemetry_readings
             WHERE node_id = p.node_id AND sensor = p.sensor
             ORDER BY timestamp DESC LIMIT 1)
     WHERE p.sensor IS NOT NULL
"""


async def latest_node_timestamp(node_id: str) -> float | None:
    """Timestamp of the newest stored reading from `node_id`, or None."""
    async with get_db() as db:
        cursor = await db.execute(
            f"WITH RECURSIVE {_LATEST_PAIRS_NODE} "
            f"SELECT MAX(timestamp) AS ts FROM ({_LATEST_ROWS})",
            {"node": node_id},
        )
        row = await cursor.fetchone()
        return row["ts"] if row else None


async def get_latest(node_id: str | None = None) -> list[dict]:
    """The newest reading of each (node, sensor), for one node or all."""
    pairs = _LATEST_PAIRS_NODE if node_id else _LATEST_PAIRS_ALL
    async with get_db() as db:
        cursor = await db.execute(
            f"WITH RECURSIVE {pairs} {_LATEST_ROWS} ORDER BY r.node_id, r.sensor",
            {"node": node_id} if node_id else {},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

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
    # Re-bucketed at the rollup tiers' own widths (retention owns the tiers).
    bucket = RESOLUTION_BUCKETS.get(resolution)
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
