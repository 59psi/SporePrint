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
from ..automation.service import deserialize_rule_row, resolve_node_target
from ..automation.smart_plugs import is_plug_target, send_plug_command, target_is_present
from ..chambers.service import chambers_for_node, get_chamber
from ..db import get_db
from ..mqtt import mqtt_publish
from ..notifications.service import notify_info, phase_reminder, pink_oyster_harvest
from ..species.models import GrowPhase, PhaseParams, SpeciesProfile
from ..species.profiles import canonical_species_id, species_id_candidates
from ..species.service import get_profile
from .models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate

log = logging.getLogger(__name__)

_PHASE_ORDER = [
    "agar", "liquid_culture", "grain_colonization",
    "substrate_colonization", "browning", "cold_storage", "primordia_induction",
    "fruiting", "rest", "complete",
]

# Where a phase borrows setpoints when the session's species profile does not
# define it — the automation engine resolves phase params through this table.
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
_COLONIZATION_PHASES = frozenset({
    "agar", "liquid_culture", "grain_colonization", "substrate_colonization",
})
# Phases a session may enter whatever its species profile defines.
_ALWAYS_ENTERABLE_PHASES = _SPECIES_AGNOSTIC_PHASES | _COLONIZATION_PHASES
_GROW_PHASES = tuple(p.value for p in GrowPhase)


class InvalidPhaseError(ValueError):
    """A phase a session cannot be advanced to (unknown, or no setpoints)."""


class UnknownChamberError(ValueError):
    """A session bound to a chamber id the Pi has no row for."""


def phase_params_source(defined: Collection[str], phase: str) -> str | None:
    """The profile phase whose setpoints `phase` runs on: the phase itself when
    the profile defines it, else its PHASE_PARAM_FALLBACKS stand-in, else None."""
    if phase in defined:
        return phase
    return next((alt for alt in PHASE_PARAM_FALLBACKS.get(phase, ()) if alt in defined), None)


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


def _params_snapshot(profile: SpeciesProfile | None, phase: str) -> str | None:
    """JSON of the species setpoints in force for ``phase`` (phase_history.params_snapshot).

    Frozen at phase entry so a later edit to a custom profile can't rewrite what
    transcripts/analysis believe the targets were. None when the profile is
    unknown or has no parameters for this phase (e.g. cold_storage).
    """
    if profile is None:
        return None
    try:
        params = profile.phases.get(GrowPhase(phase))
    except ValueError:
        return None
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
    now = time.time()
    # Normalize to the hyphenated UI spelling so the stored id matches what the
    # cloud/mobile surfaces send and locally match on, regardless of whether the
    # caller submitted the hyphenated or underscored form. get_profile() stays
    # tolerant either way. See app.species.profiles.canonical_species_id.
    species_id = canonical_species_id(data.species_profile_id)
    profile = await get_profile(species_id)
    # Same gate as advance_phase: a session created at a typo'd phase used to
    # run with no setpoints and no stage alerts (the REST route answers 422;
    # a cloud session_start reports the reason as success=false).
    if error := phase_error(data.current_phase, profile):
        raise InvalidPhaseError(error)
    snapshot = _params_snapshot(profile, data.current_phase)
    async with get_db() as db:
        # sessions.chamber_id references chambers(id): an unknown id used to
        # surface as a FOREIGN KEY IntegrityError and a bare 500.
        if data.chamber_id is not None:
            cursor = await db.execute("SELECT 1 FROM chambers WHERE id = ?", (data.chamber_id,))
            if await cursor.fetchone() is None:
                raise UnknownChamberError(f"chamber {data.chamber_id} not found")
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


async def list_sessions(status: str | None = None, species: str | None = None,
                        include_phase_history: bool = False) -> list[dict]:
    query = "SELECT * FROM sessions WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if species:
        query += " AND species_profile_id = ?"
        params.append(species)
    query += " ORDER BY created_at DESC"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        sessions = [dict(r) for r in await cursor.fetchall()]

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

        return sessions


async def get_session(session_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        session = dict(row)

        cursor = await db.execute(
            "SELECT * FROM phase_history WHERE session_id = ? ORDER BY entered_at", (session_id,)
        )
        session["phase_history"] = [_decode_phase_row(r) for r in await cursor.fetchall()]
        return session


_UPDATE_SESSION_SQL = """
UPDATE sessions SET
    name = COALESCE(?, name),
    substrate = COALESCE(?, substrate),
    substrate_volume = COALESCE(?, substrate_volume),
    substrate_prep_notes = COALESCE(?, substrate_prep_notes),
    inoculation_date = COALESCE(?, inoculation_date),
    inoculation_method = COALESCE(?, inoculation_method),
    spawn_source = COALESCE(?, spawn_source),
    tub_number = COALESCE(?, tub_number),
    shelf_number = COALESCE(?, shelf_number),
    shelf_side = COALESCE(?, shelf_side),
    growth_form = COALESCE(?, growth_form),
    pinning_tek = COALESCE(?, pinning_tek)
WHERE id = ?
"""

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


async def update_session(session_id: int, data: SessionUpdate) -> dict | None:
    raw = data.model_dump()
    # Skip the query entirely when there's nothing to change.
    if not any(raw.get(c) is not None for c in _UPDATE_SESSION_COLUMNS):
        return await get_session(session_id)

    # One atomic UPDATE. COALESCE(?, col) leaves the existing value in place
    # for any column whose Pydantic input was None ("unchanged"). No f-string
    # SQL construction — columns are fixed in _UPDATE_SESSION_SQL.
    params = tuple(raw.get(c) for c in _UPDATE_SESSION_COLUMNS) + (session_id,)
    async with get_db() as db:
        await db.execute(_UPDATE_SESSION_SQL, params)
        await db.commit()
    await _notify_session_changed(session_id)
    return await get_session(session_id)


# (_COLONIZATION_PHASES is defined with the phase-validation tables above.)
# Bulk-substrate containers that fruit in place (a bag is cut open; a tub/tray
# is opened to air). Everything else — colonized agar / liquid culture / grain
# spawn — is pulled and parked in cold storage until used. monotub/tray were
# missing here, which wrongly routed them to cold storage; they are bulk
# substrate that fruits, matching the session-wizard container selector.
_FRUITING_CONTAINERS = {"grow_bag", "bag", "bulk_bag", "monotub", "tray"}


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


async def advance_phase(session_id: int, data: PhaseAdvance) -> dict | None:
    """Move the session to data.phase. None for an unknown session; raises
    InvalidPhaseError for a phase the session cannot run (see phase_error).

    Stepping on out of a phase that owes a manual step (PhaseParams.
    exit_reminder — shiitake browning's cold-water soak) logs that step as a
    ``phase_exit_reminder`` session event alongside the phase change, so the
    timeline and transcript record when the soak was due."""
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT species_profile_id, current_phase FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    profile = await get_profile(row["species_profile_id"])
    if error := phase_error(data.phase, profile):
        raise InvalidPhaseError(error)
    snapshot = _params_snapshot(profile, data.phase)
    leaving = row["current_phase"]
    reminder = (profile.phase_exit_reminder(leaving)
                if profile is not None and _moves_forward(leaving, data.phase) else None)

    async with get_db() as db:
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
        await db.execute(
            "UPDATE sessions SET current_phase = ? WHERE id = ?",
            (data.phase, session_id),
        )
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


async def add_note(session_id: int, data: NoteCreate) -> dict:
    async with get_db() as db:
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


_PINK_OYSTER_ID = "pink_oyster"
_PINK_OYSTER_SCIENTIFIC = "pleurotus djamor"


async def _harvest_needs_immediate_processing(species_id: str | None) -> bool:
    """Pink oyster (Pleurotus djamor) dies below 40°F — a harvest can't go in the
    fridge. CLAUDE.md §4b makes the post-harvest notice mandatory. Matches the
    built-in id in either spelling and any custom profile of the same species."""
    if not species_id:
        return False
    if _PINK_OYSTER_ID in species_id_candidates(species_id):
        return True
    profile = await get_profile(species_id)
    return bool(profile and profile.scientific_name.lower().startswith(_PINK_OYSTER_SCIENTIFIC))


async def add_harvest(session_id: int, data: HarvestCreate) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT species_profile_id FROM sessions WHERE id = ?", (session_id,)
        )
        srow = await cursor.fetchone()
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
    if srow and await _harvest_needs_immediate_processing(srow["species_profile_id"]):
        await pink_oyster_harvest()
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
_CHAMBER_IDS = "(SELECT value FROM json_each(:ids))"
_CHAMBER_SESSION_SQL = (
    # 1. bound to it by sessions.chamber_id;
    "SELECT * FROM sessions WHERE status = 'active' AND chamber_id IN " + _CHAMBER_IDS +
    " ORDER BY created_at DESC, id DESC LIMIT 1",
    # 2. linked by chambers.active_session_id (and bound to no chamber);
    "SELECT * FROM sessions WHERE status = 'active' AND chamber_id IS NULL "
    "AND id IN (SELECT active_session_id FROM chambers WHERE id IN " + _CHAMBER_IDS + ")"
    " ORDER BY created_at DESC, id DESC LIMIT 1",
    # 3. the newest session bound to no chamber and linked from no OTHER one.
    "SELECT * FROM sessions WHERE status = 'active' AND chamber_id IS NULL "
    "AND id NOT IN (SELECT active_session_id FROM chambers "
    "WHERE active_session_id IS NOT NULL AND id NOT IN " + _CHAMBER_IDS + ")"
    " ORDER BY created_at DESC, id DESC LIMIT 1",
)


# The grow a node listed in NO chamber belongs to (see
# get_active_session_for_chambers([])), most specific first.
_UNCHAMBERED_SESSION_SQL = (
    # 1. the newest session bound to no existing chamber — the single-closet
    #    grow, and exactly the one telemetry.service.active_session_for_node
    #    tags such a node's readings with;
    "SELECT * FROM sessions WHERE status = 'active' "
    "AND (chamber_id IS NULL OR chamber_id NOT IN (SELECT id FROM chambers))"
    " ORDER BY created_at DESC, id DESC LIMIT 1",
    # 2. else, when every active session is bound to ONE chamber, its newest:
    #    the node can only be that grow's (its chamber's node list is just
    #    incomplete). Grows in two chambers are ambiguous — neither is picked.
    "SELECT * FROM sessions WHERE status = 'active' "
    "AND (SELECT COUNT(DISTINCT chamber_id) FROM sessions WHERE status = 'active') = 1"
    " ORDER BY created_at DESC, id DESC LIMIT 1",
)


async def get_active_session_for_chambers(chamber_ids: Sequence[int]) -> dict | None:
    """The active session the given chamber(s) run, or None.

    In order: an active session bound to one of them by sessions.chamber_id;
    else the one a chamber's active_session_id links (PATCH /api/chambers
    used to set only that link); else the newest active session bound to NO
    chamber and linked from no other chamber — a pre-migration session, or one
    an API / cloud session_start created without a chamber_id. Never another
    chamber's grow: two chambers run side by side.

    With no chamber ids (a node listed in no chamber): the newest session
    bound to no chamber (the single closet); else the grow of the only chamber
    with active sessions; else None — never a guess between two chambers.

    This is THE per-node session rule (CLAUDE.md §12). The ingest tagger
    telemetry.service.active_session_for_node is its strict subset: whenever
    the tagger names a session for a live reading this names the same one
    (the tagger also skips sessions created after a replayed reading's
    timestamp); this also resolves
    the unbound cases (a legacy chamber link, a chamberless session on a
    chambered node, a single chamber's incomplete node list) so such a grow
    stays managed.
    """
    ids = [int(i) for i in chamber_ids]
    if ids:
        queries, params = _CHAMBER_SESSION_SQL, {"ids": json.dumps(ids)}
    else:
        queries, params = _UNCHAMBERED_SESSION_SQL, {}
    async with get_db() as db:
        for sql in queries:
            cursor = await db.execute(sql, params)
            row = await cursor.fetchone()
            if row:
                return dict(row)
    return None


async def get_active_session_for_node(node_id: str) -> dict | None:
    """The active session a node's readings (or camera frames) belong to: its
    chamber's grow when the node is listed in a chamber, else the unambiguous
    chamberless grow (see get_active_session_for_chambers)."""
    chambers = await chambers_for_node(node_id)
    return await get_active_session_for_chambers([c["id"] for c in chambers])


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


# Lighting scene a session-less closet is parked in — the same scene the
# "Photoperiod — Lights Off" rule publishes.
_SESSION_END_SCENE = "colonization_dark"


def _is_held(held: set[tuple[str, str | None]], targets: set[str], channel: str | None) -> bool:
    """Mirror of the engine's is_overridden(): a hold on the exact channel or a
    whole-target hold, on either the rule's placeholder or its resolved node."""
    return any((t, channel) in held or (t, None) in held for t in targets)


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


async def _chamber_left_idle_by(session_id: int) -> list[str] | None:
    """The node ids of the chamber `session_id` was bound to, when no active
    grow runs that chamber any more (get_active_session_for_chambers — so an
    unbound session its nodes would drive keeps it busy); else None."""
    async with get_db() as db:
        cursor = await db.execute("SELECT chamber_id FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
    if row is None or row["chamber_id"] is None:
        return None
    chamber = await get_chamber(row["chamber_id"])
    if chamber is None or not chamber["node_ids"]:
        return None
    if await get_active_session_for_chambers([chamber["id"]]) is not None:
        return None
    return [str(n) for n in chamber["node_ids"]]


async def _safe_actuators_after_session_end(session_id: int) -> list[dict] | None:
    """Command automation-driven actuators OFF once no active session remains.

    With no active session the engine runs only the life-safety rules (e.g.
    the CO2 Hard Ceiling), so whatever the grow's rules last switched ON — a
    cooler plug from "Pre-cool for Hot Forecast" (no safety_max_on), the
    fruiting light scene — would otherwise stay ON indefinitely after the grow
    ends. Every actuator an automation rule can switch ON gets an explicit OFF
    (lights go to the dark scene), except those under an operator's manual
    hold. Vendor-integration actions have no generic OFF and are left alone.
    Each OFF that went out is reported to the actuator-off listeners (the
    engine's safety-ceiling bookkeeping).

    While another session is still active the engine keeps driving the
    hardware for it and a blanket OFF would fight it, so: a grow bound to a
    chamber whose own nodes no remaining grow runs (another chamber's grow is
    still active) safes only the channels / scenes of that chamber's listed
    nodes — never a plug (plugs belong to no chamber) nor another chamber's
    or an unlisted node; otherwise safing is skipped. Returns the
    per-actuator results, or None when skipped.
    """
    scope: list[str] | None = None
    if await get_active_session() is not None:
        scope = await _chamber_left_idle_by(session_id)
        if not scope:
            return None

    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data "
            "FROM automation_rules ORDER BY priority DESC, id"
        )
        rules = [deserialize_rule_row(r) for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT target, channel FROM manual_overrides "
            "WHERE locked = 1 AND (expires_at IS NULL OR expires_at >= ?)",
            (now,),
        )
        held = {(r["target"], r["channel"]) for r in await cursor.fetchall()}

    results: list[dict] = []
    seen: set[tuple[str, str | None, str]] = set()
    for rule in rules:
        action = rule.get("action") or {}
        target = action.get("target")
        channel = action.get("channel")
        if not target or action.get("vendor_slug") or action.get("state") != "on":
            continue
        # Same target resolution as the engine's _fire_rule (chamber-scoped
        # when this chamber's grow ended), so the OFF lands on the node/plug
        # the ON went to.
        resolved = await resolve_node_target(target, scope) or target
        if _is_held(held, {target, resolved}, channel):
            continue
        if await is_plug_target(resolved):
            if scope is not None:
                continue  # a plug may serve the grow that is still running
            kind, key_channel = "plug", None
        elif scope is not None and resolved not in scope:
            continue  # another chamber's (or an unlisted) node
        elif channel:
            kind, key_channel = "channel", channel
        elif action.get("scene"):
            kind, key_channel = "scene", None
        else:
            continue  # cmd/config carries no on/off state
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
                if not await target_is_present(resolved):
                    continue  # no paired plug for this role — nothing to switch
                published = await send_plug_command(resolved, "off")
            elif kind == "channel":
                published = await mqtt_publish(
                    f"sporeprint/{resolved}/cmd/{channel}",
                    {"state": "off", "reason": "session_ended"},
                )
            else:
                published = await mqtt_publish(
                    f"sporeprint/{resolved}/cmd/scene",
                    {"state": "off", "scene": _SESSION_END_SCENE},
                )
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


async def _end_session(session_id: int, status: str, event_type: str, description: str) -> dict | None:
    """Close a session: status + open phase + chamber link + event in ONE
    transaction, then safe the actuators the engine will no longer manage."""
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        if await cursor.fetchone() is None:
            return None
        if status == "completed":
            await db.execute(
                "UPDATE sessions SET status = 'completed', current_phase = 'complete', completed_at = ? "
                "WHERE id = ?",
                (now, session_id),
            )
        else:
            await db.execute(
                "UPDATE sessions SET status = ?, completed_at = ? WHERE id = ?",
                (status, now, session_id),
            )
        await db.execute(
            "UPDATE phase_history SET exited_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (now, session_id),
        )
        # The chamber no longer hosts a live grow.
        await db.execute(
            "UPDATE chambers SET active_session_id = NULL WHERE active_session_id = ?",
            (session_id,),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, event_type, "user", description),
        )
        await db.commit()
    await _safe_actuators_after_session_end(session_id)
    await _notify_session_changed(session_id)
    return await get_session(session_id)


async def abort_session(session_id: int) -> dict | None:
    return await _end_session(session_id, "aborted", "session_aborted", "Session aborted")


async def complete_session(session_id: int) -> dict | None:
    return await _end_session(session_id, "completed", "session_completed", "Session completed")


def _exit_reminder_message(phase: str, days_in_phase: int, params: PhaseParams) -> str:
    """The daily phase check for a phase that owes a manual step on exit."""
    lo, hi = (int(d) for d in params.expected_duration_days)
    label = phase.replace("_", " ")
    status = (f"Day {days_in_phase} of {label} — past its {lo}-{hi} d window."
              if days_in_phase > hi else f"Day {days_in_phase} of {label} ({lo}-{hi} d expected).")
    return f"{status} Once it is complete: {params.exit_reminder} Then advance the session."


async def check_phase_reminders(now: float | None = None) -> int:
    """INFO-tier nudge for each active session that has overrun its phase.

    Fires phase_reminder() when days in the current phase exceed the species'
    expected_duration_days max (the notifier dedups per session+phase). A phase
    that owes a manual step on exit (PhaseParams.exit_reminder — shiitake
    browning's cold-water soak) is nudged from its expected MINIMUM instead,
    with the step spelled out, since that is when the operator should start
    checking whether it is done. Meant to be run periodically (e.g. daily) by a
    background task. Returns the number of reminders sent.
    """
    now = time.time() if now is None else now
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT s.id, s.name, s.species_profile_id, s.current_phase, ph.entered_at "
            "FROM sessions s JOIN phase_history ph "
            "  ON ph.session_id = s.id AND ph.exited_at IS NULL AND ph.phase = s.current_phase "
            "WHERE s.status = 'active'"
        )
        rows = [dict(r) for r in await cursor.fetchall()]

    sent = 0
    for row in rows:
        profile = await get_profile(row["species_profile_id"])
        if profile is None:
            continue
        try:
            params = profile.phases.get(GrowPhase(row["current_phase"]))
        except ValueError:
            continue
        if params is None:
            continue
        expected_min = int(params.expected_duration_days[0])
        expected_max = int(params.expected_duration_days[1])
        days_in_phase = int((now - row["entered_at"]) // 86400)
        if params.exit_reminder and days_in_phase >= expected_min:
            await notify_info(
                f"Phase check — {row['name']}",
                _exit_reminder_message(row["current_phase"], days_in_phase, params),
                dedup_key=f"phase-exit:{row['id']}:{row['current_phase']}",
            )
            sent += 1
        elif days_in_phase > expected_max:
            await phase_reminder(row["name"], row["current_phase"], days_in_phase, expected_max)
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
    functions verbatim. Returns the resulting session dict.
    """
    if channel == "session_start":
        return await create_session(SessionCreate(**payload))
    if channel == "session_end":
        return await complete_session(payload["session_id"])
    raise ValueError(f"unknown session command channel: {channel!r}")


# Strategy 3 of resolve_session_node_id: the node listed in no chamber with
# the most samples (raw rows, plus rollup rows weighted by their sample count)
# inside [from_ts, to_ts], for :sensor when given.
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
         (raw telemetry is kept 7 days): the node in no chamber that reported
         the most data during the session — raw rows or rollups — which is
         exactly the node set the ingest tagger assigns to a chamberless grow.

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
            # 3. Chamberless (or its chamber was deleted): the unassigned node
            # with the most data in the session's window.
            cursor = await db.execute(_CHAMBERLESS_SESSION_NODE_SQL, {
                "sensor": sensor,
                "from_ts": srow["created_at"] or 0,
                "to_ts": srow["completed_at"] or time.time(),
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
        # node_type/roles resolution in app.cloud.service._resolve_node_id_by_type.
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


_VOLUME_PATTERN = re.compile(r"([\d.]+)\s*(quarts?|qt|liters?|litres?|l|gallons?|gal)\b", re.IGNORECASE)

_TO_LITERS = {
    "quart": 0.946353, "quarts": 0.946353, "qt": 0.946353,
    "liter": 1.0, "liters": 1.0, "litre": 1.0, "litres": 1.0, "l": 1.0,
    "gallon": 3.78541, "gallons": 3.78541, "gal": 3.78541,
}

# Approximate dry substrate weight: ~300g per liter
_DRY_SUBSTRATE_G_PER_LITER = 300.0


def _parse_volume_to_liters(volume_str: str | None) -> float | None:
    """Parse a volume string like '5 quarts' or '10 liters' into liters."""
    if not volume_str:
        return None
    m = _VOLUME_PATTERN.search(volume_str)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2).lower()
    factor = _TO_LITERS.get(unit)
    if factor is None:
        return None
    return value * factor


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

        # Biological Efficiency = (total fresh weight / dry substrate weight) * 100
        volume_liters = _parse_volume_to_liters(session.get("substrate_volume"))
        if volume_liters and volume_liters > 0:
            dry_substrate_g = volume_liters * _DRY_SUBSTRATE_G_PER_LITER
            biological_efficiency = round((total_wet / dry_substrate_g) * 100, 1) if dry_substrate_g > 0 else None
        else:
            biological_efficiency = None

        # Species averages via SQL aggregate (instead of loading all rows)
        species_id = session["species_profile_id"]
        cursor = await db.execute(
            """SELECT COUNT(*) as cnt, AVG(total_wet_yield_g) as avg_yield,
               MAX(total_wet_yield_g) as best_yield
               FROM sessions WHERE species_profile_id = ? AND status = 'completed'
               AND total_wet_yield_g > 0""",
            (species_id,),
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
        }


# ── Harvest Drying Tracker ───────────────────────────────────────


async def add_drying_log(session_id: int, harvest_id: int, weight_g: float) -> dict | None:
    """Add a drying log weight entry for a harvest. Returns drying progress."""
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
        await db.commit()

    progress = await get_drying_progress(session_id, harvest_id)
    if progress and progress.get("target_reached"):
        from ..notifications.service import notify_info
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

        # Get all drying log entries
        cursor = await db.execute(
            "SELECT * FROM drying_log WHERE harvest_id = ? ORDER BY timestamp",
            (harvest_id,),
        )
        entries = [dict(r) for r in await cursor.fetchall()]

        current_weight = entries[-1]["weight_g"] if entries else fresh_weight

        if fresh_weight > 0:
            moisture_loss_pct = round((1 - current_weight / fresh_weight) * 100, 1)
            dry_wet_ratio = round(current_weight / fresh_weight, 4)
        else:
            moisture_loss_pct = 0.0
            dry_wet_ratio = 1.0

        # Cracker dry target: >= 90% moisture loss
        target_reached = moisture_loss_pct >= 90.0

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
        start_idx = _PHASE_ORDER.index(start_phase)
    except ValueError:
        return timedelta(0)
    for planned in cycle.phases:
        try:
            idx = _PHASE_ORDER.index(planned.phase)
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

            # Session start event
            ev = Event()
            ev.add("summary", f"{name} — Session Started")
            ev.add("dtstart", created_dt)
            ev.add("dtend", created_dt)
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
                ev.add("dtend", ph_dt)
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
                ev.add("dtend", h_dt)
                ev.add("description", f"Flush #{h['flush_number']}: {weight}g wet")
                ev["uid"] = f"session-{sid}-harvest-{h['id']}@sporeprint"
                cal.add_component(ev)

            # Expected future events for active sessions. Dates come from the
            # planner's species-derived cycle proposer (propose_cycle), anchored
            # at this session's actual inoculation date (its creation date when no
            # inoculation date was recorded). Driving the projection off the real
            # per-phase durations keeps it consistent with /planner/propose and
            # inherits get_profile's tolerant species-id resolution.
            if session["status"] == "active":
                from ..species.service import get_profile as _get_species_profile
                from ..planner.service import propose_cycle

                profile = await _get_species_profile(session["species_profile_id"])
                if profile and profile.phases:
                    anchor = _parse_inoculation_date(session.get("inoculation_date")) or created_dt.date()
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
                        current_idx = _PHASE_ORDER.index(current_phase)
                    except ValueError:
                        current_idx = -1

                    # Only phases still ahead of the current one get an "expected"
                    # marker; phases already entered carry their real
                    # phase-history events above.
                    for future_phase in _PHASE_ORDER[current_idx + 1:]:
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
                ev.add("dtend", completed_dt)
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
) -> list[str]:
    """Generate rule-based recommendations from session data for the PDF report."""
    recs = []

    # Biological efficiency check
    volume_liters = _parse_volume_to_liters(session.get("substrate_volume"))
    total_wet = session.get("total_wet_yield_g") or 0.0
    if volume_liters and volume_liters > 0:
        dry_substrate_g = volume_liters * _DRY_SUBSTRATE_G_PER_LITER
        be = (total_wet / dry_substrate_g) * 100 if dry_substrate_g > 0 else 0
        if be < 50:
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

    # Flush count vs species expectation. Match tolerantly across the
    # hyphen/underscore drift: the stored id is hyphenated ("lions-mane") while
    # BUILTIN_PROFILES is keyed by the underscored id ("lions_mane").
    species_flush_typical = None
    from ..species.profiles import BUILTIN_PROFILES
    species_id = session.get("species_profile_id")
    id_candidates = set(species_id_candidates(species_id)) if species_id else set()
    for p in BUILTIN_PROFILES:
        if p.id in id_candidates:
            species_flush_typical = p.flush_count_typical
            break
    if species_flush_typical and len(flush_map) < species_flush_typical:
        recs.append(
            f"Fewer flushes ({len(flush_map)}) than typical for this species "
            f"({species_flush_typical}) — check hydration and rest soak technique"
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
            "SELECT analysis_claude FROM vision_frames "
            "WHERE session_id = ? AND analysis_claude IS NOT NULL",
            (session_id,),
        )
        vision_summaries = [dict(r)["analysis_claude"] for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT * FROM session_events "
            "WHERE session_id = ? AND type LIKE '%contam%' ORDER BY timestamp",
            (session_id,),
        )
        contam_events = [dict(r) for r in await cursor.fetchall()]

    recommendations = _generate_recommendations(
        session, harvests, phase_history, contam_events,
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
    md.append(f"| Total Wet Yield | {session.get('total_wet_yield_g', 0) or 0}g |")
    md.append(f"| Total Dry Yield | {session.get('total_dry_yield_g', 0) or 0}g |")
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
        for idx, summary in enumerate(vision_summaries[:10], 1):
            text = summary.strip().replace("\n", " ")
            if len(text) > 300:
                text = text[:297] + "..."
            md.append(f"{idx}. {text}")
        md.append("")

    # Contamination events
    if contam_events:
        md.append("## Contamination Events\n")
        md.append("| Time | Description |")
        md.append("|------|-------------|")
        for ev in contam_events:
            ev_dt = _ts_to_dt(ev.get("timestamp"))
            ev_time = ev_dt.strftime("%Y-%m-%d %H:%M") if ev_dt else "?"
            desc = ev.get("description", "")[:150] or ev.get("type", "")
            md.append(f"| {ev_time} | {desc} |")
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
