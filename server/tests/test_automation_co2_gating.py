"""CO2 actuation must respect the phase and the species profile.

Three independent CO2 research passes found the same defect: the FAE and
exhaust rules had no phase gate, and the profiles' fae_mode was set 49 times
and read zero times. So during colonization — when mycelium WANTS CO2 held at
5000-15000 ppm with zero fresh air — the fans ran anyway, venting exactly what
the mycelium needs and drying the substrate. p. tampanensis' own profile note
says "No opening, no FAE. Patience is the entire technique" for a 60-120 day
sealed jar; the engine ran a fan at it the whole time.

These tests pin: FAE/exhaust are suppressed when the phase says fae_mode=none;
the CO2 rules only fire during fruiting phases; and the CO2 floor (reishi
antler, king trumpet primordia) is now profile-driven, not two hardcoded rules.
"""

from types import SimpleNamespace

from app.automation.engine import _is_air_exchange_action
from app.automation.models import RuleAction
from app.automation.templates import BUILTIN_RULES


def _rule(name):
    return next(r for r in BUILTIN_RULES if r.name == name)


# ── the fae_mode guard ────────────────────────────────────────────────────


def test_fae_and_exhaust_are_recognised_as_air_exchange():
    assert _is_air_exchange_action(RuleAction(target="relay-01", channel="fae"))
    assert _is_air_exchange_action(RuleAction(target="relay-01", channel="exhaust"))


def test_circulation_and_lights_are_not_air_exchange():
    """Circulation stirs air inside the chamber — it does not vent CO2. Nor do
    lights, plugs, or the mister. fae_mode=none must not suppress those."""
    for chan in ("circulation", "aux", "white", None):
        assert not _is_air_exchange_action(RuleAction(target="relay-01", channel=chan))


# ── phase gating of the CO2 rules ─────────────────────────────────────────


def test_co2_rules_are_fruiting_only():
    """Neither may run during colonization. Before this fix both were ungated
    and latched the fans on through the entire spawn run."""
    for name in ("CO2 FAE Trigger", "Emergency CO2 Exhaust"):
        rule = _rule(name)
        assert rule.applies_to_phases, f"{name} has NO phase gate — the exact bug"
        assert "primordia_induction" in rule.applies_to_phases
        assert "fruiting" in rule.applies_to_phases
        for colonization in ("grain_colonization", "substrate_colonization", "agar", "liquid_culture"):
            assert colonization not in rule.applies_to_phases, (
                f"{name} still fires during {colonization} — venting CO2 the mycelium needs"
            )


# ── the CO2 floor is now data, not two hardcoded species rules ────────────


def test_the_two_hardcoded_floor_rules_are_gone():
    names = {r.name for r in BUILTIN_RULES}
    assert "Reishi Antler CO2 Restrict FAE" not in names
    assert "King Trumpet Primordia CO2 Restrict" not in names


def test_there_is_one_profile_driven_floor_rule():
    floor = _rule("CO2 Floor — Restrict FAE")
    t = floor.condition.threshold
    assert t.profile_ref == "co2_min_ppm", "floor must read the species profile, not a constant"
    assert t.operator == "lt"
    assert floor.action.channel == "fae" and floor.action.state == "off"
    # It must NOT be pinned to reishi/king_trumpet — any species that sets a
    # floor gets the behaviour.
    assert floor.applies_to_species is None


def _profile(species_id):
    from app.species.profiles import BUILTIN_PROFILES
    return next(p for p in BUILTIN_PROFILES if p.id == species_id)


def test_reishi_and_king_trumpet_carry_the_floor_in_data():
    """De-hardcoding must not regress the two species that had the behaviour."""
    from app.species.models import GrowPhase

    reishi = _profile("reishi").phases[GrowPhase.PRIMORDIA_INDUCTION]
    assert reishi.co2_min_ppm == 1500

    kt = _profile("king_trumpet").phases[GrowPhase.PRIMORDIA_INDUCTION]
    assert kt.co2_min_ppm == 1000


def test_species_without_a_floor_do_not_trigger_it():
    """co2_min_ppm defaults to None; the `lt None` threshold must never fire.
    (The engine's _eval_threshold returns False when profile_ref resolves to
    None — this asserts the default keeps it None.)"""
    from app.species.models import GrowPhase

    oyster = _profile("pearl_oyster").phases[GrowPhase.FRUITING]
    assert oyster.co2_min_ppm is None
