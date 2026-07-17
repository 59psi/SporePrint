from datetime import date as _date

from pydantic import BaseModel, field_validator

PLANNED_EVENT_KINDS = {"inoculate", "transfer", "harvest-window", "maintenance", "custom"}


def _check_kind(v: str) -> str:
    if v not in PLANNED_EVENT_KINDS:
        raise ValueError(f"kind must be one of {sorted(PLANNED_EVENT_KINDS)}")
    return v


def _check_date(v: str) -> str:
    try:
        _date.fromisoformat(v)
    except (ValueError, TypeError):
        raise ValueError("date must be an ISO date (YYYY-MM-DD)")
    return v


class PlannedEventCreate(BaseModel):
    title: str
    kind: str
    date: str
    chamber_id: int | None = None
    session_id: int | None = None
    notes: str | None = None

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        return _check_kind(v)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        return _check_date(v)


class PlannedEventUpdate(BaseModel):
    title: str | None = None
    kind: str | None = None
    date: str | None = None
    chamber_id: int | None = None
    session_id: int | None = None
    notes: str | None = None

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str | None) -> str | None:
        return v if v is None else _check_kind(v)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        return v if v is None else _check_date(v)


# ── Proposed grow cycle (species-derived dated per-phase timeline) ──────
#
# Distinct from the manual PlannedEvent CRUD above: a ProposedCycle is COMPUTED
# from a SpeciesProfile's phases + expected_duration_days, laying out concrete
# start/end dates from an inoculation date. It is the output of the planner
# cycle-proposer and drives the /propose endpoint and the iCal projection.


class ProposedPhaseSetpoints(BaseModel):
    """The species' target environment for a phase — temp / RH / CO2 / light."""

    temp_min_f: float
    temp_max_f: float
    humidity_min: float
    humidity_max: float
    co2_max_ppm: int
    co2_min_ppm: int | None = None
    light_hours_on: float
    light_hours_off: float
    light_spectrum: str
    fae_mode: str


class ProposedPhase(BaseModel):
    phase: str  # GrowPhase value, e.g. "substrate_colonization"
    label: str  # human-readable, e.g. "Substrate Colonization"
    start_date: _date
    end_date: _date
    duration_days: int  # laid-out span (rounded midpoint of the range below)
    min_days: int  # expected_duration_days low end
    max_days: int  # expected_duration_days high end
    setpoints: ProposedPhaseSetpoints
    notes: str = ""


class ProposedCycle(BaseModel):
    species_id: str
    common_name: str
    scientific_name: str
    start_date: _date  # inoculation date (anchor)
    end_date: _date  # end of the final phase
    total_days: int
    harvest_date: _date | None = None  # end of the fruiting phase, if present
    phases: list[ProposedPhase]
