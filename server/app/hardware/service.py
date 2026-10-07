"""Hardware node service layer — DB access + MQTT command dispatch.

Extracted from `hardware/router.py` in v3.3.2 (P12 layering cleanup) so the
router stays thin and the `hardware_nodes` table access lives in one place.
`mqtt.py` still writes directly to the table on heartbeat ingest (per-message
hot-path optimization documented in the AGENTS.md V20 exception).
"""

import json
import logging
import re
import time

from ..automation.engine import note_actuator_off, note_actuator_on
from ..automation.service import drop_duty_from_off, is_off_command
from ..db import get_db
from ..mqtt import mqtt_publish

log = logging.getLogger(__name__)

# Path segments must stay inside the per-node namespace. A caller that set
# `topic: "sporeprint/OTHER_NODE/cmd/heater"` previously bypassed it entirely.
NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
CHANNEL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

# Optional peripherals a node's cmd/config {"peripherals": {...}} switches on
# or off (firmware sp_core apply_peripheral_cmd): MH-Z19C CO2 sensor (UART),
# HX711 load-cell scale, door reed switch — a changed driver set is saved to
# NVS and the node reboots ~1.5 s later — and reed_inv (door contact wired on
# its NO lead), which is saved and applied live, no reboot. An unchanged
# request does nothing. Older firmware ignores keys it doesn't know.
PERIPHERAL_KEYS = ("mhz19", "hx711", "reed", "reed_inv")

# Camera sensor ids the cam firmware reports (X-Camera-Sensor, heartbeat
# camera_sensor): ov2640 / ov3660 / ov5640 / unknown / none.
_CAMERA_SENSOR_RE = re.compile(r"^[a-z0-9_-]{1,16}$")


async def list_nodes() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes ORDER BY last_seen DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def get_node(node_id: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes WHERE node_id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def send_command(node_id: str, command: dict) -> tuple[str, bool]:
    """Publish a command to a specific node.

    Returns `(topic, published)`. `published` is False when mqtt_publish
    refused or failed the frame (no broker connection, publish error, or
    cmd signing enforced with no HMAC key) — the command never left the Pi.

    Caller must have already validated `node_id`. This helper strips any
    caller-supplied `topic` and `channel` from `command` to prevent injection,
    then composes the canonical `sporeprint/{node}/cmd/{channel}` topic itself.

    An OFF is published without any pwm / level (deployed firmware let a duty
    value win over "off"). A published OFF to a channel or scene also clears
    the automation safety ceiling timing that actuator, so the next automation
    ON starts a fresh one instead of tripping early on the old deadline. Any
    other published channel or scene command tells the engine the actuator may
    be ON, so a rule cutoff re-sends its OFF instead of treating it as a
    redundant repeat (note_actuator_on).
    """
    command = dict(command)
    command.pop("topic", None)
    channel = command.pop("channel", None) or "config"
    if not CHANNEL_RE.match(str(channel)):
        raise ValueError("Invalid channel")
    topic = f"sporeprint/{node_id}/cmd/{channel}"
    command = drop_duty_from_off(command)
    sent_at = time.time()
    published = bool(await mqtt_publish(topic, command))
    if published and channel != "config":
        # A scene rule's bookkeeping is keyed on the node with no channel.
        key_channel = None if channel == "scene" else channel
        try:
            if is_off_command(command):
                await note_actuator_off(node_id, key_channel, sent_at=sent_at)
            else:
                await note_actuator_on(node_id, key_channel)
        except Exception as e:  # the command went out; bookkeeping must not 500 it
            log.warning("automation bookkeeping for %s:%s failed: %s", node_id, channel, e)
    return topic, published


async def publish_node_command(topic: str, payload: dict) -> bool:
    """A raw signed cmd/* publish for the OTA push's background task, which
    cannot import app.mqtt itself (app.mqtt imports ota_push). Resolves
    mqtt_publish at call time."""
    return bool(await mqtt_publish(topic, payload))


def peripherals_command(requested: dict) -> dict:
    """The cmd/config body that sets a node's optional peripherals.

    Only JSON booleans for the known keys are accepted (the firmware ignores
    anything else with a warning, which would read as success here).
    Raises ValueError otherwise.
    """
    if not isinstance(requested, dict) or not requested:
        raise ValueError(f"Send at least one of {', '.join(PERIPHERAL_KEYS)} as true/false")
    unknown = sorted(set(requested) - set(PERIPHERAL_KEYS))
    if unknown:
        raise ValueError(f"Unknown peripheral(s): {', '.join(unknown)} — "
                         f"expected {', '.join(PERIPHERAL_KEYS)}")
    not_bool = sorted(k for k, v in requested.items() if not isinstance(v, bool))
    if not_bool:
        raise ValueError(f"Peripheral flags must be true or false: {', '.join(not_bool)}")
    return {"peripherals": dict(requested)}


def normalize_camera_sensor(raw: str | None) -> str | None:
    """A camera sensor id from X-Camera-Sensor, lowercased, or None if absent/invalid."""
    value = (raw or "").strip().lower()
    return value if _CAMERA_SENSOR_RE.match(value) else None


async def record_camera_sensor(node_id: str, sensor: str) -> bool:
    """Remember which image sensor a registered camera node has.

    Stored under "camera_sensor" in hardware_nodes.config (a JSON object; other
    keys are kept), so GET /api/hardware/nodes shows it and vision prompts can
    name it. Only an existing node row is updated — nodes register themselves
    by heartbeat. Returns True when a row was updated.
    """
    async with get_db() as db:
        # Nested CASE: json_type() must never see malformed JSON.
        cursor = await db.execute(
            "UPDATE hardware_nodes SET config = json_set("
            "CASE WHEN json_valid(config) THEN "
            "  CASE WHEN json_type(config) = 'object' THEN config ELSE '{}' END "
            "ELSE '{}' END, '$.camera_sensor', ?) "
            "WHERE node_id = ?",
            (sensor, node_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_camera_sensor(node_id: str) -> str | None:
    """The image sensor recorded for a camera node, or None."""
    node = await get_node(node_id)
    if not node or not node.get("config"):
        return None
    try:
        config = json.loads(node["config"])
    except (TypeError, ValueError):
        return None
    sensor = config.get("camera_sensor") if isinstance(config, dict) else None
    return sensor if isinstance(sensor, str) else None
