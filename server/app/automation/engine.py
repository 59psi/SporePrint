import asyncio
import contextlib
import json
import logging
import time

from pydantic import TypeAdapter, ValidationError

from ..chambers.service import chambers_for_node
from ..db import get_db
from ..integrations import _actions as _vendor_actions
from ..mqtt import mqtt_publish
from ..notifications.service import co2_alert, notify_warning, notify_critical
from ..sessions.service import (
    PHASE_PARAM_FALLBACKS,
    add_actuator_off_listener,
    get_active_session_for_chambers,
)
from ..species.service import get_profile
from .service import validate_action_channel
from .smart_plugs import is_plug_target, plug_aliases, send_plug_command, target_is_present
from .models import (
    AutomationRule,
    ConditionType,
    RuleCondition,
    ThresholdCondition,
    ManualOverride,
)
from .service import (
    deserialize_rule_row,
    drop_duty_from_off,
    get_rule,
    resolve_node_target,
    rule_applies_to_species,
)

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
# Deadline (unix ts) of the watchdog currently in _safety_tasks under the same
# key. A re-fired ON keeps this deadline rather than pushing it out — otherwise
# a rule that re-fires every cooldown (Heating Trigger: 300 s) re-arms its
# 3600 s ceiling forever and the ceiling never trips.
_safety_deadlines: dict[str, float] = {}
# When the most recent ON covered by the watchdog under the same key finished
# going out. note_actuator_off() only clears a ceiling when its OFF started
# after that — an ON that went out later keeps its ceiling.
_safety_last_on: dict[str, float] = {}

# One lock per actuator (same key as _safety_tasks). _fire_rule holds it from
# its override re-check through the transport and the watchdog arm; a tripping
# ceiling holds it while it deregisters and locks automation out, before its
# OFF goes out. So an ON is either already on the wire when the trip starts
# (and the trip's OFF lands after it) or it sees the lockout and is refused —
# a re-fire can never slip in between the OFF and the lockout.
_actuator_locks: dict[str, asyncio.Lock] = {}

# Retry schedule for the safety OFF: fast backoff, then every 30 s for ~10 min
# in total. Long enough to ride out a broker restart or the boot window before
# MQTT / the vendor drivers come up (rehydrate_safety_watchdogs fires expired
# watchdogs before either is connected).
_SAFETY_OFF_RETRY_DELAYS: tuple[int, ...] = (2, 4, 8, 16, 30) + (30,) * 18

# After a ceiling trips on an actuator that was being held ON (a plug or vendor
# device, or a native channel commanded without a duration), automation is
# locked out of that actuator for this long via an expiring ManualOverride, so
# the very next telemetry frame cannot switch it straight back on.
_SAFETY_LOCKOUT_SECONDS = 15 * 60

# How a vendor device is turned OFF by the safety watchdog. Vendor rules reach
# their device through the integrations dispatcher, not MQTT, so the auto-OFF
# must go the same way. slug → (OFF action, device-id param, OFF params).
# Setpoint-only vendors (trane/quest/anden) have no OFF and are not armed.
_VENDOR_SAFETY_OFF: dict[str, tuple[str, str, dict]] = {
    "kasa": ("set_power", "ip", {"on": False}),
    "tapo": ("set_power", "ip", {"on": False}),
    "wemo": ("set_power", "ip", {"on": False}),
    "fluence": ("set_dim", "fixture_id", {"percent": 0}),
    "fohse": ("set_dim", "fixture_id", {"percent": 0}),
    "bios": ("set_dim", "fixture_id", {"percent": 0}),
    "agrowtek": ("set_output", "output_id", {"value": False}),
}

# Lax bool, exactly as the integrations dispatcher coerces a bool kwarg
# ("false"/"off"/"0" → False), so the watchdog reads a vendor rule's on/off
# the same way the device does.
_LAX_BOOL = TypeAdapter(bool)

# Guards the read-modify-write spans on the shared dicts above. Concurrent
# telemetry frames can hit evaluate_rules while the override CRUD endpoints
# mutate _overrides; without the lock, a dict resize during iteration can
# raise RuntimeError in the evaluator. We do NOT hold these across DB awaits
# — only around the in-memory mutations that follow.
_state_lock = asyncio.Lock()
_safety_tasks_lock = asyncio.Lock()

# rule_id -> when evaluate_rules last looked at the rule. A cron schedule
# matches any minute since then (capped), not just the minute a telemetry frame
# happens to land in — frames arrive every ~60 s with jitter, or every 300 s if
# the operator slows the node down, so exact-minute matching skipped cycles.
_rule_seen: dict[int, float] = {}
_CRON_CATCHUP_SECONDS = 15 * 60

# Alert dedup: "<node>:<param>:<direction>:<severity>" -> when it last went out.
# A persisting excursion is re-detected on every telemetry frame; without this
# a stuck-hot closet paged priority-5 (and forwarded to the cloud) every minute
# until the operator muted the topic. A different severity is a different key,
# so a warning that escalates to an emergency still pages at once.
_alert_last_sent: dict[str, float] = {}
_ALERT_REPEAT_SECONDS = {"warning": 5 * 60, "emergency": 15 * 60}

# "<target>:<channel>" -> when a rule's OFF last went out to that actuator. An
# OFF rule (a cutoff) is true for as long as the chamber is in range, so it used
# to re-send — and log — the same OFF every cooldown (every 60 s). Now a repeat
# OFF is only re-sent every _OFF_REASSERT_SECONDS as a safety net (or at once
# if a smart plug reports it was switched back ON). Any ON clears the entry:
# an engine ON in _send_rule_action, any other ON through note_actuator_on
# (manual/cloud/plug commands, a node reporting the channel ON).
_last_off_sent: dict[str, float] = {}
_OFF_REASSERT_SECONDS = 15 * 60

# (session id, phase) pairs whose missing phase params were already logged.
_phase_fallback_logged: set[tuple] = set()

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

# Life-safety CO2 level (OSHA IDLH, and the seeded CO2 Hard Ceiling's trigger):
# far above any cultivation band, so it pages whatever the session, phase,
# container or fae_mode — including when there is no session at all.
_CO2_LIFE_SAFETY_PPM = 40000

# A rule at or above this priority whose condition only compares readings to
# absolute values, with no phase/species scope, is a life-safety backstop (the
# seeded CO2 Hard Ceiling). It runs with no active session and is exempt from
# the sealed-container and fae_mode gates — it protects the room, not the grow.
_LIFE_SAFETY_PRIORITY = 20


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


# fae_mode values under which a timed FAE cycle is wanted. "passive" means no
# active fresh air (king trumpet primordia, enoki: CO2 is held HIGH on purpose)
# and "none" none at all — a schedule-driven FAE rule must not run there; only
# a CO2 threshold rule may drive the fans in those phases.
_SCHEDULED_FAE_MODES = {"scheduled", "continuous"}


def _is_absolute_condition(condition: RuleCondition) -> bool:
    """True when a condition only compares readings against absolute values."""
    if condition.type == ConditionType.THRESHOLD:
        t = condition.threshold
        return t is not None and t.value is not None and not t.profile_ref
    if condition.type == ConditionType.COMPOUND and condition.compound is not None:
        return bool(condition.compound.conditions) and all(
            _is_absolute_condition(c) for c in condition.compound.conditions
        )
    return False


def _is_life_safety_rule(rule: AutomationRule) -> bool:
    """See _LIFE_SAFETY_PRIORITY."""
    return (
        rule.priority >= _LIFE_SAFETY_PRIORITY
        and not rule.applies_to_phases
        and not rule.applies_to_species
        and _is_absolute_condition(rule.condition)
    )


# A phase its species profile does not define borrows another phase's
# setpoints (sessions.service.PHASE_PARAM_FALLBACKS — the phase-advance
# validation reads the same table): with no params every profile-driven rule
# AND every stage safety alert went silent. Rest runs with the lights off.
_REST_LIGHTS_OFF = {"light_hours_on": 0, "light_hours_off": 24, "light_spectrum": "none"}

# Phases whose params a session's growth_form re-selects (reishi: the profile's
# primordia phase is the elevated-CO2 ANTLER form, its fruiting phase the
# low-CO2 CONK form). See _apply_growth_form.
_FORM_PHASES = ("primordia_induction", "fruiting")


def _apply_growth_form(params, phase: str, form: str | None, by_phase: dict):
    """Pick the phase params the session's growth_form asks for.

    CO2 controls the morphology: an ANTLER session wants the phase whose
    profile holds CO2 up (co2_min_ppm set) for as long as it fruits, a CONK
    session wants the low-CO2 phase with FAE — even while pinning. The setting
    used to be stored and never read, so an antler reishi advanced to fruiting
    got the conk ceiling (800 ppm, scheduled FAE) and a conk session in
    primordia got the antler CO2 floor. Profiles without a CO2-floor phase are
    untouched.
    """
    form = (form or "").strip().lower()
    if form not in ("antler", "conk") or phase not in _FORM_PHASES:
        return params
    candidates = [by_phase[p] for p in _FORM_PHASES if p in by_phase]
    antler = next((p for p in candidates if getattr(p, "co2_min_ppm", None)), None)
    if antler is None:
        return params
    if form == "antler":
        return antler
    conk = next((p for p in reversed(candidates) if not getattr(p, "co2_min_ppm", None)), None)
    return conk if conk is not None else params


def _resolve_phase_params(session: dict, species_profile):
    """PhaseParams the session's current phase runs under, or None."""
    phase = session.get("current_phase")
    if phase == "cold_storage":
        # Species-agnostic: hold the fridge cold, drive nothing else.
        return _cold_storage_params()
    if species_profile is None:
        return None
    by_phase = {p.value: params for p, params in species_profile.phases.items()}
    params = by_phase.get(phase)
    if params is None:
        key = (session.get("id"), phase)
        for alt in PHASE_PARAM_FALLBACKS.get(phase, ()):
            if alt in by_phase:
                params = by_phase[alt]
                if phase == "rest":
                    params = params.model_copy(update=_REST_LIGHTS_OFF)
                if key not in _phase_fallback_logged:
                    _phase_fallback_logged.add(key)
                    log.warning("Profile %r has no %r phase — running it on its %r setpoints",
                                species_profile.id, phase, alt)
                break
        else:
            if key not in _phase_fallback_logged:
                _phase_fallback_logged.add(key)
                log.warning("Profile %r has no %r phase — no setpoints, profile-driven "
                            "rules and stage alerts are inactive", species_profile.id, phase)
            return None
    return _apply_growth_form(params, phase, session.get("growth_form"), by_phase)


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
            humidity_driven=False,               # a fridge's RH is not a fault to page on
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
# bulk_bag: an all-in-one bag, sealed under its filter patch until it is opened
# to fruit — the session flow already treats it as a fruiting container.
_SEALED_UNTIL_FRUITING = {"grow_bag", "bag", "bulk_bag"}
_FRUITING_PHASES = {"primordia_induction", "fruiting"}
# A shiitake block comes OUT of its bag to brown (light and air drive the
# skin), so its chamber band is the block's from browning on.
_BAG_OPEN_PHASES = _FRUITING_PHASES | {"browning"}


def _container_is_sealed(container_type: str | None, phase: str) -> bool:
    if not container_type:
        return False  # unknown → assume open (monotub/tray); don't over-gate
    ct = container_type.lower()
    if ct in _ALWAYS_SEALED_CONTAINERS:
        return True
    if ct in _SEALED_UNTIL_FRUITING:
        return phase not in _BAG_OPEN_PHASES  # the bag is opened to brown / fruit
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
    # A lock stops automation from sending NEW commands to this actuator. It
    # deliberately leaves any armed safety_max_on_seconds watchdog alone: the
    # hold says nothing about whether the actuator is ON, and cancelling the
    # ceiling on a hold (or a 30-minute cloud rule-suspend) left a heater that
    # automation had just switched on with no cutoff at all.
    async with get_db() as db:
        if override.locked:
            await db.execute(
                """INSERT INTO manual_overrides (target, channel, locked, reason, expires_at)
                   VALUES (?, ?, 1, ?, ?)""",
                (override.target, override.channel, override.reason, override.expires_at),
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


async def _session_for_node(node_id: str) -> tuple[dict | None, list[str] | None]:
    """(the active session `node_id`'s telemetry drives, its chamber's node ids).

    A node listed in a chamber belongs to THAT chamber's active session — never
    another chamber's (two chambers can run side by side, and the newest session
    anywhere used to be applied to every node's readings, and its commands sent
    to whichever relay heartbeated last). A node in no chamber keeps the
    single-closet behaviour — the newest session bound to no chamber, else the
    grow of the only chamber with active sessions — with chamber node ids
    None; with grows in two chambers it drives neither (life-safety still runs).

    The session comes from sessions.service get_active_session_for_chambers:
    bound by sessions.chamber_id, else linked by chambers.active_session_id,
    else the newest session bound to NO chamber. Without that last fallback a
    chambered node's grow went unmanaged: no heater, no cooler, no stage alerts.
    """
    chambers = await chambers_for_node(node_id)
    session = await get_active_session_for_chambers([c["id"] for c in chambers])
    if not chambers:
        return session, None
    return session, [n for c in chambers for n in c["node_ids"]]


def _arbitration_key(action, resolved: str) -> tuple[str, str | None]:
    """The physical actuator a rule's action drives (see evaluate_rules)."""
    if action.vendor_slug:
        return (_vendor_watchdog_target(action.vendor_slug, action.vendor_params or {})
                or action.target, None)
    return resolved, action.channel


def _resolved_duration(action, phase_params) -> int | None:
    """duration_sec, with a species-driven duration_profile_ref resolved."""
    duration_sec = action.duration_sec
    if action.duration_profile_ref and phase_params is not None:
        profile_duration = getattr(phase_params, action.duration_profile_ref, None)
        if profile_duration is not None:
            duration_sec = int(profile_duration)
    return duration_sec


async def evaluate_rules(
    node_id: str,
    readings: dict,
    sio=None,
):
    """Evaluate all automation rules against new telemetry readings."""
    await ensure_pause_loaded()
    now = time.time()

    # Safety DETECTION is always-on — it runs BEFORE the pause and no-rules
    # early returns below. Pause and "no enabled rules" suppress ACTUATION only;
    # they must never mute the "closet is on fire" alerts. So the session
    # lookup, phase-params resolution, and _check_safety_thresholds happen here,
    # up front: a paused engine (or one with every rule disabled) still pages the
    # operator when a reading drifts outside the active stage range but under the
    # firmware absolute limit.
    session, chamber_nodes = await _session_for_node(node_id)
    # Life-safety detection needs no session, phase, species or container.
    await _check_life_safety(node_id, readings, session.get("id") if session else None)

    # A grow this engine manages: an active session whose species is a chamber
    # target. Reference-only species (chaga on a birch, an endophyte in liquid
    # culture) have no chamber setpoints to drive — the profile exists for its
    # prose, not as a grow target. Without a managed grow only the life-safety
    # rules (the CO2 Hard Ceiling) still run.
    managed = False
    current_phase = None
    phase_params = None
    container_sealed = False
    if session:
        species_profile = await get_profile(session["species_profile_id"])
        managed = species_profile is None or getattr(species_profile, "chamber_cultivable", True)
    if managed:
        current_phase = session["current_phase"]
        phase_params = _resolve_phase_params(session, species_profile)
        # If the substrate is in a sealed vessel the chamber can't sense or
        # affect, the chamber-environment rules (CO2/FAE/humidity/circulation/
        # mist) are no-ops, and the chamber's RH/CO2 readings say nothing about
        # the substrate. Skip them wholesale rather than churn actuators (or page
        # the operator) against a sealed bag.
        container_sealed = _container_is_sealed(session.get("container_type"), current_phase)

        # Proactive safety alerts — fire regardless of rule state. These are the
        # "closet is on fire" alerts the operator must hear about even if no rule
        # has been authored to handle them, or automation is paused.
        if phase_params is not None:
            await _check_safety_thresholds(node_id, phase_params, readings, session,
                                           sealed=container_sealed)

    # ── Actuation gates. Pause and no-rules stop actuator DECISIONS here, after
    # safety detection above has already run. A remote "pause automation"
    # (cloud → set_paused) halts every actuator decision, not just filters
    # individual rules; the flag is loaded from the DB once, then cached, so the
    # hot path is a single bool read once warm. ──
    if _paused:
        return
    await ensure_overrides_loaded()
    rules = await load_rules()
    if not managed:
        rules = [r for r in rules if _is_life_safety_rule(r)]
    if not rules:
        return

    # Per-actuator arbitration. Rules run highest priority first, and an
    # actuator belongs to the highest-priority rule whose condition holds right
    # now: a lower-priority rule on the same actuator is skipped — in this pass
    # AND while that rule sits in its cooldown with its condition still true
    # (for up to its duration_sec, else its cooldown). Every matching rule used
    # to fire, so the LOWEST-priority command was the last one sent: the CO2
    # floor's FAE-off was undone by the scheduled FAE cycle, cordyceps blue by
    # the white photoperiod scene, a 255-PWM emergency exhaust by the 180-PWM
    # humidity vent. Rules of equal priority don't block each other.
    claims: dict[tuple[str, str | None], int] = {}

    for rule in rules:
        try:
            prev_seen = _rule_seen.get(rule.id)
            _rule_seen[rule.id] = now
            cron_since = (max(prev_seen, now - _CRON_CATCHUP_SECONDS)
                          if prev_seen is not None else None)
            life_safety = _is_life_safety_rule(rule)

            if rule.applies_to_phases and current_phase not in rule.applies_to_phases:
                continue

            if rule.applies_to_species and not (
                session and rule_applies_to_species(
                    rule.applies_to_species, session["species_profile_id"])):
                continue

            # Sealed vessel: the chamber can't reach the substrate, so
            # environmental actuation is a no-op. (Temperature still applies —
            # a fridge/heater warms the whole chamber including the vessel.)
            # Life-safety rules protect the room, not the grow, and are exempt
            # from this and the fae_mode gates below.
            if not life_safety and container_sealed and _acts_on_chamber_environment(rule.action):
                continue

            # Honour the species profile's fae_mode. A phase declaring
            # fae_mode="none" (every colonization phase) must not get its FAE
            # and exhaust fans driven by the CO2 rules, venting the 5000-15000ppm
            # the mycelium needs. A timed FAE schedule additionally needs a phase
            # that schedules FAE — in a "passive" phase (CO2 held high on
            # purpose) the Scheduled FAE Cycle fell back to a 20-min/300-s burst.
            if not life_safety and _is_air_exchange_action(rule.action) and phase_params is not None:
                fae_mode = getattr(phase_params, "fae_mode", None)
                if fae_mode == "none":
                    continue
                if (rule.condition.type == ConditionType.SCHEDULE
                        and fae_mode not in _SCHEDULED_FAE_MODES):
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
            resolved = (await resolve_node_target(rule.action.target, chamber_nodes)
                        or rule.action.target)
            if (is_overridden(resolved, rule.action.channel)
                    or is_overridden(rule.action.target, rule.action.channel)):
                continue

            key = _arbitration_key(rule.action, resolved)
            owner = claims.get(key)
            if owner is not None and owner > rule.priority:
                continue

            last = _last_fired.get(rule.id, 0)
            if now - last < rule.cooldown_seconds:
                # Still in force? Then it keeps the actuator from lower rules.
                hold = _resolved_duration(rule.action, phase_params) or rule.cooldown_seconds
                if now - last < hold and _evaluate_condition(
                        rule.condition, readings, phase_params, last or None, cron_since):
                    claims.setdefault(key, rule.priority)
                continue

            if _evaluate_condition(rule.condition, readings, phase_params,
                                   last if last else None, cron_since):
                claims.setdefault(key, rule.priority)
                await _fire_rule(rule, readings, session, sio, phase_params,
                                 chamber_nodes=chamber_nodes, node_id=node_id)
                async with _state_lock:
                    _last_fired[rule.id] = now

        except Exception as e:
            log.error("Error evaluating rule '%s': %s", rule.name, e)


def _alert_due(key: str, severity: str) -> bool:
    """True (and the slot is claimed) when this alert may go out now.

    See _alert_last_sent: one page per key per _ALERT_REPEAT_SECONDS window.
    """
    now = time.time()
    last = _alert_last_sent.get(key)
    if last is not None and now - last < _ALERT_REPEAT_SECONDS[severity]:
        return False
    _alert_last_sent[key] = now
    return True


def _alert_recent(key: str, severity: str) -> bool:
    """Has `key` gone out within its window? (Reads only — claims nothing.)"""
    last = _alert_last_sent.get(key)
    return last is not None and time.time() - last < _ALERT_REPEAT_SECONDS[severity]


async def _forward_event(event_type: str, data: dict) -> None:
    """Forward an alert to the cloud relay; never raises."""
    # Late import — cloud/service.py imports this module (circular).
    from ..cloud import service as cloud_service
    try:
        await cloud_service.forward_event(event_type, data)
    except Exception as e:
        log.warning("forward_event(%s) failed: %s", event_type, e)


async def _emit_co2_emergency(node_id: str, co2: float, threshold: float, sid) -> None:
    """The CO2 emergency page (local ntfy + cloud `co2_alert`), deduplicated.

    Shared by the stage band check and the life-safety check, so a reading
    that trips both pages once.
    """
    if not _alert_due(f"{node_id}:co2:high:emergency", "emergency"):
        return
    try:
        await co2_alert(int(co2))
    except Exception as e:
        log.warning("co2_alert failed: %s", e)
    await _forward_event("co2_alert", {
        "node_id": node_id, "co2_ppm": int(co2), "value": float(co2),
        "threshold_ppm": threshold, "severity": "emergency", "session_id": sid,
    })


async def _check_life_safety(node_id: str, readings: dict, sid) -> None:
    """Page on a CO2 level dangerous to people, whatever the grow state.

    The stage alerts need an active session and a phase that manages CO2, and
    skip sealed containers — none of which matter when the room itself is at
    an IDLH CO2 level. (The firmware's own >4000 ppm alert is a colonization-
    normal level and is not forwarded to local ntfy.)
    """
    co2 = readings.get("co2_ppm")
    if isinstance(co2, (int, float)) and not isinstance(co2, bool) and co2 > _CO2_LIFE_SAFETY_PPM:
        await _emit_co2_emergency(node_id, co2, _CO2_LIFE_SAFETY_PPM, sid)


async def _check_safety_thresholds(
    node_id: str, phase_params, readings: dict, session: dict | None, *, sealed: bool = False,
):
    """Page the operator when readings breach species ceilings by a safety margin.

    Two channels fire in parallel:
    - local ntfy via `temperature_alert` / `co2_alert` (so a Pi running headless
      on the LAN gets notified even if the cloud connector is disconnected)
    - cloud event via `forward_event` (so premium mobile subscribers get their
      push notification via the cloud relay's escalation engine)

    Each (node, parameter, direction, tier) goes out at most once per
    _ALERT_REPEAT_SECONDS window. ``sealed`` (the substrate is in a sealed
    vessel) skips the humidity and CO2 bands: the chamber's air is not the
    substrate's, so a sealed grow bag in a 45 %-RH closet is not an emergency.
    """
    sid = session.get("id") if session else None

    async def _emit(param: str, severity: str, direction: str, value: float, threshold: float):
        if not _alert_due(f"{node_id}:{param}:{direction}:{severity}", severity):
            return
        # Local ntfy: warning tier is low-priority, emergency is critical.
        title = f"{param.title()} {severity.upper()}"
        msg = f"{param} {value} ({direction}); threshold {threshold}"
        try:
            if severity == "emergency":
                # The title is the same for every node and direction, so it
                # can't be the ntfy dedup key: a second node's emergency (or
                # the opposite excursion) inside 15 min would be swallowed.
                await notify_critical(title, msg, tags=[param],
                                      dedup_key=f"{node_id}:{param}:{direction}:emergency")
            else:
                await notify_warning(title, msg, dedup_key=f"{node_id}:{param}:{direction}")
        except Exception as e:
            log.warning("local %s alert failed: %s", param, e)
        # Cloud escalation: `<param>_alert` is the existing emergency event the
        # cloud escalation matcher knows; `<param>_warning` is the new lower tier.
        event_type = f"{param}_alert" if severity == "emergency" else f"{param}_warning"
        await _forward_event(event_type, {
            "node_id": node_id, "value": value, "direction": direction,
            "threshold": threshold, "severity": severity, "session_id": sid,
        })

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

    if sealed:
        return

    humidity = readings.get("humidity")
    if isinstance(humidity, (int, float)):
        # When the phase doesn't actively drive humidity (cold storage — a
        # fridge idles at ~45% RH by design), only page on a HIGH excursion.
        # A low reading is expected, not an emergency the chamber is failing to
        # correct — same reasoning as the CO2 fae_mode="none" gate below.
        hum_min = (phase_params.humidity_min
                   if getattr(phase_params, "humidity_driven", True) else None)
        sev, direction = _band_severity(
            humidity, hum_min, phase_params.humidity_max,
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
            await _emit_co2_emergency(
                node_id, co2, phase_params.co2_max_ppm + _CO2_EMERG_MARGIN_PPM, sid,
            )
        elif sev == "warning":
            await _emit("co2", "warning", "high", float(co2),
                        phase_params.co2_max_ppm + _CO2_WARN_MARGIN_PPM)


def _evaluate_condition(
    condition: RuleCondition,
    readings: dict,
    phase_params=None,
    last_fired: float | None = None,
    cron_since: float | None = None,
) -> bool:
    if condition.type == ConditionType.THRESHOLD:
        return _eval_threshold(condition.threshold, readings, phase_params)
    elif condition.type == ConditionType.SCHEDULE:
        # phase_params carries the species' light window + FAE period; last_fired
        # makes interval schedules elapsed-based. Neither used to reach here.
        return _eval_schedule(condition.schedule, phase_params, last_fired, cron_since)
    elif condition.type == ConditionType.COMPOUND:
        compound = condition.compound
        results = [
            _evaluate_condition(c, readings, phase_params, last_fired, cron_since)
            for c in compound.conditions
        ]
        if compound.op.value == "AND":
            return all(results)
        else:
            return any(results)
    return False


def _temp_mid_f(phase_params):
    lo = getattr(phase_params, "temp_min_f", None)
    hi = getattr(phase_params, "temp_max_f", None)
    return None if lo is None or hi is None else (lo + hi) / 2


# profile_ref names the engine derives from PhaseParams fields rather than
# reading one directly. temp_mid_f is the midpoint of the phase's temperature
# band — the gate that keeps the forecast pre-cool rules in the upper half.
_DERIVED_PROFILE_REFS = {"temp_mid_f": _temp_mid_f}


def _profile_value(phase_params, ref: str):
    """A threshold's profile_ref resolved against the active phase params."""
    value = getattr(phase_params, ref, None)
    if value is None and ref in _DERIVED_PROFILE_REFS:
        value = _DERIVED_PROFILE_REFS[ref](phase_params)
    return value


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
        target = _profile_value(phase_params, threshold.profile_ref)
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


def _eval_cron_since(expr: str, since: float) -> bool:
    """Did any minute in (since, now] match the cron expression?

    Minutes are checked by their start time, so a minute whose start the
    previous evaluation already covered is never matched twice.
    """
    if len(expr.split()) != 5:
        return _eval_cron(expr, time.localtime())  # logs the malformed expression once
    now = time.time()
    t = (int(since) // 60 + 1) * 60
    while t <= now:
        if _eval_cron(expr, time.localtime(t)):
            return True
        t += 60
    return False


def _eval_schedule(
    schedule,
    phase_params=None,
    last_fired: float | None = None,
    cron_since: float | None = None,
) -> bool:
    if schedule is None:
        return False

    now = time.localtime()

    if schedule.photoperiod:
        return _eval_photoperiod(schedule, phase_params)

    if schedule.cron:
        # With cron_since (when the rule was last evaluated), a minute that fell
        # between two telemetry frames still counts; without it, only the
        # current minute does.
        if cron_since is not None:
            return _eval_cron_since(schedule.cron, cron_since)
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


def _vendor_is_on(action) -> bool | None:
    """What a vendor action does to its device: True switches it on, False
    switches it off, None is neither (a setpoint change).

    ``action.state`` defaults to "on" for every rule, so for a vendor action it
    says nothing — a ``set_power(on=False)`` rule still reads state="on". The
    vendor params carry the real meaning, read the way the dispatcher coerces
    them: set_power's ``on`` is a lax bool ("false"/"off"/"0" switch the device
    OFF). A value the device would not accept, or whose meaning is unclear, is
    None — neither arms a ceiling nor clears one.
    """
    params = action.vendor_params or {}
    if action.vendor_action == "set_power":
        try:
            return _LAX_BOOL.validate_python(params.get("on"))
        except ValidationError:
            return None
    if action.vendor_action in ("set_dim", "set_output"):
        value = params.get("percent" if action.vendor_action == "set_dim" else "value")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        return None
    return None


def _vendor_watchdog_target(slug: str, params: dict) -> str | None:
    """Watchdog key for a vendor device: ``vendor:<slug>:<device-id>``.

    Keyed on the DEVICE rather than the rule's free-form override target, so
    two rules driving two Kasa plugs under one ``vendor:kasa`` target each keep
    their own ceiling, and so the OFF can be rebuilt from the key alone after a
    reboot. None when the vendor has no OFF or the device id is missing.
    """
    spec = _VENDOR_SAFETY_OFF.get(slug)
    if spec is None:
        return None
    device = params.get(spec[1])
    if device is None or device == "":
        return None
    return f"vendor:{slug}:{device}"


def _vendor_safety_off(slug: str, on_params: dict) -> tuple[str, dict] | None:
    """(action, params) that switch this vendor device OFF, or None."""
    spec = _VENDOR_SAFETY_OFF.get(slug)
    if spec is None:
        return None
    off_action, id_param, off_params = spec
    device = on_params.get(id_param)
    if device is None or device == "":
        return None
    params = {id_param: device, **off_params}
    if slug == "agrowtek" and not isinstance(on_params.get("value"), bool):
        # Mirror the ON value's type: an output driven with true/false is
        # switched off with false, one driven with a number (or unknown) with 0.
        params["value"] = 0
    return off_action, params


async def _vendor_rule_for_watchdog(
    rule_name: str, slug: str, target: str,
) -> tuple[dict, str] | None:
    """(ON params, override target) of the vendor rule that armed a persisted
    watchdog, if found.

    Lets a rehydrated watchdog mirror the exact ON and lock out the key the
    rule's override check reads, and recovers rows persisted before watchdogs
    were keyed per device (their target is the rule's free-form override key,
    e.g. a bare ``vendor:kasa``). A lookup failure is None, not an error: the
    device-keyed OFF must still go out.
    """
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, name, description, enabled, priority, rule_data "
                "FROM automation_rules WHERE name = ?",
                (rule_name,),
            )
            rows = await cursor.fetchall()
    except Exception as e:
        log.error("safety watchdog: looking up rule %r failed: %s", rule_name, e)
        return None
    for row in rows:
        try:
            action = AutomationRule.model_validate(deserialize_rule_row(row)).action
        except Exception:
            continue
        if action.vendor_slug != slug:
            continue
        params = action.vendor_params or {}
        if target in (_vendor_watchdog_target(slug, params), action.target):
            return params, action.target
    return None


async def _resolve_vendor_off(
    target: str, rule_name: str, on_params: dict | None,
) -> tuple[tuple[str, str, dict] | None, str | None]:
    """((slug, action, params) that switch off the vendor device a watchdog
    guards, or None; the rule's own override target when it had to be looked up)."""
    parts = target.split(":", 2)
    if len(parts) < 2 or not parts[1]:
        return None, None
    slug = parts[1]
    device = parts[2] if len(parts) == 3 else ""
    rule_target = None
    if on_params is None:
        found = await _vendor_rule_for_watchdog(rule_name, slug, target)
        if found is not None:
            on_params, rule_target = found
    if on_params is None and device and slug in _VENDOR_SAFETY_OFF:
        on_params = {_VENDOR_SAFETY_OFF[slug][1]: device}
    if on_params is None:
        return None, rule_target
    off = _vendor_safety_off(slug, on_params)
    if off is None:
        return None, rule_target
    return (slug, off[0], off[1]), rule_target


async def _send_safety_off(
    target: str, channel: str | None, vendor_off: tuple[str, str, dict] | None,
) -> bool:
    """Send one safety OFF over the actuator's own transport.

    True only when the command went out. A vendor target goes through the
    integrations dispatcher (a publish to sporeprint/vendor:*/cmd/* reaches no
    subscriber); a plug target through its own Shelly/Tasmota topic tree; a
    native node through sporeprint/<node>/cmd/*. Transport errors raise.
    """
    if target.startswith("vendor:"):
        if vendor_off is None:
            return False
        slug, off_action, off_params = vendor_off
        await _vendor_actions.dispatch(slug, off_action, off_params)
        return True
    # Same transport split as _fire_rule: a plug target's OFF must go out on
    # the vendor's own topic tree — publishing it to sporeprint/plug-* reaches
    # nothing, which for THIS path means a stuck-on heater.
    if await is_plug_target(target):
        return await send_plug_command(target, "off")
    topic = (
        f"sporeprint/{target}/cmd/{channel}"
        if channel else f"sporeprint/{target}/cmd/config"
    )
    return await mqtt_publish(topic, {"state": "off", "reason": "safety_max_on_seconds"})


async def _persist_safety_watchdog(
    target: str, channel: str | None, rule_name: str, delay_seconds: int,
) -> None:
    """Record an armed watchdog so it can be rehydrated after Pi restart."""
    now = time.time()
    expires_at = now + delay_seconds
    async with get_db() as db:
        if channel is None:
            # SQLite treats NULLs in a PRIMARY KEY as distinct, so ON CONFLICT
            # never fires for a channel-less (plug / vendor) target and every
            # re-arm appended another row. Replace the row explicitly instead.
            await db.execute(
                "DELETE FROM safety_watchdogs WHERE target = ? AND channel IS NULL",
                (target,),
            )
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
    """Remove the persisted record when an explicit OFF makes the watchdog moot."""
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


def _actuator_lock(key: str) -> asyncio.Lock:
    """The per-actuator lock (see _actuator_locks), created on first use."""
    lock = _actuator_locks.get(key)
    if lock is None:
        lock = _actuator_locks[key] = asyncio.Lock()
    return lock


def _cancel_safety_task(target: str, channel: str | None) -> None:
    """Cancel any pending auto-off for this actuator.

    Called when a rule explicitly turns the actuator off, or when a new watchdog
    replaces this one. A manual override does NOT cancel it (see set_override).
    Persistent state cleanup is done by the caller via
    `_clear_persisted_safety_watchdog` — splitting sync cancel from async
    DB cleanup keeps this helper usable from sync code paths.
    """
    key = _safety_key(target, channel)
    _safety_deadlines.pop(key, None)
    _safety_last_on.pop(key, None)
    task = _safety_tasks.pop(key, None)
    if task and not task.done():
        task.cancel()


async def note_actuator_off(
    target: str, channel: str | None, *, sent_at: float | None = None,
) -> None:
    """Tell the safety watchdog an OFF reached this actuator outside automation.

    For a path that switches an actuator off without going through _fire_rule
    (a manual plug/node command, a cloud command, session-end safing). Call it
    after the OFF was actually published, passing ``sent_at`` = time.time()
    taken just BEFORE publishing. The ceiling on that actuator is cleared, so
    the next automation ON starts a fresh one instead of keeping a stale
    deadline and tripping early (a false page and a 15-minute lockout).

    A ceiling whose latest ON finished going out at or after ``sent_at`` is
    kept: that ON may have landed after this OFF, so the actuator may be ON.
    A plug target also clears the ceiling armed under its other name (plug id
    vs ``plug-<role>``).
    """
    sent_at = time.time() if sent_at is None else sent_at
    targets = {target}
    if channel is None and await is_plug_target(target):
        targets = await plug_aliases(target)
    cleared: list[str] = []
    async with contextlib.AsyncExitStack() as stack:
        # Sorted, so two callers can never take the same pair in opposite order.
        for t in sorted(targets):
            await stack.enter_async_context(_actuator_lock(_safety_key(t, channel)))
        for t in sorted(targets):
            if _safety_last_on.get(_safety_key(t, channel), 0.0) >= sent_at:
                continue
            _cancel_safety_task(t, channel)
            cleared.append(t)
        if cleared:
            async with get_db() as db:
                for t in cleared:
                    await db.execute(
                        "DELETE FROM safety_watchdogs WHERE target = ? AND channel IS ?",
                        (t, channel),
                    )
                await db.commit()
    if cleared:
        log.info("Safety watchdog cleared for %s (channel %s): switched OFF outside automation",
                 ", ".join(cleared), channel)


async def note_actuator_on(target: str, channel: str | None) -> None:
    """Tell the engine this actuator may be ON because of something outside it.

    For a path that switches an actuator on (or sends it any non-OFF command)
    without going through _fire_rule: a manual node or plug command, a cloud
    command, or the node's own report that a channel is ON (a physical
    override button). Call it after the command was actually published.

    Drops the redundant-OFF suppression (_last_off_sent) for the actuator, so
    a rule whose cutoff condition still holds re-sends its OFF at the next
    evaluation instead of waiting out _OFF_REASSERT_SECONDS. Safety ceilings
    are not touched: they only time automation's own ONs. A plug target also
    clears the entry kept under its other name (plug id vs ``plug-<role>``).
    """
    targets = {target}
    if channel is None and await is_plug_target(target):
        targets = await plug_aliases(target)
    for t in targets:
        _last_off_sent.pop(_safety_key(t, channel), None)


# Session-end safing (sessions.service) switches actuators OFF outside
# automation. That module can't import this one (this one imports it), so it
# calls back through its actuator-off listener list.
add_actuator_off_listener(note_actuator_off)


async def _arm_safety_watchdog(
    target: str,
    channel: str | None,
    rule: AutomationRule,
    *,
    held_on: bool,
    vendor_params: dict | None = None,
    lockout_target: str | None = None,
) -> None:
    """Arm (or keep) the safety_max_on_seconds ceiling for an actuator just switched ON.

    ``held_on`` is True when the ON stays on until something turns it off (a
    smart plug or vendor device — both ignore duration_sec — or a native
    channel commanded without a duration). A re-fired held-ON keeps the
    ceiling that is already running: the ceiling counts from when the actuator
    was first switched on, not from the latest re-fire. Re-arming on every
    re-fire is what let a Heating Trigger that re-fires every 300 s push its
    3600 s ceiling out forever. A tighter ceiling from another rule still wins.

    Keeping a ceiling whose deadline has already passed is safe: _fire_rule
    calls this under the actuator lock, and a tripping ceiling takes that lock
    before its OFF, so its OFF lands after this ON.

    A native ON with a duration is a firmware-timed pulse that ends by itself
    (and the firmware's own per-channel max-on backstops it), so each pulse
    re-arms from its own start, as before.
    """
    ceiling = rule.safety_max_on_seconds
    key = _safety_key(target, channel)
    now = time.time()
    existing = _safety_tasks.get(key)
    if held_on and existing is not None and not existing.done():
        deadline = _safety_deadlines.get(key)
        if deadline is None or deadline <= now + ceiling:
            _safety_last_on[key] = now
            return
    _cancel_safety_task(target, channel)
    # Persist BEFORE starting the task: a short ceiling could otherwise reach
    # its row-delete before the row exists, leaving a stale row that the next
    # boot turns into a spurious OFF. A persistence failure must not stop the
    # in-process ceiling from being armed, though.
    try:
        await _persist_safety_watchdog(target, channel, rule.name, ceiling)
    except Exception as e:
        log.error("persisting safety watchdog for %s:%s failed: %s", target, channel, e)
    # Another arm may have registered a task for this key while we awaited the
    # persist; replace it rather than orphan it (an orphan can't be cancelled).
    _cancel_safety_task(target, channel)
    _safety_deadlines[key] = now + ceiling
    _safety_last_on[key] = now
    _safety_tasks[key] = asyncio.create_task(_safety_auto_off(
        target, channel, ceiling, rule.name,
        vendor_params=vendor_params, held_on=held_on, lockout_target=lockout_target,
    ))


async def _safety_lockout(target: str, channel: str | None, rule_name: str) -> bool:
    """Hold automation off an actuator whose ceiling just tripped.

    An expiring ManualOverride, so it shows in the overrides list with its
    reason and the operator can clear it early. An existing hold is left alone
    (automation is already off the actuator; don't shorten the operator's hold)
    and False is returned. If the override cannot be persisted it is still
    held in memory, so automation stays off the actuator until the Pi restarts.
    Never raises: the trip's OFF must go out regardless.
    """
    try:
        await ensure_overrides_loaded()
    except Exception as e:
        log.error("loading overrides for safety lockout failed: %s", e)
    if is_overridden(target, channel):
        return False
    override = ManualOverride(
        target=target,
        channel=channel,
        locked=True,
        reason=(
            f"safety lockout: rule '{rule_name}' hit safety_max_on_seconds — "
            f"automation held off for {_SAFETY_LOCKOUT_SECONDS // 60} min"
        ),
        expires_at=time.time() + _SAFETY_LOCKOUT_SECONDS,
    )
    try:
        await set_override(override)
    except Exception as e:
        log.error("persisting safety lockout for %s:%s failed: %s — holding it in memory",
                  target, channel, e)
        async with _state_lock:
            _overrides[_override_key(target, channel)] = override
    return True


async def _safety_auto_off(
    target: str,
    channel: str | None,
    delay_seconds: float,
    rule_name: str,
    *,
    vendor_params: dict | None = None,
    held_on: bool | None = None,
    lockout_target: str | None = None,
) -> None:
    """Sleep then switch the actuator OFF; fire-risk watchdog for stuck-on actuators.

    The OFF goes out over the actuator's own transport (_send_safety_off): the
    vendor dispatcher, the smart-plug topic tree, or sporeprint/<node>/cmd/*.
    Retries back off 2 s → 30 s and keep going for ~10 min
    (_SAFETY_OFF_RETRY_DELAYS), so an MQTT outage — or the boot window before
    MQTT and the vendor drivers are up — does not leave an actuator stuck ON.
    A persistent failure is logged at ERROR and leaves the persisted watchdog
    row in place so rehydrate_safety_watchdogs() retries on the next Pi boot.

    ``held_on`` (see _arm_safety_watchdog) marks a real ceiling breach: the
    actuator was still being held ON at the deadline. Such a trip locks
    automation out of the actuator for _SAFETY_LOCKOUT_SECONDS BEFORE its OFF
    goes out (and keeps the lockout even if the OFF fails), then pages a
    WARNING (CRITICAL if the OFF could not be delivered). A self-terminating
    pulse that already ended just gets the redundant OFF. None derives it from
    the transport (plug / vendor → held ON), which is what a rehydrated row
    gets. ``lockout_target`` is the key the rule's override check reads when it
    differs from ``target`` (a vendor rule's free-form target); a rehydrated
    vendor row recovers it from its rule.
    """
    key = _safety_key(target, channel)
    try:
        await asyncio.sleep(delay_seconds)
        is_vendor = target.startswith("vendor:")
        try:
            if held_on is None:
                try:
                    held_on = is_vendor or await is_plug_target(target)
                except Exception as e:
                    log.error("safety_auto_off: transport lookup for %s:%s failed: %s",
                              target, channel, e)
                    held_on = True  # unknown → treat it as a real breach
            vendor_off = None
            if is_vendor:
                vendor_off, rule_target = await _resolve_vendor_off(target, rule_name, vendor_params)
                lockout_target = lockout_target or rule_target
                if vendor_off is None:
                    log.error(
                        "safety_auto_off: no OFF mapping for vendor target %r (rule %r) "
                        "— it cannot be switched off automatically", target, rule_name,
                    )
            # The ceiling has tripped. Under the actuator lock (which _fire_rule
            # holds from its override re-check through its ON and arm): stop
            # being the running watchdog, and lock automation out BEFORE the OFF
            # goes out. An ON already on the wire finishes first, so the OFF
            # below lands after it; any later ON sees the lockout and is refused.
            # With the lockout placed after the OFF, a re-fire in between turned
            # the heater straight back on and — finding this watchdog still
            # registered — armed no new ceiling.
            locked_out = False
            async with _actuator_lock(key):
                if _safety_tasks.get(key) is asyncio.current_task():
                    _safety_tasks.pop(key, None)
                    _safety_deadlines.pop(key, None)
                    _safety_last_on.pop(key, None)
                if held_on:
                    locked_out = await _safety_lockout(lockout_target or target, channel, rule_name)
            published = False
            attempt = 0
            while not (is_vendor and vendor_off is None):
                attempt += 1
                try:
                    published = await _send_safety_off(target, channel, vendor_off)
                except Exception as pub_err:
                    log.warning(
                        "safety_auto_off publish attempt %d for %s:%s raised %s — retrying",
                        attempt, target, channel, pub_err,
                    )
                    published = False
                if published:
                    break
                if attempt > len(_SAFETY_OFF_RETRY_DELAYS):
                    # Ran out of retries — leave the persisted row so the next
                    # boot retries via rehydrate_safety_watchdogs().
                    log.error(
                        "safety_auto_off exhausted retries for %s:%s (rule %r) — "
                        "actuator may still be ON; watchdog row retained for next boot",
                        target, channel, rule_name,
                    )
                    break
                await asyncio.sleep(_SAFETY_OFF_RETRY_DELAYS[attempt - 1])
            log.warning(
                "safety_max_on_seconds triggered for rule '%s' → %s:%s (published=%s attempts=%d)",
                rule_name, target, channel, published, attempt,
            )
            now = time.time()
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO automation_firings
                       (rule_id, rule_name, timestamp, condition_met, action_taken, session_id, status, error)
                       VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
                    (
                        None,
                        f"safety_max_on_seconds:{rule_name}",
                        now,
                        json.dumps({"reason": "safety_max_on_seconds", "original_rule": rule_name}),
                        json.dumps({"state": "off"}),
                        "sent" if published else "failed",
                        None if published else f"safety OFF not delivered after {attempt} attempts",
                    ),
                )
                if published:
                    # Only clear once the OFF went out — and only a row whose
                    # deadline has passed, so a watchdog re-armed by an ON that
                    # raced this OFF keeps its own row.
                    await db.execute(
                        "DELETE FROM safety_watchdogs "
                        "WHERE target = ? AND channel IS ? AND expires_at <= ?",
                        (target, channel, now + 5),
                    )
                await db.commit()
            if held_on:
                label = f"{target}:{channel}" if channel else target
                if published:
                    held = (
                        f"automation held off it for {_SAFETY_LOCKOUT_SECONDS // 60} min"
                        if locked_out else
                        "an existing manual hold keeps automation off it"
                    )
                    await notify_warning(
                        f"Safety cutoff: {label}",
                        f"Rule '{rule_name}' held {label} on past its safety_max_on_seconds "
                        f"ceiling. Switched OFF; {held}.",
                        dedup_key=f"safety_max_on:{key}",
                    )
                else:
                    await notify_critical(
                        f"Safety cutoff FAILED: {label}",
                        f"Could not switch {label} OFF after rule '{rule_name}' hit its "
                        f"safety_max_on_seconds ceiling — it may still be ON. Check it now.",
                        tags=["warning", "fire"],
                    )
        except Exception as e:
            log.error("safety auto-off bookkeeping for %s:%s failed: %s", target, channel, e)
    except asyncio.CancelledError:
        pass
    finally:
        current = _safety_tasks.get(key)
        if current is not None and current.done():
            _safety_tasks.pop(key, None)


async def rehydrate_safety_watchdogs() -> int:
    """Re-arm persisted safety watchdogs on Pi boot. Returns the count scheduled.

    Every persisted row becomes a _safety_auto_off task: a row still in the
    future waits out its remaining time, a row that expired while the Pi was
    down fires with no delay. The OFF is never sent inline here: this runs in
    the lifespan before MQTT is connected and before the vendor drivers start,
    so an inline publish returned False (and went to the wrong topic for plugs
    and vendor devices) while the row was deleted anyway — leaving the heater
    ON with nothing left to retry it. The task path routes each target over its
    own transport, retries until that transport is up, and deletes the row only
    once the OFF actually went out.

    Duplicate rows for one actuator (left by the old NULL-channel upsert)
    collapse to the tightest deadline; the extras are deleted.
    """
    now = time.time()
    keep: dict[str, dict] = {}
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT rowid, target, channel, rule_name, expires_at FROM safety_watchdogs "
            "ORDER BY expires_at"
        )
        extra: list[int] = []
        for row in await cursor.fetchall():
            key = _safety_key(row["target"], row["channel"])
            if key in keep:
                extra.append(row["rowid"])
            else:
                keep[key] = dict(row)
        if extra:
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query — only "?" placeholders or whitelisted column names are interpolated; every value is a bound parameter
            await db.execute(
                f"DELETE FROM safety_watchdogs WHERE rowid IN ({','.join('?' * len(extra))})",
                extra,
            )
            await db.commit()
    for key, row in keep.items():
        target = row["target"]
        channel = row["channel"]
        expires_at = float(row["expires_at"])
        remaining = max(0.0, expires_at - now)
        if remaining > 0:
            log.info("Rehydrated safety watchdog for %s:%s (%.0fs remaining)",
                     target, channel, remaining)
        else:
            log.warning(
                "Safety watchdog for %s:%s expired while offline (%.0fs overdue) — "
                "scheduling OFF now", target, channel, now - expires_at,
            )
        _cancel_safety_task(target, channel)
        _safety_deadlines[key] = expires_at
        _safety_tasks[key] = asyncio.create_task(
            _safety_auto_off(target, channel, remaining, row["rule_name"])
        )
    return len(keep)


def _watchdog_actuator(action, target: str) -> tuple[str | None, str | None]:
    """(target, channel) the safety watchdog for this action is keyed on.

    A native node or plug: the RESOLVED target, so the auto-OFF goes out on the
    same topic the ON did (V3-2). A vendor device: per DEVICE
    (``vendor:<slug>:<id>``), or None when the vendor has no OFF to send.
    """
    if action.vendor_slug:
        return _vendor_watchdog_target(action.vendor_slug, action.vendor_params or {}), None
    return target, action.channel


async def _fire_rule(rule: AutomationRule, readings: dict, session: dict | None, sio=None,
                     phase_params=None, *, chamber_nodes: list[str] | None = None,
                     node_id: str | None = None):
    action = rule.action

    # Resolve a seeded native-node placeholder (relay-01 / light-01) to the
    # chamber's real relay/lighting node before composing the topic or arming
    # the safety watchdog — a real node registers under a MAC-derived id, so a
    # command published to the placeholder reaches no subscriber and would log
    # status='sent' while nothing moves. A non-placeholder target (a real node
    # id, a plug-*, a vendor key) resolves to itself; an unresolvable
    # placeholder falls back to itself so validate_action_channel's warning
    # below still surfaces the "no node of this role" gap. (V3-2) With
    # chamber_nodes, only that chamber's (or an unassigned) node is chosen.
    target = await resolve_node_target(action.target, chamber_nodes) or action.target

    # evaluate_rules checked the hold before calling us, but a safety ceiling
    # can trip — and lock the actuator out — between that check and this
    # command reaching the wire. Re-check under the actuator lock, which the
    # tripping ceiling also takes before its OFF: either this command is sent
    # (and its watchdog armed or kept) before the lockout and the OFF, or it
    # sees the lockout here and is not sent.
    await ensure_overrides_loaded()
    wd_target, wd_channel = _watchdog_actuator(action, target)
    lock = (_actuator_lock(_safety_key(wd_target, wd_channel))
            if wd_target is not None else contextlib.nullcontext())
    async with lock:
        if (is_overridden(target, action.channel)
                or is_overridden(action.target, action.channel)):
            log.info("Rule '%s' not fired: %s:%s is held (manual hold or safety lockout)",
                     rule.name, action.target, action.channel)
            return
        status = await _send_rule_action(rule, target, readings, session, sio, phase_params)

    # Notify only after the actuator lock is released: ntfy is an HTTP call
    # (5 s timeout), and a safety ceiling tripping on this actuator takes the
    # same lock before its OFF.
    if status is not None and rule.notification:
        await _notify_rule_fired(rule, target, status, readings, node_id=node_id)


def _is_plain_off(action) -> bool:
    """A native/plug OFF with nothing else in it (no scene). A pwm on an OFF
    is never published (drop_duty_from_off), so it doesn't make one special."""
    return action.state == "off" and not action.vendor_slug and not action.scene


async def _plug_reports_on(target: str) -> bool:
    """Does the paired plug behind `target` report its relay ON?"""
    role = target[len("plug-"):] if target.startswith("plug-") else None
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT last_state FROM smart_plugs WHERE plug_id = ? OR device_role = ? "
            "ORDER BY (plug_id = ?) DESC LIMIT 1",
            (target, role, target),
        )
        row = await cursor.fetchone()
    return bool(row and (row["last_state"] or "").lower() == "on")


async def _skip_redundant_off(rule: AutomationRule, target: str, plug: bool) -> bool:
    """True when this OFF would change nothing, so it is neither sent nor logged.

    An OFF to a smart plug that isn't paired reaches no device (it used to log
    a 'failed' firing and a warning every minute). An OFF to an actuator this
    engine already switched off less than _OFF_REASSERT_SECONDS ago is skipped
    too — unless a plug reports it is ON again (switched on by hand), or an ON
    since then went through note_actuator_on (which drops the entry). Past that
    window the OFF is re-sent as a safety net.
    """
    if not _is_plain_off(rule.action):
        return False
    if plug and not await target_is_present(target):
        return True
    last = _last_off_sent.get(_safety_key(target, rule.action.channel))
    if last is None or time.time() - last >= _OFF_REASSERT_SECONDS:
        return False
    return not (plug and await _plug_reports_on(target))


def _rule_watches_co2_high(rule: AutomationRule) -> bool:
    """A rule whose trigger is plain "CO2 above X" (Emergency CO2 Exhaust, CO2
    Hard Ceiling) — the event the CO2 emergency page already reports."""
    th = rule.condition.threshold
    return (rule.condition.type == ConditionType.THRESHOLD and th is not None
            and th.sensor == "co2_ppm" and th.operator in ("gt", "gte"))


async def _notify_rule_fired(rule: AutomationRule, target: str, status: str,
                             readings: dict, *, node_id: str | None = None) -> None:
    """Honour the rule's `notification` flag — it used to be read nowhere.

    Priority >= _LIFE_SAFETY_PRIORITY pages CRITICAL, anything else is a
    WARNING; each rule notifies at most once per _ALERT_REPEAT_SECONDS window
    of its tier (an emergency exhaust re-fires every 120 s). A delivered
    CO2-exhaust rule stays quiet while `node_id`'s CO2 emergency page (sent
    earlier in the same frame, or within its window) covers the event — one
    CO2 excursion used to page twice. An undelivered one still pages: only it
    says the exhaust never came on. Never raises.
    """
    critical = rule.priority >= _LIFE_SAFETY_PRIORITY
    if (status == "sent" and node_id and _rule_watches_co2_high(rule)
            and _alert_recent(f"{node_id}:co2:high:emergency", "emergency")):
        return
    if not _alert_due(f"rule:{rule.id}:{rule.name}", "emergency" if critical else "warning"):
        return
    action = rule.action
    what = f"{target}/{action.channel}" if action.channel else target
    shown = {k: readings[k] for k in ("temp_f", "humidity", "co2_ppm", "forecast_high_f")
             if k in readings}
    title = f"Rule fired: {rule.name}"
    message = (f"{rule.description or rule.name} — {what} → {action.state} "
               f"({'sent' if status == 'sent' else 'NOT delivered'}). Readings: {shown}")
    try:
        if critical:
            await notify_critical(title, message, tags=["warning"])
        else:
            await notify_warning(title, message, dedup_key=f"rule:{rule.id}:{rule.name}")
    except Exception as e:
        log.warning("notification for rule '%s' failed: %s", rule.name, e)


async def _send_rule_action(rule: AutomationRule, target: str, readings: dict,
                            session: dict | None, sio=None, phase_params=None):
    """Send one rule's command to its (resolved) target, audit it, and arm or
    clear its safety watchdog. Called by _fire_rule under the actuator lock.

    Returns the delivery status ('sent' / 'failed'), or None when nothing was
    sent (a redundant OFF)."""
    action = rule.action
    plug = not action.vendor_slug and await is_plug_target(target)
    if await _skip_redundant_off(rule, target, plug):
        log.debug("Rule '%s': %s:%s is already OFF — not re-sent",
                  rule.name, target, action.channel)
        return None
    log.info("Firing rule '%s' → %s:%s %s", rule.name, action.target, action.channel, action.state)

    # A species-driven duration (e.g. fae_duration_sec) resolves against the
    # active phase, so one rule serves every species instead of hardcoding a
    # number the grow profile already specifies.
    duration_sec = _resolved_duration(action, phase_params)

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
    # An OFF never carries a duty value — deployed firmware let pwm win.
    payload = drop_duty_from_off(payload)

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
            await _vendor_actions.dispatch(
                action.vendor_slug,
                action.vendor_action or "",
                action.vendor_params or {},
            )
            status = "sent"
        elif plug:
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

    # Remember what this actuator was last told (see _skip_redundant_off).
    off_key = _safety_key(target, action.channel)
    if status == "sent" and _is_plain_off(action):
        _last_off_sent[off_key] = time.time()
    else:
        _last_off_sent.pop(off_key, None)

    # safety_max_on_seconds watchdog: stops actuators from staying ON beyond a
    # species/rule-defined ceiling even if the condition that triggered the
    # rule persists. This is the fire-risk guard ("heater stuck on after a
    # power blip"). Only arm the timer when the command actually went out —
    # otherwise we'd publish an OFF that never had an ON preceding it.
    #
    # Persistence: the armed watchdog is written to `safety_watchdogs` so a Pi
    # reboot rehydrates it and either re-arms or sends OFF as soon as the
    # transport is up if expires_at has passed while we were down.
    #
    # Only an explicit OFF clears a watchdog. An ON from a rule WITHOUT a
    # ceiling (e.g. Dry Weather Humidity Boost after Humidity Boost armed one)
    # leaves the running ceiling in place — it used to cancel it and arm nothing.
    if status == "sent":
        ceiling = bool(rule.safety_max_on_seconds and rule.safety_max_on_seconds > 0)
        wd_target, wd_channel = _watchdog_actuator(action, target)
        if action.vendor_slug:
            # A vendor device is watched per DEVICE and switched off through the
            # dispatcher; its on/off meaning lives in vendor_params, not state.
            vendor_params = action.vendor_params or {}
            is_on = _vendor_is_on(action)
            held_on = True  # vendor drivers have no timed actuation
            if ceiling and is_on is not False and (is_on is None or wd_target is None):
                log.warning(
                    "Rule '%s' sets safety_max_on_seconds but %s.%s(%s) is not an ON "
                    "the watchdog can bound — the ceiling is NOT enforced",
                    rule.name, action.vendor_slug, action.vendor_action, vendor_params,
                )
        else:
            vendor_params = None
            is_on = {"on": True, "off": False}.get(action.state)
            # Plugs ignore duration_sec (send_plug_command sends bare on/off),
            # so a plug ON — like a native ON without a duration — stays on
            # until something turns it off. A native ON WITH a duration is a
            # firmware-timed pulse that ends by itself.
            held_on = plug or not duration_sec
        if wd_target is not None and is_on is False:
            # OFF explicitly sent — any pending watchdog is now redundant.
            _cancel_safety_task(wd_target, wd_channel)
            await _clear_persisted_safety_watchdog(wd_target, wd_channel)
        elif wd_target is not None and is_on and ceiling:
            await _arm_safety_watchdog(
                wd_target, wd_channel, rule,
                held_on=held_on,
                vendor_params=vendor_params,
                # A vendor lockout must land on the key the rule's override
                # check reads (its free-form target), not the device key.
                lockout_target=action.target if action.vendor_slug else None,
            )

    if sio:
        await sio.emit("rule_fired", {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "target": action.target,
            "channel": action.channel,
            "action": action.state,
            "status": status,
        })
    return status
