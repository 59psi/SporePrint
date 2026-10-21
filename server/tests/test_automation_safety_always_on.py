"""Stage-aware safety alerts are always on, and only where the stage drives them.

Safety DETECTION fires whatever the rules can do: a reading outside the active
stage range (but under the firmware's absolute limit) pages the operator even
while automation is paused or no rule is enabled. The stage check used to sit
after the `if _paused: return` and `if not rules: return` early returns in
evaluate_rules, so pausing automation, or disabling every rule, silently muted
the "closet is on fire" alert on every channel.

A phase that does not drive humidity (cold storage: a fridge idles at ~45 %
RH by design) never pages on low humidity. The gate is PhaseParams.
humidity_driven, not fae_mode: colonization has fae_mode "none" too, and does
drive humidity.
"""

import pytest

from app.automation.engine import evaluate_rules, load_rules, set_paused
from app.automation.service import seed_builtin_rules
from app.chambers.models import ChamberUpdate
from app.chambers.service import update_chamber
from app.sessions.models import PhaseAdvance
from app.sessions.service import advance_phase
from app.species.service import seed_builtins
from tests._builders import chamber, start_grow

SPECIES = "cubensis_golden_teacher"  # substrate colonization: 75-80 °F, RH 70-80


@pytest.mark.parametrize("cannot_act", ["paused", "no rules"])
async def test_a_stage_emergency_pages_even_when_automation_cannot_act(alerts, cannot_act):
    await seed_builtins()
    await start_grow(SPECIES, "substrate_colonization")
    if cannot_act == "paused":
        await seed_builtin_rules()   # rules to run: only the pause stops them
        await set_paused(True)
    else:
        assert await load_rules() == []

    await evaluate_rules("relay-01", {"temp_f": 120})  # past 80 °F + the 5 °F emergency margin

    assert [t for t, _ in alerts["critical"]] == ["Temperature EMERGENCY on relay-01"]
    assert [e for e, _ in alerts["forward"]] == ["temperature_alert"]


async def _jar_in_a_fridge() -> None:
    """A spawn jar in cold storage, run by the fridge chamber it is linked to:
    a cold-storage grow drives a node only through such a link."""
    closet = await chamber("Closet", ["climate-1"])
    fridge = await chamber("Fridge", ["fridge-1"])
    jar = await start_grow(SPECIES, "grain_colonization", container_type="grain_jar",
                           chamber_id=closet)
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await update_chamber(fridge, ChamberUpdate(active_session_id=jar["id"]))


@pytest.mark.parametrize("phase,readings,paged", [
    # A fridge at 38 °F and 45 % RH: in spec, and its humidity is not driven.
    ("cold_storage", {"temp_f": 38, "humidity": 45}, []),
    # The same idle humidity in a fridge that has warmed up: the cold-storage
    # band is in force, and only the temperature pages.
    ("cold_storage", {"temp_f": 50, "humidity": 45}, ["temperature_alert"]),
    # Colonization drives humidity (fae_mode "none" all the same): a crash
    # to 45 % pages.
    ("substrate_colonization", {"temp_f": 77, "humidity": 45}, ["humidity_alert"]),
])
async def test_only_a_phase_that_drives_humidity_pages_on_low_humidity(alerts, phase, readings,
                                                                       paged):
    await seed_builtins()
    if phase == "cold_storage":
        await _jar_in_a_fridge()
        node = "fridge-1"
    else:
        await start_grow(SPECIES, phase)
        node = "climate-1"

    await evaluate_rules(node, readings)

    assert [e for e, _ in alerts["forward"]] == paged
    assert len(alerts["critical"]) == len(paged)
