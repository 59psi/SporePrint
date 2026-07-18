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
    """Send an on/off command to a smart plug. True only when it was delivered
    to a PAIRED plug; an unpaired plug is a reported no-op (False).

    Shelly and Tasmota both expect a BARE payload (`on` / `ON`), not JSON.
    `mqtt_publish` json.dumps() everything it is given, so the registered-plug
    path was putting `"on"` — with quotes — on the wire, which neither firmware
    accepts. Publish raw on every registered path.

    A plug with no `smart_plugs` row is NOT paired to this chamber. A real
    Shelly/Tasmota auto-registers a row the instant it announces its relay state
    (handle_plug_message → _update_plug_state), so an ABSENT row means the plug
    is genuinely missing. The old code inferred a `shellies/<id>` topic from the
    naming convention, published into the void, and returned True — which made
    the engine log the firing status='sent': the rule fired, the audit read
    clean, and no actuator moved. That masked the exact missing-actuator no-op
    this function exists to surface. Report it honestly instead. (V2-3)

    Resolution matches `target_is_present` EXACTLY — by plug_id OR device_role —
    so the two never disagree. Per the build guide a heater/humidifier gets an
    auto `plug-<hwid>` row (its real id) with `device_role` assigned, while the
    seeded rule fires the friendly target `plug-heater` (which is only a role,
    not that row's id). Resolving by id alone found nothing and no-op'd even
    though the plug was paired and `target_is_present` reported it available.
    The exact-id match wins the ORDER BY tie-break when both exist. (V3-1)
    """
    role = plug_id[len("plug-"):] if plug_id.startswith("plug-") else None
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT plug_type, mqtt_topic_prefix FROM smart_plugs "
            "WHERE plug_id = ? OR device_role = ? "
            "ORDER BY (plug_id = ?) DESC LIMIT 1",
            (plug_id, role, plug_id),
        )
        row = await cursor.fetchone()

    if not row:
        # No paired plug for this id — the command can reach no actuator, so it
        # is a no-op. Don't claim success (and don't spray a speculative publish
        # at a device that isn't there): the caller records status 'failed',
        # which is the truth.
        log.warning(
            "send_plug_command: no plug paired for %r — command %r is a no-op",
            plug_id, state,
        )
        return False

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
