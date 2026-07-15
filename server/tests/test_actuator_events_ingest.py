"""Relay switch-state reports must be persisted, not funnelled into the void.

The firmware publishes `telemetry/<channel>` — `{channel, state, pwm, trigger}`
on every command, safety cutoff, and 60s cadence. These frames used to fall
into the sensor-telemetry path, where store_bulk_readings stored nothing (no
key overlaps SENSOR_FIELDS): the actuator_events table, whose columns mirror
this doc exactly, had no writer anywhere and Grafana's actuator_event_count
was permanently zero.
"""

from unittest.mock import AsyncMock, patch

from app.db import get_db
from app.mqtt import _handle_message


async def test_channel_report_writes_actuator_event():
    await _handle_message(
        AsyncMock(),
        "sporeprint/relay-01/telemetry/exhaust",
        {"channel": "exhaust", "state": "on", "pwm": 255, "trigger": "command"},
    )

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT node_id, channel, action, value, trigger FROM actuator_events"
        )
        row = await cursor.fetchone()

    assert row is not None, "no actuator_events row written"
    assert row["node_id"] == "relay-01"
    assert row["channel"] == "exhaust"
    assert row["action"] == "on"
    assert row["value"] == 255
    assert row["trigger"] == "command"


async def test_channel_report_emits_actuator_state_not_telemetry():
    """The frame is actuator state, not a sensor reading — clients get it on
    its own event, and it must not run the automation engine."""
    sio = AsyncMock()
    with patch("app.automation.engine.evaluate_rules", new=AsyncMock()) as rules:
        await _handle_message(
            sio,
            "sporeprint/relay-01/telemetry/fae",
            {"channel": "fae", "state": "off", "pwm": 0, "trigger": "safety_cutoff"},
        )
        rules.assert_not_awaited()

    event_names = [c.args[0] for c in sio.emit.await_args_list]
    assert "actuator_state" in event_names
    assert "telemetry" not in event_names


async def test_channel_report_does_not_pollute_readings():
    await _handle_message(
        AsyncMock(),
        "sporeprint/relay-01/telemetry/aux",
        {"channel": "aux", "state": "on", "pwm": 255, "trigger": "command"},
    )
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS n FROM telemetry_readings")
        assert (await cursor.fetchone())["n"] == 0


async def test_heartbeat_persists_reset_reason_and_reconnects():
    """reset_reason is the panic-loop tell — a node stuck in a WDT reboot
    cycle looks 'online' on every other signal."""
    await _handle_message(
        AsyncMock(),
        "sporeprint/climate-01/status/heartbeat",
        {
            "type": "climate",
            "firmware_version": "2.0.0",
            "ip": "10.0.0.31",
            "uptime_sec": 12,
            "reset_reason": 7,
            "mqtt_reconnects": 3,
        },
    )
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT reset_reason, mqtt_reconnects FROM hardware_nodes WHERE node_id = 'climate-01'"
        )
        row = await cursor.fetchone()
    assert row["reset_reason"] == 7
    assert row["mqtt_reconnects"] == 3
