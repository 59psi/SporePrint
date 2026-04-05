from enum import Enum

from pydantic import BaseModel


class ConditionType(str, Enum):
    THRESHOLD = "threshold"
    SCHEDULE = "schedule"
    COMPOUND = "compound"


class CompoundOp(str, Enum):
    AND = "AND"
    OR = "OR"


class ThresholdCondition(BaseModel):
    sensor: str  # "temp_f", "humidity", "co2_ppm", "lux"
    operator: str  # "lt", "gt", "lte", "gte", "eq"
    value: float | None = None  # absolute value
    profile_ref: str | None = None  # e.g. "humidity_min", "co2_max_ppm", "temp_max_f"


class ScheduleCondition(BaseModel):
    cron: str | None = None  # cron expression, e.g. "*/20 * * * *"
    interval_min: int | None = None  # every N minutes
    time_range: tuple[str, str] | None = None  # ("22:00", "06:00") for night


class CompoundCondition(BaseModel):
    op: CompoundOp
    conditions: list["RuleCondition"]


class RuleCondition(BaseModel):
    type: ConditionType
    threshold: ThresholdCondition | None = None
    schedule: ScheduleCondition | None = None
    compound: CompoundCondition | None = None


class RuleAction(BaseModel):
    target: str  # node_id or smart_plug_id
    channel: str | None = None  # relay channel name
    state: str = "on"  # "on" | "off"
    pwm: int | None = None  # 0-255 for relay, 0-1023 for lighting
    duration_sec: int | None = None
    ramp_sec: int | None = None
    scene: str | None = None  # for lighting node


class AutomationRule(BaseModel):
    id: int | None = None
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 0
    applies_to_phases: list[str] | None = None  # None = all phases
    applies_to_species: list[str] | None = None  # None = all species
    condition: RuleCondition
    action: RuleAction
    cooldown_seconds: int = 60
    safety_max_on_seconds: int | None = None
    notification: bool = False
    log_to_session: bool = True


class ManualOverride(BaseModel):
    target: str
    channel: str | None = None
    locked: bool = True
    reason: str = ""
    expires_at: float | None = None  # unix timestamp, None = until cancelled


class RuleFiring(BaseModel):
    rule_id: int
    rule_name: str
    timestamp: float
    condition_met: str
    action_taken: str
    session_id: int | None = None
