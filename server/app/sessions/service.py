import json
import re
import time

from ..db import get_db
from .models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate


async def create_session(data: SessionCreate) -> dict:
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO sessions (name, species_profile_id, substrate, substrate_volume,
               substrate_prep_notes, inoculation_date, inoculation_method, spawn_source,
               current_phase, tub_number, shelf_number, shelf_side, growth_form, pinning_tek)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.name, data.species_profile_id, data.substrate, data.substrate_volume,
             data.substrate_prep_notes, data.inoculation_date, data.inoculation_method,
             data.spawn_source, data.current_phase, data.tub_number, data.shelf_number,
             data.shelf_side, data.growth_form, data.pinning_tek),
        )
        session_id = cursor.lastrowid

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

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [session_id]

    async with get_db() as db:
        await db.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)
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

        # Species averages from all completed sessions with same species
        species_id = session["species_profile_id"]
        cursor = await db.execute(
            "SELECT id, total_wet_yield_g FROM sessions WHERE species_profile_id = ? AND status = 'completed'",
            (species_id,),
        )
        species_sessions = [dict(r) for r in await cursor.fetchall()]
        species_session_count = len(species_sessions)

        if species_session_count > 0:
            yields = [s["total_wet_yield_g"] or 0.0 for s in species_sessions]
            species_avg_yield_g = round(sum(yields) / len(yields), 1)
            species_best_yield_g = round(max(yields), 1)
        else:
            species_avg_yield_g = None
            species_best_yield_g = None

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

    return await get_drying_progress(session_id, harvest_id)


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
