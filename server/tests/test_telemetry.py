from app.telemetry.service import (
    store_reading,
    store_bulk_readings,
    get_latest,
    get_history,
    SENSOR_FIELDS,
)


async def test_store_and_get_latest():
    await store_reading("node-01", "temp_f", 75.5, 1000.0)
    rows = await get_latest()
    assert len(rows) == 1
    assert rows[0]["node_id"] == "node-01"
    assert rows[0]["sensor"] == "temp_f"
    assert rows[0]["value"] == 75.5


async def test_get_latest_filtered_by_node():
    await store_reading("node-01", "temp_f", 75.0, 1000.0)
    await store_reading("node-02", "temp_f", 80.0, 1000.0)
    rows = await get_latest("node-01")
    assert len(rows) == 1
    assert rows[0]["node_id"] == "node-01"


async def test_store_bulk_readings():
    await store_bulk_readings("node-01", {"temp_f": 75, "humidity": 85, "bogus": 99}, 1000.0)
    rows = await get_latest()
    sensors = {r["sensor"] for r in rows}
    assert "temp_f" in sensors
    assert "humidity" in sensors
    assert "bogus" not in sensors


async def test_get_history_raw():
    for i in range(10):
        await store_reading("node-01", "temp_f", 70.0 + i, 1000.0 + i)
    rows = await get_history("node-01", "temp_f")
    assert len(rows) == 10
    assert rows[0]["timestamp"] < rows[-1]["timestamp"]


async def test_get_history_with_time_range():
    for i in range(10):
        await store_reading("node-01", "temp_f", 70.0, 1000.0 + i)
    rows = await get_history("node-01", "temp_f", from_ts=1003.0, to_ts=1006.0)
    assert len(rows) == 4


async def test_get_history_5min_resolution():
    # Insert readings across two 300s buckets
    for i in range(6):
        await store_reading("node-01", "temp_f", 70.0 + i, float(i * 100))
    # Bucket 0: timestamps 0,100,200 -> values 70,71,72 -> avg 71
    # Bucket 1: timestamps 300,400,500 -> values 73,74,75 -> avg 74
    rows = await get_history("node-01", "temp_f", resolution="5min")
    assert len(rows) == 2
    assert abs(rows[0]["value"] - 71.0) < 0.01
    assert abs(rows[1]["value"] - 74.0) < 0.01


async def test_get_history_hourly_resolution():
    await store_reading("node-01", "temp_f", 70.0, 0.0)
    await store_reading("node-01", "temp_f", 80.0, 3600.0)
    rows = await get_history("node-01", "temp_f", resolution="hourly")
    assert len(rows) == 2


async def test_store_reading_with_session_id():
    await store_reading("node-01", "temp_f", 75.0, 1000.0, session_id=42)
    rows = await get_latest()
    assert len(rows) == 1
