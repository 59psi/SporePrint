import csv
import io
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone


from ..db import get_db
from ..species.profiles import canonical_species_id, species_id_candidates
from ..species.service import get_profile
from .models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate

_PHASE_ORDER = [
    "agar", "liquid_culture", "grain_colonization",
    "substrate_colonization", "cold_storage", "primordia_induction",
    "fruiting", "rest", "complete",
]


async def create_session(data: SessionCreate) -> dict:
    now = time.time()
    # Normalize to the hyphenated UI spelling so the stored id matches what the
    # cloud/mobile surfaces send and locally match on, regardless of whether the
    # caller submitted the hyphenated or underscored form. get_profile() stays
    # tolerant either way. See app.species.profiles.canonical_species_id.
    species_id = canonical_species_id(data.species_profile_id)
    async with get_db() as db:
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
            "INSERT INTO phase_history (session_id, phase, entered_at, trigger) VALUES (?, ?, ?, ?)",
            (session_id, data.current_phase, now, "session_created"),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, "session_created", "user", f"Session '{data.name}' created"),
        )
        await db.commit()
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
                row = dict(r)
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
        session["phase_history"] = [dict(r) for r in await cursor.fetchall()]
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
    return await get_session(session_id)


_COLONIZATION_PHASES = {"agar", "liquid_culture", "grain_colonization", "substrate_colonization"}
# Bulk-substrate containers that fruit in place (a bag is cut open; a tub/tray
# is opened to air). Everything else — colonized agar / liquid culture / grain
# spawn — is pulled and parked in cold storage until used. monotub/tray were
# missing here, which wrongly routed them to cold storage; they are bulk
# substrate that fruits, matching the session-wizard container selector.
_FRUITING_CONTAINERS = {"grow_bag", "bag", "bulk_bag", "monotub", "tray"}


def suggested_next_phase(current_phase: str, container_type: str | None,
                         more_flushes_expected: bool = True) -> str:
    """The product spec's forks, as a suggestion the UI offers on 'advance phase'.

    Two forks:
    1. After colonization: BULK SUBSTRATE (grow bag / monotub / tray) goes on to
       fruit; colonized agar / LC / grain is pulled and parked in the fridge.
           bulk substrate → primordia_induction
           agar/LC/grain  → cold_storage
    2. The flush loop: a bag gives 2-3 flushes. After a flush you REST, then go
       back to FRUITING for the next one — until the bag is spent, then COMPLETE.
           rest → fruiting   (if more flushes expected)
           rest → complete   (bag is spent)
    Everything else follows the ordinary linear order.
    """
    ct = (container_type or "").lower()
    if current_phase in _COLONIZATION_PHASES:
        return "primordia_induction" if ct in _FRUITING_CONTAINERS else "cold_storage"
    if current_phase == "rest":
        return "fruiting" if more_flushes_expected else "complete"
    # Non-fork transitions follow the ordinary linear progression.
    from ..species.models import GrowPhase
    order = [p.value for p in GrowPhase]
    try:
        i = order.index(current_phase)
        return order[i + 1] if i + 1 < len(order) else "complete"
    except ValueError:
        return "complete"


async def advance_phase(session_id: int, data: PhaseAdvance) -> dict | None:
    now = time.time()
    async with get_db() as db:
        # Close current phase
        await db.execute(
            "UPDATE phase_history SET exited_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (now, session_id),
        )
        # Open new phase
        await db.execute(
            "INSERT INTO phase_history (session_id, phase, entered_at, trigger) VALUES (?, ?, ?, ?)",
            (session_id, data.phase, now, data.trigger),
        )
        await db.execute(
            "UPDATE sessions SET current_phase = ? WHERE id = ?",
            (data.phase, session_id),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description, data) VALUES (?, ?, ?, ?, ?)",
            (session_id, "phase_change", data.trigger, f"Phase advanced to {data.phase}",
             json.dumps({"phase": data.phase})),
        )
        await db.commit()
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


async def add_harvest(session_id: int, data: HarvestCreate) -> dict:
    async with get_db() as db:
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
        return dict(await cursor.fetchone())


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


async def get_events(session_id: int, limit: int | None = None) -> list[dict]:
    """Session events in chronological order.

    `limit` keeps the NEWEST N while preserving the ascending contract
    (transcripts/reports read the full history; feeds pass a cap).
    """
    async with get_db() as db:
        if limit is None:
            cursor = await db.execute(
                "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp",
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


async def abort_session(session_id: int) -> dict | None:
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET status = 'aborted', completed_at = ? WHERE id = ?",
            (now, session_id),
        )
        await db.execute(
            "UPDATE phase_history SET exited_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (now, session_id),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, "session_aborted", "user", "Session aborted"),
        )
        await db.commit()
    return await get_session(session_id)


async def complete_session(session_id: int) -> dict | None:
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET status = 'completed', current_phase = 'complete', completed_at = ? WHERE id = ?",
            (now, session_id),
        )
        await db.execute(
            "UPDATE phase_history SET exited_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (now, session_id),
        )
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description) VALUES (?, ?, ?, ?)",
            (session_id, "session_completed", "user", "Session completed"),
        )
        await db.commit()
    return await get_session(session_id)


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


async def resolve_session_node_id(session_id: int, sensor: str | None = None) -> str | None:
    """Resolve which hardware node's telemetry backs a session.

    Backs the per-session telemetry endpoint, which previously hardcoded
    ``climate-01`` and so returned the wrong node's series (or nothing) for any
    node not named that, and for every session whose chamber is a different node.

    Two strategies, in order:
      1. Session-tagged telemetry — if any ``telemetry_readings`` rows carry this
         ``session_id``, use the node that produced them (scoped to ``sensor``
         when given, so a session spanning several nodes resolves to the one that
         actually reports the requested sensor). This is authoritative.
      2. Chamber topology — otherwise map session → ``chamber_id`` → the
         chamber's ``node_ids`` and pick the climate/sensor node (``node_type``
         'climate'/'sensor', or a node whose ``roles`` include one of those),
         falling back to the chamber's first node.

    Returns None when neither strategy yields a node (unknown session, or a
    session with no chamber and no tagged telemetry) so the caller can return an
    empty series.
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
            "SELECT chamber_id FROM sessions WHERE id = ?", (session_id,)
        )
        srow = await cursor.fetchone()
        if not srow or srow["chamber_id"] is None:
            return None

        cursor = await db.execute(
            "SELECT node_ids FROM chambers WHERE id = ?", (srow["chamber_id"],)
        )
        crow = await cursor.fetchone()
        if not crow:
            return None
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
                        ev.add("dtstart", proposed.start_date)
                        ev["uid"] = f"session-{sid}-expected-{future_phase}@sporeprint"
                        cal.add_component(ev)

                    # Expected harvest = end of the fruiting phase in the plan.
                    if cycle.harvest_date:
                        ev = Event()
                        ev.add("summary", f"{name} — Expected Harvest")
                        ev.add("dtstart", cycle.harvest_date)
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
    md.append(f"# SporePrint Grow Report\n")
    md.append(f"| Field | Value |")
    md.append(f"|-------|-------|")
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
            datetime.utcfromtimestamp(h["timestamp"]).isoformat() if h.get("timestamp") else "",
            h.get("notes", ""),
        ])
    return buf.getvalue()
