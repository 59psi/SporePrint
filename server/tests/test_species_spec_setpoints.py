"""Built-in profile setpoints must match the authoritative CLAUDE.md §4b tables.

The CO2 ceiling (co2_max_ppm) drives the CO2→FAE rule and the warning /
emergency bands, so a ceiling above the spec means fresh air arrives only after
the fruit has already etiolated. (audit srv-rest#17, #18, #19)
"""

from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES

_P = {p.id: p for p in BUILTIN_PROFILES}


def _phase(species_id, phase):
    return _P[species_id].phases[phase]


def test_pink_oyster_fruiting_co2_ceiling_is_700():
    # §4b Pink Oyster: Fruiting | 70–85 | 85–95 | < 700
    fr = _phase("pink_oyster", GrowPhase.FRUITING)
    assert fr.co2_max_ppm == 700
    assert (fr.temp_min_f, fr.temp_max_f) == (70, 85)
    assert (fr.humidity_min, fr.humidity_max) == (85, 95)


def test_cordyceps_primordia_and_fruiting_co2_ceiling_is_800():
    # §4b Cordyceps militaris: Primordia < 800, Fruiting < 800
    assert _phase("cordyceps_militaris", GrowPhase.PRIMORDIA_INDUCTION).co2_max_ppm == 800
    assert _phase("cordyceps_militaris", GrowPhase.FRUITING).co2_max_ppm == 800


def test_king_trumpet_fruiting_co2_ceiling_is_1000():
    # §4b King Trumpet: Fruiting | 58–65 | 80–90 | < 1000
    fr = _phase("king_trumpet", GrowPhase.FRUITING)
    assert fr.co2_max_ppm == 1000
    assert fr.co2_min_ppm is None
    assert fr.co2_tolerance != "high"


def test_king_trumpet_primordia_keeps_its_elevated_co2_window():
    # §4b King Trumpet: Primordia 1000–2000 ppm (the species-unique inversion).
    pr = _phase("king_trumpet", GrowPhase.PRIMORDIA_INDUCTION)
    assert (pr.co2_min_ppm, pr.co2_max_ppm) == (1000, 2000)
