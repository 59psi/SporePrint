from pydantic import BaseModel


class CultureCreate(BaseModel):
    type: str  # spore_syringe | agar | liquid_culture | grain_spawn | sawdust_spawn | spore_print | tissue_clone
    species_profile_id: str
    source: str  # vendor | clone | spore_print | transfer
    parent_id: int | None = None
    vendor_name: str | None = None
    lot_number: str | None = None
    notes: str | None = None
    spore_print_quality: str | None = None  # excellent | good | fair | poor
    tissue_source_location: str | None = None  # cap center | stem interior | stipe base
    storage_location: str | None = None


class CultureUpdate(BaseModel):
    status: str | None = None  # active | contaminated | depleted | archived
    notes: str | None = None
    storage_location: str | None = None
    spore_print_quality: str | None = None
