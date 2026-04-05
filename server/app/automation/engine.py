import json
import logging
import time

from ..db import get_db
from ..mqtt import mqtt_publish
from ..species.service import get_profile
from .models import (
    AutomationRule,
    ConditionType,
    RuleCondition,
    ThresholdCondition,
    ManualOverride,
)
from .service import deserialize_rule_row

log = logging.getLogger(__name__)

# In-memory state
_last_fired: dict[int, float] = {}  # rule_id -> last fire timestamp
_overrides: dict[str, ManualOverride] = {}  # "target:channel" -> override
_rule_cache: list[AutomationRule] = []
_cache_ts: float = 0


async def load_rules() -> list[AutomationRule]:
    global _rule_cache, _cache_ts
    now = time.time()
    if now - _cache_ts < 5:  # cache for 5s
        return _rule_cache

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data FROM automation_rules WHERE enabled = 1 ORDER BY priority DESC"
        )
        rows = await cursor.fetchall()
        rules = [AutomationRule.model_validate(deserialize_rule_row(row)) for row in rows]
        _rule_cache = rules
        _cache_ts = now
        return rules


def set_override(override: ManualOverride):
    key = f"{override.target}:{override.channel or '*'}"
    if override.locked:
        _overrides[key] = override
        log.info("Override set: %s — %s", key, override.reason)
    else:
        _overrides.pop(key, None)
        log.info("Override cleared: %s", key)


def get_overrides() -> list[ManualOverride]:
    now = time.time()
    # Expire overrides
    expired = [k for k, v in _overrides.items() if v.expires_at and v.expires_at < now]
    for k in expired:
        log.info("Override expired: %s", k)
        del _overrides[k]
    return list(_overrides.values())


def is_overridden(target: str, channel: str | None) -> bool:
    now = time.time()
    for key in [f"{target}:{channel or '*'}", f"{target}:*"]:
        if key in _overrides:
            ov = _overrides[key]
            if ov.expires_at and ov.expires_at < now:
                del _overrides[key]
                continue
            return True
    return False


async def evaluate_rules(
    node_id: str,
    readings: dict,
    sio=None,
):
    """Evaluate all automation rules against new telemetry readings."""
    rules = await load_rules()
    if not rules:
        return

    # Get active session context
    session = await _get_active_session()
    if not session:
        return

    species_profile = await get_profile(session["species_profile_id"])
    current_phase = session["current_phase"]

    for rule in rules:
        try:
            # Check phase applicability
            if rule.applies_to_phases and current_phase not in rule.applies_to_phases:
                continue

            # Check species applicability
            if rule.applies_to_species and session["species_profile_id"] not in rule.applies_to_species:
                continue

            # Check override
            if is_overridden(rule.action.target, rule.action.channel):
                continue

            # Check cooldown
            now = time.time()
            last = _last_fired.get(rule.id, 0)
            if now - last < rule.cooldown_seconds:
                continue

            # Evaluate condition
            phase_params = None
            if species_profile and current_phase in [p.value for p in species_profile.phases]:
                from ..species.models import GrowPhase
                try:
                    phase_params = species_profile.phases[GrowPhase(current_phase)]
                except (ValueError, KeyError):
                    pass

            if _evaluate_condition(rule.condition, readings, phase_params):
                await _fire_rule(rule, readings, session, sio)
                _last_fired[rule.id] = now

        except Exception as e:
            log.error("Error evaluating rule '%s': %s", rule.name, e)


def _evaluate_condition(
    condition: RuleCondition,
    readings: dict,
    phase_params=None,
) -> bool:
    if condition.type == ConditionType.THRESHOLD:
        return _eval_threshold(condition.threshold, readings, phase_params)
    elif condition.type == ConditionType.SCHEDULE:
        return _eval_schedule(condition.schedule)
    elif condition.type == ConditionType.COMPOUND:
        compound = condition.compound
        results = [
            _evaluate_condition(c, readings, phase_params)
            for c in compound.conditions
        ]
        if compound.op.value == "AND":
            return all(results)
        else:
            return any(results)
    return False


def _eval_threshold(
    threshold: ThresholdCondition,
    readings: dict,
    phase_params=None,
) -> bool:
    if threshold.sensor not in readings:
        return False

    actual = readings[threshold.sensor]

    # Resolve target value
    if threshold.value is not None:
        target = threshold.value
    elif threshold.profile_ref and phase_params:
        target = getattr(phase_params, threshold.profile_ref, None)
        if target is None:
            return False
    else:
        return False

    ops = {
        "lt": lambda a, b: a < b,
        "gt": lambda a, b: a > b,
        "lte": lambda a, b: a <= b,
        "gte": lambda a, b: a >= b,
        "eq": lambda a, b: abs(a - b) < 0.1,
    }
    op_fn = ops.get(threshold.operator)
    if not op_fn:
        return False

    return op_fn(actual, target)


def _eval_schedule(schedule) -> bool:
    if schedule is None:
        return False

    now = time.localtime()

    if schedule.interval_min:
        # Check if current minute aligns with interval
        total_min = now.tm_hour * 60 + now.tm_min
        return total_min % schedule.interval_min == 0

    if schedule.time_range:
        start_h, start_m = map(int, schedule.time_range[0].split(":"))
        end_h, end_m = map(int, schedule.time_range[1].split(":"))
        current = now.tm_hour * 60 + now.tm_min
        start = start_h * 60 + start_m
        end = end_h * 60 + end_m

        if start <= end:
            return start <= current < end
        else:  # overnight range
            return current >= start or current < end

    return False


async def _fire_rule(rule: AutomationRule, readings: dict, session: dict, sio=None):
    action = rule.action
    log.info("Firing rule '%s' → %s:%s %s", rule.name, action.target, action.channel, action.state)

    # Build MQTT command
    payload = {"state": action.state}
    if action.pwm is not None:
        payload["pwm"] = action.pwm
    if action.duration_sec is not None:
        payload["duration_sec"] = action.duration_sec
    if action.ramp_sec is not None:
        payload["ramp_sec"] = action.ramp_sec
    if action.scene:
        payload["scene"] = action.scene

    # Determine topic
    if action.channel:
        topic = f"sporeprint/{action.target}/cmd/{action.channel}"
    else:
        topic = f"sporeprint/{action.target}/cmd/config"

    await mqtt_publish(topic, payload)

    # Log to session + firing in a single transaction
    async with get_db() as db:
        if rule.log_to_session and session:
            await db.execute(
                "INSERT INTO session_events (session_id, type, source, description, data) VALUES (?, ?, ?, ?, ?)",
                (
                    session["id"],
                    "automation",
                    f"rule:{rule.name}",
                    f"Rule '{rule.name}' fired: {action.target}/{action.channel} → {action.state}",
                    json.dumps({"rule_id": rule.id, "action": payload, "trigger_readings": readings}),
                ),
            )
        await db.execute(
            """INSERT INTO automation_firings (rule_id, rule_name, timestamp, condition_met, action_taken, session_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                rule.id, rule.name, time.time(),
                json.dumps({"readings": {k: readings.get(k) for k in ["temp_f", "humidity", "co2_ppm", "lux"] if k in readings}}),
                json.dumps(payload),
                session["id"] if session else None,
            ),
        )
        await db.commit()

    # Socket.IO broadcast
    if sio:
        await sio.emit("rule_fired", {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "target": action.target,
            "channel": action.channel,
            "action": action.state,
        })


async def _get_active_session() -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
