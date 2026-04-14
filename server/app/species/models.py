from enum import Enum

from pydantic import BaseModel


class GrowPhase(str, Enum):
    AGAR = "agar"
    LIQUID_CULTURE = "liquid_culture"
    GRAIN_COLONIZATION = "grain_colonization"
    SUBSTRATE_COLONIZATION = "substrate_colonization"
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
