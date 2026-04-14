from pydantic import BaseModel


class ExperimentCreate(BaseModel):
    title: str
    hypothesis: str
    control_session_id: int
    variant_session_id: int
    independent_variable: str
    control_value: str
    variant_value: str
    dependent_variables: list[str] = ["total_wet_yield_g", "colonization_days", "contamination_count"]


class ExperimentUpdate(BaseModel):
    status: str | None = None  # active | completed | cancelled
    conclusion: str | None = None
