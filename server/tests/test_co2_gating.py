"""Gap 5 + CO2 audit: colonization is temp-only, and CO2 actuation is gated.

Three independent CO2 audits found the same root cause:
- "CO2 FAE Trigger" had NO phase gate and no fae_mode check, so it ran the FAE
  fan through the entire colonization run (where mycelium WANTS high CO2).
- "Emergency CO2 Exhaust" was a global hardcoded 3000 ppm with NO phase gate —
  it vented colonization CO2 and made reishi antler morphology (~3000 ppm)
  impossible.
- fae_mode ("none") was set 49 times and read zero times.

Post-fix: both CO2 rules are fruiting-side only; the engine refuses to vent when
fae_mode="none"; CO2 rules are skipped when the container seals the substrate
away from the sensor; and the emergency threshold is the species' own band, not
a global constant. The two hardcoded CO2 floors are now species-derived.
"""

import pytest

from app.automation.engine import _eval_threshold, evaluate_rules
from app.automation.models import (
    AutomationRule, ConditionType, RuleAction, RuleCondition, ThresholdCondition,
)
from app.automation.service import create_rule, seed_builtin_rules
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.models import PhaseParams
from app.species.service import seed_builtins


def _phase(**over):
    d = dict(
        temp_min_f=72, temp_max_f=76, humidity_min=85, humidity_max=92,
        co2_max_ppm=800, co2_tolerance="low", light_hours_on=12, light_hours_off=12,
        light_spectrum="daylight_6500k", fae_mode="scheduled", expected_duration_days=(7, 14),
    )
    d.update(over)
    return PhaseParams(**d)


async def _published(mock_mqtt, node_readings, phase, container=None,
                     species="blue_oyster", seed_rules=True):
    await seed_builtins()
    if seed_rules:
        await seed_builtin_rules()
    await create_session(SessionCreate(
        name="t", species_profile_id=species,
        current_phase=phase, container_type=container))
    await evaluate_rules("relay-01", node_readings, sio=None)
    return [t for (t, _p) in mock_mqtt]


def _fired(topics, suffix):
    return any(t.endswith(f"/cmd/{suffix}") for t in topics)


# ── Emergency band is species-derived, not a global 3000 ──────────────────

async def test_emergency_exhaust_does_not_vent_colonization(mock_mqtt):
    # 3500 ppm during colonization: pre-fix the global-3000 rule fired the
    # exhaust at full power. Post-fix colonization is not a venting phase.
    topics = await _published(mock_mqtt, {"co2_ppm": 3500}, "substrate_colonization",
                              container="monotub")
    assert not _fired(topics, "exhaust")
    assert not _fired(topics, "fae")


async def test_co2_fae_trigger_runs_in_fruiting(mock_mqtt):
    topics = await _published(mock_mqtt, {"co2_ppm": 2500}, "fruiting", container="monotub")
    assert _fired(topics, "fae")


async def test_reishi_antler_not_vented_at_3000(mock_mqtt):
    # Reishi antler morphology is induced around 3000 ppm. The emergency band is
    # co2_max_ppm + margin; reishi primordia runs CO2 high, so 3000 is nominal.
    topics = await _published(mock_mqtt, {"co2_ppm": 3000}, "primordia_induction",
                              container="monotub", species="reishi")
    assert not _fired(topics, "exhaust")


# ── fae_mode="none" means no venting, enforced in the engine ──────────────

async def test_fae_mode_none_blocks_user_fae_rule(mock_mqtt):
    await seed_builtins()
    # A user authors an un-gated FAE rule that WOULD fire during colonization.
    await create_rule(AutomationRule(
        name="user-fae", priority=5,
        applies_to_phases=["substrate_colonization", "fruiting"],
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="co2_ppm", operator="gt", value=100)),
        action=RuleAction(target="relay-01", channel="fae", state="on"),
    ))
    # blue_oyster substrate_colonization declares fae_mode="none".
    await create_session(SessionCreate(name="c", species_profile_id="blue_oyster",
                                       current_phase="substrate_colonization", container_type="monotub"))
    await evaluate_rules("relay-01", {"co2_ppm": 2500}, sio=None)
    assert not _fired([t for (t, _p) in mock_mqtt], "fae")


# ── Sealed container makes CO2 control meaningless ────────────────────────

async def test_sealed_container_suppresses_co2_rule(mock_mqtt):
    await seed_builtins()
    # A user CO2 rule that IS phase-allowed during colonization + fruiting.
    await create_rule(AutomationRule(
        name="user-co2-vent", priority=5,
        applies_to_phases=["fruiting"],
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="co2_ppm", operator="gt", value=100)),
        action=RuleAction(target="relay-01", channel="exhaust", state="on"),
    ))
    # A grow bag during fruiting is cut open → CO2 coupled → rule fires.
    await create_session(SessionCreate(name="bag", species_profile_id="blue_oyster",
                                       current_phase="fruiting", container_type="grow_bag"))
    await evaluate_rules("relay-01", {"co2_ppm": 2500}, sio=None)
    assert _fired([t for (t, _p) in mock_mqtt], "exhaust")


async def test_grain_jar_never_couples_co2(mock_mqtt):
    await seed_builtins()
    await create_rule(AutomationRule(
        name="user-co2-vent2", priority=5,
        applies_to_phases=["fruiting", "grain_colonization"],
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="co2_ppm", operator="gt", value=100)),
        action=RuleAction(target="relay-01", channel="exhaust", state="on"),
    ))
    await create_session(SessionCreate(name="jar", species_profile_id="blue_oyster",
                                       current_phase="grain_colonization", container_type="grain_jar"))
    await evaluate_rules("relay-01", {"co2_ppm": 5000}, sio=None)
    assert not _fired([t for (t, _p) in mock_mqtt], "exhaust")


# ── Species-derived thresholds resolve through profile_ref ────────────────

def test_co2_emergency_ppm_resolves():
    p = _phase(co2_max_ppm=800, co2_emergency_margin_ppm=1000)
    t = ThresholdCondition(sensor="co2_ppm", operator="gt", profile_ref="co2_emergency_ppm")
    assert _eval_threshold(t, {"co2_ppm": 1900}, p) is True   # > 1800 edge
    assert _eval_threshold(t, {"co2_ppm": 1700}, p) is False


def test_co2_floor_resolves_from_profile():
    """The de-hardcoded reishi/king_trumpet floors read co2_min_ppm."""
    p = _phase(co2_max_ppm=10000, co2_min_ppm=1500)
    t = ThresholdCondition(sensor="co2_ppm", operator="lt", profile_ref="co2_min_ppm")
    assert _eval_threshold(t, {"co2_ppm": 900}, p) is True    # below floor → hold FAE off
    assert _eval_threshold(t, {"co2_ppm": 2000}, p) is False


def test_co2_floor_absent_is_inert():
    """With no floor set (co2_min_ppm=None) the floor rule never fires."""
    p = _phase()  # co2_min_ppm defaults to None
    t = ThresholdCondition(sensor="co2_ppm", operator="lt", profile_ref="co2_min_ppm")
    assert _eval_threshold(t, {"co2_ppm": 100}, p) is False
