import math
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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
    """When a rule is allowed to fire.

    ``photoperiod`` and ``profile_interval_ref`` make the SCHEDULE itself
    species-driven, the way ``ThresholdCondition.profile_ref`` already does for
    setpoints. The grow profile states how many hours of light a phase wants and
    how often it wants fresh air; those numbers should drive the schedule rather
    than be duplicated as literals in a rule that then ignores the species.
    """

    cron: str | None = None  # 5-field cron, e.g. "*/20 * * * *"
    interval_min: int | None = None  # every N minutes since this rule last fired
    time_range: tuple[str, str] | None = None  # ("22:00", "06:00") for night

    # Species-driven light cycle. "on" matches while the current phase's light
    # window is open, "off" while it is closed. The window length is the
    # profile's light_hours_on — so a 12/12 species gets a real 12/12 cycle, and
    # a dark colonization phase (light_hours_on = 0) never opens it at all.
    photoperiod: str | None = None  # "on" | "off" (see PHOTOPERIOD_VALUES)
    photoperiod_start: str = "06:00"  # local clock time the light window opens

    # Species-driven period: names a PhaseParams field holding minutes
    # (e.g. "fae_interval_min"). Takes precedence over interval_min.
    profile_interval_ref: str | None = None

    @field_validator("photoperiod", mode="before")
    @classmethod
    def _normalize_photoperiod(cls, v):
        # " ON" and "on" are the same window. Normalised, never refused: stored
        # rules are validated on every load, so a raise here would stop every
        # rule. A value that is neither is refused (422) when a rule is created
        # or updated (automation.service.rule_value_error), and never matches.
        return v.strip().lower() if isinstance(v, str) else v


class CompoundCondition(BaseModel):
    op: CompoundOp
    conditions: list["RuleCondition"]


class RuleCondition(BaseModel):
    type: ConditionType
    threshold: ThresholdCondition | None = None
    schedule: ScheduleCondition | None = None
    compound: CompoundCondition | None = None


class RuleAction(BaseModel):
    """Action a rule fires when its condition matches.

    Two action types share the same model so v3.x rules keep working:

    - **Native (default):** ``target`` is a node_id or smart_plug_id;
      the engine publishes ``sporeprint/{target}/cmd/{channel}`` with
      ``state``, ``pwm``, ``duration_sec``, etc. (existing v3.x shape).

    - **Vendor (v4.1.4):** set ``vendor_slug`` to a registered
      integration (``wemo``, ``kasa``, ``tapo``, ``fluence``, …) and
      ``vendor_action`` to one of that vendor's writable actions
      (``set_power``, ``set_dim``, ``set_setpoint``, …). Engine
      forwards ``vendor_params`` as kwargs to the integrations
      dispatcher. ``target`` then names the rule's manual-override key
      (typically ``vendor:{slug}:{ip-or-id}``).
    """

    target: str  # node_id, smart_plug_id, or vendor:* override key
    channel: str | None = None  # relay channel name (native action type)
    state: str = "on"  # "on" | "off" (see ACTION_STATES)
    pwm: int | None = None  # 0-255 for relay, 0-1023 for lighting
    duration_sec: int | None = None
    ramp_sec: int | None = None
    scene: str | None = None  # for lighting node

    # Species-driven duration: names a PhaseParams field holding seconds
    # (e.g. "fae_duration_sec"). Resolved at fire time; overrides duration_sec.
    duration_profile_ref: str | None = None

    # v4.1.4 — vendor write-action escape hatch. When set, the engine
    # routes through `app.integrations._actions.dispatch` instead of
    # MQTT. `vendor_slug` MUST be a registered integration; the
    # dispatcher rejects unknown slugs with a clear 404.
    vendor_slug: str | None = None
    vendor_action: str | None = None
    vendor_params: dict[str, Any] = {}

    @field_validator("state", mode="before")
    @classmethod
    def _normalize_state(cls, v):
        # The firmware, the plugs and is_off_command read the state without
        # regard to case or surrounding space; the engine's safety ceiling and
        # redundant-OFF bookkeeping compare it exactly, so "ON" switched a
        # heater on with no ceiling and "OFF" never cleared one. Normalised
        # here, never refused (see ScheduleCondition); create/update refuse
        # anything but ACTION_STATES.
        return v.strip().lower() if isinstance(v, str) else v


# What a rule may set RuleAction.state / ScheduleCondition.photoperiod to.
ACTION_STATES = ("on", "off")
PHOTOPERIOD_VALUES = ("on", "off")


class AutomationRule(BaseModel):
    id: int | None = None
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 0
    applies_to_phases: list[str] | None = None  # None = all phases
    applies_to_species: list[str] | None = None  # None = all species
    # Capability-aware fallback: fire this rule ONLY IF the named target is NOT
    # present on this chamber. It's how "vent with the fans when there's no
    # dehumidifier" degrades gracefully — the fan-evacuation rule sets this to
    # the dehumidifier plug, so it goes silent the moment a real dehumidifier is
    # paired, and the two never fight over the same excess-humidity event.
    requires_absent_target: str | None = None
    condition: RuleCondition
    action: RuleAction
    cooldown_seconds: int = 60
    safety_max_on_seconds: int | None = None
    notification: bool = False
    log_to_session: bool = True


# A locked override pins an actuator OUT of automation's reach. Left open-ended
# it silently disables climate control on that channel until someone remembers
# to clear it — a forgotten "hold" becomes a dead heater or an un-vented chamber
# for a live grow. So every override carries a hard server-side TTL ceiling:
# a null ("until cancelled") or any longer-than-ceiling request is clamped down
# to now + this. An operator who genuinely needs longer re-applies the hold —
# a deliberate, logged act, not an indefinite silent one.
MAX_OVERRIDE_TTL_SECONDS = 24 * 60 * 60  # 24h — covers any maintenance window


def _held_state(value) -> str | None:
    """A hold's actuation the way node firmware reads a command state: "on"
    in any case is ON, any other string OFF; anything else is not known."""
    if isinstance(value, str):
        return "on" if value.strip().lower() == "on" else "off"
    return None


class ManualOverride(BaseModel):
    target: str
    channel: str | None = None
    locked: bool = True
    reason: str = ""
    expires_at: float | None = None  # unix ts; clamped to now + MAX_OVERRIDE_TTL_SECONDS
    # The state the actuator was switched to with the hold ("on" / "off"),
    # when the hold pins a manual command; None for a hold that only keeps
    # automation off (a rule suspension, a safety lockout). An "on" hold ends
    # when the node's own safety cutoff switches the channel off
    # (engine.end_on_hold_after_cutoff).
    held_state: str | None = None

    @field_validator("held_state", mode="before")
    @classmethod
    def _normalise_held_state(cls, v):
        return _held_state(v)

    @model_validator(mode="after")
    def _clamp_expiry(self) -> "ManualOverride":
        # Runs on every construction (unlike a field_validator, which pydantic
        # skips for a defaulted None — the exact sticky-forever case we close).
        # A null, NaN or over-long expiry is pulled back to the ceiling (NaN
        # compares false both ways, so it would never expire); a past expiry,
        # 0 included, is left alone (it just reads as already-expired, which
        # several override paths rely on).
        ceiling = time.time() + MAX_OVERRIDE_TTL_SECONDS
        if self.expires_at is None or math.isnan(self.expires_at) or self.expires_at > ceiling:
            self.expires_at = ceiling
        return self


class OverrideRequest(BaseModel):
    """The body of POST /api/automation/overrides: a ManualOverride whose
    window may be given as `duration_sec`, counted from now on the Pi's own
    clock. An absolute `expires_at` from a dashboard comes from the browser's
    clock, which can be minutes or hours off the Pi's (a Pi with no
    battery-backed clock that booted without NTP): the hold then ran hours
    past its window, or had already expired when it arrived. `duration_sec`
    wins when both are sent; a client sending only `expires_at` is served as
    before."""

    target: str
    channel: str | None = None
    locked: bool = True
    reason: str = ""
    expires_at: float | None = None
    duration_sec: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    # Additive: the state the client switched the actuator to with this hold
    # (ManualOverride.held_state). Omitted, the hold pins no state.
    state: str | None = None

    def to_override(self) -> ManualOverride:
        expires_at = time.time() + self.duration_sec if self.duration_sec is not None else self.expires_at
        return ManualOverride(
            target=self.target,
            channel=self.channel,
            locked=self.locked,
            reason=self.reason,
            expires_at=expires_at,
            held_state=self.state,
        )
