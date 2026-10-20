import math
from enum import Enum

from pydantic import BaseModel


class GrowPhase(str, Enum):
    AGAR = "agar"
    LIQUID_CULTURE = "liquid_culture"
    GRAIN_COLONIZATION = "grain_colonization"
    SUBSTRATE_COLONIZATION = "substrate_colonization"
    # Shiitake only (CLAUDE.md §4b): the colonized block, out of its bag, forms
    # a brown, popcorned outer skin and is NOT ready to fruit until that skin is
    # complete. Its own closet setpoints (60-70 °F, 70-80 % RH, passive FAE,
    # indirect light), so a profile must define it to enter it — there is no
    # fallback. substrate_colonization → browning → primordia_induction.
    BROWNING = "browning"
    # Fully colonized agar / LC / grain that is not going straight to fruiting
    # goes in the fridge to hold until use. Only temperature matters here — no
    # light, no FAE, no CO2 control. This is the fork the product spec describes:
    # a grow bag advances to PRIMORDIA_INDUCTION; everything else parks in
    # COLD_STORAGE.
    COLD_STORAGE = "cold_storage"
    PRIMORDIA_INDUCTION = "primordia_induction"
    FRUITING = "fruiting"
    REST = "rest"
    COMPLETE = "complete"


# The lifecycle's stage groups, defined once for every module that branches on
# them (sessions, the automation engine, vision). The colonization stages run
# in a sealed vessel (plate, LC jar, grain jar, bag); the fruiting stages are
# the ones mushrooms form in.
COLONIZATION_PHASES = frozenset({
    GrowPhase.AGAR.value, GrowPhase.LIQUID_CULTURE.value,
    GrowPhase.GRAIN_COLONIZATION.value, GrowPhase.SUBSTRATE_COLONIZATION.value,
})
FRUITING_PHASES = frozenset({GrowPhase.PRIMORDIA_INDUCTION.value, GrowPhase.FRUITING.value})


class PhaseParams(BaseModel):
    temp_min_f: float
    temp_max_f: float
    temp_swing_required: bool = False
    temp_swing_delta_f: float | None = None
    humidity_min: float
    humidity_max: float
    # Whether the chamber actively drives humidity in this phase. Default True
    # (every cultivation phase mists/dehumidifies toward the band). Cold storage
    # sets this False: a fridge's ~45% RH is incidental, not a fault, so the
    # safety monitor must not page a low-humidity EMERGENCY every frame there.
    # Mirrors the fae_mode="none" gate that already suppresses CO2 alerts.
    humidity_driven: bool = True
    co2_max_ppm: int
    # Some species want CO2 held HIGH, not just capped — reishi antler formation
    # and king trumpet primordia both restrict FAE below a floor. This was two
    # hardcoded rules (templates.py) before; now it is data. None = no floor.
    co2_min_ppm: int | None = None
    co2_tolerance: str  # "low" | "moderate" | "high"
    # Provenance for the CO2 figure. Most values in the library are class-based
    # inference, not measured — and the user cannot tell them apart because they
    # render identically. Default False (honest): opt IN to claiming a citation.
    co2_sourced: bool = False
    co2_source: str | None = None  # citation string; renders in the UI when set
    # The emergency exhaust used to fire at a hardcoded 3000ppm — which is normal
    # for a reishi antler fruiting (1000-10000ppm) or a maitake rosette, so the
    # global threshold fought species that legitimately hold CO2 high. Now it
    # fires at the species' OWN edge (co2_max_ppm + this margin), exposed as a
    # computed property so a rule can name it via profile_ref like any field.
    co2_emergency_margin_ppm: int = 1000

    @property
    def co2_emergency_ppm(self) -> int:
        return int(self.co2_max_ppm + self.co2_emergency_margin_ppm)

    light_hours_on: float
    light_hours_off: float
    light_spectrum: str  # "none" | "daylight_6500k" | "blue_450nm" | "blue_emphasis"
    light_lux_target: int | None = None
    fae_mode: str  # "none" | "passive" | "scheduled" | "continuous"
    fae_interval_min: int | None = None
    fae_duration_sec: int | None = None
    # Optional per-phase override for the internal circulation cadence. None =
    # use the Circulation Cycle rule's default. Left None on every species for
    # now — a real value belongs to the cultivation research, not to code.
    circulation_interval_min: int | None = None
    substrate_moisture: str = "field_capacity"
    expected_duration_days: tuple[int, int]
    notes: str = ""
    # A MANUAL step due when a session leaves this phase — shiitake browning's
    # cold-water soak, the pinning trigger the closet cannot perform. "" = none.
    # The daily phase reminder offers it once the phase has run its minimum
    # expected duration, GET /api/sessions/{id}/next-phase returns it, and
    # advancing out of the phase logs it to the session (phase_exit_reminder).
    exit_reminder: str = ""


class TekStep(BaseModel):
    step_number: int
    title: str
    description: str
    duration: str
    tips: list[str] = []
    common_mistakes: list[str] = []


class SubstrateRecipe(BaseModel):
    name: str  # "CVG", "Masters Mix", "Supplemented Sawdust"
    ingredients: dict[str, str]  # {"coco coir": "650g", "vermiculite": "2 quarts", ...}
    water_liters_per_liter_substrate: float
    spawn_rate_percent: int  # 5-20%
    sterilization_method: str  # "pasteurize_hot_water" | "pasteurize_cold_lime" | "pressure_sterilize"
    sterilization_time_min: int
    sterilization_temp_f: int | None = None
    suitability: str  # "optimal" | "good" | "acceptable"
    notes: str = ""


class SpeciesProfile(BaseModel):
    id: str
    common_name: str
    scientific_name: str
    category: str  # "gourmet" | "medicinal" | "active" | "novelty"
    # Some profiles are useful REFERENCE but not chamber-cultivable (chaga is a
    # sclerotium on a living birch over ~10 years; pestalotiopsis is an endophyte
    # with no fruit body). False ⇒ excluded from automation-enabled sessions and
    # the UI shows cultivation_note instead of a phase setpoint table.
    chamber_cultivable: bool = True
    cultivation_note: str = ""
    strain: str | None = None
    substrate_types: list[str]
    colonization_visual_description: str
    contamination_risk_notes: str
    pinning_trigger_description: str
    phases: dict[GrowPhase, PhaseParams]
    flush_count_typical: int
    yield_notes: str
    tags: list[str] = []
    tldr: str = ""  # One-paragraph summary of growing conditions + key tips
    flavor_profile: str = ""  # Culinary description (or "Not edible" for non-food species)
    edible: bool = True  # False = NOT safe for human consumption (display prominent warning)
    safety_warning: str = ""  # Red warning text displayed prominently (e.g., "NOT EDIBLE" or legal disclaimer)
    legal_disclaimer: str = ""  # Legal notice for active species (jurisdiction check)
    tek_guide: list[TekStep] = []
    substrate_recipes: list[SubstrateRecipe] = []
    substrate_preference_ranking: list[str] = []  # ordered best→worst
    contamination_risks: list[str] = []  # species-specific contamination vulnerabilities
    regional_notes: str = ""  # sourcing / availability notes
    photo_references: dict[str, str] = {}  # phase → reference URL, e.g., {"fruiting": "https://..."}
    # How a harvest must be handled at once, for a species that cannot wait
    # (pink oyster cannot be refrigerated; shaggy mane dissolves into ink
    # within hours). Recording a harvest sends it as a CRITICAL notification.
    # "" = none.
    harvest_notice: str = ""

    def phase_exit_reminder(self, phase: str) -> str | None:
        """The manual step due when a session leaves ``phase``, or None.

        PhaseParams.exit_reminder of a phase this profile itself defines —
        shiitake browning's cold-water soak. A phase running on a
        PHASE_PARAM_FALLBACKS stand-in does not inherit the stand-in's step.
        """
        try:
            params = self.phases.get(GrowPhase(phase))
        except ValueError:
            return None
        return (params.exit_reminder or None) if params is not None else None


def _finite(*values: float | None) -> bool:
    return all(v is None or math.isfinite(v) for v in values)


def phase_params_problems(params: PhaseParams) -> list[str]:
    """What makes a phase's setpoints unusable for automation, or [].

    The rules drive the heater below temp_min_f and the cooler above
    temp_max_f (the humidifier and dehumidifier the same way on the humidity
    band), so a swapped band runs both against each other and its cutoffs can
    never hold. Checked when a profile is written (species.service); a row
    already stored is read as it is.
    """
    problems: list[str] = []
    if not _finite(params.temp_min_f, params.temp_max_f, params.humidity_min,
                   params.humidity_max, params.light_hours_on, params.light_hours_off,
                   params.temp_swing_delta_f):
        return ["every number must be finite"]
    if params.temp_min_f > params.temp_max_f:
        problems.append(f"temp_min_f {params.temp_min_f:g} is above temp_max_f {params.temp_max_f:g}")
    if not 0 <= params.humidity_min <= 100 or not 0 <= params.humidity_max <= 100:
        problems.append("humidity_min and humidity_max must be within 0-100")
    if params.humidity_min > params.humidity_max:
        problems.append(
            f"humidity_min {params.humidity_min:g} is above humidity_max {params.humidity_max:g}")
    if params.co2_max_ppm <= 0:
        problems.append("co2_max_ppm must be above 0")
    if params.co2_min_ppm is not None and not 0 <= params.co2_min_ppm <= params.co2_max_ppm:
        problems.append(
            f"co2_min_ppm {params.co2_min_ppm} must be within 0-co2_max_ppm ({params.co2_max_ppm})")
    if params.co2_emergency_margin_ppm < 0:
        problems.append("co2_emergency_margin_ppm must not be negative")
    on, off = params.light_hours_on, params.light_hours_off
    if not 0 <= on <= 24 or not 0 <= off <= 24 or abs(on + off - 24) > 1e-6:
        problems.append(
            f"light_hours_on {on:g} and light_hours_off {off:g} must each be within 0-24 "
            "and add up to 24")
    lo, hi = params.expected_duration_days
    if not 0 <= lo <= hi:
        problems.append(f"expected_duration_days ({lo}, {hi}) must be 0 <= min <= max")
    for name in ("fae_interval_min", "fae_duration_sec", "circulation_interval_min"):
        value = getattr(params, name)
        if value is not None and value <= 0:
            problems.append(f"{name} must be above 0")
    if params.temp_swing_delta_f is not None and params.temp_swing_delta_f < 0:
        problems.append("temp_swing_delta_f must not be negative")
    if params.light_lux_target is not None and params.light_lux_target < 0:
        problems.append("light_lux_target must not be negative")
    return problems


def profile_problems(profile: SpeciesProfile) -> list[str]:
    """phase_params_problems for every phase of `profile`, each named by its phase."""
    return [f"{phase.value}: {problem}"
            for phase, params in profile.phases.items()
            for problem in phase_params_problems(params)]
