from typing import Literal

from pydantic import BaseModel, model_validator


class ExperimentCreate(BaseModel):
    title: str
    hypothesis: str
    control_session_id: int
    variant_session_id: int
    independent_variable: str
    control_value: str
    variant_value: str
    dependent_variables: list[str] = ["total_wet_yield_g", "colonization_days", "contamination_count"]

    @model_validator(mode="after")
    def _two_different_sessions(self) -> "ExperimentCreate":
        # A grow compared with itself ties on every metric (and the paid
        # analysis of it says nothing).
        if self.control_session_id == self.variant_session_id:
            raise ValueError("control_session_id and variant_session_id must be different sessions")
        return self


class ExperimentUpdate(BaseModel):
    # Only these: 'completed' stamps completed_at and the auto-conclusion, and
    # the list filters on the exact value ('Completed' or 'done' did neither).
    status: Literal["active", "completed", "cancelled"] | None = None
    conclusion: str | None = None
