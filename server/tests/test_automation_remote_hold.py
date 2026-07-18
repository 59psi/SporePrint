"""Remote automation hold — pause + rule-suspend wiring (GAPS V4-1/V4-2/V4-4).

Before this fix, cloud/service.py imported ``set_paused`` and ``suspend_rule``
from automation.engine but NEITHER existed, so every remote "pause automation" /
"suspend rule" command failed with "automation engine not available on this Pi"
— dead code. ``ManualOverride.expires_at`` also allowed null (a sticky-forever
hold) with no TTL clamp. These tests pin the fix:

  - ``set_paused`` short-circuits ``evaluate_rules`` (no actuator fires while
    paused), and the pause persists so it survives a reboot;
  - ``suspend_rule`` pins an expiring manual override on the rule's action
    target — the same mechanism the Pi LAN UI's suspend button uses;
  - ``ManualOverride`` clamps ``expires_at`` to a bounded, non-null TTL;
  - the cloud system-command dispatcher resolves both imports and drives them.
"""

import json
import time

import pytest

import app.automation.engine as engine
from app.automation.engine import (
    evaluate_rules,
    get_overrides,
    is_overridden,
    set_override,
    set_paused,
    suspend_rule,
)
from app.automation.models import (
    MAX_OVERRIDE_TTL_SECONDS,
    AutomationRule,
    ConditionType,
    ManualOverride,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule
from app.cloud.service import _dispatch_system_command
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session

# A real relay node registers under a MAC-derived id, DISTINCT from the seeded
# relay-01 placeholder that _seed_session_and_rule's rule names. (V4-1)
MAC_RELAY_NODE = "node-a3f1"


@pytest.fixture(autouse=True)
def _reset_pause_state():
    """Contain the pause flag within this module.

    conftest's ``_reset_engine_state`` clears the other engine globals but
    predates ``_paused`` / ``_pause_loaded``; reset them here (before AND after)
    so a paused test can't leak True into another test's ``evaluate_rules``.
    Each test also gets a fresh temp DB from the autouse ``_db`` fixture, so the
    persisted flag starts clean too.
    """
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


async def _seed_session_and_rule(*, cooldown_seconds: int = 0) -> int:
    """An active session + a rule whose condition a benign reading meets.

    Uses an unknown species id so ``get_profile`` returns None → phase_params is
    None → the species safety-threshold path is skipped, keeping the test
    deterministic and free of profile internals. The action channel is 'heater'
    (not air-exchange / chamber-env) so no fae_mode / sealed-container gate
    suppresses the fire. Returns the new rule's id.
    """
    await create_session(SessionCreate(
        name="remote-hold-test",
        species_profile_id="unit-test-species",
        substrate="CVG",
        current_phase="substrate_colonization",
    ))
    rule = AutomationRule(
        name="heat-on-when-cold",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=70),
        ),
        action=RuleAction(target="relay-01", channel="heater", state="on"),
        cooldown_seconds=cooldown_seconds,
    )
    return await create_rule(rule)


async def _register_node(node_id: str, node_type: str) -> None:
    """Register a firmware-v2 node so resolve_node_target maps the placeholder
    (relay-01) to this MAC-derived id at fire time."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type, json.dumps([node_type]), time.time()),
        )
        await db.commit()


# ── pause stops evaluate_rules ─────────────────────────────────────────────


async def test_remote_pause_short_circuits_evaluate_rules(mock_mqtt):
    await _seed_session_and_rule()
    cold = {"temp_f": 60}

    # Control: not paused → the rule fires (heater ON published).
    await evaluate_rules("relay-01", cold)
    assert any(t == "sporeprint/relay-01/cmd/heater" for t, _ in mock_mqtt), \
        "sanity: rule must fire when automation is not paused"
    fired = len(mock_mqtt)

    # Remote pause → the very same reading must drive nothing.
    await set_paused(True)
    await evaluate_rules("relay-01", cold)
    assert len(mock_mqtt) == fired, "paused engine must not fire any rule"

    # Resume → firing resumes (proves the pause was the cause, not cooldown).
    await set_paused(False)
    await evaluate_rules("relay-01", cold)
    assert len(mock_mqtt) > fired, "resume must re-enable rule firing"


async def test_pause_flag_persists_across_reload():
    """A remote pause must outlive a process restart (persisted to the DB)."""
    await set_paused(True)
    assert engine._paused is True

    # Simulate a restart: drop the in-memory flag + load gate, force a reload.
    engine._paused = False
    engine._pause_loaded = False
    await engine.ensure_pause_loaded()
    assert engine._paused is True, "pause flag was not persisted across reload"


# ── suspend_rule ───────────────────────────────────────────────────────────


async def test_suspend_rule_creates_expiring_override(mock_mqtt):
    rule_id = await _seed_session_and_rule()

    before = time.time()
    await suspend_rule(rule_id, minutes=10)

    # The rule's action target/channel is now overridden…
    assert is_overridden("relay-01", "heater") is True
    ov = next(
        o for o in await get_overrides()
        if o.target == "relay-01" and o.channel == "heater"
    )
    # …and the override is EXPIRING ~10 minutes out (not forever).
    assert ov.expires_at is not None
    assert 9.5 * 60 <= (ov.expires_at - before) <= 10.5 * 60
    assert "suspended" in ov.reason


async def test_suspended_rule_does_not_fire(mock_mqtt):
    """The end-to-end point of suspend: evaluate_rules skips the rule."""
    rule_id = await _seed_session_and_rule()
    await suspend_rule(rule_id, minutes=10)

    await evaluate_rules("relay-01", {"temp_f": 60})
    assert not any(t == "sporeprint/relay-01/cmd/heater" for t, _ in mock_mqtt), \
        "a suspended rule must not fire"


async def test_suspend_rule_unknown_id_raises():
    with pytest.raises(ValueError):
        await suspend_rule(999_999, minutes=10)


async def test_suspend_rule_clamps_absurd_duration(mock_mqtt):
    """A huge minutes value can't pin the actuator past the TTL ceiling."""
    rule_id = await _seed_session_and_rule()
    before = time.time()
    await suspend_rule(rule_id, minutes=100_000)  # ~69 days
    ov = next(o for o in await get_overrides() if o.target == "relay-01")
    assert ov.expires_at is not None
    assert ov.expires_at <= before + MAX_OVERRIDE_TTL_SECONDS + 1


# ── ManualOverride TTL clamp ───────────────────────────────────────────────


def test_override_null_expiry_is_clamped():
    before = time.time()
    ov = ManualOverride(target="relay-01", channel="heater")
    assert ov.expires_at is not None, "null 'forever' expiry must be clamped"
    assert (before + MAX_OVERRIDE_TTL_SECONDS - 1
            <= ov.expires_at
            <= time.time() + MAX_OVERRIDE_TTL_SECONDS + 1)


def test_override_overlong_expiry_is_clamped():
    ten_years = time.time() + 10 * 365 * 24 * 60 * 60
    ov = ManualOverride(target="relay-01", channel="heater", expires_at=ten_years)
    assert ov.expires_at <= time.time() + MAX_OVERRIDE_TTL_SECONDS + 1


def test_override_within_ceiling_expiry_is_preserved():
    soon = time.time() + 5 * 60
    ov = ManualOverride(target="relay-01", channel="heater", expires_at=soon)
    assert abs(ov.expires_at - soon) < 0.01, "a within-ceiling expiry must be untouched"


def test_override_past_expiry_is_preserved():
    """A past expiry stays past — several override paths read it as expired."""
    past = time.time() - 10
    ov = ManualOverride(target="relay-01", channel="heater", expires_at=past)
    assert abs(ov.expires_at - past) < 0.01


# ── cloud → engine wiring (the formerly-dead import path) ──────────────────


async def test_cloud_dispatch_automation_pause(mock_mqtt):
    """The cloud 'system'/'automation' command resolves set_paused and pauses."""
    ok, err = await _dispatch_system_command("automation", {"paused": True})
    assert ok is True and err is None
    assert engine._paused is True

    ok, err = await _dispatch_system_command("automation", {"paused": False})
    assert ok is True and err is None
    assert engine._paused is False


async def test_cloud_dispatch_rule_suspend(mock_mqtt):
    """The cloud 'system'/'rule' command resolves suspend_rule and overrides."""
    rule_id = await _seed_session_and_rule()
    ok, err = await _dispatch_system_command(
        "rule", {"rule_id": str(rule_id), "minutes": 15}
    )
    assert ok is True and err is None
    assert is_overridden("relay-01", "heater") is True


def test_engine_exports_pause_and_suspend_symbols():
    """Guard: cloud/service.py imports these by name; keep them importable."""
    from app.automation.engine import set_paused, suspend_rule  # noqa: F401


# ── manual hold on the resolved node survives the next tick (V4-1) ──────────


async def test_manual_hold_on_resolved_node_is_not_clawed_back(mock_mqtt):
    """A manual hold is stored under the node's RESOLVED MAC-derived id, but the
    seeded rule names the relay-01 placeholder. The override gate must resolve
    the rule's target before checking, or the rule re-fires on the next
    telemetry tick and claws back the operator's hold. (GAP V4-1)

    The existing suspend_rule tests place the override on relay-01 itself and
    register no real node, so they can't catch this — here the node is
    registered under a MAC-style id DISTINCT from the placeholder.
    """
    await _register_node(MAC_RELAY_NODE, "relay")
    await _seed_session_and_rule()
    resolved_topic = f"sporeprint/{MAC_RELAY_NODE}/cmd/heater"

    # Sanity: with no hold, the cold reading fires the heater on the RESOLVED
    # node's topic (proving the placeholder resolves to node-a3f1).
    await evaluate_rules(MAC_RELAY_NODE, {"temp_f": 60})
    assert any(t == resolved_topic for t, _ in mock_mqtt), \
        "sanity: seeded rule must fire on the resolved node when unheld"
    fired = len(mock_mqtt)

    # The operator pins a manual hold on the RESOLVED node — exactly what the
    # cloud override path does (set_override(target=node_id, …)), NOT relay-01.
    await set_override(ManualOverride(
        target=MAC_RELAY_NODE, channel="heater", locked=True,
        reason="manual hold", expires_at=time.time() + 600,
    ))

    # The very same reading must now drive nothing: the hold is respected even
    # though the rule names relay-01, not the resolved node.
    await evaluate_rules(MAC_RELAY_NODE, {"temp_f": 60})
    assert len(mock_mqtt) == fired, \
        "rule clawed back a manual hold placed on the resolved node"
