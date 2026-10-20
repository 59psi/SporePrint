import csv
import io
import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Collection, Sequence
from datetime import date, datetime, timedelta, timezone


# NOTE: app.automation.engine imports this module at its top, so nothing
# imported here may import app.sessions.service at module level in turn.
from ..automation.service import (
    deserialize_rule_row,
    hold_applies,
    node_off_command,
    placeholder_nodes,
)
from ..automation.smart_plugs import (
    chamber_plug,
    is_plug_target,
    plugs_for_target,
    send_plug_command,
)
from ..chambers.service import ChamberBusyError, chamber_contexts, chambers_for_node
from ..contamination.service import insert_event, publish_event
from ..db import get_db
from ..integrations import _actions as vendor_actions
from ..mqtt import mqtt_publish
from ..notifications.service import harvest_notice, notify_info, phase_reminder
from ..species.models import COLONIZATION_PHASES, GrowPhase, PhaseParams, SpeciesProfile
from ..species.profiles import BUILTIN_PROFILES, canonical_species_id
from ..species.service import get_profile, stored_species_id
from ..vision.service import _deserialize_frame
from .models import (
    FRUITING_CONTAINERS,
    ContaminationMark,
    HarvestCreate,
    NoteCreate,
    PhaseAdvance,
    SessionCreate,
    SessionUpdate,
)

log = logging.getLogger(__name__)

# Where a phase borrows setpoints when the session's species profile does not
# define it — phase_params_for (the automation engine and every other reader
# of the setpoints in force) resolves phase params through this table.
# 33 of 74 profiles fold pinning into fruiting (no primordia_induction) and 71
# have no rest phase, yet the lifecycle walks sessions through both. Rest
# borrows fruiting's envelope with the lights off (the block rests / soaks in
# the dark). Browning has NO stand-in: it is shiitake's own stage (cooler and
# much drier than the fruiting envelope), so a profile without browning
# setpoints refuses it (phase_error → 422).
PHASE_PARAM_FALLBACKS: dict[str, tuple[str, ...]] = {
    "primordia_induction": ("fruiting",),
    "fruiting": ("primordia_induction",),
    "rest": ("fruiting", "primordia_induction"),
}

# Phases that run on no species setpoints: cold storage holds the fridge cold
# whatever the species, and a complete session is not managed.
_SPECIES_AGNOSTIC_PHASES = frozenset({"cold_storage", "complete"})
# The colonization stages run in a sealed vessel (plate, LC jar, grain jar,
# bag) that the closet at most holds near ambient; CLAUDE.md §4b lists them
# as ambient / n/a / in-bag, and §6 makes agar / LC / grain optional stages.
# Profiles define only the ones they drive (71 of 74 built-ins define no
# agar phase; the sclerotia species define grain but not substrate), so a
# missing one means "no closet setpoints", never "unreachable".
_COLONIZATION_PHASES = COLONIZATION_PHASES
# Phases a session may enter whatever its species profile defines.
_ALWAYS_ENTERABLE_PHASES = _SPECIES_AGNOSTIC_PHASES | _COLONIZATION_PHASES
# Every phase, in lifecycle order (GrowPhase's).
_GROW_PHASES = tuple(p.value for p in GrowPhase)


class InvalidPhaseError(ValueError):
    """A phase a session cannot be advanced to (unknown, or no setpoints)."""


class UnknownChamberError(ValueError):
    """A session bound to a chamber id the Pi has no row for."""


class SessionConflictError(ValueError):
    """A change the session's state no longer allows (409): a grow that has
    ended (ending it again as something else rewrote its outcome and end
    time; advancing it reopened a phase), or one whose phase changed while
    the change was being made."""


def phase_params_source(defined: Collection[str], phase: str) -> str | None:
    """The profile phase whose setpoints `phase` runs on: the phase itself when
    the profile defines it, else its PHASE_PARAM_FALLBACKS stand-in, else None."""
    if phase in defined:
        return phase
    return next((alt for alt in PHASE_PARAM_FALLBACKS.get(phase, ()) if alt in defined), None)


# Rest runs on its stand-in's envelope with the lights off: the block rests
# (or soaks) in the dark.
_REST_LIGHTS_OFF = {"light_hours_on": 0, "light_hours_off": 24, "light_spectrum": "none"}

# Phases whose params a session's growth_form re-selects (reishi: the profile's
# primordia phase is the elevated-CO2 ANTLER form, its fruiting phase the
# low-CO2 CONK form). See _apply_growth_form.
_FORM_PHASES = ("primordia_induction", "fruiting")


def _apply_growth_form(params: PhaseParams, phase: str, form: str | None,
                       by_phase: dict[str, PhaseParams]) -> PhaseParams:
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


def phase_params_for(profile: SpeciesProfile | None, phase: str,
                     growth_form: str | None = None) -> PhaseParams | None:
    """The species setpoints a session in `phase` runs on, or None.

    The ones the automation engine drives: the phase's own params when the
    profile defines it, else its PHASE_PARAM_FALLBACKS stand-in's (rest with
    the lights off), then the session's growth_form applied (reishi antler /
    conk). Forecast alerts, the weather impact, planner warnings and phase
    snapshots read the setpoints in force here, so none of them goes silent in
    a phase the engine runs on a stand-in (rest, and pinning on a profile that
    folds it into fruiting).

    None with no profile, for a phase nothing stands in for, and for cold
    storage and complete: those run on no species setpoints (the engine holds
    a fridge at its own fixed band), so no closet forecast or planner check is
    measured against them.
    """
    if profile is None or phase in _SPECIES_AGNOSTIC_PHASES:
        return None
    by_phase = {p.value: params for p, params in profile.phases.items()}
    source = phase_params_source(by_phase, phase)
    if source is None:
        return None
    params = by_phase[source]
    if phase == "rest" and source != "rest":
        params = params.model_copy(update=_REST_LIGHTS_OFF)
    return _apply_growth_form(params, phase, growth_form, by_phase)


def phase_error(phase: str, profile: SpeciesProfile | None) -> str | None:
    """Why a session on `profile` cannot enter `phase`, or None if it can.

    A typo ('fruitng') or a phase the profile neither defines nor falls back
    for used to be stored as-is — and from then on every profile-driven rule
    and every stage safety alert was silent, because no setpoints resolve for
    it. Only the closet-driven stages (browning, primordia induction, fruiting,
    rest) need setpoints: the colonization stages, cold storage and complete are
    always enterable (_ALWAYS_ENTERABLE_PHASES). With no profile (unknown /
    deleted species) only the name is checked.
    """
    if phase not in _GROW_PHASES:
        return f"Unknown phase {phase!r} — expected one of: {', '.join(_GROW_PHASES)}"
    if profile is None or phase in _ALWAYS_ENTERABLE_PHASES:
        return None
    defined = {p.value for p in profile.phases}
    if phase_params_source(defined, phase) is not None:
        return None
    listed = ", ".join(p for p in _GROW_PHASES if p in defined) or "none"
    return (f"Species profile {profile.id!r} defines no {phase!r} phase (it defines: "
            f"{listed}), so automation would run it with no setpoints or safety alerts")


def _params_snapshot(profile: SpeciesProfile | None, phase: str,
                     growth_form: str | None = None) -> str | None:
    """JSON of the species setpoints in force for ``phase`` (phase_history.params_snapshot).

    Frozen at phase entry so a later edit to a custom profile can't rewrite what
    transcripts/analysis believe the targets were. The setpoints in force are
    phase_params_for's: a rest phase the profile does not define records the
    fruiting envelope with the lights off that the engine runs. None when the
    profile is unknown or no species setpoints apply (e.g. cold_storage).
    """
    params = phase_params_for(profile, phase, growth_form)
    return params.model_dump_json() if params is not None else None


def _moves_forward(from_phase: str, to_phase: str) -> bool:
    """A step on into the grow: later in the lifecycle, and not parked or ended.

    Only such a step owes the phase-exit reminder (SpeciesProfile.
    phase_exit_reminder) — a correction back a stage, a jar parked in cold
    storage or a session completed does not need a soak.
    """
    if to_phase in _SPECIES_AGNOSTIC_PHASES:
        return False
    try:
        return _GROW_PHASES.index(to_phase) > _GROW_PHASES.index(from_phase)
    except ValueError:
        return False


def _decode_phase_row(row) -> dict:
    """A phase_history row with its params_snapshot JSON decoded to a dict."""
    ph = dict(row)
    raw = ph.get("params_snapshot")
    if isinstance(raw, str):
        try:
            ph["params_snapshot"] = json.loads(raw)
        except json.JSONDecodeError:
            ph["params_snapshot"] = None
    return ph


# Called with a session id after every change to it (create, edit, phase,
# harvest, end). The cloud connector registers one to send the session to the
# cloud (app.cloud.session_sync); this module never imports the cloud package.
SessionChangeListener = Callable[[int], Awaitable[None]]
_session_change_listeners: list[SessionChangeListener] = []


def add_session_change_listener(listener: SessionChangeListener) -> None:
    """Register `listener` for session changes (idempotent)."""
    if listener not in _session_change_listeners:
        _session_change_listeners.append(listener)


async def _notify_session_changed(session_id: int) -> None:
    for listener in list(_session_change_listeners):
        try:
            await listener(session_id)
        except Exception as e:  # a sync failure must never fail the change itself
            log.warning("session-change listener failed for session %s: %s", session_id, e)


async def create_session(data: SessionCreate) -> dict:
    """Start a grow. Raises InvalidPhaseError for a phase it cannot start in,
    UnknownChamberError for a chamber the Pi has no row for, and
    ChamberBusyError for a chamber that already runs an active grow."""
    now = time.time()
    # Stored in the hyphenated UI spelling the cloud and the dashboards send
    # and match on, whenever that spelling finds the same profile again
    # (species.service.stored_species_id): a custom id that mixes separators
    # used to be stored in a spelling that found no profile, and its grow ran
    # with no setpoints and no stage alerts.
    species_id = await stored_species_id(data.species_profile_id)
    profile = await get_profile(species_id)
    # Same gate as advance_phase: a session created at a typo'd phase used to
    # run with no setpoints and no stage alerts (the REST route answers 422;
    # a cloud session_start reports the reason as success=false).
    if error := phase_error(data.current_phase, profile):
        raise InvalidPhaseError(error)
    if data.current_phase == "complete":
        # It would be an active grow the engine manages with no setpoints.
        raise InvalidPhaseError("A session cannot start complete")
    snapshot = _params_snapshot(profile, data.current_phase, data.growth_form)
    async with get_db() as db:
        # sessions.chamber_id references chambers(id): an unknown id used to
        # surface as a FOREIGN KEY IntegrityError and a bare 500.
        if data.chamber_id is not None:
            cursor = await db.execute("SELECT 1 FROM chambers WHERE id = ?", (data.chamber_id,))
            if await cursor.fetchone() is None:
                raise UnknownChamberError(f"chamber {data.chamber_id} not found")
            # A chamber runs one grow's setpoints. A second grow bound to it
            # took the chamber over (the newest wins: a grain jar's sealed
            # colonization ran a fruiting tub's chamber with no fresh air or
            # humidity control), and ending it left the chamber looking idle
            # while the first grow still ran.
            if occupant := await chamber_occupant(db, data.chamber_id):
                raise ChamberBusyError(_busy_message(data.chamber_id, occupant))
        cursor = await db.execute(
            """INSERT INTO sessions (name, species_profile_id, substrate, substrate_volume,
               substrate_prep_notes, inoculation_date, inoculation_method, spawn_source,
               current_phase, container_type, tub_number, shelf_number, shelf_side, growth_form, pinning_tek,
               chamber_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.name, species_id, data.substrate, data.substrate_volume,
             data.substrate_prep_notes, data.inoculation_date, data.inoculation_method,
             data.spawn_source, data.current_phase, data.container_type, data.tub_number, data.shelf_number,
             data.shelf_side, data.growth_form, data.pinning_tek, data.chamber_id),
        )
        session_id = cursor.lastrowid

        if data.chamber_id:
            await db.execute(
                "UPDATE chambers SET active_session_id = ? WHERE id = ?",
                (session_id, data.chamber_id),
            )

        await db.execute(
            "INSERT INTO phase_history (session_id, phase, entered_at, trigger, params_snapshot) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, data.current_phase, now, "session_created", snapshot),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, "session_created", "user", f"Session '{data.name}' created"),
        )
        await db.commit()
    await _notify_session_changed(session_id)
    return await get_session(session_id)


# A session's species, in any separator spelling: sessions store the
# hyphenated form ("lions-mane") since 5.0 and the id as given before, while
# the species list hands out the underscored built-in ids ("lions_mane").
_SAME_SPECIES = "replace(species_profile_id, '_', '-') = ?"


async def list_sessions(status: str | None = None, species: str | None = None,
                        include_phase_history: bool = False,
                        yield_since: float | None = None) -> list[dict]:
    """Sessions, newest first. With `yield_since` (Unix seconds) each row also
    carries `wet_yield_since_g`: the wet grams of its harvests logged at or
    after that time (0 when none), so a "yield in the last N days" figure
    counts what was picked in the window, whenever the grow started."""
    query = "SELECT * FROM sessions WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if species:
        query += " AND " + _SAME_SPECIES
        params.append(canonical_species_id(species))
    query += " ORDER BY created_at DESC"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        sessions = [_session_row(r) for r in await cursor.fetchall()]

        if include_phase_history and sessions:
            # One grouped query (not a per-session loop), same row shape and
            # ordering as get_session's phase_history.
            placeholders = ",".join("?" * len(sessions))
            cursor = await db.execute(
                f"SELECT * FROM phase_history WHERE session_id IN ({placeholders}) "
                "ORDER BY entered_at",
                [s["id"] for s in sessions],
            )
            history_by_session = defaultdict(list)
            for r in await cursor.fetchall():
                row = _decode_phase_row(r)
                history_by_session[row["session_id"]].append(row)
            for s in sessions:
                s["phase_history"] = history_by_session[s["id"]]

        if yield_since is not None and sessions:
            cursor = await db.execute(
                "SELECT session_id, SUM(wet_weight_g) AS wet FROM harvests "
                "WHERE timestamp >= ? GROUP BY session_id",
                (yield_since,),
            )
            wet_by_session = {r["session_id"]: r["wet"] or 0.0 for r in await cursor.fetchall()}
            for s in sessions:
                # rounded: a float sum of 0.1 g entries reads 300.29999999999995
                s["wet_yield_since_g"] = round(wet_by_session.get(s["id"], 0.0), 1)

        return sessions


def _session_row(row) -> dict:
    """A sessions row as the API returns it.

    biological_efficiency is derived from the substrate volume and the logged
    wet yield, the figure GET /api/sessions/{id}/stats reports. The column is
    never written, so every row used to carry null.
    """
    session = dict(row)
    session["biological_efficiency"] = _biological_efficiency(
        session.get("substrate_volume"), session.get("total_wet_yield_g") or 0.0)
    return session


async def get_session(session_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        session = _session_row(row)

        cursor = await db.execute(
            "SELECT * FROM phase_history WHERE session_id = ? ORDER BY entered_at", (session_id,)
        )
        session["phase_history"] = [_decode_phase_row(r) for r in await cursor.fetchall()]
        return session


# The columns PATCH /api/sessions/{id} writes. All but the name may be
# cleared with an explicit null.
_UPDATE_SESSION_COLUMNS = (
    "name",
    "substrate",
    "substrate_volume",
    "substrate_prep_notes",
    "inoculation_date",
    "inoculation_method",
    "spawn_source",
    "tub_number",
    "shelf_number",
    "shelf_side",
    "growth_form",
    "pinning_tek",
)
_NOT_NULL_COLUMNS = frozenset({"name"})


async def update_session(session_id: int, data: SessionUpdate) -> dict | None:
    """Partial update; None for an unknown session.

    A field left out keeps its value; an explicit null clears it (a null name
    is ignored: a session always has one). With COALESCE(?, col) a null could
    never clear anything, so a growth_form once set kept its form-specific
    setpoints for good. One atomic UPDATE.
    """
    raw = data.model_dump()
    changes = {c: raw[c] for c in _UPDATE_SESSION_COLUMNS
               if c in data.model_fields_set
               and (raw[c] is not None or c not in _NOT_NULL_COLUMNS)}
    if not changes:
        return await get_session(session_id)
    # The column names come from _UPDATE_SESSION_COLUMNS, never from the request.
    assignments = ", ".join(f"{column} = ?" for column in changes)
    async with get_db() as db:
        await db.execute(f"UPDATE sessions SET {assignments} WHERE id = ?",
                         (*changes.values(), session_id))
        await db.commit()
    await _notify_session_changed(session_id)
    return await get_session(session_id)


# (_COLONIZATION_PHASES is defined with the phase-validation tables above.)
# Bulk-substrate containers that fruit in place (a bag is cut open; a tub/tray
# is opened to air). Everything else — colonized agar / liquid culture / grain
# spawn — is pulled and parked in cold storage until used. One definition
# with the engine's sealed-vessel gate (sessions.models).
_FRUITING_CONTAINERS = FRUITING_CONTAINERS


def suggested_next_phase(current_phase: str, container_type: str | None,
                         more_flushes_expected: bool = True, *,
                         profile_phases: Collection[str] | None = None) -> str:
    """The product spec's forks, as a suggestion the UI offers on 'advance phase'.

    Two forks:
    1. After colonization: BULK SUBSTRATE (grow bag / monotub / tray) goes on to
       fruit; colonized agar / LC / grain is pulled and parked in the fridge.
           bulk substrate → primordia_induction
                            (→ browning first when the profile defines it:
                             a shiitake block browns before it can fruit, and
                             browning → primordia_induction after the soak)
           agar/LC/grain  → cold_storage
    2. The flush loop: a bag gives 2-3 flushes. After a flush you REST, then go
       back to FRUITING for the next one — until the bag is spent, then COMPLETE.
           rest → fruiting   (if more flushes expected)
           rest → complete   (bag is spent)
    Everything else follows the ordinary linear order.

    ``profile_phases`` (the phases the session's species profile defines)
    skips forward past phases the profile doesn't define: pink oyster folds
    pinning into fruiting, so its bag goes straight to fruiting. REST stays in
    the flush loop whenever fruiting setpoints exist to run it on, and
    cold_storage / complete need no setpoints. Browning is only ever suggested
    to a profile that defines it.
    """
    ct = (container_type or "").lower()
    if current_phase in _COLONIZATION_PHASES:
        if ct not in _FRUITING_CONTAINERS:
            candidate = "cold_storage"
        elif profile_phases is not None and "browning" in profile_phases:
            candidate = "browning"
        else:
            candidate = "primordia_induction"
    elif current_phase == "browning":
        # Not the linear successor (cold_storage is the jar fork): a browned
        # block is soaked and goes on to pin.
        candidate = "primordia_induction"
    elif current_phase == "rest":
        candidate = "fruiting" if more_flushes_expected else "complete"
    else:
        # Non-fork transitions follow the ordinary linear progression.
        try:
            i = _GROW_PHASES.index(current_phase)
            candidate = _GROW_PHASES[i + 1] if i + 1 < len(_GROW_PHASES) else "complete"
        except ValueError:
            candidate = "complete"
    if profile_phases is None:
        return candidate

    defined = set(profile_phases)

    def _suggestable(phase: str) -> bool:
        if phase in _SPECIES_AGNOSTIC_PHASES or phase in defined:
            return True
        return phase == "rest" and phase_params_source(defined, phase) is not None

    for phase in _GROW_PHASES[_GROW_PHASES.index(candidate):]:
        if phase != current_phase and _suggestable(phase):
            return phase
    return "complete"


async def release_cold_storage_links() -> int:
    """Drop chamber links that still hold a grow in cold storage in the
    chamber it grew in; returns how many. Run at start-up.

    advance_phase drops them when a grow enters cold storage; a grow that
    entered it before that kept the link its creation set, and with it the
    chamber it left. A link from a chamber the session is not bound to (a
    fridge it was moved to), or to a session that never grew anywhere (it
    began in cold storage), is kept.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE chambers SET active_session_id = NULL WHERE active_session_id IN ("
            "SELECT s.id FROM sessions s WHERE s.status = 'active' "
            "AND s.current_phase = 'cold_storage' AND s.chamber_id = chambers.id "
            "AND EXISTS (SELECT 1 FROM phase_history p "
            "WHERE p.session_id = s.id AND p.phase != 'cold_storage'))"
        )
        released = cursor.rowcount
        await db.commit()
    if released:
        log.info("Released %d chamber link(s) to grows in cold storage", released)
    return released


async def advance_phase(session_id: int, data: PhaseAdvance) -> dict | None:
    """Move the session to data.phase. None for an unknown session; raises
    InvalidPhaseError for a phase the session cannot run (see phase_error),
    and SessionConflictError for a grow that has ended or that changed phase
    while this ran (two advances at once both "left" the same phase).

    Advancing to complete completes the grow (complete_session: ended, its
    actuators switched off): it used to set only the phase, leaving an
    active grow the engine kept managing with no setpoints.

    Stepping on out of a phase that owes a manual step (PhaseParams.
    exit_reminder — shiitake browning's cold-water soak) logs that step as a
    ``phase_exit_reminder`` session event alongside the phase change, so the
    timeline and transcript record when the soak was due. One transaction."""
    if data.phase == "complete":
        return await complete_session(session_id)
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT species_profile_id, current_phase, growth_form, status FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if row["status"] != "active":
            raise SessionConflictError(
                f"Session {session_id} is {row['status']}: only an active grow changes phase")
        profile = await get_profile(row["species_profile_id"])
        if error := phase_error(data.phase, profile):
            raise InvalidPhaseError(error)
        snapshot = _params_snapshot(profile, data.phase, row["growth_form"])
        leaving = row["current_phase"]
        reminder = (profile.phase_exit_reminder(leaving)
                    if profile is not None and _moves_forward(leaving, data.phase) else None)

        # Only while it is still the active grow in the phase read above.
        cursor = await db.execute(
            "UPDATE sessions SET current_phase = ? "
            "WHERE id = ? AND status = 'active' AND current_phase = ?",
            (data.phase, session_id, leaving),
        )
        if cursor.rowcount == 0:
            await db.rollback()
            raise SessionConflictError(
                f"Session {session_id} changed while it was being advanced: reload it and try again")
        # Close current phase
        await db.execute(
            "UPDATE phase_history SET exited_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (now, session_id),
        )
        # Open new phase, freezing the setpoints it starts under.
        await db.execute(
            "INSERT INTO phase_history (session_id, phase, entered_at, trigger, params_snapshot) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, data.phase, now, data.trigger, snapshot),
        )
        if data.phase == "cold_storage" and leaving != "cold_storage":
            # The jar leaves the chamber it grew in for the fridge: the chamber
            # stops running it (see _CHAMBER_SESSION_SQL). Linking it to a
            # chamber again places it there (a fridge with its own node).
            await db.execute(_RELINK_CHAMBERS_SQL, {"sid": session_id})
        # The exit reminder goes in BEFORE the phase change: both carry the
        # same second, so the event id is the only order, and the step owed
        # on the way out (shiitake browning's cold soak) must read before
        # "Phase advanced to primordia induction" in the timeline and in
        # the transcript fed to Claude analysis.
        if reminder:
            await db.execute(
                "INSERT INTO session_events (session_id, type, source, description, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, "phase_exit_reminder", "system",
                 f"Leaving {leaving.replace('_', ' ')} — {reminder}",
                 json.dumps({"phase": leaving, "next_phase": data.phase, "reminder": reminder})),
            )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description, data) VALUES (?, ?, ?, ?, ?)",
            # Readable text ("primordia induction") like the reminder above;
            # the raw value stays in data.phase for code that needs it.
            (session_id, "phase_change", data.trigger,
             f"Phase advanced to {data.phase.replace('_', ' ')}",
             json.dumps({"phase": data.phase})),
        )
        await db.commit()
    await _notify_session_changed(session_id)
    return await get_session(session_id)


async def add_note(session_id: int, data: NoteCreate) -> dict | None:
    """None for an unknown session (the route's 404; the insert failed on the
    foreign key with a 500)."""
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        if await cursor.fetchone() is None:
            return None
        cursor = await db.execute(
            "INSERT INTO session_notes (session_id, text, tags, image_id) VALUES (?, ?, ?, ?)",
            (session_id, data.text, json.dumps(data.tags) if data.tags else None, data.image_id),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, "note_added", "user", data.text[:100]),
        )
        await db.commit()
        note_id = cursor.lastrowid
        cursor = await db.execute("SELECT * FROM session_notes WHERE id = ?", (note_id,))
        return dict(await cursor.fetchone())


async def _harvest_handling(species_id: str | None) -> tuple[str, str] | None:
    """(species name, notice) when a harvest of this species must be handled
    at once — the profile's harvest_notice (pink oyster cannot be
    refrigerated, shaggy mane turns to ink, paddy straw keeps a day), else
    the notice of the built-in profile of the same species, for a custom
    profile cloned before profiles carried one. CLAUDE.md §4b makes the pink
    oyster notice mandatory. None when nothing is owed."""
    profile = await get_profile(species_id) if species_id else None
    if profile is None:
        return None
    if profile.harvest_notice:
        return profile.common_name, profile.harvest_notice
    binomial = profile.scientific_name.strip().lower()
    builtin = next((p for p in BUILTIN_PROFILES if p.harvest_notice
                    and binomial.startswith(p.scientific_name.lower())), None)
    return (profile.common_name, builtin.harvest_notice) if builtin else None


async def add_harvest(session_id: int, data: HarvestCreate) -> dict | None:
    """None for an unknown session (the route's 404; the insert failed on the
    foreign key with a 500)."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT species_profile_id FROM sessions WHERE id = ?", (session_id,)
        )
        srow = await cursor.fetchone()
        if srow is None:
            return None
        cursor = await db.execute(
            """INSERT INTO harvests (session_id, flush_number, wet_weight_g, dry_weight_g,
               quality_rating, notes, image_ids) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, data.flush_number, data.wet_weight_g, data.dry_weight_g,
             data.quality_rating, data.notes,
             json.dumps(data.image_ids) if data.image_ids else None),
        )
        # Update session totals
        if data.wet_weight_g:
            await db.execute(
                "UPDATE sessions SET total_wet_yield_g = total_wet_yield_g + ? WHERE id = ?",
                (data.wet_weight_g, session_id),
            )
        if data.dry_weight_g:
            await db.execute(
                "UPDATE sessions SET total_dry_yield_g = total_dry_yield_g + ? WHERE id = ?",
                (data.dry_weight_g, session_id),
            )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description, data) VALUES (?, ?, ?, ?, ?)",
            (session_id, "harvest", "user", f"Flush #{data.flush_number} harvested",
             json.dumps({"flush": data.flush_number, "wet_g": data.wet_weight_g, "dry_g": data.dry_weight_g})),
        )
        await db.commit()
        harvest_id = cursor.lastrowid
        cursor = await db.execute("SELECT * FROM harvests WHERE id = ?", (harvest_id,))
        harvest = dict(await cursor.fetchone())

    await _notify_session_changed(session_id)
    if handling := await _harvest_handling(srow["species_profile_id"]):
        await harvest_notice(*handling, dedup_key=f"harvest-notice:{harvest_id}")
    return harvest


async def flush_status(session_id: int) -> dict:
    """How many flushes has this session yielded, and are more expected?

    A grow bag typically gives 2-3 flushes: fruit → harvest → rest → re-fruit,
    until it's spent. `expected` comes from the species' flush_count_typical.
    The UI uses `more_expected` to decide whether REST loops back to FRUITING
    (another flush) or advances to COMPLETE (bag is done).
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT flush_number) AS n, MAX(flush_number) AS latest "
            "FROM harvests WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        harvested = row["n"] or 0
        latest = row["latest"] or 0
        cursor = await db.execute(
            "SELECT species_profile_id FROM sessions WHERE id = ?", (session_id,)
        )
        srow = await cursor.fetchone()

    expected = None
    if srow:
        profile = await get_profile(srow["species_profile_id"])
        if profile is not None:
            expected = getattr(profile, "flush_count_typical", None)

    more_expected = expected is None or harvested < expected
    return {
        "flushes_harvested": harvested,
        "latest_flush": latest,
        "expected_flushes": expected,
        "more_expected": more_expected,
    }


async def get_active_session() -> dict | None:
    """Return the most recent active session, or None."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


# The grow a chamber runs, most specific link first (see
# get_active_session_for_chambers). :ids is a JSON array of chamber ids.
#
# A session in cold storage has left the chamber it grew in (advance_phase
# drops the chamber links to it): it is in the fridge, not in that chamber's
# air. It runs a chamber again only when a chamber links it (PATCH
# /api/chambers active_session_id: a fridge with its own node), and no
# fallback picks it — otherwise the closet ran the jar's 35-40 °F setpoints
# (cooler on, a temperature emergency page every 15 min) and a grow sharing
# the closet's nodes went unmanaged.
_CHAMBER_IDS = "(SELECT value FROM json_each(:ids))"
_CHAMBER_LINKED = "(SELECT active_session_id FROM chambers WHERE id IN " + _CHAMBER_IDS + ")"
# With :before_ts set, only sessions started by then (see
# get_active_session_for_chambers).
_STARTED = "(:before_ts IS NULL OR COALESCE(created_at, 0) <= :before_ts)"
_NEWEST = " ORDER BY created_at DESC, id DESC LIMIT 1"
# 1. bound to it by sessions.chamber_id (in cold storage: only while linked);
_BOUND_HERE = ("chamber_id IN " + _CHAMBER_IDS +
               " AND (current_phase != 'cold_storage' OR id IN " + _CHAMBER_LINKED + ")")
# 2. linked by chambers.active_session_id (and bound to no chamber — or in
#    cold storage: a jar linked to a fridge stays bound where it grew);
_LINKED_HERE = ("(chamber_id IS NULL OR current_phase = 'cold_storage') "
                "AND id IN " + _CHAMBER_LINKED)
_CHAMBER_SESSION_SQL = (
    "SELECT * FROM sessions WHERE status = 'active' AND " + _STARTED +
    " AND " + _BOUND_HERE + _NEWEST,
    "SELECT * FROM sessions WHERE status = 'active' AND " + _STARTED +
    " AND " + _LINKED_HERE + _NEWEST,
    # 3. the newest session bound to no chamber and linked from no OTHER one.
    "SELECT * FROM sessions WHERE status = 'active' AND " + _STARTED +
    " AND chamber_id IS NULL "
    "AND current_phase != 'cold_storage' "
    "AND id NOT IN (SELECT active_session_id FROM chambers "
    "WHERE active_session_id IS NOT NULL AND id NOT IN " + _CHAMBER_IDS + ")" + _NEWEST,
)

# The grow a chamber runs by its own binding or link (the first two queries
# above, not the chamberless fallback), other than session :besides: a
# chamber runs one grow's setpoints, so no second grow is bound to it.
_CHAMBER_OCCUPANT_SQL = (
    "SELECT id, name FROM sessions WHERE status = 'active' AND id IS NOT :besides "
    "AND ((" + _BOUND_HERE + ") OR (" + _LINKED_HERE + "))" + _NEWEST
)

# Points the chamber links (chambers.active_session_id) to session :sid — a
# grow that ended or went to cold storage — at the grow the chamber still
# runs bound to it, if any (the newest active one not in cold storage), else
# at nothing: the dashboards show a chamber's grow by its link, so clearing
# it showed a chamber idle while its other grow still ran there.
_RELINK_CHAMBERS_SQL = (
    "UPDATE chambers SET active_session_id = ("
    "SELECT s.id FROM sessions s WHERE s.chamber_id = chambers.id AND s.status = 'active' "
    "AND s.id != :sid AND s.current_phase != 'cold_storage' "
    "ORDER BY s.created_at DESC, s.id DESC LIMIT 1) "
    "WHERE active_session_id = :sid"
)


async def chamber_occupant(db, chamber_id: int, besides: int | None = None) -> dict | None:
    """{id, name} of the active grow chamber `chamber_id` runs bound to it or
    linked from it, other than session `besides`; None when it runs none. On
    the caller's connection, inside its transaction (create_session and the
    chamber PATCH refuse to bind a second grow to a busy chamber)."""
    cursor = await db.execute(_CHAMBER_OCCUPANT_SQL, {
        "ids": json.dumps([int(chamber_id)]), "besides": besides})
    row = await cursor.fetchone()
    return dict(row) if row else None


def _busy_message(chamber_id: int, occupant: dict) -> str:
    return (f"Chamber {chamber_id} already runs grow session {occupant['id']} "
            f"('{occupant['name']}'): complete or abort it (or advance it to cold "
            "storage) before starting another grow there")


# The grow a node listed in NO chamber belongs to (see
# get_active_session_for_chambers([])): the newest session bound to no
# existing chamber — the single-closet grow. Never a session in cold storage
# (see _CHAMBER_SESSION_SQL), and never a chamber's grow: an unlisted node
# used to take the only chamber's grow when no chamberless grow ran, so the
# closet's nodes ran another chamber's setpoints the moment the closet's own
# grow ended.
_UNCHAMBERED_SESSION_SQL = (
    "SELECT * FROM sessions WHERE status = 'active' AND " + _STARTED +
    " AND current_phase != 'cold_storage' "
    "AND (chamber_id IS NULL OR chamber_id NOT IN (SELECT id FROM chambers))" + _NEWEST,
)


async def get_active_session_for_chambers(
    chamber_ids: Sequence[int], *, before_ts: float | None = None,
) -> dict | None:
    """The active session the given chamber(s) run, or None.

    In order: an active session bound to one of them by sessions.chamber_id;
    else the one a chamber's active_session_id links (PATCH /api/chambers
    used to set only that link); else the newest active session bound to NO
    chamber and linked from no other chamber — a pre-migration session, or one
    an API / cloud session_start created without a chamber_id. Never another
    chamber's grow: two chambers run side by side.

    With no chamber ids (a node listed in no chamber): the newest session
    bound to no chamber (the single closet), else None — never a chamber's
    grow: list a node in its chamber for that chamber's grow to run it.

    This is THE per-node session rule (CLAUDE.md §12): the rules engine drives
    a node's grow by it, and the MQTT ingest tags the node's readings with it
    (telemetry.service.active_session_for_node), so a grow's history holds the
    readings it was run on. ``before_ts`` counts only sessions started by then:
    a reading replayed from a node's buffer belongs to no grow started after
    it was taken.
    """
    ids = [int(i) for i in chamber_ids]
    if ids:
        queries, params = _CHAMBER_SESSION_SQL, {"ids": json.dumps(ids)}
    else:
        queries, params = _UNCHAMBERED_SESSION_SQL, {}
    params["before_ts"] = before_ts
    async with get_db() as db:
        for sql in queries:
            cursor = await db.execute(sql, params)
            row = await cursor.fetchone()
            if row:
                return dict(row)
    return None


async def get_active_session_for_node(
    node_id: str, *, before_ts: float | None = None,
) -> dict | None:
    """The active session a node's readings (or camera frames) belong to: its
    chamber's grow when the node is listed in a chamber, else the unambiguous
    chamberless grow (see get_active_session_for_chambers, which also says
    what ``before_ts`` does)."""
    chambers = await chambers_for_node(node_id)
    return await get_active_session_for_chambers(
        [c["id"] for c in chambers], before_ts=before_ts)


async def chamber_nodes_running(session_id: int) -> list[str]:
    """Node ids of every chamber whose grow (get_active_session_for_chambers)
    is this session — a chamberless session included, which the rule hands
    to a chamber with no grow of its own. Empty for a session no longer
    active."""
    async with get_db() as db:
        cursor = await db.execute("SELECT id, node_ids FROM chambers")
        chambers = [dict(r) for r in await cursor.fetchall()]
    nodes: list[str] = []
    for chamber in chambers:
        session = await get_active_session_for_chambers([chamber["id"]])
        if not session or session["id"] != session_id:
            continue
        try:
            listed = json.loads(chamber["node_ids"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(listed, list):
            nodes.extend(str(n) for n in listed if str(n) not in nodes)
    return nodes


async def get_events(session_id: int, limit: int | None = None) -> list[dict]:
    """Session events in chronological order.

    `limit` keeps the NEWEST N while preserving the ascending contract
    (transcripts/reports read the full history; feeds pass a cap).
    """
    async with get_db() as db:
        if limit is None:
            cursor = await db.execute(
                # id breaks ties: events written in the same second (a
                # phase change and its exit reminder) keep their insert order.
                "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp, id",
                (session_id,),
            )
            return [dict(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT * FROM ("
            "SELECT * FROM session_events WHERE session_id = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT ?"
            ") ORDER BY timestamp, id",
            (session_id, max(1, min(limit, 1000))),
        )
        return [dict(r) for r in await cursor.fetchall()]



def _is_held(held: set[tuple[str, str | None]], names: Collection[str], action: dict) -> bool:
    """Whether a hold in `held` keeps automation off the actuator a rule's
    `action` drives, known by `names` (its placeholder and the node it
    resolved to; a plug's id and role names), by the rule the engine reads
    holds by (automation.service.hold_applies): a hold on the action's
    channel or on the whole target, and for a scene a hold on any channel
    of its node."""
    return any(
        hold_applies(target, channel, names, channel=action.get("channel"),
                     scene=action.get("scene"), vendor_slug=action.get("vendor_slug"))
        for target, channel in held
    )


# Awaited as listener(target, channel, sent_at=...) after session-end safing
# actually published an OFF to that actuator. The automation engine registers
# note_actuator_off here, so a safety ceiling timing an ON that this OFF ended
# is cleared (otherwise the next ON keeps the stale deadline and trips early).
# The engine imports this module at its top, so this module cannot import it.
ActuatorOffListener = Callable[..., Awaitable[None]]
_actuator_off_listeners: list[ActuatorOffListener] = []


def add_actuator_off_listener(listener: ActuatorOffListener) -> None:
    """Register `listener` for OFFs session-end safing publishes (idempotent)."""
    if listener not in _actuator_off_listeners:
        _actuator_off_listeners.append(listener)


async def _notify_actuator_off(target: str, channel: str | None, sent_at: float) -> None:
    for listener in list(_actuator_off_listeners):
        try:
            await listener(target, channel, sent_at=sent_at)
        except Exception as e:  # bookkeeping must never strand the other OFFs
            log.warning("actuator-off listener failed for %s:%s: %s", target, channel, e)


async def _automation_rules_and_holds() -> tuple[list[dict], set[tuple[str, str | None]]]:
    """Every automation rule, and the (target, channel) pairs under an
    operator's manual hold now."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data "
            "FROM automation_rules ORDER BY priority DESC, id"
        )
        rules = [deserialize_rule_row(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT target, channel FROM manual_overrides "
            "WHERE locked = 1 AND (expires_at IS NULL OR expires_at >= ?)",
            (time.time(),),
        )
        held = {(r["target"], r["channel"]) for r in await cursor.fetchall()}
    return rules, held


async def _actuator_nodes(target: str) -> list[str]:
    """The nodes a rule's native-node target can land on: every node a seeded
    placeholder stands for (placeholder_nodes; the placeholder's own name
    when none is paired), else the target itself."""
    nodes = await placeholder_nodes(target)
    if nodes is None:
        return [target]
    return nodes or [target]


async def _rule_targets(rules: list[dict]) -> tuple[set[str], list[str]]:
    """(every node a rule can switch something ON on, every plug target a
    rule switches ON)."""
    nodes: set[str] = set()
    plug_targets: list[str] = []
    for rule in rules:
        action = rule.get("action") or {}
        target = action.get("target")
        if not target or action.get("vendor_slug") or action.get("state") != "on":
            continue
        if await is_plug_target(target):
            if target not in plug_targets:
                plug_targets.append(target)
            continue
        nodes.update(await _actuator_nodes(target))
    return nodes, plug_targets


async def _node_grows(nodes: set[str]) -> dict[str, int | None]:
    """The id of the grow each node runs now (get_active_session_for_node),
    or None."""
    grows: dict[str, int | None] = {}
    by_chambers: dict[tuple[int, ...], int | None] = {}
    for node in nodes:
        chambers = tuple(sorted(c["id"] for c in await chambers_for_node(node)))
        if chambers not in by_chambers:
            grow = await get_active_session_for_chambers(list(chambers))
            by_chambers[chambers] = grow["id"] if grow else None
        grows[node] = by_chambers[chambers]
    return grows


async def _plug_grows(plug_targets: list[str]) -> dict[str, set[int]]:
    """The grows whose rules reach each paired plug through `plug_targets`,
    by plug id.

    The engine runs a grow's rules for the nodes of each set of chambers
    (chambers.service.chamber_contexts) and for the nodes in no chamber,
    each with the grow they run, and each reaches one plug of a target the
    way smart_plugs.chamber_plug resolves it: a chamber its own, else one no
    chamber lists; the nodes in no chamber one no chamber lists, else one of
    a chamber that runs their grow. So several grows can reach one plug: a
    plug no chamber lists serves every chamber without its own plug of the
    role."""
    if not plug_targets:
        return {}
    contexts: list[tuple[list[str] | None, int]] = []
    listed: set[str] = set()
    for chamber_ids, nodes in await chamber_contexts():
        listed.update(nodes)
        grow = await get_active_session_for_chambers(chamber_ids)
        if grow:
            contexts.append((nodes, grow["id"]))
    async with get_db() as db:
        cursor = await db.execute("SELECT node_id FROM hardware_nodes")
        unlisted = any(row["node_id"] not in listed for row in await cursor.fetchall())
    grow = await get_active_session_for_chambers([]) if unlisted else None
    if grow:
        contexts.append((None, grow["id"]))
    grows: dict[str, set[int]] = {}
    for nodes, grow_id in contexts:
        for target in plug_targets:
            plug = await chamber_plug(target, nodes, grow_id=grow_id)
            if plug is not None:
                grows.setdefault(plug["plug_id"], set()).add(grow_id)
    return grows


async def _actuator_grows(rules: list[dict]) -> dict[str, set[int]]:
    """The grows that drive each node and plug the rules can switch ON, by
    id: a node the grow it runs (_node_grows), a plug every grow whose rules
    reach it (_plug_grows)."""
    nodes, plug_targets = await _rule_targets(rules)
    grows = {node: {grow} if grow is not None else set()
             for node, grow in (await _node_grows(nodes)).items()}
    grows.update(await _plug_grows(plug_targets))
    return grows


async def _nodes_run_by(session_id: int) -> set[str]:
    """The nodes and plugs the rules can switch on that grow `session_id`
    drives (_actuator_grows) — read while it is still active, so its end can
    switch off exactly what it ran."""
    rules, _held = await _automation_rules_and_holds()
    return {actuator for actuator, grows in (await _actuator_grows(rules)).items()
            if session_id in grows}


async def _grows_remaining() -> bool:
    """Whether an active grow still runs anything. A grow parked in cold
    storage that no chamber links runs nothing: it is in the fridge, so the
    closet's end must not wait on it."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM sessions WHERE status = 'active' AND (current_phase != 'cold_storage' "
            "OR id IN (SELECT active_session_id FROM chambers WHERE active_session_id IS NOT NULL)) "
            "LIMIT 1"
        )
        return await cursor.fetchone() is not None


async def _safe_actuators_after_session_end(
    session_id: int, ran: Collection[str] = (),
) -> list[dict] | None:
    """Command automation-driven actuators OFF when a grow ends.

    With no grow left the engine runs only the life-safety rules (e.g. the
    CO2 Hard Ceiling), so whatever the grow's rules last switched ON — a
    cooler plug from "Pre-cool for Hot Forecast" (no safety_max_on), the
    fruiting light scene, a vendor plug — would otherwise stay ON
    indefinitely. Every actuator an automation rule can switch ON gets an
    explicit OFF (lights go to the dark scene; a vendor device the OFF its
    safety ceiling sends, through the integrations dispatcher), except those
    under an operator's manual hold, read as the engine reads it (_is_held):
    a light with one channel pinned keeps its scene, and a plug is held by
    its id or its role name, whichever the rule names. A placeholder target
    (relay-01 / light-01) is switched off on every node it can stand for,
    and a plug role on every plug of the role (plugs_for_target): the engine
    sent the ON to its chamber's node or plug, which resolving it once, to
    the one seen last or found first anywhere, missed. Each node or plug OFF
    that went out is reported to the actuator-off listeners (the engine's
    safety-ceiling bookkeeping); a vendor OFF reports itself through the
    dispatcher's write listeners.

    While another grow still runs, the engine keeps driving the hardware for
    it and a blanket OFF would fight it, so only what this grow drove
    (`ran`, read before it ended) that no remaining grow drives is switched
    off (_actuator_grows): its chamber's nodes, the unlisted closet nodes of
    a chamberless grow, an idle chamber's nodes it ran, and the plugs its
    rules reached that no remaining grow's rules reach — a plug no chamber
    lists stays on while a grow runs a chamber without its own plug of the
    role. Never a vendor device while another grow runs (those serve every
    chamber). A grow in cold storage that no chamber links runs nothing and
    does not count. Returns the per-actuator results, or None when nothing
    was left to switch off.
    """
    rules, held = await _automation_rules_and_holds()
    idle: set[str] | None = None  # None: no grow left, switch everything off
    if await _grows_remaining():
        grows = await _actuator_grows(rules)
        idle = {actuator for actuator in ran if not grows.get(actuator)}
        if not idle:
            return None

    results: list[dict] = []
    seen: set[tuple[str, str | None, str]] = set()
    for rule in rules:
        action = rule.get("action") or {}
        target = action.get("target")
        channel = action.get("channel")
        if not target:
            continue
        if action.get("vendor_slug"):
            if idle is None:
                if result := await _vendor_off_at_session_end(action, held, seen):
                    results.append(result)
            continue
        if action.get("state") != "on":
            continue
        if await is_plug_target(target):
            kind, key_channel = "plug", None
            plugs = await plugs_for_target(target)  # none paired: nothing to switch
            if idle is not None:
                # Only an idle chamber's own plug: one no chamber lists may
                # serve the grow that is still running.
                plugs = [p for p in plugs if p["plug_id"] in idle]
            # Each plug under every name a hold on it may carry: the rule's,
            # its id and its role.
            actuators = [
                (p["plug_id"], {target, p["plug_id"]}
                 | ({f"plug-{p['device_role']}"} if p["device_role"] else set()))
                for p in plugs
            ]
        else:
            if channel:
                kind, key_channel = "channel", channel
            elif action.get("scene"):
                kind, key_channel = "scene", None
            else:
                continue  # cmd/config carries no on/off state
            nodes = await _actuator_nodes(target)
            if idle is not None:
                nodes = [n for n in nodes if n in idle]
            actuators = [(node, {target, node}) for node in nodes]
        for resolved, names in actuators:
            if _is_held(held, names, action):
                continue
            key = (resolved, key_channel, kind)
            if key in seen:
                continue
            seen.add(key)

            published = False
            # Taken just before the publish: a ceiling armed by an ON that went
            # out after this moment is not ended by this OFF.
            sent_at = time.time()
            try:
                if kind == "plug":
                    published = await send_plug_command(resolved, "off")
                else:
                    # A channel's OFF, or (no channel) the all-off scene — the
                    # same command the engine's OFFs send.
                    published = await mqtt_publish(
                        *node_off_command(resolved, key_channel, "session_ended"))
            except Exception as e:  # one unreachable actuator must not strand the rest
                log.warning("session-end OFF for %s:%s failed: %s", resolved, key_channel, e)
            if published:
                await _notify_actuator_off(resolved, key_channel, sent_at)
            results.append({
                "target": resolved, "channel": key_channel, "kind": kind,
                "published": bool(published),
            })

    if results:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO session_events (session_id, type, source, description, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, "actuators_safed", "system",
                 f"Session ended — {len(results)} automation actuator(s) commanded off",
                 json.dumps({"actuators": results})),
            )
            await db.commit()
    return results


async def _vendor_off_at_session_end(
    action: dict, held: set[tuple[str, str | None]], seen: set[tuple[str, str | None, str]],
) -> dict | None:
    """Switch off the vendor device a rule's action switches ON, the way its
    safety ceiling does (integrations VENDOR_SAFETY_OFF); None when the
    action switches nothing on, the vendor has no OFF, the device is held or
    already done. Sent as a write from outside automation (dispatch_manual),
    so the engine clears the device's safety ceiling."""
    slug = action["vendor_slug"]
    params = action.get("vendor_params") or {}
    if not vendor_actions.vendor_params_on(slug, action.get("vendor_action"), params):
        return None
    off = vendor_actions.vendor_safety_off(slug, params)
    device = vendor_actions.vendor_device_key(slug, params)
    if off is None or device is None:
        return None
    key = (device, None, "vendor")
    if key in seen or _is_held(held, {action["target"], device}, action):
        return None
    seen.add(key)
    published = False
    try:
        await vendor_actions.dispatch_manual(slug, *off)
        published = True
    except Exception as e:  # one unreachable device must not strand the rest
        log.warning("session-end OFF for %s failed: %s", device, e)
    return {"target": device, "channel": None, "kind": "vendor", "published": published}


async def _end_session(session_id: int, status: str, event_type: str, description: str,
                       *, contamination: ContaminationMark | None = None) -> dict | None:
    """Close a session: status + open phase + chamber link + event in ONE
    transaction, then safe the actuators the engine will no longer manage.
    With `contamination`, a manual contamination event against the session
    and its chamber is logged in that same transaction.

    None for an unknown session. A grow that has already ended is not ended
    again: in the same status it comes back unchanged (nothing written,
    nothing switched off); in another it raises SessionConflictError —
    aborting a completed grow used to rewrite its outcome and end time, log
    a second end and switch its chamber off again."""
    async with get_db() as db:
        cursor = await db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
    if row is None:
        return None
    if row["status"] != "active":
        return await _already_ended(session_id, row["status"], status)
    ran = await _nodes_run_by(session_id)
    now = time.time()
    contamination_event_id = None
    async with get_db() as db:
        cursor = await db.execute("SELECT chamber_id FROM sessions WHERE id = ?", (session_id,))
        session_row = await cursor.fetchone()
        if status == "completed":
            cursor = await db.execute(
                "UPDATE sessions SET status = 'completed', current_phase = 'complete', completed_at = ? "
                "WHERE id = ? AND status = 'active'",
                (now, session_id),
            )
        else:
            cursor = await db.execute(
                "UPDATE sessions SET status = ?, completed_at = ? WHERE id = ? AND status = 'active'",
                (status, now, session_id),
            )
        if cursor.rowcount == 0:  # ended meanwhile
            await db.rollback()
            cursor = await db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,))
            ended = await cursor.fetchone()
            return await _already_ended(session_id, ended["status"], status)
        await db.execute(
            "UPDATE phase_history SET exited_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (now, session_id),
        )
        # The chamber no longer hosts this grow (it shows the other grow
        # still bound to it, if any).
        await db.execute(_RELINK_CHAMBERS_SQL, {"sid": session_id})
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, event_type, "user", description),
        )
        if contamination is not None:
            contamination_event_id = await insert_event(
                db,
                source="manual",
                session_id=session_id,
                chamber_id=session_row["chamber_id"],
                contamination_type=(contamination.contamination_type or "").strip() or None,
                notes=contamination.notes,
                detected_at=now,
            )
        await db.commit()
    if contamination_event_id is not None:
        await publish_event(contamination_event_id)
    await _safe_actuators_after_session_end(session_id, ran)
    await _notify_session_changed(session_id)
    return await get_session(session_id)


async def _already_ended(session_id: int, current: str, requested: str) -> dict | None:
    """_end_session for a grow that has ended: unchanged when it already
    holds the requested status, else SessionConflictError."""
    if current == requested:
        return await get_session(session_id)
    raise SessionConflictError(
        f"Session {session_id} has already ended ({current}): it cannot be {requested} now")


async def abort_session(session_id: int) -> dict | None:
    return await _end_session(session_id, "aborted", "session_aborted", "Session aborted")


async def mark_contaminated(session_id: int, data: ContaminationMark) -> dict | None:
    """End a grow lost to contamination (POST /api/sessions/{id}/contaminated).

    The session is aborted, the terminal status the cloud and every dashboard
    know, and a manual contamination event is logged against it and its
    chamber in the same transaction. Chamber stats, experiment comparisons,
    the Contamination page, the Prometheus exporter and the cloud all count
    contamination from those events: the Sessions page's "mark contaminated"
    used to abort only, which none of them saw. None for an unknown session.
    """
    what = (data.contamination_type or "").strip()
    description = f"Session aborted — contaminated ({what})" if what else "Session aborted — contaminated"
    return await _end_session(session_id, "aborted", "session_aborted", description,
                              contamination=data)


async def complete_session(session_id: int) -> dict | None:
    return await _end_session(session_id, "completed", "session_completed", "Session completed")


def _exit_reminder_message(phase: str, days_in_phase: int, params: PhaseParams,
                           reminder: str) -> str:
    """The daily phase check for a phase that owes a manual step on exit."""
    lo, hi = (int(d) for d in params.expected_duration_days)
    label = phase.replace("_", " ")
    status = (f"Day {days_in_phase} of {label} — past its {lo}-{hi} d window."
              if days_in_phase > hi else f"Day {days_in_phase} of {label} ({lo}-{hi} d expected).")
    return f"{status} Once it is complete: {reminder} Then advance the session."


async def check_phase_reminders(now: float | None = None) -> int:
    """INFO-tier nudge for each active session that has overrun its phase.

    Fires phase_reminder() when days in the current phase exceed the species'
    expected_duration_days max (the notifier dedups per session+phase). A phase
    that owes a manual step on exit (PhaseParams.exit_reminder — shiitake
    browning's cold-water soak) is nudged from its expected MINIMUM instead,
    with the step spelled out, since that is when the operator should start
    checking whether it is done. Meant to be run periodically (e.g. daily) by a
    background task. Returns the number of reminders sent.

    The window is that of the setpoints the phase runs on (phase_params_for:
    its own, or its PHASE_PARAM_FALLBACKS stand-in's, with the session's
    growth form), so a rest or a pinning phase the profile folds into
    fruiting is nudged on fruiting's window; looked up directly, those phases
    never were. The exit step is only ever the phase's own
    (SpeciesProfile.phase_exit_reminder): a stand-in's step is not owed.
    """
    now = time.time() if now is None else now
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT s.id, s.name, s.species_profile_id, s.current_phase, s.growth_form, "
            "ph.entered_at "
            "FROM sessions s JOIN phase_history ph "
            "  ON ph.session_id = s.id AND ph.exited_at IS NULL AND ph.phase = s.current_phase "
            "WHERE s.status = 'active'"
        )
        rows = [dict(r) for r in await cursor.fetchall()]

    sent = 0
    for row in rows:
        profile = await get_profile(row["species_profile_id"])
        params = phase_params_for(profile, row["current_phase"], row["growth_form"])
        if params is None:
            continue
        expected_min = int(params.expected_duration_days[0])
        expected_max = int(params.expected_duration_days[1])
        days_in_phase = int((now - row["entered_at"]) // 86400)
        reminder = profile.phase_exit_reminder(row["current_phase"])
        if reminder and days_in_phase >= expected_min:
            await notify_info(
                f"Phase check — {row['name']}",
                _exit_reminder_message(row["current_phase"], days_in_phase, params, reminder),
                dedup_key=f"phase-exit:{row['id']}:{row['current_phase']}",
            )
            sent += 1
        elif days_in_phase > expected_max:
            await phase_reminder(row["id"], row["name"], row["current_phase"],
                                 days_in_phase, expected_max)
            sent += 1
    return sent


# ── Cloud → Pi remote command seam ───────────────────────────────


async def handle_remote_command(channel: str, payload: dict) -> dict | None:
    """Execute a cloud-relayed chamber "system" command against this service.

    Dispatched by ``app.cloud.service._dispatch_system_command`` for the
    ``session_start`` / ``session_end`` channels (target_kind="system"). That
    dispatcher wraps this call in a try/except and reports the outcome in the
    relay ``command_result`` ack, so any exception raised here surfaces to the
    originating client as ``success=false`` with its reason.

    - ``session_start``: create a grow session from ``payload`` (SessionCreate fields).
    - ``session_end``:   mark the session ``payload['session_id']`` complete.

    Reuses the existing ``create_session`` / ``complete_session`` service
    functions verbatim. Returns the resulting session dict. An end for no
    such session (or a session_id that is not an integer) raises, so the
    client hears success=false: it used to hear that a grow ended when
    nothing had.
    """
    if channel == "session_start":
        return await create_session(SessionCreate(**payload))
    if channel == "session_end":
        raw = payload["session_id"]
        if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not str(raw).strip().isdigit():
            raise ValueError(f"session_id must be an integer, got {raw!r}")
        session_id = int(raw)
        session = await complete_session(session_id)
        if session is None:
            raise LookupError(f"session {session_id} not found")
        return session
    raise ValueError(f"unknown session command channel: {channel!r}")


# Strategy 3 of resolve_session_node_id: of the nodes listed in no chamber and
# the nodes in :running (a JSON array: the chambers whose grow this session
# is), the one with the most samples (raw rows, plus rollup rows weighted by
# their sample count) inside [from_ts, to_ts], for :sensor when given.
_CHAMBERLESS_SESSION_NODE_SQL = """
    WITH chambered AS (
        SELECT DISTINCT j.value AS node_id FROM chambers c,
               json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j
    ),
    samples AS (
        SELECT node_id, 1 AS n FROM telemetry_readings
         WHERE timestamp >= :from_ts AND timestamp <= :to_ts
           AND (:sensor IS NULL OR sensor = :sensor)
        UNION ALL
        SELECT node_id, COALESCE(count, 1) AS n FROM telemetry_rollups
         WHERE timestamp >= :from_ts AND timestamp <= :to_ts
           AND (:sensor IS NULL OR sensor = :sensor)
    )
    SELECT node_id FROM samples
     WHERE node_id NOT IN (SELECT node_id FROM chambered)
        OR node_id IN (SELECT value FROM json_each(:running))
     GROUP BY node_id
     ORDER BY SUM(n) DESC, node_id
     LIMIT 1
"""


async def resolve_session_node_id(session_id: int, sensor: str | None = None) -> str | None:
    """Resolve which hardware node's telemetry backs a session.

    Backs the per-session telemetry endpoint, which previously hardcoded
    ``climate-01`` and so returned the wrong node's series (or nothing) for any
    node not named that, and for every session whose chamber is a different node.

    Three strategies, in order:
      1. Session-tagged telemetry — if any ``telemetry_readings`` rows carry this
         ``session_id``, use the node that produced them (scoped to ``sensor``
         when given, so a session spanning several nodes resolves to the one that
         actually reports the requested sensor). This is authoritative.
      2. Chamber topology — otherwise map session → ``chamber_id`` → the
         chamber's ``node_ids`` and pick the climate/sensor node (``node_type``
         'climate'/'sensor', or a node whose ``roles`` include one of those),
         falling back to the chamber's first node.
      3. A chamberless session whose tagged raw rows have aged into rollups
         (raw telemetry is kept 7 days): of the nodes in no chamber and the
         nodes of every chamber this (active) session is the grow of
         (chamber_nodes_running), the one that reported the most data during
         the session — raw rows or rollups. Those are the nodes the per-node
         session rule hands a chamberless grow.

    Returns None when no strategy yields a node (unknown session, or no
    telemetry at all) so the caller can return an empty series.
    """
    async with get_db() as db:
        # 1. Prefer telemetry actually tagged with this session.
        if sensor:
            cursor = await db.execute(
                "SELECT node_id FROM telemetry_readings "
                "WHERE session_id = ? AND sensor = ? "
                "GROUP BY node_id ORDER BY COUNT(*) DESC, MAX(timestamp) DESC LIMIT 1",
                (session_id, sensor),
            )
        else:
            cursor = await db.execute(
                "SELECT node_id FROM telemetry_readings WHERE session_id = ? "
                "GROUP BY node_id ORDER BY COUNT(*) DESC, MAX(timestamp) DESC LIMIT 1",
                (session_id,),
            )
        row = await cursor.fetchone()
        if row:
            return row["node_id"]

        # 2. Fall back to the session's chamber's climate/sensor node.
        cursor = await db.execute(
            "SELECT chamber_id, created_at, completed_at FROM sessions WHERE id = ?",
            (session_id,),
        )
        srow = await cursor.fetchone()
        if not srow:
            return None
        crow = None
        if srow["chamber_id"] is not None:
            cursor = await db.execute(
                "SELECT node_ids FROM chambers WHERE id = ?", (srow["chamber_id"],)
            )
            crow = await cursor.fetchone()
        if not crow:
            # 3. Chamberless (or its chamber was deleted): the unassigned node,
            # or a node of a chamber this grow runs, with the most data in the
            # session's window.
            cursor = await db.execute(_CHAMBERLESS_SESSION_NODE_SQL, {
                "sensor": sensor,
                "from_ts": srow["created_at"] or 0,
                "to_ts": srow["completed_at"] or time.time(),
                "running": json.dumps(await chamber_nodes_running(session_id)),
            })
            row = await cursor.fetchone()
            return row["node_id"] if row else None
        try:
            node_ids = json.loads(crow["node_ids"] or "[]")
        except (json.JSONDecodeError, TypeError):
            node_ids = []
        if not node_ids:
            return None

        # Pick the climate/sensor node among the chamber's nodes, mirroring the
        # node_type/roles matching in app.cloud.service._fitting_nodes.
        placeholders = ",".join("?" for _ in node_ids)
        cursor = await db.execute(
            f"SELECT node_id FROM hardware_nodes "
            f"WHERE node_id IN ({placeholders}) "
            f"AND (node_type IN ('climate', 'sensor') "
            f"     OR EXISTS (SELECT 1 FROM json_each(hardware_nodes.roles) "
            f"                WHERE json_each.value IN ('climate', 'sensor'))) "
            f"LIMIT 1",
            node_ids,
        )
        nrow = await cursor.fetchone()
        if nrow:
            return nrow["node_id"]

        # No registry classification — the chamber's first node is the best guess.
        return node_ids[0]


# ── Volume parsing helper ────────────────────────────────────────


# "5 quarts", "2.5 L", "1,5 l" (a decimal comma), "12 x 1.5 L" (twelve
# 1.5 L bags). A number starts only where no digit, '.' or ',' comes before
# it: "1.5.2 l" and "approx. L" read as no volume, where "[\d.]+" took "."
# or the "2" (float(".") made /stats, the report and the session list 500),
# and the search stays linear on a long run of digits (it backtracked
# quadratically, stalling the event loop).
_VOLUME_PATTERN = re.compile(
    r"(?<![\d.,])(?:(\d+)\s*[x×*]\s*)?(\d+(?:[.,]\d+)?|\.\d+)\s*"
    r"(quarts?|qt|liters?|litres?|l|gallons?|gal)\b",
    re.IGNORECASE,
)

_TO_LITERS = {
    "quart": 0.946353, "quarts": 0.946353, "qt": 0.946353,
    "liter": 1.0, "liters": 1.0, "litre": 1.0, "litres": 1.0, "l": 1.0,
    "gallon": 3.78541, "gallons": 3.78541, "gal": 3.78541,
}

# Approximate dry substrate weight: ~300g per liter
_DRY_SUBSTRATE_G_PER_LITER = 300.0


def _parse_volume_to_liters(volume_str: str | None) -> float | None:
    """Parse a volume string like '5 quarts' or '10 liters' into liters;
    None when it holds no readable volume."""
    if not volume_str:
        return None
    m = _VOLUME_PATTERN.search(volume_str)
    if not m:
        return None
    try:
        value = float(m.group(2).replace(",", "."))
        count = int(m.group(1)) if m.group(1) else 1
    except ValueError:
        return None
    factor = _TO_LITERS.get(m.group(3).lower())
    if factor is None:
        return None
    return count * value * factor


def _biological_efficiency(substrate_volume: str | None, total_wet_g: float) -> float | None:
    """Biological efficiency in percent, one decimal: fresh yield over the dry
    substrate weight estimated from its volume. None without a parseable
    volume. The one formula behind the session rows, /stats and the report."""
    volume_liters = _parse_volume_to_liters(substrate_volume)
    if not volume_liters or volume_liters <= 0:
        return None
    dry_substrate_g = volume_liters * _DRY_SUBSTRATE_G_PER_LITER
    return round((total_wet_g / dry_substrate_g) * 100, 1)


# ── Yield Statistics + Biological Efficiency ─────────────────────


async def get_session_stats(session_id: int) -> dict | None:
    """Calculate yield statistics and biological efficiency for a session."""
    async with get_db() as db:
        # Verify session exists
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        session = await cursor.fetchone()
        if not session:
            return None
        session = dict(session)

        # Get all harvests for this session, ordered by flush
        cursor = await db.execute(
            "SELECT * FROM harvests WHERE session_id = ? ORDER BY flush_number, timestamp",
            (session_id,),
        )
        harvests = [dict(r) for r in await cursor.fetchall()]

        # Per-flush yields: aggregate by flush_number
        flush_map: dict[int, dict] = {}
        for h in harvests:
            fn = h["flush_number"]
            if fn not in flush_map:
                flush_map[fn] = {"flush_number": fn, "wet_weight_g": 0.0, "dry_weight_g": 0.0}
            flush_map[fn]["wet_weight_g"] += h["wet_weight_g"] or 0.0
            flush_map[fn]["dry_weight_g"] += h["dry_weight_g"] or 0.0

        flush_yields = sorted(flush_map.values(), key=lambda f: f["flush_number"])

        # Totals
        total_wet = sum(f["wet_weight_g"] for f in flush_yields)
        total_dry = sum(f["dry_weight_g"] for f in flush_yields)

        # Flush-over-flush decline percentages
        flush_decline_pct = []
        for i in range(1, len(flush_yields)):
            prev_wet = flush_yields[i - 1]["wet_weight_g"]
            curr_wet = flush_yields[i]["wet_weight_g"]
            if prev_wet > 0:
                decline = ((prev_wet - curr_wet) / prev_wet) * 100
                flush_decline_pct.append(round(decline, 1))
            else:
                flush_decline_pct.append(0.0)

        biological_efficiency = _biological_efficiency(session.get("substrate_volume"), total_wet)

        # Species averages via SQL aggregate (instead of loading all rows),
        # over the species' completed grows in any id spelling.
        species_id = session["species_profile_id"]
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt, AVG(total_wet_yield_g) as avg_yield, "
            "MAX(total_wet_yield_g) as best_yield FROM sessions WHERE " + _SAME_SPECIES +
            " AND status = 'completed' AND total_wet_yield_g > 0",
            (canonical_species_id(species_id),),
        )
        agg = dict(await cursor.fetchone())
        species_session_count = agg["cnt"]
        species_avg_yield_g = round(agg["avg_yield"], 1) if agg["avg_yield"] else None
        species_best_yield_g = round(agg["best_yield"], 1) if agg["best_yield"] else None

        return {
            "session_id": session_id,
            "species_profile_id": species_id,
            "flush_yields": flush_yields,
            "flush_decline_pct": flush_decline_pct,
            "total_wet_yield_g": round(total_wet, 1),
            "total_dry_yield_g": round(total_dry, 1),
            "biological_efficiency": biological_efficiency,
            "flush_count": len(flush_yields),
            "species_avg_yield_g": species_avg_yield_g,
            "species_best_yield_g": species_best_yield_g,
            "species_session_count": species_session_count,
            # When the newest harvest was logged (None before the first): the
            # dashboard's harvest form numbers the next flush from it without
            # reading the grow's whole event history.
            "last_harvest_at": max((h["timestamp"] for h in harvests if h["timestamp"] is not None), default=None),
        }


# ── Harvest Drying Tracker ───────────────────────────────────────


# Cracker-dry: the harvest has lost this share of its fresh weight.
_DRY_TARGET_LOSS_PCT = 90.0


def _moisture_loss(fresh_g: float, current_g: float) -> tuple[float, float]:
    """(moisture loss %, dry/wet ratio) of a harvest dried from fresh_g to current_g."""
    if fresh_g > 0:
        return round((1 - current_g / fresh_g) * 100, 1), round(current_g / fresh_g, 4)
    return 0.0, 1.0


async def add_drying_log(session_id: int, harvest_id: int, weight_g: float) -> dict | None:
    """Add a drying log weight entry for a harvest. Returns drying progress.

    An entry at the cracker-dry target (and any later one past it) is the
    harvest's dry weight: it is written to the harvest and the session's dry
    yield is re-summed from its harvests, in the same transaction. Dry yield
    used to come only from a weight typed in at harvest time, so stats, the
    report, the CSV and the cloud showed 0 g for a harvest dried later.
    """
    async with get_db() as db:
        # Verify harvest exists and belongs to session
        cursor = await db.execute(
            "SELECT * FROM harvests WHERE id = ? AND session_id = ?",
            (harvest_id, session_id),
        )
        harvest = await cursor.fetchone()
        if not harvest:
            return None

        await db.execute(
            "INSERT INTO drying_log (harvest_id, session_id, weight_g) VALUES (?, ?, ?)",
            (harvest_id, session_id, weight_g),
        )
        loss_pct, _ratio = _moisture_loss(harvest["wet_weight_g"] or 0.0, weight_g)
        dried = loss_pct >= _DRY_TARGET_LOSS_PCT
        if dried:
            await db.execute("UPDATE harvests SET dry_weight_g = ? WHERE id = ?",
                             (weight_g, harvest_id))
            # Re-summed rather than added to, so a later entry replaces the
            # weight and a dry weight given at harvest time is not counted twice.
            await db.execute(
                "UPDATE sessions SET total_dry_yield_g = ("
                "SELECT COALESCE(SUM(dry_weight_g), 0) FROM harvests WHERE session_id = ?) "
                "WHERE id = ?",
                (session_id, session_id),
            )
        await db.commit()
    if dried:
        await _notify_session_changed(session_id)

    progress = await get_drying_progress(session_id, harvest_id)
    if progress and progress.get("target_reached"):
        session = await get_session(session_id)
        name = session["name"] if session else f"Session {session_id}"
        await notify_info(
            f"Drying Complete — {name}",
            f"Flush #{progress['flush_number']} has reached cracker-dry "
            f"({progress['moisture_loss_pct']:.0f}% moisture loss, {progress['current_weight_g']}g final weight)",
            dedup_key=f"drying:{harvest_id}",
        )
    return progress


async def get_drying_progress(session_id: int, harvest_id: int) -> dict | None:
    """Get drying progress for a harvest including moisture loss calculations."""
    async with get_db() as db:
        # Verify harvest exists and belongs to session
        cursor = await db.execute(
            "SELECT * FROM harvests WHERE id = ? AND session_id = ?",
            (harvest_id, session_id),
        )
        harvest = await cursor.fetchone()
        if not harvest:
            return None
        harvest = dict(harvest)

        fresh_weight = harvest["wet_weight_g"] or 0.0

        # Get all drying log entries (id breaks a same-second tie: the
        # newest entry is the current weight)
        cursor = await db.execute(
            "SELECT * FROM drying_log WHERE harvest_id = ? ORDER BY timestamp, id",
            (harvest_id,),
        )
        entries = [dict(r) for r in await cursor.fetchall()]

        current_weight = entries[-1]["weight_g"] if entries else fresh_weight
        moisture_loss_pct, dry_wet_ratio = _moisture_loss(fresh_weight, current_weight)
        target_reached = moisture_loss_pct >= _DRY_TARGET_LOSS_PCT

        return {
            "harvest_id": harvest_id,
            "flush_number": harvest["flush_number"],
            "fresh_weight_g": fresh_weight,
            "entries": entries,
            "current_weight_g": current_weight,
            "moisture_loss_pct": moisture_loss_pct,
            "target_reached": target_reached,
            "dry_wet_ratio": dry_wet_ratio,
        }


# ── iCal Calendar Feed ─────────────────────────────────────────


def _ts_to_dt(ts: float | None) -> datetime | None:
    """Convert a Unix timestamp to a timezone-aware datetime, or None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _parse_inoculation_date(raw) -> date | None:
    """Parse the session's free-text ``inoculation_date`` (a TEXT column) to a date.

    The UI stores an ISO date ('YYYY-MM-DD'); a full ISO datetime is tolerated by
    taking its date part. Returns None when unset or unparseable so the caller can
    fall back to the session's creation date.
    """
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _cycle_shift(cycle, start_phase: str | None, anchor: date) -> timedelta:
    """How far a proposed cycle must move so ``start_phase`` begins at ``anchor``.

    The first planned phase at or after the session's starting phase (canonical
    order) is the one the anchor date refers to. Unknown/unplanned start → 0.
    """
    try:
        start_idx = _GROW_PHASES.index(start_phase)
    except ValueError:
        return timedelta(0)
    for planned in cycle.phases:
        try:
            idx = _GROW_PHASES.index(planned.phase)
        except ValueError:
            continue
        if idx >= start_idx:
            return planned.start_date - anchor
    return timedelta(0)


async def generate_ical() -> str:
    """Generate an iCal calendar with events for all sessions."""
    from icalendar import Calendar, Event  # lazy — only loaded when calendar is requested

    cal = Calendar()
    cal.add("prodid", "-//SporePrint//Grow Calendar//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "SporePrint Grows")

    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM sessions ORDER BY created_at")
        sessions = [dict(r) for r in await cursor.fetchall()]

        # Batch load all phases and harvests (instead of N+1 per session)
        cursor = await db.execute(
            "SELECT * FROM phase_history ORDER BY entered_at"
        )
        all_phases = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT * FROM harvests ORDER BY timestamp"
        )
        all_harvests = [dict(r) for r in await cursor.fetchall()]

        # Group by session_id
        phases_by_session = defaultdict(list)
        for p in all_phases:
            phases_by_session[p["session_id"]].append(p)
        harvests_by_session = defaultdict(list)
        for h in all_harvests:
            harvests_by_session[h["session_id"]].append(h)

        for session in sessions:
            sid = session["id"]
            name = session["name"] or f"Session {sid}"
            species = session["species_profile_id"] or "unknown"
            substrate = session["substrate"] or ""
            created_dt = _ts_to_dt(session["created_at"])
            if not created_dt:
                continue

            # Session start event. The start, phase, harvest and end events
            # are moments: no DTEND (RFC 5545 §3.6.1: such an event ends at
            # its start). A DTEND equal to DTSTART is invalid (§3.8.2.2), and
            # strict calendar clients dropped those events.
            ev = Event()
            ev.add("summary", f"{name} — Session Started")
            ev.add("dtstart", created_dt)
            ev.add("description", f"Species: {species}\nSubstrate: {substrate}")
            ev["uid"] = f"session-{sid}-start@sporeprint"
            cal.add_component(ev)

            # Phase transitions (from batch-loaded data)
            phases = phases_by_session[sid]
            for ph in phases:
                ph_dt = _ts_to_dt(ph["entered_at"])
                if not ph_dt:
                    continue
                ev = Event()
                ev.add("summary", f"{name} — Phase: {ph['phase']}")
                ev.add("dtstart", ph_dt)
                ev.add("description", f"Trigger: {ph.get('trigger', 'manual')}")
                ev["uid"] = f"session-{sid}-phase-{ph['id']}@sporeprint"
                cal.add_component(ev)

            # Harvests (from batch-loaded data)
            harvests = harvests_by_session[sid]
            for h in harvests:
                h_dt = _ts_to_dt(h["timestamp"])
                if not h_dt:
                    continue
                weight = h.get("wet_weight_g") or 0
                ev = Event()
                ev.add("summary", f"{name} — Flush #{h['flush_number']} Harvest")
                ev.add("dtstart", h_dt)
                ev.add("description", f"Flush #{h['flush_number']}: {weight}g wet")
                ev["uid"] = f"session-{sid}-harvest-{h['id']}@sporeprint"
                cal.add_component(ev)

            # Expected future events for active sessions. Dates come from the
            # planner's species-derived cycle proposer (propose_cycle), anchored
            # at this session's actual inoculation date (else the local date it
            # was created on, the Pi's clock and the date the operator lived:
            # the UTC date put an evening start in a western zone a day late).
            # Driving the projection off the real per-phase durations keeps it
            # consistent with /planner/propose and inherits get_profile's
            # tolerant species-id resolution.
            if session["status"] == "active":
                # planner.service imports this module at its top: a cycle.
                from ..planner.service import propose_cycle

                profile = await get_profile(session["species_profile_id"])
                if profile and profile.phases:
                    anchor = (_parse_inoculation_date(session.get("inoculation_date"))
                              or datetime.fromtimestamp(session["created_at"]).date())
                    cycle = propose_cycle(profile, anchor)
                    # propose_cycle lays out every phase the species lists,
                    # including optional agar/LC/grain. A session that started
                    # later (substrate_colonization by default) never ran those,
                    # so shift the plan until its first phase starts at the anchor.
                    start_phase = phases[0]["phase"] if phases else session.get("current_phase")
                    shift = _cycle_shift(cycle, start_phase, anchor)
                    proposed_by_phase = {p.phase: p for p in cycle.phases}

                    current_phase = session.get("current_phase", "")
                    try:
                        current_idx = _GROW_PHASES.index(current_phase)
                    except ValueError:
                        current_idx = -1

                    # Only phases still ahead of the current one get an "expected"
                    # marker; phases already entered carry their real
                    # phase-history events above.
                    for future_phase in _GROW_PHASES[current_idx + 1:]:
                        if future_phase == "complete":
                            break
                        proposed = proposed_by_phase.get(future_phase)
                        if not proposed:
                            continue
                        ev = Event()
                        ev.add("summary", f"{name} — {future_phase.replace('_', ' ').title()} (Expected)")
                        ev.add("dtstart", proposed.start_date - shift)
                        ev["uid"] = f"session-{sid}-expected-{future_phase}@sporeprint"
                        cal.add_component(ev)

                    # Expected harvest = end of the fruiting phase in the plan.
                    if cycle.harvest_date:
                        ev = Event()
                        ev.add("summary", f"{name} — Expected Harvest")
                        ev.add("dtstart", cycle.harvest_date - shift)
                        ev["uid"] = f"session-{sid}-expected-harvest@sporeprint"
                        cal.add_component(ev)

            # Session completion
            completed_dt = _ts_to_dt(session.get("completed_at"))
            if completed_dt:
                ev = Event()
                ev.add("summary", f"{name} — Session {session['status'].title()}")
                ev.add("dtstart", completed_dt)
                ev.add("description", f"Final status: {session['status']}")
                ev["uid"] = f"session-{sid}-end@sporeprint"
                cal.add_component(ev)

    return cal.to_ical().decode()


# ── PDF Session Report ──────────────────────────────────────────


def _generate_recommendations(
    session: dict,
    harvests: list[dict],
    phase_history: list[dict],
    contam_events: list[dict],
    flush_count_typical: int | None = None,
) -> list[str]:
    """Generate rule-based recommendations from session data for the PDF
    report. ``flush_count_typical`` is the session's species profile's (None
    when the profile is unknown)."""
    recs = []

    # Biological efficiency check
    be = _biological_efficiency(session.get("substrate_volume"),
                                session.get("total_wet_yield_g") or 0.0)
    if be is not None and be < 50:
        recs.append(
            "Low biological efficiency — try supplementing substrate "
            "or increasing spawn rate"
        )

    # Flush decline check
    flush_map: dict[int, float] = {}
    for h in harvests:
        fn = h["flush_number"]
        flush_map.setdefault(fn, 0.0)
        flush_map[fn] += h["wet_weight_g"] or 0.0
    flush_yields = [flush_map[fn] for fn in sorted(flush_map.keys())]
    if len(flush_yields) >= 2:
        first = flush_yields[0]
        second = flush_yields[1]
        if first > 0 and ((first - second) / first) * 100 > 50:
            recs.append(
                "Sharp yield decline after flush 1 — consider shorter rest "
                "periods or substrate supplements between flushes"
            )

    # Flush count vs the species' profile (a custom strain's included: the
    # built-in list alone left the operator's own profiles out).
    if flush_count_typical and len(flush_map) < flush_count_typical:
        recs.append(
            f"Fewer flushes ({len(flush_map)}) than typical for this species "
            f"({flush_count_typical}) — check hydration and rest soak technique"
        )

    # Colonization duration check
    for ph in phase_history:
        if ph["phase"] in ("substrate_colonization", "grain_colonization"):
            entered = ph.get("entered_at")
            exited = ph.get("exited_at")
            if entered and exited:
                dur_days = (exited - entered) / 86400
                if dur_days > 20:
                    recs.append(
                        f"Extended colonization ({dur_days:.0f} days) — higher "
                        "spawn rate or warmer incubation may help"
                    )
                    break

    # Contamination events
    if contam_events:
        recs.append(
            f"Contamination detected ({len(contam_events)} event(s)) — review "
            "sterile technique, air filtration, and substrate pasteurization"
        )

    # Always include
    recs.append(
        "Keep detailed notes for each phase to identify patterns across grows"
    )

    return recs


# The report lists the grow's newest Claude analyses, at most this many, out
# of its newest _REPORT_VISION_SCAN stored ones.
_REPORT_VISION_ANALYSES = 10
_REPORT_VISION_SCAN = 50
_REPORT_VISION_TEXT_MAX = 300


def _report_vision_lines(rows) -> list[str]:
    """One line per analysis for the report, oldest first, from vision_frames
    rows newest first: the analysis' time, assessment and summary.

    The stored JSON used to be printed raw, cut at 300 characters, which
    always lost the summary (the prompt asks for it last), and the rows were
    read unordered, so the ten listed were the grow's oldest. An unreadable
    or non-object analysis is skipped.
    """
    lines = []
    for row in rows:
        try:
            analysis = _deserialize_frame(row)["analysis_claude"]
        except ValueError:
            continue
        if not isinstance(analysis, dict) or analysis.get("error"):
            continue
        summary = analysis.get("summary")
        health = analysis.get("health_assessment")
        if not isinstance(summary, str) or not summary.strip():
            summary = analysis.get("growth_stage")
        parts = [str(p).strip() for p in (health, summary) if p not in (None, "")]
        if not parts:
            continue
        text = ": ".join(parts).replace("\n", " ")
        if len(text) > _REPORT_VISION_TEXT_MAX:
            text = text[:_REPORT_VISION_TEXT_MAX - 3] + "..."
        when = _ts_to_dt(row["timestamp"])
        lines.append(f"{when.strftime('%Y-%m-%d %H:%M')} — {text}" if when else text)
        if len(lines) == _REPORT_VISION_ANALYSES:
            break
    return lines[::-1]


def _md_cell(value) -> str:
    """Free text as one Markdown table cell (no line breaks, no column bars)."""
    return " ".join(str(value or "").split()).replace("|", "\\|")


async def generate_session_report_md(session_id: int) -> str | None:
    """Generate a Markdown grow report for a session."""
    session = await get_session(session_id)
    if not session:
        return None

    name = session["name"] or f"Session {session_id}"
    species = session["species_profile_id"] or "unknown"
    substrate = session["substrate"] or "N/A"
    status = session["status"]
    created = _ts_to_dt(session["created_at"])
    completed = _ts_to_dt(session.get("completed_at"))
    phase_history = session.get("phase_history", [])

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM harvests WHERE session_id = ? ORDER BY flush_number, timestamp",
            (session_id,),
        )
        harvests = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT id, timestamp, analysis_claude FROM vision_frames "
            "WHERE session_id = ? AND analysis_claude IS NOT NULL "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            (session_id, _REPORT_VISION_SCAN),
        )
        vision_summaries = _report_vision_lines(await cursor.fetchall())

        # Every detection — vision, identify, a manual mark — is recorded in
        # contamination_events; no session event type ever carried one, so
        # reading session_events left every report clean.
        cursor = await db.execute(
            "SELECT detected_at, source, contamination_type, confidence, notes "
            "FROM contamination_events WHERE session_id = ? ORDER BY detected_at, id",
            (session_id,),
        )
        contam_events = [dict(r) for r in await cursor.fetchall()]

    profile = await get_profile(session["species_profile_id"])
    recommendations = _generate_recommendations(
        session, harvests, phase_history, contam_events,
        profile.flush_count_typical if profile is not None else None,
    )

    # Build Markdown report
    md = []
    md.append("# SporePrint Grow Report\n")
    md.append("| Field | Value |")
    md.append("|-------|-------|")
    md.append(f"| Session | {name} |")
    md.append(f"| Species | {species} |")
    md.append(f"| Substrate | {substrate} |")
    md.append(f"| Status | {status} |")
    md.append(f"| Started | {created.strftime('%Y-%m-%d %H:%M UTC') if created else 'N/A'} |")
    md.append(f"| Completed | {completed.strftime('%Y-%m-%d %H:%M UTC') if completed else 'In progress'} |")
    # Rounded: the totals are float sums of 0.1 g entries (300.29999999999995).
    md.append(f"| Total Wet Yield | {round(session.get('total_wet_yield_g', 0) or 0, 1)}g |")
    md.append(f"| Total Dry Yield | {round(session.get('total_dry_yield_g', 0) or 0, 1)}g |")
    md.append(f"| Flushes | {len(set(h['flush_number'] for h in harvests))} |")
    md.append("")

    # Yield breakdown
    if harvests:
        md.append("## Yield Per Flush\n")
        md.append("| Flush | Wet Weight (g) | Dry Weight (g) | Quality |")
        md.append("|-------|----------------|----------------|---------|")
        for h in harvests:
            md.append(f"| #{h['flush_number']} | {h.get('wet_weight_g') or 0:.1f} | {h.get('dry_weight_g') or '—'} | {h.get('quality_rating') or '—'} |")
        md.append("")

    # Phase timeline
    if phase_history:
        md.append("## Phase Timeline\n")
        md.append("| Phase | Entered | Duration |")
        md.append("|-------|---------|----------|")
        for ph in phase_history:
            entered = _ts_to_dt(ph.get("entered_at"))
            exited = _ts_to_dt(ph.get("exited_at"))
            entered_str = entered.strftime("%Y-%m-%d %H:%M") if entered else "?"
            if exited and entered:
                dur_days = (ph["exited_at"] - ph["entered_at"]) / 86400
                dur_str = f"{dur_days:.1f} days"
            elif entered and not exited:
                dur_str = "ongoing"
            else:
                dur_str = "?"
            md.append(f"| {ph['phase'].replace('_', ' ').title()} | {entered_str} | {dur_str} |")
        md.append("")

    # Vision summaries
    if vision_summaries:
        md.append("## Vision Analysis Summaries\n")
        for idx, line in enumerate(vision_summaries, 1):
            md.append(f"{idx}. {line}")
        md.append("")

    # Contamination events
    if contam_events:
        md.append("## Contamination Events\n")
        md.append("| Time | Type | Source | Confidence | Notes |")
        md.append("|------|------|--------|------------|-------|")
        for ev in contam_events:
            ev_dt = _ts_to_dt(ev.get("detected_at"))
            ev_time = ev_dt.strftime("%Y-%m-%d %H:%M") if ev_dt else "?"
            confidence = ev.get("confidence")
            if isinstance(confidence, (int, float)):
                shown = f"{confidence:.0%}" if 0 <= confidence <= 1 else f"{confidence:g}"
            else:
                shown = "—"
            md.append(f"| {ev_time} | {_md_cell(ev.get('contamination_type')) or 'unspecified'} "
                      f"| {_md_cell(ev.get('source')) or '—'} | {shown} "
                      f"| {_md_cell(ev.get('notes'))[:150] or '—'} |")
        md.append("")

    # Recommendations
    if recommendations:
        md.append("## Recommendations for Next Grow\n")
        for idx, rec in enumerate(recommendations, 1):
            md.append(f"{idx}. {rec}")
        md.append("")

    return "\n".join(md)


async def generate_session_report_csv(session_id: int) -> str | None:
    """Generate a CSV export of session harvest data."""
    session = await get_session(session_id)
    if not session:
        return None

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM harvests WHERE session_id = ? ORDER BY flush_number, timestamp",
            (session_id,),
        )
        harvests = [dict(r) for r in await cursor.fetchall()]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["session_id", "session_name", "species", "flush_number",
                      "wet_weight_g", "dry_weight_g", "quality_rating", "timestamp", "notes"])
    for h in harvests:
        writer.writerow([
            session_id,
            session.get("name", ""),
            session.get("species_profile_id", ""),
            h["flush_number"],
            h.get("wet_weight_g", ""),
            h.get("dry_weight_g", ""),
            h.get("quality_rating", ""),
            _ts_to_dt(h["timestamp"]).isoformat() if h.get("timestamp") else "",
            h.get("notes", ""),
        ])
    return buf.getvalue()
