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


async def test_a_channel_report_is_an_actuator_event_not_a_reading():
    """Stored as the actuator event its columns mirror, sent to clients as
    actuator state, and never a sensor reading: no telemetry row, no
    telemetry event, no rule evaluation."""
    sio = AsyncMock()
    with patch("app.automation.engine.evaluate_rules", new=AsyncMock()) as rules:
        await _handle_message(
            sio,
            "sporeprint/relay-01/telemetry/exhaust",
            {"channel": "exhaust", "state": "on", "pwm": 255, "trigger": "command"},
        )
    rules.assert_not_awaited()

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT node_id, channel, action, value, trigger FROM actuator_events"
        )
        events = [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute("SELECT COUNT(*) AS n FROM telemetry_readings")
        readings = (await cursor.fetchone())["n"]
    assert events == [{"node_id": "relay-01", "channel": "exhaust", "action": "on",
                       "value": 255, "trigger": "command"}]
    assert readings == 0
    event_names = [c.args[0] for c in sio.emit.await_args_list]
    assert "actuator_state" in event_names
    assert "telemetry" not in event_names


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
