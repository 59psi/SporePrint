"""Commands must reach the device that is supposed to act on them.

The wire-contract test proves we use the right field NAMES. This one proves we
publish them to the right TOPIC — the other half of the same silent-failure
class. MQTT accepts a publish to any topic, so a command sent to a topic no
device subscribes to "succeeds": the rule logs status='sent', the audit trail
reads clean, and the actuator never moves.

Two live instances of that, both fixed here:
  * scene actions were published to cmd/config, whose firmware handler reads
    only the interval/calibration keys and ignores `scene` — so every seeded
    "Light Scene" rule was a no-op.
  * smart-plug rules were published to sporeprint/plug-*/cmd/*, which no
    Shelly or Tasmota device subscribes to. They listen on their own topic
    trees. Every seeded humidifier/heater/cooler rule fired into the void.
"""

import json

from app.automation.engine import _fire_rule
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.db import get_db

# Real nodes register under MAC-derived ids with a provisioned node_type, NOT
# the seeded placeholders relay-01 / light-01. The engine resolves the
# placeholder a seeded rule names to the chamber's real node of that role at
# fire time, so the command reaches the topic the node is actually subscribed
# to. Registering nodes the way provisioning does is what proves that. (V3-2)
RELAY_NODE = "node-relay-7a3f1c"
LIGHT_NODE = "node-light-9b2c4d"


def _rule(action: RuleAction, name: str = "r") -> AutomationRule:
    return AutomationRule(
        id=1,
        name=name,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="lt", value=80),
        ),
        action=action,
        log_to_session=False,
    )


async def _register_node(
    node_id: str, node_type: str, channels: list[str] | None = None
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type, json.dumps(channels) if channels is not None else None,
             1_752_700_000.0),
        )
        await db.commit()


async def _register_plug(
    plug_id: str, plug_type: str, prefix: str, role: str | None = None
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name, device_role) "
            "VALUES (?, ?, ?, ?, ?)",
            (plug_id, plug_type, prefix, plug_id, role),
        )
        await db.commit()


# ── scene routing ──────────────────────────────────────────────────────


async def test_scene_action_publishes_to_cmd_scene(mock_mqtt):
    """The firmware only reads `scene` on the cmd/scene suffix (cmd_router.h).

    The seeded rule names the placeholder light-01; the real lighting node is
    MAC-derived, so the scene must publish to the RESOLVED node's cmd/scene."""
    await _register_node(LIGHT_NODE, "lighting")
    await _fire_rule(
        _rule(RuleAction(target="light-01", scene="fruiting_standard"), "scene"),
        {"humidity": 70},
        session=None,
    )
    topics = [t for t, _ in mock_mqtt]
    assert topics == [f"sporeprint/{LIGHT_NODE}/cmd/scene"], topics


async def test_channel_action_still_publishes_to_cmd_channel(mock_mqtt):
    """A channel action must keep its own suffix even if a scene is also set —
    published to the chamber's real relay node, not the relay-01 placeholder."""
    await _register_node(RELAY_NODE, "relay", ["fae", "exhaust", "circulation", "aux"])
    await _fire_rule(
        _rule(RuleAction(target="relay-01", channel="fae", state="on"), "chan"),
        {"humidity": 70},
        session=None,
    )
    topics = [t for t, _ in mock_mqtt]
    assert topics == [f"sporeprint/{RELAY_NODE}/cmd/fae"], topics


async def test_bare_action_still_publishes_to_cmd_config(mock_mqtt):
    """No channel and no scene = a config command. Unchanged."""
    await _fire_rule(
        _rule(RuleAction(target="climate-01", state="on"), "cfg"),
        {"humidity": 70},
        session=None,
    )
    topics = [t for t, _ in mock_mqtt]
    assert topics == ["sporeprint/climate-01/cmd/config"], topics


# ── smart-plug routing ─────────────────────────────────────────────────


async def test_shelly_plug_rule_reaches_the_shelly_topic(mock_mqtt, mock_mqtt_raw):
    # Paired the way the build guide provisions it: a plug-<hwid> row with a
    # device_role. The seeded rule fires the friendly role target.
    await _register_plug("plug-9f7e", "shelly", "shellies/9f7e", role="humidifier")

    await _fire_rule(
        _rule(RuleAction(target="plug-humidifier", state="on"), "plug"),
        {"humidity": 70},
        session=None,
    )

    # Nothing on the sporeprint/* tree — a plug does not speak that protocol.
    assert [t for t, _ in mock_mqtt] == []
    # Bare payload, not JSON: Shelly rejects `"on"` (quoted).
    assert mock_mqtt_raw == [("shellies/9f7e/relay/0/command", "on")]


async def test_tasmota_plug_rule_reaches_the_tasmota_topic(mock_mqtt, mock_mqtt_raw):
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")

    await _fire_rule(
        _rule(RuleAction(target="plug-heater", state="off"), "plug"),
        {"humidity": 70},
        session=None,
    )

    assert [t for t, _ in mock_mqtt] == []
    assert mock_mqtt_raw == [("tasmota/a1b2c3/cmnd/POWER", "OFF")]


async def test_unregistered_plug_is_an_honest_no_op(mock_mqtt, mock_mqtt_raw):
    """plug-<id> with no DB row is NOT paired: no actuator can receive the
    command, so it must be a reported no-op — not a speculative publish that
    logs status='sent' for hardware that was never there. (V2-3)"""
    await _fire_rule(
        _rule(RuleAction(target="plug-cooler", state="on"), "plug"),
        {"humidity": 70},
        session=None,
    )
    # Nothing published anywhere — not on sporeprint/*, and not on a guessed
    # shellies/* topic for a plug that was never paired.
    assert [t for t, _ in mock_mqtt] == []
    assert mock_mqtt_raw == []
    # The audit row tells the truth: the firing actuated nothing.
    async with get_db() as db:
        cursor = await db.execute("SELECT status FROM automation_firings")
        row = await cursor.fetchone()
    assert row["status"] == "failed", row["status"]


async def test_safety_auto_off_routes_plug_targets_to_plug_topic(mock_mqtt, mock_mqtt_raw):
    """The fire-risk watchdog's OFF must reach the plug too — a stuck-on
    heater whose OFF goes to sporeprint/plug-* stays on."""
    from app.automation.engine import _safety_auto_off

    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    await _safety_auto_off("plug-heater", None, 0, "heater-guard")

    assert [t for t, _ in mock_mqtt] == []
    assert ("tasmota/a1b2c3/cmnd/POWER", "OFF") in mock_mqtt_raw


async def test_plug_firing_is_recorded_as_sent(mock_mqtt, mock_mqtt_raw):
    """The audit row must reflect the plug transport, not claim a failure —
    a PAIRED plug (by role, under its hardware id) records status='sent'."""
    await _register_plug("plug-9f7e", "shelly", "shellies/9f7e", role="humidifier")
    await _fire_rule(
        _rule(RuleAction(target="plug-humidifier", state="on"), "plug"),
        {"humidity": 70},
        session=None,
    )
    async with get_db() as db:
        cursor = await db.execute("SELECT status, error FROM automation_firings")
        row = await cursor.fetchone()
    assert row["status"] == "sent", row["error"]
