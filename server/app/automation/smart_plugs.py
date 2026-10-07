"""Smart plug integration for Shelly (Gen1 and Gen2+) and Tasmota MQTT devices.

Provides unified control interface for binary on/off devices:
- Humidifier, Dehumidifier, Space Heater, Peltier Cooler

Shelly Gen1 (plug_type 'shelly'):
                shellies/<device_id>/relay/0 → "on"/"off"
                shellies/<device_id>/relay/0/command ← "on"/"off"
                shellies/<device_id>/relay/0/power → watts
                shellies/<device_id>/online → true/false (retained; the LWT)

Shelly Gen2+ (plug_type 'shelly_gen2') — every device on Shelly's JSON-RPC
"Gen2 API": Plus, Pro and Mini, Gen3 and Gen4 (plugs, 1/1PM, 2PM, 4PM, Power
Strip). The device's MQTT topic prefix (Settings → MQTT → "MQTT prefix",
config key topic_prefix) MUST be one level under shellies/ — shellies/<role>,
e.g. shellies/humidifier. The broker ACL grants the plug login (sp-3p)
shellies/# and the server shellies/+/rpc, nothing more, and Mosquitto drops
everything else without telling either side. The factory prefix is the
device id (shellyplusplugs-<mac>, a top-level tree): Mosquitto wildcards whole
levels only, so no ACL line could grant those trees without also granting
every other top-level tree on the broker.
                <prefix>/rpc ← {"id": n, "src": "<prefix>/sporeprint",
                                "method": "Switch.Set", "params": {"id": 0, "on": true}}
                <prefix>/sporeprint/rpc → the device's JSON-RPC replies (to src)
                <prefix>/events/rpc → NotifyStatus / NotifyFullStatus,
                                      {"params": {"switch:0": {"output": true, ...}}}
                <prefix>/status/switch:<id> → the full switch status, when
                                      "Generic status update over MQTT" is on
                <prefix>/online → true/false (retained; the LWT)
                A switch status carries `output` (bool) and, on metering
                models, `apower` (W). Gen3/Gen4 add voltage/current/freq/pf,
                aenergy/ret_aenergy and `errors` (overpower, overtemp, ...);
                only output, apower and errors are read. NotifyStatus is a
                delta: a missing key means unchanged, never off.
                switch:0 is plug-<role>; switch:<n> on a multi-channel device
                is plug-<role>-<n> (its switch id is kept in the row's config).

Tasmota topics: tasmota/<device_id>/stat/POWER → "ON"/"OFF"
                tasmota/<device_id>/stat/RESULT → {"POWER": "ON"} (command replies)
                tasmota/<device_id>/tele/STATE → {..., "POWER": "ON"} (periodic)
                tasmota/<device_id>/cmnd/POWER ← "ON"/"OFF"
                tasmota/<device_id>/tele/SENSOR → JSON with energy
                tasmota/<device_id>/tele/LWT → "Online"/"Offline" (retained)

Any state report marks its plug `status` 'online'; the online/LWT topics set
'online'/'offline' on every row under that topic prefix.
"""

import itertools
import json
import logging
import math
import re
import time

from .. import mqtt as _mqtt
from ..db import get_db
# Not called here (plug frames go out raw through _publish_raw), but the test
# suite's mock_mqtt fixture patches this module attribute.
from ..mqtt import mqtt_publish  # noqa: F401

log = logging.getLogger(__name__)

# smart_plugs.plug_type values. 'shelly' predates Gen2 support and stays the
# Gen1 value, so every row registered before it keeps working unchanged.
PLUG_TYPE_SHELLY = "shelly"
PLUG_TYPE_SHELLY_GEN2 = "shelly_gen2"
PLUG_TYPE_TASMOTA = "tasmota"

# A Gen2 RPC request names its sender (`src`) and the device publishes the
# reply on `<src>/rpc`. src = <prefix>/sporeprint keeps every reply inside the
# plug's own shellies/<role>/ subtree — sp-3p may publish there, the server
# already reads shellies/#, and the reply topic names the plug it is about.
_GEN2_REPLY_SEGMENT = "sporeprint"
_gen2_rpc_ids = itertools.count(1)

# The only prefixes a Gen2 command can reach: the server's ACL grant is
# shellies/+/rpc (one level; no MQTT wildcards in the name).
_GEN2_PREFIX_RE = re.compile(r"shellies/[^/#+]+")
_GEN2_SWITCH_RE = re.compile(r"switch:([0-9]{1,3})")

# Newest Gen2 `errors` list logged per plug: a status republished every minute
# logs an overpower / overtemp trip once, not every frame.
_gen2_errors_seen: dict[str, tuple[str, ...]] = {}
_GEN2_ERRORS_TRACK_CAP = 256


async def handle_plug_message(sio, topic: str, payload):
    """Route incoming Shelly/Tasmota MQTT messages."""
    parts = topic.split("/")

    if topic.startswith("shellies/"):
        await _handle_shelly_message(sio, parts, payload)

    elif topic.startswith("tasmota/") and len(parts) >= 4:
        device_id = parts[1]
        plug_id = f"plug-{device_id}"
        prefix = f"tasmota/{device_id}"

        if parts[2] == "stat" and parts[3] == "POWER":
            state = payload if isinstance(payload, str) else str(payload)
            await _update_plug_state(plug_id, PLUG_TYPE_TASMOTA, prefix, state.lower(),
                                     name=device_id)
            await sio.emit("plug_state", {"plug_id": plug_id, "state": state.lower()})

        elif (parts[2], parts[3]) in (("stat", "RESULT"), ("tele", "STATE")):
            # A command reply (stat/RESULT) and the periodic status (tele/STATE)
            # carry the relay as JSON {"POWER": "ON"} — POWER1 on multi-relay
            # firmware. A plug whose SetOption kept stat/POWER quiet reported
            # its state nowhere else, so last_state went stale.
            state = _tasmota_json_power(payload)
            if state is not None:
                await _update_plug_state(plug_id, PLUG_TYPE_TASMOTA, prefix, state,
                                         name=device_id)
                await sio.emit("plug_state", {"plug_id": plug_id, "state": state})

        elif parts[2] == "tele" and parts[3] == "SENSOR":
            energy = payload.get("ENERGY") if isinstance(payload, dict) else None
            power = _watts(energy.get("Power")) if isinstance(energy, dict) else None
            if power is not None:
                await _update_plug_power(plug_id, power)

        elif parts[2] == "tele" and parts[3] == "LWT":
            online = _online_flag(payload)
            if online is not None:
                await _update_plug_online(sio, prefix, online)


async def _handle_shelly_message(sio, parts: list[str], payload) -> None:
    """One frame under shellies/<device_id>/ — Gen1 or Gen2+, told apart by topic."""
    if len(parts) < 3 or not parts[1]:
        return  # shellies/announce, shellies/command: fleet-wide, no device
    device_id, tail = parts[1], parts[2:]
    prefix = f"shellies/{device_id}"

    if tail == ["online"]:
        # Both generations publish it (retained, the LWT is `false`).
        online = _online_flag(payload)
        if online is None:
            return
        await _update_plug_online(sio, prefix, online)
        if online:
            # A (re)connected Gen2 device publishes no status of its own, and
            # the server reads this retained flag of every device right after
            # it subscribes — so this refreshes each Gen2 plug's state after a
            # power cut, a broker restart or a server restart, and registers a
            # new one without waiting for a toggle. A Gen1 device never reads
            # <prefix>/rpc; the query is harmless there.
            await _request_gen2_status(prefix)
        return

    if tail[:2] == ["relay", "0"]:
        # Gen1. Only relay 0 is a plug (a Shelly 2.5's relay/1 is not).
        plug_id = f"plug-{device_id}"
        if len(tail) == 2:
            state = (payload if isinstance(payload, str) else str(payload)).lower()
            await _update_plug_state(plug_id, PLUG_TYPE_SHELLY, prefix, state, name=device_id)
            await sio.emit("plug_state", {"plug_id": plug_id, "state": state})
        elif tail[2:] == ["power"]:
            power = _watts(payload)
            if power is not None:
                await _update_plug_power(plug_id, power)
        return

    # Gen2+. <prefix>/rpc is a REQUEST — the server hears its own commands
    # echoed back on shellies/# — and the device's other components (sys,
    # wifi, input:N, ...) are not plugs: both fall through untouched.
    if tail == ["events", "rpc"]:
        if isinstance(payload, dict) and payload.get("method") in ("NotifyStatus",
                                                                    "NotifyFullStatus"):
            await _apply_gen2_switches(sio, device_id, _gen2_switches(payload.get("params")))
    elif len(tail) == 2 and tail[0] == "status":
        match = _GEN2_SWITCH_RE.fullmatch(tail[1])
        if match and isinstance(payload, dict):
            await _apply_gen2_switches(sio, device_id, {int(match.group(1)): payload})
    elif tail == [_GEN2_REPLY_SEGMENT, "rpc"]:
        await _handle_gen2_reply(sio, device_id, payload)


async def _handle_gen2_reply(sio, device_id: str, payload) -> None:
    """A JSON-RPC reply to one of our requests (src = <prefix>/sporeprint)."""
    if not isinstance(payload, dict):
        return
    error = payload.get("error")
    if isinstance(error, dict):
        # A refused Switch.Set never moves the relay; say so where the operator
        # looks (a bad switch id, RPC over MQTT disabled on the device, ...).
        log.warning("Shelly plug shellies/%s refused RPC request %s: %s (code %s)",
                    device_id, payload.get("id"), error.get("message"), error.get("code"))
        return
    # Shelly.GetStatus answers with the whole device status, keyed like
    # NotifyFullStatus; Switch.Set answers {"was_on": ...}, which has no switch.
    await _apply_gen2_switches(sio, device_id, _gen2_switches(payload.get("result")))


def _gen2_switches(doc) -> dict[int, dict]:
    """{switch id: status} for every `switch:<n>` object in a Gen2 status document."""
    if not isinstance(doc, dict):
        return {}
    found: dict[int, dict] = {}
    for key, value in doc.items():
        match = _GEN2_SWITCH_RE.fullmatch(key) if isinstance(key, str) else None
        if match and isinstance(value, dict):
            found[int(match.group(1))] = value
    return found


def _gen2_plug_id(device_id: str, switch_id: int) -> str:
    return f"plug-{device_id}" if switch_id == 0 else f"plug-{device_id}-{switch_id}"


async def _apply_gen2_switches(sio, device_id: str, switches: dict[int, dict]) -> None:
    """Record each Gen2 switch status: register the plug, its state and power.

    Any switch status registers its plug — it proves a Gen2 switch is behind
    shellies/<device_id> — even a delta with neither key (an energy-counter
    tick); `output` and `apower` update only when present.
    """
    prefix = f"shellies/{device_id}"
    for switch_id, status in sorted(switches.items()):
        plug_id = _gen2_plug_id(device_id, switch_id)
        output = status.get("output")
        state = ("on" if output else "off") if isinstance(output, bool) else None
        await _update_plug_state(
            plug_id, PLUG_TYPE_SHELLY_GEN2, prefix, state,
            name=plug_id.removeprefix("plug-"),
            power=_watts(status.get("apower")),
            config={"switch_id": switch_id},
        )
        if "errors" in status:
            _note_gen2_errors(plug_id, status["errors"])
        if state is not None:
            await sio.emit("plug_state", {"plug_id": plug_id, "state": state})


def _note_gen2_errors(plug_id: str, errors) -> None:
    """Log a Gen2 switch's fault list (overpower, overtemp, ...) when it changes."""
    current = tuple(sorted(str(e) for e in errors)) if isinstance(errors, list) else ()
    if _gen2_errors_seen.get(plug_id, ()) == current:
        return
    if len(_gen2_errors_seen) >= _GEN2_ERRORS_TRACK_CAP:
        _gen2_errors_seen.clear()
    _gen2_errors_seen[plug_id] = current
    if current:
        # The device cut the relay itself; output:false in the same status
        # already recorded that.
        log.warning("Shelly plug %s reports %s", plug_id, ", ".join(current))
    else:
        log.info("Shelly plug %s: faults cleared", plug_id)


def _gen2_rpc_frame(prefix: str, method: str, params: dict | None = None) -> str:
    """One JSON-RPC request frame for a Gen2 device at `prefix`."""
    frame = {"id": next(_gen2_rpc_ids), "src": f"{prefix}/{_GEN2_REPLY_SEGMENT}",
             "method": method}
    if params is not None:
        frame["params"] = params
    return json.dumps(frame, separators=(",", ":"))


async def _request_gen2_status(prefix: str) -> bool:
    """Ask a Gen2 device for its whole status; the reply lands on <prefix>/sporeprint/rpc."""
    if not _GEN2_PREFIX_RE.fullmatch(prefix):
        return False
    return await _publish_raw(f"{prefix}/rpc", _gen2_rpc_frame(prefix, "Shelly.GetStatus"))


def _gen2_switch_id(row: dict) -> int:
    """The Gen2 switch a smart_plugs row drives (config {"switch_id": n}; default 0)."""
    try:
        value = json.loads(row.get("config") or "{}").get("switch_id", 0)
    except (TypeError, ValueError, AttributeError):
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _online_flag(payload) -> bool | None:
    """True/False from an online/LWT payload (Shelly JSON true/false, Tasmota Online/Offline)."""
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, str):
        return {"true": True, "online": True,
                "false": False, "offline": False}.get(payload.strip().lower())
    return None


def _watts(value) -> float | None:
    """A finite power reading in watts, or None for anything that isn't one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _tasmota_json_power(payload) -> str | None:
    """"on"/"off" from a Tasmota RESULT/STATE document, or None if it has no relay state."""
    if not isinstance(payload, dict):
        return None
    for key in ("POWER", "POWER1"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip().upper() in ("ON", "OFF"):
            return value.strip().lower()
    return None


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


async def plug_aliases(target: str) -> set[str]:
    """Every automation target that reaches the same paired plug as `target`.

    A rule can name a plug by its id (`plug-a1b2c3`) or by its role
    (`plug-heater`); both reach one physical plug, resolved exactly as
    send_plug_command resolves it. Always includes `target` itself.
    """
    role = target[len("plug-"):] if target.startswith("plug-") else None
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT plug_id, device_role FROM smart_plugs "
            "WHERE plug_id = ? OR device_role = ? "
            "ORDER BY (plug_id = ?) DESC LIMIT 1",
            (target, role, target),
        )
        row = await cursor.fetchone()
    aliases = {target}
    if row:
        aliases.add(row["plug_id"])
        if row["device_role"]:
            aliases.add(f"plug-{row['device_role']}")
    return aliases


async def paired_plug(plug_id: str) -> dict | None:
    """The paired smart_plugs row a command to `plug_id` reaches, or None.

    Matched by plug_id OR device_role (`plug-heater` → role 'heater'), the exact
    id winning a tie — the same resolution target_is_present uses.
    """
    role = plug_id[len("plug-"):] if plug_id.startswith("plug-") else None
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM smart_plugs "
            "WHERE plug_id = ? OR device_role = ? "
            "ORDER BY (plug_id = ?) DESC LIMIT 1",
            (plug_id, role, plug_id),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def send_plug_command(plug_id: str, state: str) -> bool:
    """Send an on/off command to a smart plug. True only when it was delivered
    to a PAIRED plug; an unpaired plug is a reported no-op (False).

    Shelly Gen1 and Tasmota both expect a BARE payload (`on` / `ON`), not JSON.
    `mqtt_publish` json.dumps() everything it is given, so the registered-plug
    path was putting `"on"` — with quotes — on the wire, which neither firmware
    accepts. Publish raw on every registered path. A Shelly Gen2+ plug takes a
    JSON-RPC frame instead (Switch.Set {id, on}; see _send_gen2_command), also
    published raw: it is not a sporeprint cmd/* frame, so it is never signed.

    The state maps exactly as the plug reads it — `state.lower() == "off"` is
    the only OFF, which is the same test POST /api/automation/plugs/{id}/command
    uses before it clears a safety ceiling (note_actuator_off).

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
    row = await paired_plug(plug_id)
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
    if row["plug_type"] == PLUG_TYPE_SHELLY:
        return await _publish_raw(f"{prefix}/relay/0/command", state.lower())
    if row["plug_type"] == PLUG_TYPE_TASMOTA:
        return await _publish_raw(f"{prefix}/cmnd/POWER", state.upper())
    if row["plug_type"] == PLUG_TYPE_SHELLY_GEN2:
        return await _send_gen2_command(row, state)

    log.warning("Unknown plug_type %r for plug %s", row["plug_type"], plug_id)
    return False


async def _send_gen2_command(row: dict, state: str) -> bool:
    """Switch a Shelly Gen2+ plug: a JSON-RPC Switch.Set (or Switch.Toggle) frame.

    False — nothing published — for a state the Switch API has no meaning for,
    or a prefix outside shellies/<name>: the server may only publish
    shellies/+/rpc, and Mosquitto drops anything else without an error, so a
    publish there would read as sent while no relay moved.
    """
    prefix = row["mqtt_topic_prefix"]
    if not _GEN2_PREFIX_RE.fullmatch(prefix or ""):
        log.warning(
            "Shelly plug %s has MQTT prefix %r — set the device's prefix to "
            "shellies/<role> (one level under shellies/); the broker drops a "
            "command anywhere else", row["plug_id"], prefix,
        )
        return False
    switch_id = _gen2_switch_id(row)
    wanted = state.lower()
    if wanted in ("on", "off"):
        method, params = "Switch.Set", {"id": switch_id, "on": wanted == "on"}
    elif wanted == "toggle":
        method, params = "Switch.Toggle", {"id": switch_id}
    else:
        log.warning("Shelly plug %s: no Switch command for state %r — not sent",
                    row["plug_id"], state)
        return False
    return await _publish_raw(f"{prefix}/rpc", _gen2_rpc_frame(prefix, method, params))


async def _publish_raw(topic: str, payload: str) -> bool:
    """Publish an unencoded payload — vendor plugs want bare text, not JSON.

    False when there is no broker connection or the publish fails, like
    mqtt_publish: a caller must never read a raised transport error as sent.
    The client is read from the mqtt module at call time — it is replaced on
    every reconnect.
    """
    client = _mqtt._client
    if client is None:
        return False
    try:
        await client.publish(topic, payload)
    except Exception as e:
        log.warning("plug publish to %s failed: %s", topic, e)
        return False
    return True


async def register_plug(
    plug_id: str,
    name: str,
    plug_type: str,
    mqtt_topic_prefix: str,
    device_role: str | None = None,
):
    """Register a smart plug in the database.

    plug_type 'shelly' on a row the device itself reported as Gen2+ (same
    prefix) keeps 'shelly_gen2': POST /api/automation/plugs defaults plug_type
    to 'shelly', so assigning a role to an auto-registered Gen2 plug would
    otherwise switch its commands to the Gen1 topic (shellies/<id>/relay/0/
    command), which a Gen2 device never reads.
    """
    async with get_db() as db:
        await db.execute(
            """INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, device_role)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(plug_id) DO UPDATE SET
                 name=excluded.name,
                 plug_type=CASE
                   WHEN excluded.plug_type = ? AND smart_plugs.plug_type = ?
                        AND excluded.mqtt_topic_prefix = smart_plugs.mqtt_topic_prefix
                   THEN smart_plugs.plug_type ELSE excluded.plug_type END,
                 mqtt_topic_prefix=excluded.mqtt_topic_prefix,
                 device_role=excluded.device_role""",
            (plug_id, name, plug_type, mqtt_topic_prefix, device_role,
             PLUG_TYPE_SHELLY, PLUG_TYPE_SHELLY_GEN2),
        )
        await db.commit()


async def get_all_plugs() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM smart_plugs ORDER BY name")
        return [dict(r) for r in await cursor.fetchall()]


async def _update_plug_state(
    plug_id: str,
    plug_type: str,
    prefix: str,
    state: str | None,
    *,
    name: str,
    power: float | None = None,
    config: dict | None = None,
):
    """Upsert the plug a report came from, registering it on first sight.

    The report's topic proves the device's transport, so plug_type and
    mqtt_topic_prefix follow it: a row registered by hand under the wrong type,
    or a Gen1 plug swapped for a Gen2 one under the same name, heals on the
    next report instead of being commanded on topics the device never reads.
    The operator's name and device_role are kept. A None state, power or
    config keeps the stored value. A report proves the plug is online.
    """
    async with get_db() as db:
        await db.execute(
            """INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, config,
                                        status, last_state, last_power_w, last_seen)
               VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?)
               ON CONFLICT(plug_id) DO UPDATE SET
                 plug_type=excluded.plug_type,
                 mqtt_topic_prefix=excluded.mqtt_topic_prefix,
                 config=COALESCE(excluded.config, smart_plugs.config),
                 status='online',
                 last_state=COALESCE(excluded.last_state, smart_plugs.last_state),
                 last_power_w=COALESCE(excluded.last_power_w, smart_plugs.last_power_w),
                 last_seen=excluded.last_seen""",
            (plug_id, name, plug_type, prefix,
             json.dumps(config) if config is not None else None,
             state, power, time.time()),
        )
        await db.commit()


async def _update_plug_online(sio, prefix: str, online: bool) -> None:
    """Apply an online/LWT report to every plug under `prefix` (a multi-channel
    Gen2 device is several rows). A device with no row yet is not a plug yet:
    the flag cannot say which transport it speaks, so it registers nothing."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT plug_id, status FROM smart_plugs WHERE mqtt_topic_prefix = ?", (prefix,)
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        if not rows:
            return
        if online:
            await db.execute(
                "UPDATE smart_plugs SET status = 'online', last_seen = ? "
                "WHERE mqtt_topic_prefix = ?", (time.time(), prefix),
            )
        else:
            # The broker publishes the LWT for a device it lost: not a sighting.
            await db.execute(
                "UPDATE smart_plugs SET status = 'offline' WHERE mqtt_topic_prefix = ?",
                (prefix,),
            )
        await db.commit()
    for row in rows:
        if not online and row["status"] != "offline":
            # It keeps its last relay state while unreachable, and nothing the
            # Pi sends — a safety OFF included — reaches it until it is back.
            log.warning("Smart plug %s (%s) went offline", row["plug_id"], prefix)
        await sio.emit("plug_online", {"plug_id": row["plug_id"], "online": online})


async def _update_plug_power(plug_id: str, power: float):
    async with get_db() as db:
        await db.execute(
            "UPDATE smart_plugs SET last_power_w = ?, last_seen = ? WHERE plug_id = ?",
            (power, time.time(), plug_id),
        )
        await db.commit()
