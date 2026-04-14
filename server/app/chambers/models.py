from pydantic import BaseModel


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
