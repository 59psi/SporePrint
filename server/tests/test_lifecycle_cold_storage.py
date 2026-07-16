"""Cold storage, the colonization fork, and sealed-container gating.

The product spec: a user inoculates something (agar / LC / grain / bag) and
colonizes it. A grow BAG then goes on to fruit (pinning → flushes). Everything
else is pulled once colonized and parked in the FRIDGE until used. And because
the CO2/RH sensors read chamber air — not the inside of a sealed vessel — the
chamber's environmental control is meaningless for a sealed bag or jar and must
not churn the fans against it.
"""

import pytest

from app.automation.engine import (
    _acts_on_chamber_environment,
    _cold_storage_params,
    _container_is_sealed,
)
from app.automation.models import RuleAction
from app.sessions.service import suggested_next_phase


# ── the colonization fork ─────────────────────────────────────────────────


def test_colonized_bag_advances_to_fruiting():
    for phase in ("grain_colonization", "substrate_colonization"):
        assert suggested_next_phase(phase, "grow_bag") == "primordia_induction"


def test_colonized_monotub_and_tray_fruit_in_place():
    # Bulk substrate (monotub, tray) fruits in place like a cut bag — it must not
    # be parked in cold storage. Regression for the container-fork fix.
    for container in ("monotub", "tray"):
        assert suggested_next_phase("substrate_colonization", container) == "primordia_induction"


def test_colonized_jar_and_agar_go_to_cold_storage():
    assert suggested_next_phase("grain_colonization", "jar") == "cold_storage"
    assert suggested_next_phase("agar", "agar_plate") == "cold_storage"
    assert suggested_next_phase("liquid_culture", "jar") == "cold_storage"


def test_non_colonization_transitions_stay_linear():
    assert suggested_next_phase("primordia_induction", "grow_bag") == "fruiting"
    assert suggested_next_phase("fruiting", "grow_bag") == "rest"


# ── cold storage params ───────────────────────────────────────────────────


def test_cold_storage_is_a_fridge_with_nothing_else_running():
    p = _cold_storage_params()
    assert 35 <= p.temp_min_f <= p.temp_max_f <= 45
    assert p.fae_mode == "none"
    assert p.light_hours_on == 0
    # never vent a fridge to "lower CO2"
    assert p.co2_max_ppm >= 10000


# ── sealed-container gating ────────────────────────────────────────────────


def test_a_sealed_bag_during_colonization_is_sealed():
    assert _container_is_sealed("grow_bag", "substrate_colonization") is True


def test_the_bag_is_open_once_it_fruits():
    """You cut the bag to fruit — CO2 control becomes real again."""
    assert _container_is_sealed("grow_bag", "fruiting") is False
    assert _container_is_sealed("grow_bag", "primordia_induction") is False


def test_jars_and_agar_are_always_sealed():
    assert _container_is_sealed("jar", "fruiting") is True
    assert _container_is_sealed("agar_plate", "primordia_induction") is True


def test_a_monotub_is_never_sealed():
    for phase in ("substrate_colonization", "fruiting"):
        assert _container_is_sealed("monotub", phase) is False
        assert _container_is_sealed("tray", phase) is False


def test_unknown_container_is_treated_as_open():
    """Don't over-gate — an unknown/legacy container keeps full control."""
    assert _container_is_sealed(None, "fruiting") is False


def test_environmental_actions_are_recognised():
    for chan in ("fae", "exhaust", "circulation", "aux"):
        assert _acts_on_chamber_environment(RuleAction(target="relay-01", channel=chan))
    for plug in ("plug-humidifier", "plug-dehumidifier"):
        assert _acts_on_chamber_environment(RuleAction(target=plug))
    # temperature actuators are NOT chamber-air — a heater warms the vessel too
    assert not _acts_on_chamber_environment(RuleAction(target="plug-heater"))
    assert not _acts_on_chamber_environment(RuleAction(target="light-01", scene="x"))
