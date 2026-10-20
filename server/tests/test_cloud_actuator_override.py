"""Cloud manual actuator override — the relay-path twin of the Pi's LAN
POST/DELETE /api/automation/overrides (closes the cloud→Pi override half).

The cloud's POST /devices/{id}/actuator emits TWO frames per manual toggle: the
raw relay command (already handled Pi-side → MQTT publish) AND an
`automation`/`override` command so the rules engine doesn't re-flip the manual
change on its next tick. Before this fix the Pi rejected the second frame
outright (`automation` wasn't an accepted target_kind), so a manual cloud toggle
lived only until the next telemetry tick, then automation clawed it back.

These pin the Pi-side handling of that second frame:
  - set     → an expiring ManualOverride on the actuator's node/channel;
  - release → the override is cleared and automation resumes control.

Driven through the importable `_dispatch_automation_command` seam. That the
hold runs `duration_sec` on the Pi's own clock, whatever the cloud's
expires_at says, is test_override_duration.py.
"""

import time

import pytest

from app.automation.engine import get_overrides, is_overridden
from app.automation.models import MAX_OVERRIDE_TTL_SECONDS
from app.cloud.service import _dispatch_automation_command
from tests._pi_b2_cloud import register_node

RELAY_BANK = ["aux", "circulation", "exhaust", "fae"]
LIGHT_BANK = ["blue", "far_red", "red", "white"]

# (node_id, node_type, reported channels or None)
_UNREPORTED_RELAY = ("relay-01", "relay", None)
_UNREPORTED_LIGHT = ("light-01", "lighting", None)
_RELAY_BANK_NODE = ("node-relay-1", "relay", RELAY_BANK)
_LIGHT_BANK_NODE = ("node-light-1", "lighting", LIGHT_BANK)


async def _register(*nodes) -> None:
    for node_id, node_type, channels in nodes:
        await register_node(node_id, node_type, roles=[node_type], channels=channels)


async def _set(channel: str, **payload):
    return await _dispatch_automation_command(
        "override", {"channel": channel, "state": "on", **payload})


async def _override(channel: str):
    return next(o for o in await get_overrides() if o.channel == channel)


# ── set registers an expiring override ─────────────────────────────────────


async def test_a_set_pins_the_channel_for_its_duration_not_forever():
    """A cloud 'set' pins the fan's relay channel out of automation's reach,
    locked and expiring — not a sticky-forever hold. A NaN expires_at (it
    compares false against every deadline) beside the duration changes
    nothing."""
    await _register(_UNREPORTED_RELAY)
    before = time.time()
    assert await _set("fae", duration_sec=300, expires_at=float("nan")) == (True, None)
    assert is_overridden("relay-01", "fae") is True
    ov = await _override("fae")
    assert ov.target == "relay-01" and ov.locked is True
    assert 4.5 * 60 <= ov.expires_at - before <= 5.5 * 60


@pytest.mark.parametrize("nodes, channel, node", [
    # A node that has not reported its channels is found by the channel's bank.
    ([_UNREPORTED_RELAY, _UNREPORTED_LIGHT], "fae", "relay-01"),
    # white is a lighting-bank channel → the lighting node (what a light
    # rule's action targets), not the relay node.
    ([_UNREPORTED_RELAY, _UNREPORTED_LIGHT], "white", "light-01"),
    # exhaust (relay) and far_red (lighting) were refused as mapping to no
    # node, though both banks report them.
    ([_RELAY_BANK_NODE, _LIGHT_BANK_NODE], "exhaust", "node-relay-1"),
    ([_RELAY_BANK_NODE, _LIGHT_BANK_NODE], "far_red", "node-light-1"),
], ids=["unreported-relay", "unreported-lighting", "reported-relay", "reported-lighting"])
async def test_the_override_lands_on_the_node_that_has_the_channel(nodes, channel, node):
    await _register(*nodes)
    assert await _set(channel, duration_sec=300) == (True, None)
    assert is_overridden(node, channel) is True
    assert [o.target for o in await get_overrides()] == [node]


# ── release clears the override ────────────────────────────────────────────


async def test_override_release_clears_override():
    """A cloud 'release' clears the hold so automation resumes control."""
    await _register(_UNREPORTED_RELAY)
    assert (await _set("aux", duration_sec=600))[0] is True
    assert is_overridden("relay-01", "aux") is True

    ok, err = await _dispatch_automation_command("override", {"channel": "aux", "release": True})
    assert (ok, err) == (True, None)
    assert is_overridden("relay-01", "aux") is False
    assert await get_overrides() == []


# ── an expiry the Pi cannot honour ─────────────────────────────────────────


@pytest.mark.parametrize("expiry", [
    lambda now: now + 10 * 365 * 24 * 3600,
    lambda now: float("nan"),
    lambda now: float("inf"),
], ids=["ten-years", "nan", "inf"])
async def test_an_expiry_past_the_ceiling_or_not_finite_is_held_to_the_ceiling(expiry):
    """With no duration, a fat-fingered or non-finite expiry is clamped to
    the Pi's 24 h ceiling: it can't pin the actuator for a year, and NaN can't
    make a hold that never reads as expired."""
    await _register(_UNREPORTED_RELAY)
    before = time.time()
    assert (await _set("fae", expires_at=expiry(before)))[0] is True
    ov = await _override("fae")
    assert before < ov.expires_at <= before + MAX_OVERRIDE_TTL_SECONDS + 1
    assert is_overridden("relay-01", "fae") is True


async def test_a_zero_expiry_reads_as_expired():
    await _register(_UNREPORTED_RELAY)
    assert (await _set("fae", expires_at=0))[0] is True
    assert is_overridden("relay-01", "fae") is False


# ── honest refusal, never a crash and never a silent success ──────────────


@pytest.mark.parametrize("nodes, channel, payload, error", [
    # A smart-plug/unknown channel (heater/pump → no relay/lighting node).
    ([], "override", {"channel": "heater", "state": "on", "duration_sec": 600},
     "Channel 'heater' maps to no relay/lighting node"),
    ([], "override", {"channel": "fae", "release": True}, "No registered relay node"),
    ([], "override", {"state": "on"}, "automation override requires payload.channel"),
    ([], "bogus", {"channel": "fae"}, "Unknown automation channel 'bogus'"),
    ([("relay-a", "relay", RELAY_BANK), ("relay-b", "relay", RELAY_BANK)], "override",
     {"channel": "fae", "state": "on", "duration_sec": 300}, "Ambiguous target"),
], ids=["unmappable-channel", "no-node", "no-channel", "unknown-channel", "two-candidates"])
async def test_an_override_the_pi_cannot_place_is_refused_and_registers_nothing(
        nodes, channel, payload, error):
    await _register(*nodes)
    ok, err = await _dispatch_automation_command(channel, payload)
    assert ok is False
    assert err.startswith(error), err
    assert await get_overrides() == []
