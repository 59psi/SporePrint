"""Which frame fields become readings, and raw history windows and buckets.
(The rollup tiers are in test_telemetry_history_rollups.py.)"""

import pytest

from app.telemetry.service import (
    get_history,
    get_latest,
    store_bulk_readings,
    store_reading,
)


async def test_every_sensor_field_is_stored_and_nothing_else():
    """The firmware's sensor keys are stored as readings (a door state as
    1.0 / 0.0, telemetry_readings.value being REAL); other keys are not. A
    sensor key dropped from SENSOR_FIELDS (weight_g, door_open and
    pressure_hpa each shipped unstored once) fails here."""
    await store_bulk_readings("node-01", {
        "temp_f": 75.0, "temp_c": 23.9, "humidity": 85.0, "co2_ppm": 900, "lux": 120.5,
        "dew_point_f": 70.1, "weight_g": 482.5, "door_open": True, "pressure_hpa": 1006.5,
        "bogus": 99,
    }, 1000.0)
    await store_bulk_readings("node-02", {"door_open": False}, 1000.0)
    await store_bulk_readings("node-03", {"bogus": 1, "rssi": -60}, 1000.0)
    latest = {(r["node_id"], r["sensor"]): r["value"] for r in await get_latest()}
    assert latest == {
        ("node-01", "temp_f"): 75.0, ("node-01", "temp_c"): 23.9,
        ("node-01", "humidity"): 85.0, ("node-01", "co2_ppm"): 900.0,
        ("node-01", "lux"): 120.5, ("node-01", "dew_point_f"): 70.1,
        ("node-01", "weight_g"): 482.5, ("node-01", "door_open"): 1.0,
        ("node-01", "pressure_hpa"): 1006.5,
        ("node-02", "door_open"): 0.0,
    }


async def test_a_history_window_is_inclusive_and_oldest_first():
    for i in reversed(range(10)):
        await store_reading("node-01", "temp_f", 70.0 + i, 1000.0 + i)
    rows = await get_history("node-01", "temp_f", from_ts=1003.0, to_ts=1006.0)
    assert [(r["timestamp"], r["value"]) for r in rows] == [
        (1003.0, 73.0), (1004.0, 74.0), (1005.0, 75.0), (1006.0, 76.0)]


@pytest.mark.parametrize("resolution,points", [
    # 0,100,200 -> 70,71,72 and 300,400,500 -> 73,74,75
    ("5min", [(0, 71.0), (300, 74.0)]),
    ("hourly", [(0, 72.5)]),
])
async def test_history_averages_raw_readings_into_resolution_buckets(resolution, points):
    for i in range(6):
        await store_reading("node-01", "temp_f", 70.0 + i, float(i * 100))
    rows = await get_history("node-01", "temp_f", resolution=resolution)
    assert [(r["timestamp"], pytest.approx(r["value"])) for r in rows] == points
