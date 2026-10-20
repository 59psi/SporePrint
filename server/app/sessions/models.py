from pydantic import BaseModel, Field


# Container classes: the one definition the automation engine's sealed-vessel
# gate and the phase-advance suggestion (sessions.service.suggested_next_phase)
# both read. Culture vessels stay sealed and park in cold storage once
# colonized; bags are sealed until opened to brown or fruit; open containers
# fruit in place with the substrate in the chamber air. A type in none of them
# (an older or hand-written spelling) is treated as open. The dashboards offer
# agar_plate, liquid_culture, grain_jar, grow_bag, monotub and tray.
CULTURE_CONTAINERS = frozenset({"jar", "grain_jar", "agar_plate", "agar", "liquid_culture"})
BAG_CONTAINERS = frozenset({"grow_bag", "bag", "bulk_bag"})
OPEN_CONTAINERS = frozenset({"monotub", "tray"})
FRUITING_CONTAINERS = BAG_CONTAINERS | OPEN_CONTAINERS

# "5 quarts", "12 x 1.5 L": the volume biological efficiency is read from.
SUBSTRATE_VOLUME_MAX_LENGTH = 100


class SessionCreate(BaseModel):
    name: str
    species_profile_id: str
    substrate: str | None = None
    substrate_volume: str | None = Field(default=None, max_length=SUBSTRATE_VOLUME_MAX_LENGTH)
    substrate_prep_notes: str | None = None
    inoculation_date: str | None = None
    inoculation_method: str | None = None
    spawn_source: str | None = None
    current_phase: str = "substrate_colonization"
    # One of the container classes above. Drives the colonization fork (bag →
    # fruiting; jar/agar/LC → cold storage) and gates environmental control
    # while the vessel is sealed. Defaults to an open monotub so existing
    # behaviour is unchanged.
    container_type: str = "monotub"
    tub_number: str | None = None
    shelf_number: int | None = None
    shelf_side: str | None = None  # "left" | "right"
    growth_form: str | None = None
    pinning_tek: str | None = None
    chamber_id: int | None = None


class SessionUpdate(BaseModel):
    name: str | None = None
    substrate: str | None = None
    substrate_volume: str | None = Field(default=None, max_length=SUBSTRATE_VOLUME_MAX_LENGTH)
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
    # The cloud's harvest bounds. There is no harvest edit or delete, and a
    # negative weight subtracted from the session's yield total (and flush 0
    # counted as a flush) in every stat, report and sync for good.
    flush_number: int = Field(ge=1, le=50)
    wet_weight_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    dry_weight_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    quality_rating: int | None = Field(default=None, ge=0, le=10)
    notes: str | None = None
    image_ids: list[int] | None = None


class ContaminationMark(BaseModel):
    """POST /api/sessions/{id}/contaminated: what was seen, both optional."""
    contamination_type: str | None = None
    notes: str | None = None


class DryingLogEntry(BaseModel):
    # A weighed batch: a zero or negative weight read as more than 100 %
    # moisture loss and announced "Drying Complete".
    weight_g: float = Field(gt=0, allow_inf_nan=False)
