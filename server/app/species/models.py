from enum import Enum

from pydantic import BaseModel


class GrowPhase(str, Enum):
    AGAR = "agar"
    LIQUID_CULTURE = "liquid_culture"
    GRAIN_COLONIZATION = "grain_colonization"
    SUBSTRATE_COLONIZATION = "substrate_colonization"
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


class PhaseParams(BaseModel):
    temp_min_f: float
    temp_max_f: float
    temp_swing_required: bool = False
    temp_swing_delta_f: float | None = None
    humidity_min: float
    humidity_max: float
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
