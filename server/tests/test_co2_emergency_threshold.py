"""The emergency exhaust fires at the species' own edge, not a global 3000.

The hardcoded 3000 ppm was normal, even low, for a species that fruits with
CO2 held high (wood ear 3000, enoki 5000, a reishi antler up to 10000), so the
exhaust fought them. co2_emergency_ppm is the phase's co2_max_ppm plus a
margin; the profile-independent CO2 Hard Ceiling (40000 ppm) backstops grows
with no profile (tests/test_automation_audit_rules.py).
"""

import pytest

from app.automation.engine import evaluate_rules
from app.automation.service import seed_builtin_rules
from app.species.models import PhaseParams
from app.species.service import seed_builtins
from tests._pi_a_engine import alerts, clock, engine_state, local, start_grow  # noqa: F401


@pytest.mark.parametrize("co2_max,margin,edge", [
    (800, 1000, 1800),     # oyster
    (3000, 1000, 4000),    # wood ear / maitake: not the old 3000
    (5000, 1000, 6000),    # reishi antler: no longer vented at 3000
    (5000, 250, 5250),     # a profile's own margin
])
def test_the_emergency_edge_is_the_phase_ceiling_plus_its_margin(co2_max, margin, edge):
    params = PhaseParams(
        temp_min_f=60, temp_max_f=75, humidity_min=85, humidity_max=95,
        co2_max_ppm=co2_max, co2_emergency_margin_ppm=margin, co2_tolerance="moderate",
        light_hours_on=12, light_hours_off=12, light_spectrum="none", fae_mode="scheduled",
        expected_duration_days=(5, 10),
    )
    assert params.co2_emergency_ppm == edge


@pytest.mark.parametrize("co2,vented", [(3500, False), (4500, True)])
async def test_the_emergency_exhaust_waits_for_the_species_edge(mock_mqtt, alerts, co2, vented):
    """Wood ear fruits at up to 3000 ppm: 3500 is above the old global 3000
    but inside its own edge (4000)."""
    await seed_builtins()
    await seed_builtin_rules()
    await start_grow("wood_ear", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": co2, "temp_f": 75})
    exhaust_on = [p for t, p in mock_mqtt if t.endswith("/cmd/exhaust") and p["state"] == "on"]
    assert bool(exhaust_on) is vented
