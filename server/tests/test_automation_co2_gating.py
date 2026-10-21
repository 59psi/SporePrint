"""CO2 actuation must respect the phase and the species profile.

Three independent CO2 research passes found the same defect: the FAE and
exhaust rules had no phase gate, and the profiles' fae_mode was set 49 times
and read zero times. So during colonization — when mycelium WANTS CO2 held at
5000-15000 ppm with zero fresh air — the fans ran anyway, venting exactly what
the mycelium needs and drying the substrate.

These tests pin: FAE/exhaust are what fae_mode=none suppresses; the CO2 rules
only fire during fruiting phases; and the CO2 floor (reishi antler, king
trumpet primordia) is profile-driven, not two hardcoded rules (those are
retired: tests/test_builtin_rule_upgrades.py).
"""

import pytest

from app.automation.engine import _is_air_exchange_action, _Target
from app.automation.models import RuleAction
from app.automation.templates import BUILTIN_RULES
from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES


def _rule(name):
    return next(r for r in BUILTIN_RULES if r.name == name)


def _plug(role: str) -> _Target:
    return _Target("plug-a1", frozenset({"plug-a1"}), plug=True, role=role)


@pytest.mark.parametrize("channel,target,exchanges_air", [
    ("fae", None, True),
    ("exhaust", None, True),
    # Circulation stirs the chamber's air; it vents no CO2. Nor do the
    # mister, the lights or a bare config command.
    ("circulation", None, False),
    ("aux", None, False),
    ("white", None, False),
    (None, None, False),
    # A plug-driven fan is judged by the plug's role.
    (None, _plug("exhaust"), True),
    (None, _plug("humidifier"), False),
])
def test_only_fae_and_exhaust_exchange_the_chambers_air(channel, target, exchanges_air):
    """fae_mode=none suppresses exactly these."""
    action = RuleAction(target="relay-01", channel=channel)
    assert _is_air_exchange_action(action, target) is exchanges_air


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


def test_there_is_one_profile_driven_floor_rule():
    floor = _rule("CO2 Floor — Restrict FAE")
    t = floor.condition.threshold
    assert t.profile_ref == "co2_min_ppm", "floor must read the species profile, not a constant"
    assert t.operator == "lt"
    assert floor.action.channel == "fae" and floor.action.state == "off"
    # Not pinned to reishi / king trumpet: any species that sets a floor gets it.
    assert floor.applies_to_species is None


def test_reishi_and_king_trumpet_carry_the_floor_in_data():
    """De-hardcoding must not regress the two species that had the behaviour."""
    profiles = {p.id: p for p in BUILTIN_PROFILES}
    assert profiles["reishi"].phases[GrowPhase.PRIMORDIA_INDUCTION].co2_min_ppm == 1500
    assert profiles["king_trumpet"].phases[GrowPhase.PRIMORDIA_INDUCTION].co2_min_ppm == 1000
