"""Smart plug integration for Shelly and Tasmota MQTT devices.

Provides unified control interface for binary on/off devices:
- Humidifier, Dehumidifier, Space Heater, Peltier Cooler

Shelly topics:  shellies/<device_id>/relay/0 → "on"/"off"
                shellies/<device_id>/relay/0/command ← "on"/"off"
                shellies/<device_id>/relay/0/power → watts

Tasmota topics: tasmota/<device_id>/stat/POWER → "ON"/"OFF"
                tasmota/<device_id>/cmnd/POWER ← "ON"/"OFF"
                tasmota/<device_id>/tele/SENSOR → JSON with energy
"""

import json
import logging
import time

from ..db import get_db
from ..mqtt import mqtt_publish

log = logging.getLogger(__name__)


async def handle_plug_message(sio, topic: str, payload):
    """Route incoming Shelly/Tasmota MQTT messages."""
    parts = topic.split("/")

    if topic.startswith("shellies/") and len(parts) >= 4:
        device_id = parts[1]
        plug_id = f"plug-{device_id}"

        if parts[2] == "relay" and parts[3] == "0":
            if len(parts) == 4:
                # State report: "on" or "off"
                state = payload if isinstance(payload, str) else str(payload)
                await _update_plug_state(plug_id, "shelly", device_id, state.lower())
                await sio.emit("plug_state", {"plug_id": plug_id, "state": state.lower()})

        if len(parts) == 5 and parts[4] == "power":
            # Power report
            power = float(payload) if not isinstance(payload, dict) else 0
            await _update_plug_power(plug_id, power)

    elif topic.startswith("tasmota/") and len(parts) >= 4:
        device_id = parts[1]
        plug_id = f"plug-{device_id}"

        if parts[2] == "stat" and parts[3] == "POWER":
            state = payload if isinstance(payload, str) else str(payload)
            await _update_plug_state(plug_id, "tasmota", device_id, state.lower())
            await sio.emit("plug_state", {"plug_id": plug_id, "state": state.lower()})

        elif parts[2] == "tele" and parts[3] == "SENSOR":
            if isinstance(payload, dict) and "ENERGY" in payload:
                power = payload["ENERGY"].get("Power", 0)
                await _update_plug_power(plug_id, power)


async def send_plug_command(plug_id: str, state: str):
    """Send on/off command to a smart plug."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT plug_type, mqtt_topic_prefix FROM smart_plugs WHERE plug_id = ?",
            (plug_id,),
        )
        row = await cursor.fetchone()

    if not row:
        # Try to infer from plug_id convention: plug-<shelly_device_id>
        device_id = plug_id.replace("plug-", "", 1)
        # Default to Shelly
        await _send_shelly_command(device_id, state)
        return

    plug_type = row["plug_type"]
    prefix = row["mqtt_topic_prefix"]

    if plug_type == "shelly":
        topic = f"{prefix}/relay/0/command"
        await mqtt_publish(topic, state)  # Shelly wants plain string, not JSON
    elif plug_type == "tasmota":
        topic = f"{prefix}/cmnd/POWER"
        await mqtt_publish(topic, state.upper())


async def _send_shelly_command(device_id: str, state: str):
    topic = f"shellies/{device_id}/relay/0/command"
    # Shelly expects plain text, but our mqtt_publish sends JSON
    # For smart plugs, we publish raw
    from ..mqtt import _client
    if _client:
        await _client.publish(topic, state.lower())


async def register_plug(
    plug_id: str,
    name: str,
    plug_type: str,
    mqtt_topic_prefix: str,
    device_role: str | None = None,
):
    """Register a smart plug in the database."""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, device_role)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(plug_id) DO UPDATE SET
                 name=excluded.name, plug_type=excluded.plug_type,
                 mqtt_topic_prefix=excluded.mqtt_topic_prefix,
                 device_role=excluded.device_role""",
            (plug_id, name, plug_type, mqtt_topic_prefix, device_role),
        )
        await db.commit()


async def get_all_plugs() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM smart_plugs ORDER BY name")
        return [dict(r) for r in await cursor.fetchall()]


async def _update_plug_state(plug_id: str, plug_type: str, device_id: str, state: str):
    prefix = f"shellies/{device_id}" if plug_type == "shelly" else f"tasmota/{device_id}"
    async with get_db() as db:
        await db.execute(
            """INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, last_state, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(plug_id) DO UPDATE SET
                 last_state=excluded.last_state, last_seen=excluded.last_seen""",
            (plug_id, device_id, plug_type, prefix, state, time.time()),
        )
        await db.commit()


async def _update_plug_power(plug_id: str, power: float):
    async with get_db() as db:
        await db.execute(
            "UPDATE smart_plugs SET last_power_w = ?, last_seen = ? WHERE plug_id = ?",
            (power, time.time(), plug_id),
        )
        await db.commit()
