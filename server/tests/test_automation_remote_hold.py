"""Remote automation holds: the cloud's pause and rule-suspend commands.

cloud/service.py used to import ``set_paused`` and ``suspend_rule`` from the
engine while neither existed, so every remote "pause automation" / "suspend
rule" failed with "automation engine not available on this Pi". These pin:

  - ``set_paused`` stops evaluate_rules driving any actuator, and the pause
    survives a reboot;
  - ``suspend_rule`` pins an expiring hold on the rule's own target/channel,
    the mechanism the Pi's own suspend button uses, clamped to the hold TTL;
  - the cloud system-command dispatcher reaches both (suspend by an int or
    a numeric-string rule id: tests/test_cloud_rule_id_contract.py).
"""

import time

import pytest

import app.automation.engine as engine
from app.automation.engine import (
    evaluate_rules,
    get_overrides,
    set_override,
    set_paused,
    suspend_rule,
)
from app.automation.models import MAX_OVERRIDE_TTL_SECONDS, ManualOverride, RuleAction
from app.automation.service import create_rule
from app.cloud.service import _dispatch_system_command
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    engine_state,
    make_rule,
    register_node,
    start_grow,
    threshold,
)

# A real relay registers under a MAC-derived id, distinct from the relay-01
# placeholder the rule names.
MAC_RELAY_NODE = "node-a3f1"
COLD = {"temp_f": 60}


async def _grow_and_heat_rule() -> int:
    """An active grow and a rule the COLD frame meets.

    The species id is unknown, so the grow has no setpoints: no stage alert
    runs, and only the rule decides. The action is a heater (not air
    exchange or chamber air), so no fae_mode / sealed-container gate applies.
    """
    await start_grow("unit-test-species", "substrate_colonization")
    return await create_rule(make_rule(
        RuleAction(target="relay-01", channel="heater", state="on"),
        condition=threshold("temp_f", "lt", 70), name="heat-on-when-cold", rule_id=None,
        cooldown_seconds=0,
    ))


def _heater_cmds(mock_mqtt, node="relay-01"):
    return [t for t, _ in mock_mqtt if t == f"sporeprint/{node}/cmd/heater"]


async def test_remote_pause_short_circuits_evaluate_rules(mock_mqtt):
    await _grow_and_heat_rule()
    await evaluate_rules("relay-01", COLD)
    assert len(_heater_cmds(mock_mqtt)) == 1, "the rule fires while automation runs"

    await set_paused(True)
    await evaluate_rules("relay-01", COLD)
    assert len(_heater_cmds(mock_mqtt)) == 1, "a paused engine fires no rule"

    await set_paused(False)
    await evaluate_rules("relay-01", COLD)
    assert len(_heater_cmds(mock_mqtt)) == 2, "resuming fires again (not a cooldown)"


async def test_a_cloud_pause_survives_a_restart_and_a_resume_clears_it():
    assert await _dispatch_system_command("automation", {"paused": True}) == (True, None)
    engine._paused = False          # a restart: the flag reloads from the table
    engine._pause_loaded = False
    await engine.ensure_pause_loaded()
    assert engine._paused is True
    assert await _dispatch_system_command("automation", {"paused": False}) == (True, None)
    engine._pause_loaded = False
    await engine.ensure_pause_loaded()
    assert engine._paused is False


@pytest.mark.parametrize("minutes,held_for", [
    (10, 10 * 60),
    (100_000, MAX_OVERRIDE_TTL_SECONDS),   # ~69 days: no longer than the hold ceiling
])
async def test_a_suspended_rule_is_held_off_for_its_window(mock_mqtt, minutes, held_for):
    rule_id = await _grow_and_heat_rule()
    before = time.time()
    await suspend_rule(rule_id, minutes=minutes)

    (hold,) = await get_overrides()
    assert (hold.target, hold.channel) == ("relay-01", "heater")
    assert "suspended" in hold.reason
    assert hold.expires_at == pytest.approx(before + held_for, abs=30)
    await evaluate_rules("relay-01", COLD)
    assert _heater_cmds(mock_mqtt) == [], "a suspended rule does not fire"


async def test_suspend_rule_unknown_id_raises():
    with pytest.raises(ValueError):
        await suspend_rule(999_999, minutes=10)


async def test_manual_hold_on_resolved_node_is_not_clawed_back(mock_mqtt):
    """A hold is stored under the node's resolved MAC-derived id (the cloud
    override path pins the real node), while the seeded rule names relay-01.
    The engine must resolve the rule's target before checking, or the rule
    re-fires on the next frame and claws back the operator's hold."""
    await register_node(MAC_RELAY_NODE, "relay")
    await _grow_and_heat_rule()
    await evaluate_rules(MAC_RELAY_NODE, COLD)
    assert len(_heater_cmds(mock_mqtt, MAC_RELAY_NODE)) == 1, "the placeholder resolves to the node"

    await set_override(ManualOverride(target=MAC_RELAY_NODE, channel="heater",
                                      reason="manual hold", expires_at=time.time() + 600))
    await evaluate_rules(MAC_RELAY_NODE, COLD)
    assert len(_heater_cmds(mock_mqtt, MAC_RELAY_NODE)) == 1
