"""Gap 1 + container model: COLD_STORAGE fork and CO2 physicality.

The product owner's spec: after full colonization a grow BAG moves on to
fruiting, but agar / liquid culture / grain jars are pulled and put in COLD
STORAGE (the fridge). REST (between-flush rehydration) is NOT cold storage.

Pre-fix state these pin:
- GrowPhase had no COLD_STORAGE member at all (AttributeError below).
- There was no container-aware fork; advance had no notion of it.
- Nothing knew that a sealed bag/jar decouples chamber CO2 from the substrate.
"""

import pytest

from app.species.models import DEFAULT_COLD_STORAGE, GrowPhase
from app.species.service import resolve_phase_params, get_profile, seed_builtins
from app.sessions.lifecycle import co2_control_meaningful, next_phase
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import advance_phase, create_session


def test_cold_storage_phase_exists():
    assert GrowPhase.COLD_STORAGE.value == "cold_storage"
    # It is deliberately distinct from REST (between-flushes rehydration).
    assert GrowPhase.COLD_STORAGE is not GrowPhase.REST


def test_cold_storage_default_is_fridge_temps_no_light_no_fae():
    p = DEFAULT_COLD_STORAGE
    assert 33 <= p.temp_min_f <= 40 and 35 <= p.temp_max_f <= 42
    assert p.light_hours_on == 0
    assert p.fae_mode == "none"


def test_fork_non_bag_goes_to_cold_storage():
    for c in ("agar_plate", "liquid_culture", "grain_jar"):
        assert next_phase("grain_colonization", c) == "cold_storage"
        assert next_phase("substrate_colonization", c) == "cold_storage"


def test_fork_grow_bag_goes_to_fruiting_path():
    assert next_phase("substrate_colonization", "grow_bag") == "primordia_induction"
    assert next_phase("grain_colonization", "monotub") == "primordia_induction"
    # Unknown container defaults to the fruiting path (most sessions are grows).
    assert next_phase("substrate_colonization", None) == "primordia_induction"


def test_fork_flush_cycle_is_fruiting_rest_fruiting():
    assert next_phase("primordia_induction", "grow_bag") == "fruiting"
    assert next_phase("fruiting", "grow_bag") == "rest"      # between-flush rest
    assert next_phase("rest", "grow_bag") == "fruiting"      # next flush
    assert next_phase("cold_storage", "agar_plate") == "complete"


def test_co2_meaningless_in_sealed_vessels():
    # Culture / spawn vessels are always sealed from the chamber sensor.
    assert co2_control_meaningful("agar_plate", "substrate_colonization") is False
    assert co2_control_meaningful("grain_jar", "grain_colonization") is False
    # A sealed grow bag during colonization: also decoupled.
    assert co2_control_meaningful("grow_bag", "substrate_colonization") is False
    # ...but cut open for fruiting: now coupled.
    assert co2_control_meaningful("grow_bag", "fruiting") is True
    # Monotub: substrate is in the sensed volume throughout.
    assert co2_control_meaningful("monotub", "substrate_colonization") is True
    # Unknown container must not silently disable CO2 control (legacy sessions).
    assert co2_control_meaningful(None, "fruiting") is True


async def test_resolver_falls_back_to_default_cold_storage():
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None
    # blue_oyster has no COLD_STORAGE phase authored, but the resolver supplies
    # the shared fridge default so the engine still knows the conditions.
    params = resolve_phase_params(profile, "cold_storage")
    assert params is not None
    assert params.fae_mode == "none" and params.light_hours_on == 0


async def test_advance_auto_forks_by_container():
    await seed_builtins()
    bag = await create_session(SessionCreate(
        name="bag", species_profile_id="blue_oyster",
        current_phase="substrate_colonization", container_type="grow_bag"))
    plate = await create_session(SessionCreate(
        name="plate", species_profile_id="blue_oyster",
        current_phase="grain_colonization", container_type="agar_plate"))

    bag = await advance_phase(bag["id"], PhaseAdvance(phase="auto"))
    plate = await advance_phase(plate["id"], PhaseAdvance(phase="auto"))

    assert bag["current_phase"] == "primordia_induction"
    assert plate["current_phase"] == "cold_storage"
