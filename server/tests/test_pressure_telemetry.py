"""Barometric pressure on the telemetry wire (firmware BME280 / BMP280 driver).

The unified node publishes ``pressure_hpa`` (hPa = mbar, one decimal) when a
BME280 or BMP280 is on its I2C bus (firmware/lib/sp_drivers/bme280.cpp, wired
in firmware/src/node/main.cpp). The key is additive: older nodes never send
it, and the Pi must persist it like every other sensor field rather than
silently dropping it (test_firmware_wire_contract pins "nothing emitted is
dropped" in general; this pins the concrete value path end to end).
"""

import time

import pytest

from app.mqtt import _handle_message
from app.telemetry.service import SENSOR_FIELDS, get_latest, store_bulk_readings


class _Sio:
    async def emit(self, event, data):
        return None


@pytest.fixture()
def quiet_ingest(monkeypatch):
    async def _no_rules(node_id, readings, sio=None):
        return None

    async def _no_forward(node_id, payload):
        return None

    monkeypatch.setattr("app.automation.engine.evaluate_rules", _no_rules)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _no_forward)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)


def test_pressure_is_a_persisted_sensor_field():
    assert "pressure_hpa" in SENSOR_FIELDS


async def test_store_bulk_readings_pressure_hpa():
    await store_bulk_readings("climate-01", {"pressure_hpa": 1006.5}, 1000.0)
    rows = await get_latest()
    assert len(rows) == 1
    assert rows[0]["sensor"] == "pressure_hpa"
    assert rows[0]["value"] == 1006.5


async def test_node_frame_with_pressure_is_persisted(quiet_ingest):
    # A climate node with an SHT31-D + BME280: temp/RH from the SHT, pressure
    # from the BME280, all on one frame.
    await _handle_message(
        _Sio(), "sporeprint/climate-01/telemetry",
        {"ts": time.time(), "temp_f": 72.1, "temp_c": 22.3, "humidity": 91.0,
         "dew_point_f": 69.4, "pressure_hpa": 1012.4},
    )
    latest = {r["sensor"]: r["value"] for r in await get_latest("climate-01")}
    assert latest["pressure_hpa"] == 1012.4
    assert latest["humidity"] == 91.0


async def test_frame_without_pressure_is_unchanged(quiet_ingest):
    # Every node without a BMx280 (and every pre-driver firmware) omits the
    # key — nothing is stored for it, nothing else changes.
    await _handle_message(
        _Sio(), "sporeprint/climate-02/telemetry",
        {"ts": time.time(), "temp_f": 70.0},
    )
    sensors = {r["sensor"] for r in await get_latest("climate-02")}
    assert sensors == {"temp_f"}
