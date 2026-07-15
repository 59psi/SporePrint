"""The emergency exhaust fires at the species' own edge, not a global 3000.

Salvaged from the parallel lifecycle work (SporePrint#48). The hardcoded 3000
was normal — even low — for a reishi antler fruiting (1000-10000ppm) or a
maitake rosette, so it fought species that legitimately hold CO2 high. Now
co2_emergency_ppm = the phase's co2_max_ppm + margin, and a profile-independent
40000ppm hard ceiling backstops sessions with no active grow profile.
"""
from app.species.models import PhaseParams
from app.automation.templates import BUILTIN_RULES


def _pp(co2_max, margin=1000):
    return PhaseParams(temp_min_f=60, temp_max_f=75, humidity_min=85, humidity_max=95,
                       co2_max_ppm=co2_max, co2_emergency_margin_ppm=margin,
                       co2_tolerance="moderate", light_hours_on=12, light_hours_off=12,
                       light_spectrum="none", fae_mode="scheduled",
                       expected_duration_days=(5, 10))


def test_emergency_edge_tracks_the_species_ceiling():
    assert _pp(800).co2_emergency_ppm == 1800     # oyster: emergency at 1800
    assert _pp(3000).co2_emergency_ppm == 4000    # maitake/wood_ear: 4000, not the old 3000
    assert _pp(5000).co2_emergency_ppm == 6000    # reishi antler: no longer vented at 3000


def test_property_is_reachable_via_getattr_for_profile_ref():
    # _eval_threshold resolves profile_ref through getattr — a @property must answer.
    assert getattr(_pp(2000), "co2_emergency_ppm") == 3000


def test_emergency_rule_is_species_relative_now():
    r = next(x for x in BUILTIN_RULES if x.name == "Emergency CO2 Exhaust")
    assert r.condition.threshold.profile_ref == "co2_emergency_ppm"
    assert r.condition.threshold.value is None


def test_hard_ceiling_is_profile_independent_and_far_above_any_grow():
    r = next(x for x in BUILTIN_RULES if x.name == "CO2 Hard Ceiling")
    assert r.condition.threshold.value == 40000     # above a 10-40k colonization
    assert r.applies_to_phases is None              # fires with no profile at all
    assert r.condition.threshold.profile_ref is None
