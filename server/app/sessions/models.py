from pydantic import BaseModel


class SessionCreate(BaseModel):
    name: str
    species_profile_id: str
    substrate: str | None = None
    substrate_volume: str | None = None
    substrate_prep_notes: str | None = None
    inoculation_date: str | None = None
    inoculation_method: str | None = None
    spawn_source: str | None = None
    current_phase: str = "substrate_colonization"
    tub_number: str | None = None
    shelf_number: int | None = None
    shelf_side: str | None = None  # "left" | "right"
    growth_form: str | None = None
    pinning_tek: str | None = None
    chamber_id: int | None = None


class SessionUpdate(BaseModel):
    name: str | None = None
    substrate: str | None = None
    substrate_volume: str | None = None
    substrate_prep_notes: str | None = None
    inoculation_date: str | None = None
    inoculation_method: str | None = None
    spawn_source: str | None = None
    tub_number: str | None = None
    shelf_number: int | None = None
    shelf_side: str | None = None
    growth_form: str | None = None
    pinning_tek: str | None = None


class PhaseAdvance(BaseModel):
    phase: str
    trigger: str = "manual"


class NoteCreate(BaseModel):
    text: str
    tags: list[str] | None = None
    image_id: int | None = None


class HarvestCreate(BaseModel):
    flush_number: int
    wet_weight_g: float | None = None
    dry_weight_g: float | None = None
    quality_rating: int | None = None
    notes: str | None = None
    image_ids: list[int] | None = None


class DryingLogEntry(BaseModel):
    weight_g: float
