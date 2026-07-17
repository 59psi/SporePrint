import asyncio
import json
import logging
import time

from ..db import get_db
from ..mqtt import mqtt_publish
from ..notifications.service import co2_alert, temperature_alert, notify_warning, notify_critical
from ..sessions.service import get_active_session
from ..species.service import get_profile
from .service import validate_action_channel
from .smart_plugs import is_plug_target, send_plug_command, target_is_present
from .models import (
    AutomationRule,
    ConditionType,
    RuleCondition,
    ThresholdCondition,
    ManualOverride,
)
from .service import deserialize_rule_row, get_rule, resolve_node_target

log = logging.getLogger(__name__)

# In-memory caches populated from the DB. The manual_overrides table is the
# source of truth — this dict is a hot-path read cache kept coherent with it.
_last_fired: dict[int, float] = {}  # rule_id -> last fire timestamp
_overrides: dict[str, ManualOverride] = {}
_rule_cache: list[AutomationRule] = []
_cache_ts: float = 0
_overrides_loaded: bool = False

# Whole-engine pause. When True, evaluate_rules short-circuits before any rule
# runs, so no telemetry frame can drive an actuator. Persisted to user_settings
# (key below) so a remote "pause automation" survives a Pi reboot — the same
# durability manual_overrides and safety_watchdogs already have. Read on the hot
# path without a lock (a single-bool read is atomic under the GIL, matching the
# is_overridden convention); the DB load runs once, gated by _pause_loaded.
_paused: bool = False
_pause_loaded: bool = False
_PAUSE_SETTING_KEY = "automation_paused"

# Per-actuator auto-off tasks for safety_max_on_seconds enforcement.
# Key is "target:channel"; value is the asyncio.Task waiting to publish OFF.
# Not guarded by an asyncio lock: single dict.get/pop/setitem ops are atomic
# under the CPython GIL, and _cancel_safety_task is called from sync callers
# (e.g. set_override) that can't acquire an async lock. The only realistic
# race — two rules firing on the same actuator and both replacing the task —
# is a logical concern (rule precedence), not a data-corruption one.
_safety_tasks: dict[str, asyncio.Task] = {}

# Guards the read-modify-write spans on the shared dicts above. Concurrent
# telemetry frames can hit evaluate_rules while the override CRUD endpoints
# mutate _overrides; without the lock, a dict resize during iteration can
# raise RuntimeError in the evaluator. We do NOT hold these across DB awaits
# — only around the in-memory mutations that follow.
_state_lock = asyncio.Lock()
_safety_tasks_lock = asyncio.Lock()

# Two-tier alert bands, per the product spec: "first a WARNING range, then an
# EMERGENCY range." Nominal is the species' [min,max] for the phase. A reading
# just outside it is a WARNING (act soon); a reading past the emergency margin
# is an EMERGENCY (act now — contamination/loss territory). Widths are sensible
# defaults; a species can tighten them later via optional PhaseParams overrides
# without touching this code.
_TEMP_WARN_MARGIN_F = 2.0
_TEMP_EMERG_MARGIN_F = 5.0
_HUMIDITY_WARN_MARGIN = 3.0
_HUMIDITY_EMERG_MARGIN = 8.0
_CO2_WARN_MARGIN_PPM = 500
_CO2_EMERG_MARGIN_PPM = 1000

# Back-compat: the old single-tier names, still referenced by tests.
_TEMP_SAFETY_MARGIN_F = _TEMP_EMERG_MARGIN_F
_CO2_SAFETY_MARGIN_PPM = _CO2_EMERG_MARGIN_PPM


def _band_severity(value, lo, hi, warn_margin, emerg_margin):
    """Classify a reading against a nominal [lo,hi] band. Returns
    (severity, direction) where severity ∈ {None, "warning", "emergency"} and
    direction ∈ {"high","low",None}. `lo` may be None for a ceiling-only band."""
    if hi is not None:
        if value > hi + emerg_margin:
            return "emergency", "high"
        if value > hi + warn_margin:
            return "warning", "high"
    if lo is not None:
        if value < lo - emerg_margin:
            return "emergency", "low"
        if value < lo - warn_margin:
            return "warning", "low"
    return None, None


def _override_key(target: str, channel: str | None) -> str:
    return f"{target}:{channel or '*'}"


# Channels whose whole job is to exchange chamber air with ambient. Driving any
# of these vents CO2 (and humidity, and heat). fae_mode="none" phases must not
# actuate them — see the guard in evaluate_rules.
_AIR_EXCHANGE_CHANNELS = {"fae", "exhaust"}


def _is_air_exchange_action(action) -> bool:
    return action.channel in _AIR_EXCHANGE_CHANNELS


# Cold storage is preservation, not cultivation: hold the fridge cold, and do
# nothing else. Species-agnostic — a colonized jar in the fridge doesn't care
# what it will eventually grow. Built lazily to avoid importing the species
# model at engine import time.
_COLD_STORAGE_PARAMS = None


def _cold_storage_params():
    global _COLD_STORAGE_PARAMS
    if _COLD_STORAGE_PARAMS is None:
        from ..species.models import PhaseParams
        _COLD_STORAGE_PARAMS = PhaseParams(
            temp_min_f=35, temp_max_f=40,
            humidity_min=80, humidity_max=95,   # incidental; not actively driven
            co2_max_ppm=100000, co2_tolerance="high",  # never vent a sealed fridge
            light_hours_on=0, light_hours_off=24, light_spectrum="none",
            fae_mode="none",                     # no fresh air — it's a fridge
            expected_duration_days=(0, 365),
            notes="Cold storage — hold at fridge temperature. No light, FAE, or CO2 control.",
        )
    return _COLD_STORAGE_PARAMS


# Substrate containers the chamber's sensors cannot see into, and whose interior
# CO2/humidity the chamber's actuators cannot change. Running a CO2 or humidity
# rule against the chamber does nothing for a sealed vessel — the sensor reads
# room air, the fan moves room air, the substrate stays sealed. Grow bags are
# sealed during colonization and OPENED to fruit; jars/agar stay sealed (they
# go to cold storage, they don't fruit in-chamber).
_ALWAYS_SEALED_CONTAINERS = {"jar", "grain_jar", "agar_plate", "agar"}
_SEALED_UNTIL_FRUITING = {"grow_bag", "bag"}
_FRUITING_PHASES = {"primordia_induction", "fruiting"}


def _container_is_sealed(container_type: str | None, phase: str) -> bool:
    if not container_type:
        return False  # unknown → assume open (monotub/tray); don't over-gate
    ct = container_type.lower()
    if ct in _ALWAYS_SEALED_CONTAINERS:
        return True
    if ct in _SEALED_UNTIL_FRUITING:
        return phase not in _FRUITING_PHASES  # the bag is opened to fruit
    return False  # monotub, tray, open, anything else → the substrate is in the sensed air


# Rules whose actuation only makes sense when the substrate is in the sensed
# volume. If the container is sealed, these are no-ops that just churn actuators.
_CHAMBER_ENV_CHANNELS = {"fae", "exhaust", "circulation", "aux"}


def _acts_on_chamber_environment(action) -> bool:
    if action.channel in _CHAMBER_ENV_CHANNELS:
        return True
    # humidifier / dehumidifier plugs also act on chamber air, not the vessel
    return action.target in ("plug-humidifier", "plug-dehumidifier")


async def _load_overrides_from_db():
    """Populate _overrides from the manual_overrides table; drop expired rows."""
    global _overrides_loaded
    now = time.time()
    # Fetch under DB lock only; swap the in-memory dict atomically afterward
    # under _state_lock so concurrent evaluators never see a half-loaded cache.
    fresh: dict[str, ManualOverride] = {}
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
            fresh[_override_key(ov.target, ov.channel)] = ov
    async with _state_lock:
        _overrides.clear()
        _overrides.update(fresh)
        _overrides_loaded = True
    log.info("Loaded %d manual overrides from DB", len(fresh))


async def ensure_overrides_loaded():
    if not _overrides_loaded:
        await _load_overrides_from_db()


async def _load_pause_from_db() -> None:
    """Load the persisted automation-pause flag into memory (once).

    The flag lives in the user_settings key-value table (same upsert shape
    settings_service uses) so a remote pause outlives a reboot. An absent row
    reads as not-paused — pause is strictly opt-in.
    """
    global _paused, _pause_loaded
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT value FROM user_settings WHERE key = ?", (_PAUSE_SETTING_KEY,)
        )
        row = await cursor.fetchone()
    _paused = bool(row and row["value"] == "1")
    _pause_loaded = True


async def ensure_pause_loaded() -> None:
    if not _pause_loaded:
        await _load_pause_from_db()


async def set_paused(paused: bool) -> None:
    """Pause or resume this Pi's automation engine.

    While paused, evaluate_rules returns before loading a single rule, so no
    telemetry frame drives an actuator. Persisted to user_settings so the hold
    survives a reboot. This is the target of the cloud relay's `system` /
    `automation` command (payload ``{paused: bool}``) — see cloud/service.py.
    """
    global _paused, _pause_loaded
    async with get_db() as db:
        await db.execute(
            """INSERT INTO user_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=unixepoch('now')""",
            (_PAUSE_SETTING_KEY, "1" if paused else "0"),
        )
        await db.commit()
    _paused = bool(paused)
    _pause_loaded = True
    log.info("Automation engine %s", "PAUSED" if paused else "RESUMED")


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
    # Update the cache outside the DB scope under the state lock so concurrent
    # callers can't observe a torn _rule_cache / _cache_ts pair.
    async with _state_lock:
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
            await db.commit()
            async with _state_lock:
                _overrides[key] = override
            log.info("Override set: %s — %s", key, override.reason)
            return
        else:
            await db.execute(
                "DELETE FROM manual_overrides WHERE target = ? AND (channel IS ? OR channel = ?)",
                (override.target, override.channel, override.channel),
            )
            await db.commit()
        async with _state_lock:
            _overrides.pop(key, None)
        log.info("Override cleared: %s", key)


async def clear_override(target: str, channel: str | None):
    await set_override(
        ManualOverride(target=target, channel=channel, locked=False, reason="")
    )


async def suspend_rule(rule_id: str | int, minutes: int = 30) -> None:
    """Temporarily suspend one automation rule, driven from the cloud relay.

    Mirrors the Pi LAN UI's "suspend" button (POST /api/automation/overrides →
    set_override): pin an expiring manual override on the rule's OWN action
    target/channel so evaluate_rules skips it via is_overridden until the
    override lapses. Reusing set_override means a cloud-suspended rule shows up
    in the same /overrides list and is cleared the same way as a UI-suspended
    one — one mechanism, not two.

    ``expires_at`` is set to now + minutes, then clamped by ManualOverride to
    its server-side TTL ceiling, so a bogus ``minutes`` can never pin the
    actuator forever. Raises ValueError for an unknown or non-numeric rule id;
    the caller (cloud/service.py) surfaces that as the command_result error.
    """
    rule = await get_rule(int(rule_id))
    if rule is None:
        raise ValueError(f"No automation rule with id {rule_id!r}")
    action = AutomationRule.model_validate(rule).action
    minutes = max(1, int(minutes))
    await set_override(ManualOverride(
        target=action.target,
        channel=action.channel,
        locked=True,
        reason=f"rule '{rule['name']}' suspended {minutes}m via cloud",
        expires_at=time.time() + minutes * 60,
    ))
    log.info(
        "Suspended rule %s ('%s') for %dm → override %s:%s",
        rule_id, rule["name"], minutes, action.target, action.channel,
    )


async def get_overrides() -> list[ManualOverride]:
    await ensure_overrides_loaded()
    now = time.time()
    # Snapshot expired keys under the lock so we don't race with set_override.
    async with _state_lock:
        expired = [k for k, v in _overrides.items() if v.expires_at and v.expires_at < now]
    if expired:
        async with get_db() as db:
            await db.execute(
                "DELETE FROM manual_overrides WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            await db.commit()
        async with _state_lock:
            for k in expired:
                log.info("Override expired: %s", k)
                _overrides.pop(k, None)
    async with _state_lock:
        return list(_overrides.values())


def is_overridden(target: str, channel: str | None) -> bool:
    # Sync function called from the hot evaluation path — dict reads in CPython
    # are atomic under the GIL, so we don't take the async lock here. The
    # worst-case race is a stale-by-one-tick read (missing an override that was
    # just set, or seeing an override that was just cleared), both of which
    # self-heal on the next telemetry frame.
    now = time.time()
    stale_keys: list[str] = []
    for key in [_override_key(target, channel), _override_key(target, None)]:
        ov = _overrides.get(key)
        if ov is None:
            continue
        if ov.expires_at and ov.expires_at < now:
            stale_keys.append(key)
            continue
        # Before declaring the channel overridden, sweep any expired entries
        # we noticed along the way so callers don't accumulate cruft.
        for k in stale_keys:
            _overrides.pop(k, None)
        return True
    for k in stale_keys:
        _overrides.pop(k, None)
    return False


async def evaluate_rules(
    node_id: str,
    readings: dict,
    sio=None,
):
    """Evaluate all automation rules against new telemetry readings."""
    await ensure_pause_loaded()

    # Safety DETECTION is always-on — it runs BEFORE the pause and no-rules
    # early returns below. Pause and "no enabled rules" suppress ACTUATION only;
    # they must never mute the "closet is on fire" alerts. So the active-session
    # lookup, phase-params resolution, and _check_safety_thresholds happen here,
    # up front: a paused engine (or one with every rule disabled) still pages the
    # operator when a reading drifts outside the active stage range but under the
    # firmware absolute limit.
    session = await get_active_session()
    if not session:
        return

    species_profile = await get_profile(session["species_profile_id"])
    # Reference-only species (chaga on a birch, an endophyte in liquid culture)
    # have no chamber setpoints to drive. Don't evaluate any rule against them —
    # the profile exists for its prose, not as a grow target.
    if species_profile is not None and not getattr(species_profile, "chamber_cultivable", True):
        return
    current_phase = session["current_phase"]
    container_type = session.get("container_type")

    phase_params = None
    if current_phase == "cold_storage":
        # Species-agnostic: hold the fridge cold, drive nothing else.
        phase_params = _cold_storage_params()
    elif species_profile and current_phase in [p.value for p in species_profile.phases]:
        from ..species.models import GrowPhase
        try:
            phase_params = species_profile.phases[GrowPhase(current_phase)]
        except (ValueError, KeyError):
            pass

    # Proactive safety alerts — fire regardless of rule state. These are the
    # "closet is on fire" alerts the operator must hear about even if no rule
    # has been authored to handle them, or automation is paused.
    if phase_params is not None:
        await _check_safety_thresholds(node_id, phase_params, readings, session)

    # ── Actuation gates. Pause and no-rules stop actuator DECISIONS here, after
    # safety detection above has already run. A remote "pause automation"
    # (cloud → set_paused) halts every actuator decision, not just filters
    # individual rules; the flag is loaded from the DB once, then cached, so the
    # hot path is a single bool read once warm. ──
    if _paused:
        return
    await ensure_overrides_loaded()
    rules = await load_rules()
    if not rules:
        return

    # If the substrate is in a sealed vessel the chamber can't sense or affect,
    # the chamber-environment rules (CO2/FAE/humidity/circulation/mist) are
    # no-ops. Skip them wholesale rather than churn actuators against a sealed
    # bag — the UI surfaces "sealed container: environmental control paused".
    container_sealed = _container_is_sealed(container_type, current_phase)

    for rule in rules:
        try:
            if rule.applies_to_phases and current_phase not in rule.applies_to_phases:
                continue

            if rule.applies_to_species and session["species_profile_id"] not in rule.applies_to_species:
                continue

            # Honour the species profile's fae_mode. It is set on every phase
            # (49 times) and, until now, read NOWHERE — so a phase declaring
            # fae_mode="none" (every colonization phase) still got its FAE and
            # exhaust fans driven by the CO2 rules, venting the 5000-15000ppm
            # the mycelium needs. The profile said "no fresh air this phase" in
            # a field the engine ignored. It doesn't any more.
            # Sealed vessel: the chamber can't reach the substrate, so
            # environmental actuation is a no-op. (Temperature still applies —
            # a fridge/heater warms the whole chamber including the vessel.)
            if container_sealed and _acts_on_chamber_environment(rule.action):
                continue

            if _is_air_exchange_action(rule.action) and phase_params is not None:
                if getattr(phase_params, "fae_mode", None) == "none":
                    continue

            # Capability-aware fallback: a rule that should only run when a
            # preferred actuator is ABSENT (e.g. vent with fans only if there's
            # no dehumidifier). Goes silent the moment the real device is paired.
            if rule.requires_absent_target and await target_is_present(rule.requires_absent_target):
                continue

            # A manual hold is stored under the target it was placed on. A cloud
            # override pins the chamber's REAL node (a MAC-derived id resolved
            # from the role), while a seeded rule still names the placeholder
            # (relay-01 / light-01). Resolve the rule's target the same way
            # _fire_rule does and treat the rule as held if EITHER the resolved
            # node or the placeholder is overridden — otherwise the rule re-fires
            # on the next telemetry tick and claws back the operator's hold. (V4-1)
            resolved = await resolve_node_target(rule.action.target) or rule.action.target
            if (is_overridden(resolved, rule.action.channel)
                    or is_overridden(rule.action.target, rule.action.channel)):
                continue

            now = time.time()
            last = _last_fired.get(rule.id, 0)
            if now - last < rule.cooldown_seconds:
                continue

            if _evaluate_condition(rule.condition, readings, phase_params,
                                   last if last else None):
                await _fire_rule(rule, readings, session, sio, phase_params)
                async with _state_lock:
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

    sid = session.get("id") if session else None

    async def _emit(param: str, severity: str, direction: str, value: float, threshold: float):
        # Local ntfy: warning tier is deduped/low-priority, emergency is critical.
        title = f"{param.title()} {severity.upper()}"
        msg = f"{param} {value} ({direction}); threshold {threshold}"
        try:
            if severity == "emergency":
                await notify_critical(title, msg, tags=[param])
            else:
                await notify_warning(title, msg, dedup_key=f"{node_id}:{param}:{direction}")
        except Exception as e:
            log.warning("local %s alert failed: %s", param, e)
        # Cloud escalation: `<param>_alert` is the existing emergency event the
        # cloud escalation matcher knows; `<param>_warning` is the new lower tier.
        event_type = f"{param}_alert" if severity == "emergency" else f"{param}_warning"
        try:
            await forward_event(event_type, {
                "node_id": node_id, "value": value, "direction": direction,
                "threshold": threshold, "severity": severity, "session_id": sid,
            })
        except Exception as e:
            log.warning("forward_event(%s) failed: %s", event_type, e)

    temp = readings.get("temp_f")
    if isinstance(temp, (int, float)):
        sev, direction = _band_severity(
            temp, phase_params.temp_min_f, phase_params.temp_max_f,
            _TEMP_WARN_MARGIN_F, _TEMP_EMERG_MARGIN_F,
        )
        if sev:
            margin = _TEMP_EMERG_MARGIN_F if sev == "emergency" else _TEMP_WARN_MARGIN_F
            threshold = (phase_params.temp_max_f + margin if direction == "high"
                         else phase_params.temp_min_f - margin)
            await _emit("temperature", sev, direction, float(temp), threshold)

    humidity = readings.get("humidity")
    if isinstance(humidity, (int, float)):
        sev, direction = _band_severity(
            humidity, phase_params.humidity_min, phase_params.humidity_max,
            _HUMIDITY_WARN_MARGIN, _HUMIDITY_EMERG_MARGIN,
        )
        if sev:
            margin = _HUMIDITY_EMERG_MARGIN if sev == "emergency" else _HUMIDITY_WARN_MARGIN
            threshold = (phase_params.humidity_max + margin if direction == "high"
                         else phase_params.humidity_min - margin)
            await _emit("humidity", sev, direction, float(humidity), threshold)

    # CO2 alerts only where CO2 is actively managed. During colonization
    # (fae_mode="none") high CO2 is intended, not an emergency — the species'
    # own ceiling is high there, but we don't page the operator for it.
    co2 = readings.get("co2_ppm")
    if isinstance(co2, (int, float)) and getattr(phase_params, "fae_mode", None) != "none":
        sev, direction = _band_severity(
            co2, None, phase_params.co2_max_ppm,
            _CO2_WARN_MARGIN_PPM, _CO2_EMERG_MARGIN_PPM,
        )
        if sev == "emergency":
            try:
                await co2_alert(int(co2))
            except Exception as e:
                log.warning("co2_alert failed: %s", e)
            threshold = phase_params.co2_max_ppm + _CO2_EMERG_MARGIN_PPM
            try:
                await forward_event("co2_alert", {
                    "node_id": node_id, "co2_ppm": int(co2), "value": float(co2),
                    "threshold_ppm": threshold, "severity": "emergency", "session_id": sid,
                })
            except Exception as e:
                log.warning("forward_event(co2_alert) failed: %s", e)
        elif sev == "warning":
            await _emit("co2", "warning", "high", float(co2),
                        phase_params.co2_max_ppm + _CO2_WARN_MARGIN_PPM)


def _evaluate_condition(
    condition: RuleCondition,
    readings: dict,
    phase_params=None,
    last_fired: float | None = None,
) -> bool:
    if condition.type == ConditionType.THRESHOLD:
        return _eval_threshold(condition.threshold, readings, phase_params)
    elif condition.type == ConditionType.SCHEDULE:
        # phase_params carries the species' light window + FAE period; last_fired
        # makes interval schedules elapsed-based. Neither used to reach here.
        return _eval_schedule(condition.schedule, phase_params, last_fired)
    elif condition.type == ConditionType.COMPOUND:
        compound = condition.compound
        results = [
            _evaluate_condition(c, readings, phase_params, last_fired)
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


def _cron_field_matches(field: str, value: int) -> bool:
    """One cron field against one time component. Supports *, */n, a-b, a,b, n."""
    for part in field.split(","):
        if part == "*":
            return True
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                return False
            step = int(step_s)
        if part == "*":
            if value % step == 0:
                return True
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            if not (lo_s.isdigit() and hi_s.isdigit()):
                return False
            lo, hi = int(lo_s), int(hi_s)
        elif part.isdigit():
            lo = hi = int(part)
        else:
            return False
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def _eval_cron(expr: str, now: time.struct_time) -> bool:
    """5-field cron: minute hour day-of-month month day-of-week (0/7 = Sunday).

    Hand-rolled rather than pulling in a dependency, but it is REAL: the `cron`
    field was declared on ScheduleCondition — and documented with an example —
    while nothing ever read it, so every cron rule a user wrote silently never
    fired. A schedule that cannot be evaluated must not quietly evaluate false.
    """
    fields = expr.split()
    if len(fields) != 5:
        log.warning("Ignoring malformed cron %r (need 5 fields, got %d)", expr, len(fields))
        return False
    minute, hour, dom, month, dow = fields
    # cron dow: 0 and 7 are both Sunday; struct_time tm_wday is Mon=0..Sun=6.
    cron_dow = (now.tm_wday + 1) % 7
    return (
        _cron_field_matches(minute, now.tm_min)
        and _cron_field_matches(hour, now.tm_hour)
        and _cron_field_matches(dom, now.tm_mday)
        and _cron_field_matches(month, now.tm_mon)
        and (_cron_field_matches(dow, cron_dow) or (cron_dow == 0 and _cron_field_matches(dow, 7)))
    )


def _eval_photoperiod(schedule, phase_params) -> bool:
    """Is the species' light window open (or closed) right now?

    The grow profile already states light_hours_on / light_hours_off per phase.
    Nothing read them: the seeded light rules just re-asserted a fixed scene
    every 60 minutes, so "12/12" species ran their lights 24/7 and dark
    colonization phases were never actually dark.
    """
    if phase_params is None:
        return False
    hours_on = getattr(phase_params, "light_hours_on", None)
    if hours_on is None:
        return False

    want_on = schedule.photoperiod == "on"
    if hours_on <= 0:      # fully dark phase — the window never opens
        return not want_on
    if hours_on >= 24:     # continuous light — it never closes
        return want_on

    try:
        start_h, start_m = map(int, schedule.photoperiod_start.split(":"))
    except (ValueError, AttributeError):
        log.warning("Bad photoperiod_start %r — defaulting to 06:00", schedule.photoperiod_start)
        start_h, start_m = 6, 0

    now = time.localtime()
    current = now.tm_hour * 60 + now.tm_min
    start = start_h * 60 + start_m
    end = (start + int(hours_on * 60)) % (24 * 60)

    inside = start <= current < end if start <= end else (current >= start or current < end)
    return inside if want_on else not inside


def _eval_schedule(schedule, phase_params=None, last_fired: float | None = None) -> bool:
    if schedule is None:
        return False

    now = time.localtime()

    if schedule.photoperiod:
        return _eval_photoperiod(schedule, phase_params)

    if schedule.cron:
        return _eval_cron(schedule.cron, now)

    # Species-driven period (e.g. fae_interval_min) wins over the literal.
    interval = None
    if schedule.profile_interval_ref and phase_params is not None:
        interval = getattr(phase_params, schedule.profile_interval_ref, None)
    if interval is None:
        interval = schedule.interval_min

    if interval:
        # Elapsed-since-last-fire, not wall-clock modulo. The old
        # `(hour*60+min) % interval == 0` only matched if an evaluation landed
        # exactly on a matching minute — rules are evaluated when telemetry
        # arrives (~60s, and it drifts), so a single late frame skipped the
        # whole cycle and the FAE fan simply never ran that round.
        if last_fired is None:
            return True
        return (time.time() - last_fired) >= interval * 60

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
        # Same transport split as _fire_rule: a plug target's OFF must go out
        # on the vendor's own topic tree — publishing it to sporeprint/plug-*
        # reaches nothing, which for THIS path means a stuck-on heater.
        plug = await is_plug_target(target)
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
                    if plug:
                        published = await send_plug_command(target, "off")
                    else:
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


async def _fire_rule(rule: AutomationRule, readings: dict, session: dict, sio=None,
                     phase_params=None):
    action = rule.action
    log.info("Firing rule '%s' → %s:%s %s", rule.name, action.target, action.channel, action.state)

    # A species-driven duration (e.g. fae_duration_sec) resolves against the
    # active phase, so one rule serves every species instead of hardcoding a
    # number the grow profile already specifies.
    duration_sec = action.duration_sec
    if action.duration_profile_ref and phase_params is not None:
        profile_duration = getattr(phase_params, action.duration_profile_ref, None)
        if profile_duration is not None:
            duration_sec = int(profile_duration)

    # Resolve a seeded native-node placeholder (relay-01 / light-01) to the
    # chamber's real relay/lighting node before composing the topic or arming
    # the safety watchdog — a real node registers under a MAC-derived id, so a
    # command published to the placeholder reaches no subscriber and would log
    # status='sent' while nothing moves. A non-placeholder target (a real node
    # id, a plug-*, a vendor key) resolves to itself; an unresolvable
    # placeholder falls back to itself so validate_action_channel's warning
    # below still surfaces the "no node of this role" gap. (V3-2)
    target = await resolve_node_target(action.target) or action.target

    payload = {"state": action.state}
    if action.pwm is not None:
        payload["pwm"] = action.pwm
    if duration_sec is not None:
        payload["duration_sec"] = duration_sec
    if action.ramp_sec is not None:
        payload["ramp_sec"] = action.ramp_sec
    if action.scene:
        payload["scene"] = action.scene
    # v4.1.4 — vendor write actions append to the audit payload so the
    # session-events timeline shows which vendor was driven and how.
    if action.vendor_slug:
        payload["vendor_slug"] = action.vendor_slug
        payload["vendor_action"] = action.vendor_action
        payload["vendor_params"] = action.vendor_params

    # Rules written before channel validation existed (or straight into the DB)
    # can still name a channel the node drops. MQTT accepts any topic, so the
    # publish "succeeds" and we'd log a fired row for an actuator that never
    # moved. We don't refuse — the node may just be offline, and a live rule is
    # not ours to veto mid-grow — but the audit trail should not read clean.
    if channel_error := await validate_action_channel(action):
        log.warning("Rule '%s' fires into an unknown channel: %s", rule.name, channel_error)

    # Command routing. The firmware's cmd_router dispatches on the EXACT topic
    # suffix (firmware lib/sp_core/cmd_router.h), so the suffix is the contract:
    #   cmd/<channel> — switch/dim a named channel
    #   cmd/scene     — apply a lighting scene
    #   cmd/config    — read/publish intervals, calibration
    # `scene` used to fall to cmd/config, whose handler reads only the interval
    # and calibration keys and ignores `scene` entirely — so every seeded
    # "Light Scene" rule published, logged status='sent', and did nothing.
    if action.channel:
        topic = f"sporeprint/{target}/cmd/{action.channel}"
    elif action.scene:
        topic = f"sporeprint/{target}/cmd/scene"
    else:
        topic = f"sporeprint/{target}/cmd/config"

    condition_met = json.dumps({
        "readings": {k: readings.get(k) for k in
                     ["temp_f", "humidity", "co2_ppm", "lux", "weight_g", "door_open"]
                     if k in readings}
    })
    action_taken = json.dumps(payload)

    # Reserve the audit row BEFORE publishing so we never claim "fired" without
    # evidence the command actually went out.
    firing_id: int | None = None
    async with get_db() as db:
        if rule.log_to_session and session:
            # v4.1.5 — vendor actions get a more descriptive timeline
            # row so chamber post-mortems read like
            #   "Rule 'night-fog' fired: kasa.set_power({ip:10.0.0.20, on:true})"
            # instead of the misleading legacy
            #   "Rule 'night-fog' fired: vendor:kasa/None → on"
            if action.vendor_slug:
                description = (
                    f"Rule '{rule.name}' fired: "
                    f"{action.vendor_slug}.{action.vendor_action}"
                    f"({json.dumps(action.vendor_params, separators=(',', ':'))})"
                )
            else:
                description = (
                    f"Rule '{rule.name}' fired: "
                    f"{action.target}/{action.channel} → {action.state}"
                )
            await db.execute(
                "INSERT INTO session_events (session_id, type, source, description, data) VALUES (?, ?, ?, ?, ?)",
                (
                    session["id"],
                    "automation",
                    f"rule:{rule.name}",
                    description,
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
        if action.vendor_slug:
            # v4.1.4 — vendor write action. Bypasses MQTT entirely.
            from ..integrations import _actions as _vendor_actions
            await _vendor_actions.dispatch(
                action.vendor_slug,
                action.vendor_action or "",
                action.vendor_params or {},
            )
            status = "sent"
        elif await is_plug_target(target):
            # Smart plugs do NOT speak the sporeprint/<node>/cmd/* protocol —
            # Shelly listens on shellies/<id>/relay/0/command and Tasmota on
            # tasmota/<id>/cmnd/POWER. Publishing to sporeprint/plug-*/cmd/*
            # reached no subscriber at all, so every seeded humidifier / heater
            # / cooler rule fired into the void while logging status='sent'.
            published = await send_plug_command(target, action.state)
            status = "sent" if published else "failed"
            if not published:
                error = "plug command not published (client disconnected?)"
        else:
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
        # Key the watchdog on the RESOLVED target: its auto-OFF must go out on
        # the same topic the ON did, or a stuck-on heater whose OFF is aimed at
        # the placeholder never turns off. (V3-2)
        _cancel_safety_task(target, action.channel)
        if action.state == "on" and rule.safety_max_on_seconds and rule.safety_max_on_seconds > 0:
            key = _safety_key(target, action.channel)
            _safety_tasks[key] = asyncio.create_task(
                _safety_auto_off(target, action.channel, rule.safety_max_on_seconds, rule.name)
            )
            await _persist_safety_watchdog(
                target, action.channel, rule.name, rule.safety_max_on_seconds,
            )
        elif action.state == "off":
            # OFF explicitly published — any pending watchdog is now redundant.
            await _clear_persisted_safety_watchdog(target, action.channel)

    if sio:
        await sio.emit("rule_fired", {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "target": action.target,
            "channel": action.channel,
            "action": action.state,
            "status": status,
        })
