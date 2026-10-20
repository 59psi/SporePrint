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

The safety ceiling's OFF takes the same routes: tests/test_safety_max_on.py.
"""

import json

import pytest

from app.automation.engine import _fire_rule
from app.automation.models import RuleAction
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    FakeSio,
    RELAY_CHANNELS,
    engine_state,
    firings,
    insert_plug,
    make_rule,
    register_node,
    threshold,
)

# Real nodes register under MAC-derived ids, NOT the seeded placeholders
# relay-01 / light-01: the command must reach the topic the chamber's real
# node of that role is subscribed to.
RELAY_NODE = "node-relay-7a3f1c"
LIGHT_NODE = "node-light-9b2c4d"


def _rule(action: RuleAction, name: str = "r"):
    return make_rule(action, condition=threshold("humidity", "lt", 80), name=name,
                     log_to_session=False)


@pytest.mark.parametrize("action,topic,payload", [
    # The firmware reads `scene` only on cmd/scene (cmd_router.h).
    (RuleAction(target="light-01", scene="fruiting_standard"),
     f"sporeprint/{LIGHT_NODE}/cmd/scene", {"state": "on", "scene": "fruiting_standard"}),
    # A channel action keeps its own suffix, a scene set beside it or not.
    (RuleAction(target="relay-01", channel="fae", state="on", pwm=180, ramp_sec=5),
     f"sporeprint/{RELAY_NODE}/cmd/fae", {"state": "on", "pwm": 180, "ramp_sec": 5}),
    (RuleAction(target="relay-01", channel="fae", scene="fruiting_standard"),
     f"sporeprint/{RELAY_NODE}/cmd/fae", {"state": "on", "scene": "fruiting_standard"}),
    # No channel and no scene is a config command.
    (RuleAction(target="climate-01", state="on"), "sporeprint/climate-01/cmd/config",
     {"state": "on"}),
])
async def test_a_node_command_goes_to_the_topic_its_firmware_reads(mock_mqtt, action, topic,
                                                                    payload):
    await register_node(RELAY_NODE, "relay", RELAY_CHANNELS)
    await register_node(LIGHT_NODE, "lighting")
    sio = FakeSio()
    await _fire_rule(_rule(action), {"humidity": 70}, None, sio)
    assert mock_mqtt == [(topic, payload)]
    assert sio.events[-1][0] == "rule_fired" and sio.events[-1][1]["status"] == "sent"


# (the paired plug, the rule's action) -> what reaches the plug's own topic tree.
_PLUG_RULES = {
    # Bare text, not JSON: a Shelly rejects "on" with quotes.
    "shelly": (("plug-9f7e", "shelly", "shellies/9f7e", "humidifier"),
               RuleAction(target="plug-humidifier", state="on"),
               [("shellies/9f7e/relay/0/command", "on")]),
    "tasmota": (("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", "heater"),
                RuleAction(target="plug-heater", state="off"),
                [("tasmota/a1b2c3/cmnd/POWER", "OFF")]),
    "shelly gen2": (("plug-shellyplugus-c4", "shelly_gen2", "shellies/shellyplugus-c4",
                     "humidifier"), RuleAction(target="plug-humidifier", state="on"),
                    [("shellies/shellyplugus-c4/rpc", ("Switch.Set", {"id": 0, "on": True}))]),
}


@pytest.mark.parametrize("transport", list(_PLUG_RULES))
async def test_a_plug_rule_reaches_the_plugs_own_topic_tree(mock_mqtt, mock_mqtt_raw, transport):
    """Paired the way the build guide provisions it (plug-<hwid> with a
    device_role) while the seeded rule names the role. Nothing goes on the
    sporeprint/* tree, and the firing is recorded as sent."""
    (plug_id, plug_type, prefix, role), action, sent = _PLUG_RULES[transport]
    await insert_plug(plug_id, plug_type, prefix, role=role)
    await _fire_rule(_rule(action, "plug"), {"humidity": 70}, None)

    assert mock_mqtt == []
    wire = [(t, (json.loads(p)["method"], json.loads(p)["params"]) if t.endswith("/rpc") else p)
            for t, p in mock_mqtt_raw]
    assert wire == sent
    assert [f["status"] for f in await firings("plug")] == ["sent"]


async def test_an_unregistered_plug_is_an_honest_no_op(mock_mqtt, mock_mqtt_raw):
    """plug-<id> with no row is NOT paired: no actuator can receive the
    command, so it is a reported no-op, not a speculative publish that logs
    status='sent' for hardware that was never there."""
    await _fire_rule(_rule(RuleAction(target="plug-cooler", state="on"), "plug"),
                     {"humidity": 70}, None)
    assert mock_mqtt == [] and mock_mqtt_raw == []
    assert [f["status"] for f in await firings("plug")] == ["failed"]
