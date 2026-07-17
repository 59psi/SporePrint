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

from app.automation.models import RuleAction
from app.automation.service import validate_action_channel
from app.db import get_db
from app.mqtt import _handle_message

RELAY_CHANNELS = ["aux", "circulation", "exhaust", "fae"]

# Real relay nodes register under a MAC-derived id, not the seeded placeholder
# relay-01. Rules authored against relay-01 must be validated against the
# chamber's actual relay node (resolved by node_type), so registering the node
# the way provisioning does — and still targeting relay-01 in the rule — is what
# proves the resolve-then-validate path rather than masking it. (V3-2)
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


async def test_health_doc_without_channels_leaves_existing_list_intact():
    """A sensor-only node's health doc has no `channels` key — don't wipe."""
    await _register_node("relay-01", RELAY_CHANNELS)

    await _handle_message(
        AsyncMock(), "sporeprint/relay-01/health", {"sensors": {"sht4x": {"ok": True}}}
    )

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT channels FROM hardware_nodes WHERE node_id = 'relay-01'"
        )
        row = await cursor.fetchone()

    assert json.loads(row["channels"]) == RELAY_CHANNELS


# ─── Validation ────────────────────────────────────────────────────────


async def test_known_channel_passes():
    # Rule targets the relay-01 placeholder; the real node is MAC-derived. The
    # channel is validated against the resolved node's reported channels.
    await _register_node(RELAY_NODE, RELAY_CHANNELS)
    action = RuleAction(target="relay-01", channel="aux", state="on")
    assert await validate_action_channel(action) is None


async def test_unknown_channel_is_rejected_and_names_the_alternatives():
    """The `mister` → `aux` case. The error has to be actionable."""
    await _register_node(RELAY_NODE, RELAY_CHANNELS)
    action = RuleAction(target="relay-01", channel="mister", state="on")

    error = await validate_action_channel(action)

    assert error is not None
    assert "mister" in error
    assert "aux" in error


async def test_node_that_never_reported_channels_gets_no_opinion():
    """Validate, don't discover — an un-heard-from node isn't evidence."""
    await _register_node(RELAY_NODE, None)
    action = RuleAction(target="relay-01", channel="anything", state="on")
    assert await validate_action_channel(action) is None


async def test_unregistered_placeholder_target_is_flagged():
    """A seeded rule still naming relay-01 when NO relay node is paired can't
    reach any actuator — flag it instead of letting it fire status='sent'. (V3-2)"""
    action = RuleAction(target="relay-01", channel="fae", state="on")
    error = await validate_action_channel(action)
    assert error is not None
    assert "relay" in error


async def test_placeholder_resolves_to_matching_node_type_only():
    """relay-01 must not resolve to a lighting node — a rule for the relay role
    is unreachable when only a lighting node is paired."""
    await _register_node("node-light-9b2c", None, node_type="lighting")
    action = RuleAction(target="relay-01", channel="fae", state="on")
    error = await validate_action_channel(action)
    assert error is not None
    assert "relay" in error


async def test_unknown_target_gets_no_opinion():
    """Smart plugs and vendor override keys aren't nodes; don't block them."""
    action = RuleAction(target="smart-plug-7", channel="whatever", state="on")
    assert await validate_action_channel(action) is None


async def test_vendor_action_is_not_channel_checked():
    """Vendor writes route through the integrations dispatcher, not MQTT."""
    await _register_node("relay-01", RELAY_CHANNELS)
    action = RuleAction(
        target="vendor:kasa:10.0.0.5",
        channel="not-a-node-channel",
        state="on",
        vendor_slug="kasa",
        vendor_action="set_power",
    )
    assert await validate_action_channel(action) is None


async def test_config_action_without_channel_passes():
    await _register_node(RELAY_NODE, RELAY_CHANNELS)
    action = RuleAction(target="relay-01", state="on")
    assert await validate_action_channel(action) is None


# ─── API surface ───────────────────────────────────────────────────────


def _rule(channel: str) -> dict:
    return {
        "name": "Misting",
        "condition": {
            "type": "threshold",
            "threshold": {"sensor": "humidity", "operator": "lt", "value": 80},
        },
        "action": {"target": "relay-01", "channel": channel, "state": "on"},
    }


async def test_create_rule_rejects_unknown_channel(client):
    await _register_node(RELAY_NODE, RELAY_CHANNELS)

    response = client.post("/api/automation/rules", json=_rule("mister"))

    assert response.status_code == 422
    assert "aux" in response.json()["detail"]

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) AS n FROM automation_rules WHERE name = 'Misting'"
        )
        assert (await cursor.fetchone())["n"] == 0


async def test_create_rule_accepts_known_channel(client):
    await _register_node(RELAY_NODE, RELAY_CHANNELS)

    response = client.post("/api/automation/rules", json=_rule("aux"))

    assert response.status_code == 200
    assert response.json()["action"]["channel"] == "aux"


async def test_update_rule_rejects_unknown_channel(client):
    await _register_node(RELAY_NODE, RELAY_CHANNELS)
    rule_id = client.post("/api/automation/rules", json=_rule("aux")).json()["id"]

    response = client.put(f"/api/automation/rules/{rule_id}", json=_rule("mister"))

    assert response.status_code == 422
