import asyncio
import json
import logging
import time

from ..db import get_db
from ..mqtt import mqtt_publish
from ..notifications.service import co2_alert, temperature_alert
from ..sessions.service import get_active_session
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

# In-memory caches populated from the DB. The manual_overrides table is the
# source of truth — this dict is a hot-path read cache kept coherent with it.
_last_fired: dict[int, float] = {}  # rule_id -> last fire timestamp
_overrides: dict[str, ManualOverride] = {}
_rule_cache: list[AutomationRule] = []
_cache_ts: float = 0
_overrides_loaded: bool = False

# Per-actuator auto-off tasks for safety_max_on_seconds enforcement.
# Key is "target:channel"; value is the asyncio.Task waiting to publish OFF.
_safety_tasks: dict[str, asyncio.Task] = {}

# How much a reading must exceed the species ceiling before we page the operator.
_TEMP_SAFETY_MARGIN_F = 5.0
_CO2_SAFETY_MARGIN_PPM = 1000


def _override_key(target: str, channel: str | None) -> str:
    return f"{target}:{channel or '*'}"


async def _load_overrides_from_db():
    """Populate _overrides from the manual_overrides table; drop expired rows."""
    global _overrides_loaded
    now = time.time()
    _overrides.clear()
    async with get_db() as db:
        await db.execute(
            "DELETE FROM manual_overrides WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT target, channel, locked, reason, expires_at FROM manual_overrides WHERE locked = 1"
        )
        for row in await cursor.fetchall():
            ov = ManualOverride(
                target=row["target"],
                channel=row["channel"],
                locked=bool(row["locked"]),
                reason=row["reason"] or "",
                expires_at=row["expires_at"],
            )
            _overrides[_override_key(ov.target, ov.channel)] = ov
    _overrides_loaded = True
    log.info("Loaded %d manual overrides from DB", len(_overrides))


async def ensure_overrides_loaded():
    if not _overrides_loaded:
        await _load_overrides_from_db()


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


async def set_override(override: ManualOverride):
    """Persist the override to the DB and refresh the in-memory cache."""
    await ensure_overrides_loaded()
    key = _override_key(override.target, override.channel)
    # Cancel the safety task (sync, in-process) before we start the DB work so
    # a slow DB write doesn't let the watchdog fire in the meantime.
    if override.locked:
        _cancel_safety_task(override.target, override.channel)
    async with get_db() as db:
        if override.locked:
            await db.execute(
                """INSERT INTO manual_overrides (target, channel, locked, reason, expires_at)
                   VALUES (?, ?, 1, ?, ?)""",
                (override.target, override.channel, override.reason, override.expires_at),
            )
            # Remove the safety_watchdog row in the same transaction so the two
            # tables don't diverge. _clear_persisted_safety_watchdog opens its
            # own get_db() block which would deadlock under SQLite's single-
            # writer contract, so inline the DELETE here.
            if override.channel is None:
                await db.execute(
                    "DELETE FROM safety_watchdogs WHERE target = ? AND channel IS NULL",
                    (override.target,),
                )
            else:
                await db.execute(
                    "DELETE FROM safety_watchdogs WHERE target = ? AND channel = ?",
                    (override.target, override.channel),
                )
            _overrides[key] = override
            log.info("Override set: %s — %s", key, override.reason)
        else:
            await db.execute(
                "DELETE FROM manual_overrides WHERE target = ? AND (channel IS ? OR channel = ?)",
                (override.target, override.channel, override.channel),
            )
            _overrides.pop(key, None)
            log.info("Override cleared: %s", key)
        await db.commit()


async def clear_override(target: str, channel: str | None):
    await set_override(
        ManualOverride(target=target, channel=channel, locked=False, reason="")
    )


async def get_overrides() -> list[ManualOverride]:
    await ensure_overrides_loaded()
    now = time.time()
    expired = [k for k, v in _overrides.items() if v.expires_at and v.expires_at < now]
    if expired:
        async with get_db() as db:
            await db.execute(
                "DELETE FROM manual_overrides WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            await db.commit()
        for k in expired:
            log.info("Override expired: %s", k)
            del _overrides[k]
    return list(_overrides.values())


def is_overridden(target: str, channel: str | None) -> bool:
    now = time.time()
    for key in [_override_key(target, channel), _override_key(target, None)]:
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
    await ensure_overrides_loaded()
    rules = await load_rules()
    if not rules:
        return

    session = await get_active_session()
    if not session:
        return

    species_profile = await get_profile(session["species_profile_id"])
    current_phase = session["current_phase"]

    phase_params = None
    if species_profile and current_phase in [p.value for p in species_profile.phases]:
        from ..species.models import GrowPhase
        try:
            phase_params = species_profile.phases[GrowPhase(current_phase)]
        except (ValueError, KeyError):
            pass

    # Proactive safety alerts — fire regardless of rule state. These are the
    # "closet is on fire" alerts the operator must hear about even if no rule
    # has been authored to handle them.
    if phase_params is not None:
        await _check_safety_thresholds(node_id, phase_params, readings, session)

    for rule in rules:
        try:
            if rule.applies_to_phases and current_phase not in rule.applies_to_phases:
                continue

            if rule.applies_to_species and session["species_profile_id"] not in rule.applies_to_species:
                continue

            if is_overridden(rule.action.target, rule.action.channel):
                continue

            now = time.time()
            last = _last_fired.get(rule.id, 0)
            if now - last < rule.cooldown_seconds:
                continue

            if _evaluate_condition(rule.condition, readings, phase_params):
                await _fire_rule(rule, readings, session, sio)
                _last_fired[rule.id] = now

        except Exception as e:
            log.error("Error evaluating rule '%s': %s", rule.name, e)


async def _check_safety_thresholds(node_id: str, phase_params, readings: dict, session: dict | None):
    """Page the operator when readings breach species ceilings by a safety margin.

    Two channels fire in parallel:
    - local ntfy via `temperature_alert` / `co2_alert` (so a Pi running headless
      on the LAN gets notified even if the cloud connector is disconnected)
    - cloud event via `forward_event` (so premium mobile subscribers get their
      push notification via the cloud relay's escalation engine)
    """
    # Late import — forward_event lives in cloud/service.py which imports us transitively.
    from ..cloud.service import forward_event

    temp = readings.get("temp_f")
    if isinstance(temp, (int, float)):
        direction = None
        if temp > phase_params.temp_max_f + _TEMP_SAFETY_MARGIN_F:
            direction = "high"
        elif temp < phase_params.temp_min_f - _TEMP_SAFETY_MARGIN_F:
            direction = "low"
        if direction:
            try:
                await temperature_alert(float(temp), direction)
            except Exception as e:
                log.warning("temperature_alert failed: %s", e)
            try:
                await forward_event("temperature_alert", {
                    "node_id": node_id,
                    "temp_f": float(temp),
                    "direction": direction,
                    "threshold_f": (
                        phase_params.temp_max_f + _TEMP_SAFETY_MARGIN_F if direction == "high"
                        else phase_params.temp_min_f - _TEMP_SAFETY_MARGIN_F
                    ),
                    "session_id": session.get("id") if session else None,
                })
            except Exception as e:
                log.warning("forward_event(temperature_alert) failed: %s", e)

    co2 = readings.get("co2_ppm")
    if isinstance(co2, (int, float)):
        if co2 > phase_params.co2_max_ppm + _CO2_SAFETY_MARGIN_PPM:
            try:
                await co2_alert(int(co2))
            except Exception as e:
                log.warning("co2_alert failed: %s", e)
            try:
                await forward_event("co2_alert", {
                    "node_id": node_id,
                    "co2_ppm": int(co2),
                    "threshold_ppm": phase_params.co2_max_ppm + _CO2_SAFETY_MARGIN_PPM,
                    "session_id": session.get("id") if session else None,
                })
            except Exception as e:
                log.warning("forward_event(co2_alert) failed: %s", e)


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


def _safety_key(target: str, channel: str | None) -> str:
    return f"{target}:{channel or '*'}"


async def _persist_safety_watchdog(
    target: str, channel: str | None, rule_name: str, delay_seconds: int,
) -> None:
    """Record an armed watchdog so it can be rehydrated after Pi restart."""
    now = time.time()
    expires_at = now + delay_seconds
    async with get_db() as db:
        await db.execute(
            """INSERT INTO safety_watchdogs (target, channel, rule_name, armed_at, expires_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(target, channel) DO UPDATE SET
                 rule_name = excluded.rule_name,
                 armed_at = excluded.armed_at,
                 expires_at = excluded.expires_at""",
            (target, channel, rule_name, now, expires_at),
        )
        await db.commit()


async def _clear_persisted_safety_watchdog(target: str, channel: str | None) -> None:
    """Remove the persisted record when a watchdog fires, is cancelled, or overridden."""
    async with get_db() as db:
        # sqlite treats NULL in = comparisons as false, so we need IS NULL path.
        if channel is None:
            await db.execute(
                "DELETE FROM safety_watchdogs WHERE target = ? AND channel IS NULL",
                (target,),
            )
        else:
            await db.execute(
                "DELETE FROM safety_watchdogs WHERE target = ? AND channel = ?",
                (target, channel),
            )
        await db.commit()


def _cancel_safety_task(target: str, channel: str | None) -> None:
    """Cancel any pending auto-off for this actuator.

    Called when a new rule explicitly turns the actuator off, or when an
    operator sets a manual override (they want to control timing themselves).
    Persistent state cleanup is done by the caller via
    `_clear_persisted_safety_watchdog` — splitting sync cancel from async
    DB cleanup keeps this helper usable from sync code paths.
    """
    key = _safety_key(target, channel)
    task = _safety_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()


async def _safety_auto_off(target: str, channel: str | None, delay_seconds: int, rule_name: str) -> None:
    """Sleep then publish OFF; fire-risk watchdog for stuck-on actuators.

    v3.3.3 — publish retries bounded-exponential (2s, 4s, 8s, 16s, 30s cap) for
    up to 60 s total so a transient MQTT disconnect during the exact moment the
    watchdog fires does not leave an actuator stuck ON until the next rule
    fire or reboot. A persistent publish failure is still logged at ERROR and
    leaves the persisted watchdog row in place so rehydrate_safety_watchdogs()
    will re-arm and retry on the next Pi boot.
    """
    try:
        await asyncio.sleep(delay_seconds)
        topic = (
            f"sporeprint/{target}/cmd/{channel}"
            if channel else f"sporeprint/{target}/cmd/config"
        )
        try:
            published = False
            attempt = 0
            delays = (2, 4, 8, 16, 30)
            while True:
                attempt += 1
                try:
                    published = await mqtt_publish(
                        topic, {"state": "off", "reason": "safety_max_on_seconds"}
                    )
                except Exception as pub_err:
                    log.warning(
                        "safety_auto_off publish attempt %d for %s:%s raised %s — retrying",
                        attempt, target, channel, pub_err,
                    )
                    published = False
                if published:
                    break
                if attempt >= len(delays) + 1:
                    # Ran out of retries — leave the persisted row so the next
                    # boot retries via rehydrate_safety_watchdogs().
                    log.error(
                        "safety_auto_off exhausted retries for %s:%s (rule %r) — "
                        "actuator may still be ON; watchdog row retained for next boot",
                        target, channel, rule_name,
                    )
                    break
                await asyncio.sleep(delays[attempt - 1])
            log.warning(
                "safety_max_on_seconds triggered for rule '%s' → %s:%s (published=%s attempts=%d)",
                rule_name, target, channel, published, attempt,
            )
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO automation_firings
                       (rule_id, rule_name, timestamp, condition_met, action_taken, session_id, status, error)
                       VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
                    (
                        None,
                        f"safety_max_on_seconds:{rule_name}",
                        time.time(),
                        json.dumps({"reason": "safety_max_on_seconds", "original_rule": rule_name}),
                        json.dumps({"state": "off"}),
                        "sent" if published else "failed",
                        None if published else f"mqtt_publish failed after {attempt} attempts",
                    ),
                )
                await db.commit()
            if published:
                # Only clear the persisted row once we've successfully published.
                await _clear_persisted_safety_watchdog(target, channel)
        except Exception as e:
            log.error("safety auto-off bookkeeping for %s:%s failed: %s", target, channel, e)
    except asyncio.CancelledError:
        pass
    finally:
        key = _safety_key(target, channel)
        current = _safety_tasks.get(key)
        if current is not None and current.done():
            _safety_tasks.pop(key, None)


async def rehydrate_safety_watchdogs() -> int:
    """Re-arm persisted safety watchdogs on Pi boot. Returns the count rehydrated.

    - Rows whose expires_at is still in the future: re-arm for the remaining time.
    - Rows whose expires_at has already passed (e.g. Pi was off long enough that
      the scheduled OFF should have fired while we were down): publish OFF
      immediately so the actuator doesn't stay ON.
    """
    now = time.time()
    rehydrated = 0
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT target, channel, rule_name, expires_at FROM safety_watchdogs"
        )
        rows = await cursor.fetchall()
    for row in rows:
        target = row["target"]
        channel = row["channel"]
        rule_name = row["rule_name"]
        expires_at = float(row["expires_at"])
        remaining = expires_at - now
        if remaining > 0:
            key = _safety_key(target, channel)
            _safety_tasks[key] = asyncio.create_task(
                _safety_auto_off(target, channel, int(remaining), rule_name)
            )
            log.info("Rehydrated safety watchdog for %s:%s (%.0fs remaining)",
                     target, channel, remaining)
            rehydrated += 1
        else:
            # Expired while we were down — publish OFF NOW.
            log.warning(
                "Safety watchdog for %s:%s expired while offline (%.0fs overdue) — publishing OFF now",
                target, channel, -remaining,
            )
            topic = (
                f"sporeprint/{target}/cmd/{channel}"
                if channel else f"sporeprint/{target}/cmd/config"
            )
            try:
                await mqtt_publish(topic, {"state": "off", "reason": "safety_max_on_seconds_expired_offline"})
            except Exception as e:
                log.error("Immediate safety-off publish failed for %s:%s: %s", target, channel, e)
            await _clear_persisted_safety_watchdog(target, channel)
    return rehydrated


async def _fire_rule(rule: AutomationRule, readings: dict, session: dict, sio=None):
    action = rule.action
    log.info("Firing rule '%s' → %s:%s %s", rule.name, action.target, action.channel, action.state)

    payload = {"state": action.state}
    if action.pwm is not None:
        payload["pwm"] = action.pwm
    if action.duration_sec is not None:
        payload["duration_sec"] = action.duration_sec
    if action.ramp_sec is not None:
        payload["ramp_sec"] = action.ramp_sec
    if action.scene:
        payload["scene"] = action.scene

    if action.channel:
        topic = f"sporeprint/{action.target}/cmd/{action.channel}"
    else:
        topic = f"sporeprint/{action.target}/cmd/config"

    condition_met = json.dumps({
        "readings": {k: readings.get(k) for k in ["temp_f", "humidity", "co2_ppm", "lux"] if k in readings}
    })
    action_taken = json.dumps(payload)

    # Reserve the audit row BEFORE publishing so we never claim "fired" without
    # evidence the command actually went out.
    firing_id: int | None = None
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
        cursor = await db.execute(
            """INSERT INTO automation_firings
               (rule_id, rule_name, timestamp, condition_met, action_taken, session_id, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (
                rule.id, rule.name, time.time(),
                condition_met, action_taken,
                session["id"] if session else None,
            ),
        )
        firing_id = cursor.lastrowid
        await db.commit()

    # Publish + update status to reflect what actually happened on the wire.
    status = "failed"
    error: str | None = None
    try:
        published = await mqtt_publish(topic, payload)
        status = "sent" if published else "failed"
        if not published:
            error = "mqtt_publish returned False (client disconnected?)"
    except Exception as e:
        error = str(e)
        log.warning("Rule '%s' publish failed: %s", rule.name, e)

    async with get_db() as db:
        await db.execute(
            "UPDATE automation_firings SET status = ?, error = ? WHERE id = ?",
            (status, error, firing_id),
        )
        await db.commit()

    # safety_max_on_seconds watchdog: stops actuators from staying ON beyond a
    # species/rule-defined ceiling even if the condition that triggered the
    # rule persists. This is the fire-risk guard ("heater stuck on after a
    # power blip"). Only arm the timer when the command actually went out —
    # otherwise we'd publish an OFF that never had an ON preceding it.
    #
    # Persistence: the armed watchdog is written to `safety_watchdogs` so a Pi
    # reboot rehydrates it and either re-arms or publishes OFF immediately if
    # expires_at has passed while we were down.
    if status == "sent":
        _cancel_safety_task(action.target, action.channel)
        if action.state == "on" and rule.safety_max_on_seconds and rule.safety_max_on_seconds > 0:
            key = _safety_key(action.target, action.channel)
            _safety_tasks[key] = asyncio.create_task(
                _safety_auto_off(action.target, action.channel, rule.safety_max_on_seconds, rule.name)
            )
            await _persist_safety_watchdog(
                action.target, action.channel, rule.name, rule.safety_max_on_seconds,
            )
        elif action.state == "off":
            # OFF explicitly published — any pending watchdog is now redundant.
            await _clear_persisted_safety_watchdog(action.target, action.channel)

    if sio:
        await sio.emit("rule_fired", {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "target": action.target,
            "channel": action.channel,
            "action": action.state,
            "status": status,
        })
