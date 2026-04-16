import csv
import io
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone


from ..db import get_db
from .models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate

_PHASE_ORDER = [
    "agar", "liquid_culture", "grain_colonization",
    "substrate_colonization", "primordia_induction",
    "fruiting", "rest", "complete",
]


async def create_session(data: SessionCreate) -> dict:
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO sessions (name, species_profile_id, substrate, substrate_volume,
               substrate_prep_notes, inoculation_date, inoculation_method, spawn_source,
               current_phase, tub_number, shelf_number, shelf_side, growth_form, pinning_tek,
               chamber_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.name, data.species_profile_id, data.substrate, data.substrate_volume,
             data.substrate_prep_notes, data.inoculation_date, data.inoculation_method,
             data.spawn_source, data.current_phase, data.tub_number, data.shelf_number,
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


async def list_sessions(status: str | None = None, species: str | None = None) -> list[dict]:
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
        return [dict(r) for r in await cursor.fetchall()]


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


async def update_session(session_id: int, data: SessionUpdate) -> dict | None:
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_session(session_id)

    async with get_db() as db:
        for col, val in updates.items():
            # Each column is from the Pydantic model — not user input
            await db.execute(
                {
                    "name": "UPDATE sessions SET name = ? WHERE id = ?",
                    "substrate": "UPDATE sessions SET substrate = ? WHERE id = ?",
                    "substrate_volume": "UPDATE sessions SET substrate_volume = ? WHERE id = ?",
                    "substrate_prep_notes": "UPDATE sessions SET substrate_prep_notes = ? WHERE id = ?",
                    "inoculation_date": "UPDATE sessions SET inoculation_date = ? WHERE id = ?",
                    "inoculation_method": "UPDATE sessions SET inoculation_method = ? WHERE id = ?",
                    "spawn_source": "UPDATE sessions SET spawn_source = ? WHERE id = ?",
                    "tub_number": "UPDATE sessions SET tub_number = ? WHERE id = ?",
                    "shelf_number": "UPDATE sessions SET shelf_number = ? WHERE id = ?",
                    "shelf_side": "UPDATE sessions SET shelf_side = ? WHERE id = ?",
                    "growth_form": "UPDATE sessions SET growth_form = ? WHERE id = ?",
                    "pinning_tek": "UPDATE sessions SET pinning_tek = ? WHERE id = ?",
                }[col],
                (val, session_id),
            )
        await db.commit()
    return await get_session(session_id)


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


async def get_active_session() -> dict | None:
    """Return the most recent active session, or None."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_events(session_id: int) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp", (session_id,)
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

            # Expected future events for active sessions
            if session["status"] == "active":
                from ..species.service import get_profile as _get_species_profile

                profile = await _get_species_profile(session["species_profile_id"])
                if profile and profile.phases:
                    current_phase = session.get("current_phase", "")
                    last_phase_entry = session["created_at"]
                    for p in phases:
                        if p["phase"] == current_phase and p.get("entered_at"):
                            last_phase_entry = p["entered_at"]

                    try:
                        current_idx = _PHASE_ORDER.index(current_phase)
                    except ValueError:
                        current_idx = -1

                    predicted_time = last_phase_entry

                    for future_phase in _PHASE_ORDER[current_idx + 1:]:
                        if future_phase == "complete":
                            break
                        phase_params = profile.phases.get(future_phase)
                        if not phase_params:
                            continue
                        dur = phase_params.expected_duration_days
                        if dur and isinstance(dur, (list, tuple)) and len(dur) == 2:
                            avg_days = (dur[0] + dur[1]) / 2
                        else:
                            avg_days = 7
                        predicted_time += avg_days * 86400

                        ev = Event()
                        ev.add("summary", f"{name} — {future_phase.replace('_', ' ').title()} (Expected)")
                        ev.add("dtstart", datetime.utcfromtimestamp(predicted_time).date())
                        ev["uid"] = f"session-{sid}-expected-{future_phase}@sporeprint"
                        cal.add_component(ev)

                    # Expected harvest date (after fruiting phase)
                    fruiting_params = profile.phases.get("fruiting")
                    if fruiting_params:
                        fruiting_dur = fruiting_params.expected_duration_days
                        if fruiting_dur and isinstance(fruiting_dur, (list, tuple)) and len(fruiting_dur) == 2:
                            harvest_time = predicted_time + ((fruiting_dur[0] + fruiting_dur[1]) / 2) * 86400
                            ev = Event()
                            ev.add("summary", f"{name} — Expected Harvest")
                            ev.add("dtstart", datetime.utcfromtimestamp(harvest_time).date())
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

    # Flush count vs species expectation
    species_flush_typical = None
    from ..species.profiles import BUILTIN_PROFILES
    species_id = session.get("species_profile_id")
    for p in BUILTIN_PROFILES:
        if p.id == species_id:
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
