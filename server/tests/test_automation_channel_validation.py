"""Automation rules may only name channels their node actually answers to.

The motivating bug: firmware and the BOM call relay channel 4 `aux` (GPIO 14 →
peristaltic pump → misting nozzle), but the frontend's demo data called it
`mister`. Channel names are MQTT routing keys matched exactly by the node, so a
rule written for `mister` publishes fine, logs a "fired" audit row, and never
moves the pump. These tests pin the whole path: node reports its channels →
rules are validated against them → bad channels are refused, not silently lost.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.automation.models import RuleAction
from app.automation.service import validate_action_channel
from app.db import get_db
from app.mqtt import _handle_message

RELAY_CHANNELS = ["aux", "circulation", "exhaust", "fae"]

# Real relay nodes register under a MAC-derived id, not the seeded placeholder
# relay-01. Rules authored against relay-01 must be validated against the
# chamber's actual relay node (resolved by node_type), so registering the node
# the way provisioning does — and still targeting relay-01 in the rule — is what
# proves the resolve-then-validate path rather than masking it.
RELAY_NODE = "node-relay-7a3f1c"


async def _register_node(
    node_id: str, channels: list[str] | None, node_type: str = "relay"
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type,
             json.dumps(channels) if channels is not None else None, 1_752_700_000.0),
        )
        await db.commit()


# ─── Harvesting channel names from the node's health doc ────────────────


async def test_health_doc_persists_channel_names():
    """The health doc is the only place a node enumerates its channels."""
    await _handle_message(
        AsyncMock(),
        "sporeprint/relay-01/health",
        {
            "channels": {
                "fae": {"state": False, "pwm": 0, "cycle_count": 3},
                "exhaust": {"state": True, "pwm": 255, "cycle_count": 9},
                "circulation": {"state": False, "pwm": 0, "cycle_count": 1},
                "aux": {"state": False, "pwm": 0, "cycle_count": 0},
            }
        },
    )

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT channels FROM hardware_nodes WHERE node_id = 'relay-01'"
        )
        row = await cursor.fetchone()

    assert json.loads(row["channels"]) == RELAY_CHANNELS


async def _channels(node_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT channels FROM hardware_nodes WHERE node_id = ?", (node_id,)
        )
        row = await cursor.fetchone()
    return row["channels"]


async def test_health_doc_without_channels_clears_a_stale_list():
    """Every switch or dim image lists its channels in every health doc, so a
    doc without them is a node that answers to none (re-provisioned from a
    relay bank to climate). Its old list must not keep validating rules."""
    await _register_node("relay-01", RELAY_CHANNELS)

    await _handle_message(
        AsyncMock(), "sporeprint/relay-01/health", {"sensors": {"sht4x": {"ok": True}}}
    )

    assert await _channels("relay-01") == "[]"
    err = await validate_action_channel(RuleAction(target="relay-01", channel="fae"))
    assert err is not None and "fae" in err


async def test_health_doc_with_unreadable_channels_changes_nothing():
    await _register_node("relay-01", RELAY_CHANNELS)
    await _handle_message(
        AsyncMock(), "sporeprint/relay-01/health", {"channels": ["fae", "aux"]}
    )
    assert json.loads(await _channels("relay-01")) == RELAY_CHANNELS


async def test_node_that_never_reported_channels_stays_unreported():
    await _register_node("climate-01", None, node_type="climate")
    await _handle_message(
        AsyncMock(), "sporeprint/climate-01/health", {"sensors": {"sht4x": {"ok": True}}}
    )
    assert await _channels("climate-01") is None


# ─── Validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize("nodes,action,refusal", [
    # The rule names the relay-01 placeholder; the real node is MAC-derived,
    # and the channel is checked against the node it resolves to.
    ([(RELAY_NODE, RELAY_CHANNELS, "relay")], RuleAction(target="relay-01", channel="aux"), None),
    # The `mister` → `aux` case: refused, naming what the node does answer to.
    ([(RELAY_NODE, RELAY_CHANNELS, "relay")], RuleAction(target="relay-01", channel="mister"),
     ["mister", "aux"]),
    # Validate, don't discover: a node that never reported channels is no evidence.
    ([(RELAY_NODE, None, "relay")], RuleAction(target="relay-01", channel="anything"), None),
    # A placeholder with no node of its role reaches nothing: flagged, not
    # left to fire status='sent' ...
    ([], RuleAction(target="relay-01", channel="fae"), ["relay"]),
    # ... and a node of another role is not one of its role.
    ([("node-light-9b2c", None, "lighting")], RuleAction(target="relay-01", channel="fae"),
     ["relay"]),
    # Smart plugs and vendor override keys are not nodes: no opinion.
    ([], RuleAction(target="smart-plug-7", channel="whatever"), None),
    # Vendor writes go through the integrations dispatcher, not MQTT.
    ([("relay-01", RELAY_CHANNELS, "relay")],
     RuleAction(target="vendor:kasa:10.0.0.5", channel="not-a-node-channel",
                vendor_slug="kasa", vendor_action="set_power"), None),
    # No channel: a config command.
    ([(RELAY_NODE, RELAY_CHANNELS, "relay")], RuleAction(target="relay-01"), None),
])
async def test_a_rule_may_name_only_a_channel_its_node_answers_to(nodes, action, refusal):
    for node_id, channels, node_type in nodes:
        await _register_node(node_id, channels, node_type)
    error = await validate_action_channel(action)
    if refusal is None:
        assert error is None
    else:
        assert error is not None and all(word in error for word in refusal), error

# The LAN route and the cloud relay refuse such a rule alike (422):
# tests/test_rule_crud.py.
