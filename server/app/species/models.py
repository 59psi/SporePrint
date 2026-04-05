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
