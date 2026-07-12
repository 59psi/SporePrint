import time

from ..db import get_db
from ..retention.service import RAW_RETENTION_DAYS

SENSOR_FIELDS = [
    "temp_f", "temp_c", "humidity", "co2_ppm", "lux", "dew_point_f",
    # v4.2 sensor-completeness: HX711 load-cell weight + reed-switch door
    # state, both already on the wire (firmware/src/node/main.cpp), just
    # never persisted to telemetry history until now.
    "weight_g", "door_open",
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


async def get_history(
    node_id: str,
    sensor: str,
    from_ts: float | None = None,
    to_ts: float | None = None,
    resolution: str | None = None,
) -> list[dict]:
    params: list = [node_id, sensor]
    time_filters = ""
    if from_ts:
        time_filters += " AND timestamp >= ?"
        params.append(from_ts)
    if to_ts:
        time_filters += " AND timestamp <= ?"
        params.append(to_ts)

    bucket = _RESOLUTION_BUCKETS.get(resolution)

    async with get_db() as db:
        # Query raw telemetry first
        if bucket:
            query = f"""
                SELECT CAST(timestamp / {bucket} AS INT) * {bucket} as timestamp, AVG(value) as value
                FROM telemetry_readings WHERE node_id = ? AND sensor = ?{time_filters}
                GROUP BY CAST(timestamp / {bucket} AS INT)
                ORDER BY timestamp
            """
        else:
            query = f"SELECT timestamp, value FROM telemetry_readings WHERE node_id = ? AND sensor = ?{time_filters} ORDER BY timestamp"

        cursor = await db.execute(query, params)
        results = [dict(r) for r in await cursor.fetchall()]

        # Supplement with rollups for older data that's been compressed
        raw_cutoff = time.time() - RAW_RETENTION_DAYS * 86400
        if from_ts is not None and from_ts < raw_cutoff:
            rollup_resolution = resolution or "hourly"
            rollup_params: list = [node_id, sensor, rollup_resolution]
            rollup_filters = " AND timestamp >= ?"
            rollup_params.append(from_ts)
            rollup_filters += " AND timestamp < ?"
            rollup_params.append(raw_cutoff)

            cursor = await db.execute(
                f"SELECT timestamp, avg_value as value FROM telemetry_rollups "
                f"WHERE node_id = ? AND sensor = ? AND resolution = ?{rollup_filters} "
                f"ORDER BY timestamp",
                rollup_params,
            )
            rollup_rows = [dict(r) for r in await cursor.fetchall()]
            # Prepend rollup data before raw data
            results = rollup_rows + results

        return results
