from enum import Enum

from pydantic import BaseModel


class GrowPhase(str, Enum):
    AGAR = "agar"
    LIQUID_CULTURE = "liquid_culture"
    GRAIN_COLONIZATION = "grain_colonization"
    SUBSTRATE_COLONIZATION = "substrate_colonization"
    # Terminal fork for culture / spawn vessels. A fully-colonized agar plate,
    # liquid culture or grain jar is not headed for a fruiting chamber — it goes
    # in the fridge until it is used to inoculate the next thing. This branches
    # OFF the colonization phases; it is not a step on the linear road to
    # fruiting, so it is deliberately absent from _PHASE_ORDER in sessions.
    COLD_STORAGE = "cold_storage"
    PRIMORDIA_INDUCTION = "primordia_induction"
    FRUITING = "fruiting"
    # REST is the between-flushes rest (substrate rehydrating before the next
    # flush) — NOT cold storage. The two were conflated before COLD_STORAGE
    # existed; they want opposite environments (REST: soaked, warm, dark).
    REST = "rest"
    COMPLETE = "complete"


class PhaseParams(BaseModel):
    temp_min_f: float
    temp_max_f: float
    temp_swing_required: bool = False
    temp_swing_delta_f: float | None = None
    humidity_min: float
    humidity_max: float
    co2_max_ppm: int
    co2_tolerance: str  # "low" | "moderate" | "high"
    light_hours_on: float
    light_hours_off: float
    light_spectrum: str  # "none" | "daylight_6500k" | "blue_450nm" | "blue_emphasis"
    light_lux_target: int | None = None
    fae_mode: str  # "none" | "passive" | "scheduled" | "continuous"
    fae_interval_min: int | None = None
    fae_duration_sec: int | None = None
    substrate_moisture: str = "field_capacity"
    expected_duration_days: tuple[int, int]
    notes: str = ""

    # ── CO2 floor (v4.3) ────────────────────────────────────────────────
    # co2_max_ppm is the CEILING (vent above it). Some species instead want CO2
    # held HIGH — reishi antler morphology, cordyceps, king trumpet primordia —
    # so they need a FLOOR: stop venting / hold FAE off below this. Two rules
    # already hardcoded such floors (reishi <1500, king_trumpet <1000); this
    # field de-hardcodes them so the value lives with the species, not the rule.
    # None = no floor (the common case: vent freely toward ambient).
    co2_min_ppm: int | None = None

    # ── Internal air circulation cadence (v4.3) ─────────────────────────
    # Distinct from FAE (fresh-air EXCHANGE, which vents CO2): circulation just
    # stirs the existing chamber air to break up CO2 stratification and stagnant
    # high-RH pockets. It does NOT vent, so it is safe during high-CO2 phases.
    # Species-tunable via the scheduler; sane defaults so the circulation fan
    # (sold in every Tier-2 kit) actually runs instead of sitting idle.
    circulation_interval_min: int = 30
    circulation_duration_sec: int = 120

    # ── Two-tier alert bands (v4.3) ─────────────────────────────────────
    # min/max above define the NOMINAL band — where automation steers, silently.
    # These margins say how far OUTSIDE nominal a reading must drift before the
    # operator is told, and how loudly:
    #     nominal            → automation corrects, no alert
    #     + warn margin      → WARNING   (ntfy priority 4, deduped)
    #     + emergency margin → EMERGENCY (ntfy priority 5, cloud critical push)
    # Per-species/per-phase because tolerance is a species trait: a tight-CO2
    # fruiting phase wants a narrow band; reishi antler formation runs CO2 high
    # on purpose and must not scream about it.
    #
    # Defaults: the EMERGENCY margins reproduce EXACTLY the single global
    # constants the engine used before tiers existed (temp 5F, CO2 1000 ppm), so
    # the critical tier's behaviour is unchanged. The WARNING margins are new and
    # sit strictly inside them. These are band WIDTHS, not cultivation values —
    # no species number is implied or changed by them.
    temp_warn_margin_f: float = 2.0
    temp_emergency_margin_f: float = 5.0
    humidity_warn_margin: float = 5.0
    humidity_emergency_margin: float = 10.0
    co2_warn_margin_ppm: int = 500
    co2_emergency_margin_ppm: int = 1000

    # Computed band edges — exposed as attributes so an automation rule can name
    # them through ThresholdCondition.profile_ref (e.g. the emergency-exhaust
    # rule fires on co2 > co2_emergency_ppm) exactly like it names co2_max_ppm.
    # A plain @property is reachable via getattr() on a pydantic-v2 instance,
    # which is all _eval_threshold needs; model_dump / round-trip ignore them.
    @property
    def co2_warn_ppm(self) -> int:
        return int(self.co2_max_ppm + self.co2_warn_margin_ppm)

    @property
    def co2_emergency_ppm(self) -> int:
        return int(self.co2_max_ppm + self.co2_emergency_margin_ppm)


# Cold storage is refrigeration, not cultivation: one fridge holds every
# species' plates and LC jars. Species that genuinely differ (pink oyster, which
# must NOT be refrigerated — see notifications.pink_oyster_harvest) can override
# by adding GrowPhase.COLD_STORAGE to their own `phases` dict; the resolver in
# species.service falls back to this default when they don't.
#
# Temperature is the product owner's stated fridge range. Humidity and CO2 are
# expressed as "don't care" (0-100 / high tolerance) the same way the AGAR and
# LIQUID_CULTURE phases already express ambient conditions — nothing steers a
# fridge, and inventing sensor numbers for it would be a lie.
DEFAULT_COLD_STORAGE = PhaseParams(
    temp_min_f=35,
    temp_max_f=40,
    humidity_min=0,
    humidity_max=100,
    co2_max_ppm=5000,
    co2_tolerance="high",
    light_hours_on=0,
    light_hours_off=24,
    light_spectrum="none",
    fae_mode="none",
    expected_duration_days=(30, 180),
    notes=(
        "Refrigerated storage for a fully-colonized culture or spawn vessel. "
        "No light, no FAE, no humidity steering — temperature only."
    ),
)


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
    category: str  # "gourmet" | "medicinal" | "active"
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
