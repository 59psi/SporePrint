from pydantic import BaseModel, field_validator


class ChamberCreate(BaseModel):
    name: str
    description: str | None = None
    node_ids: list[str] = []


class ChamberUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    node_ids: list[str] | None = None
    active_session_id: int | None = None
    automation_rule_ids: list[int] | None = None


MAINTENANCE_KINDS = {"clean", "calibrate", "inspect", "repair"}


class MaintenanceCreate(BaseModel):
    kind: str
    due_at: float | None = None  # unix timestamp
    notes: str | None = None

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in MAINTENANCE_KINDS:
            raise ValueError(f"kind must be one of {sorted(MAINTENANCE_KINDS)}")
        return v


class MaintenanceComplete(BaseModel):
    notes: str | None = None
