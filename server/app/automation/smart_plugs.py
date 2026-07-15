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


async def is_plug_target(target: str) -> bool:
    """Is this automation target a smart plug rather than an ESP32 node?

    Plugs are reached over the vendor's own topic tree, never `sporeprint/*`,
    so the engine has to know which transport a target wants before publishing.
    This is a TRANSPORT question — the `plug-` prefix is enough to answer it,
    whether or not the plug has actually been paired yet.
    """
    if target.startswith("plug-"):
        return True
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM smart_plugs WHERE plug_id = ?", (target,)
        )
        return await cursor.fetchone() is not None


async def target_is_present(target: str) -> bool:
    """Is this actuator ACTUALLY paired to this chamber right now?

    Distinct from is_plug_target, which answers "how would I reach it" by naming
    convention. This answers "is it really there" — a registered smart_plugs row
    (by id or device_role), or a node channel the firmware has reported in its
    health doc. Used for capability-aware fallbacks (vent when no dehumidifier).
    """
    async with get_db() as db:
        # Smart plug: a real row, matched by id or by assigned role
        # (plug-dehumidifier ⇢ device_role 'dehumidifier').
        role = target[len("plug-"):] if target.startswith("plug-") else None
        cursor = await db.execute(
            "SELECT 1 FROM smart_plugs WHERE plug_id = ? OR device_role = ? LIMIT 1",
            (target, role),
        )
        if await cursor.fetchone() is not None:
            return True
        # Node channel: does any node report a channel by this name?
        cursor = await db.execute(
            "SELECT channels FROM hardware_nodes WHERE channels IS NOT NULL"
        )
        for row in await cursor.fetchall():
            try:
                if target in json.loads(row["channels"]):
                    return True
            except (json.JSONDecodeError, TypeError):
                continue
    return False


async def send_plug_command(plug_id: str, state: str) -> bool:
    """Send an on/off command to a smart plug. True if it reached the broker.

    Shelly and Tasmota both expect a BARE payload (`on` / `ON`), not JSON.
    `mqtt_publish` json.dumps() everything it is given, so the registered-plug
    path was putting `"on"` — with quotes — on the wire, which neither firmware
    accepts. (The unregistered fallback published raw and was correct, which is
    what gave the bug away.) Publish raw on every path.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT plug_type, mqtt_topic_prefix FROM smart_plugs WHERE plug_id = ?",
            (plug_id,),
        )
        row = await cursor.fetchone()

    if not row:
        # Unregistered: infer from the plug-<shelly_device_id> convention.
        device_id = plug_id.replace("plug-", "", 1)
        return await _publish_raw(f"shellies/{device_id}/relay/0/command", state.lower())

    prefix = row["mqtt_topic_prefix"]
    if row["plug_type"] == "shelly":
        return await _publish_raw(f"{prefix}/relay/0/command", state.lower())
    if row["plug_type"] == "tasmota":
        return await _publish_raw(f"{prefix}/cmnd/POWER", state.upper())

    log.warning("Unknown plug_type %r for plug %s", row["plug_type"], plug_id)
    return False


async def _publish_raw(topic: str, payload: str) -> bool:
    """Publish an unencoded payload — vendor plugs want bare text, not JSON."""
    from ..mqtt import _client

    if _client is None:
        return False
    await _client.publish(topic, payload)
    return True


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
