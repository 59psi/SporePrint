from pydantic import BaseModel


class ContaminationEventCreate(BaseModel):
    """Manual contamination-event log (the page's manual-mark flow)."""
    session_id: int | None = None
    chamber_id: int | None = None
    contamination_type: str | None = None
    confidence: float | None = None
    frame_id: int | None = None
    notes: str | None = None


class RootCauseUpdate(BaseModel):
    root_cause: str
