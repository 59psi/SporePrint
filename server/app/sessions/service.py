import json
import time

from ..db import get_db
from .models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate


async def create_session(data: SessionCreate) -> dict:
    now = time.time()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO sessions (name, species_profile_id, substrate, substrate_volume,
               substrate_prep_notes, inoculation_date, inoculation_method, spawn_source,
               current_phase, growth_form, pinning_tek)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.name, data.species_profile_id, data.substrate, data.substrate_volume,
             data.substrate_prep_notes, data.inoculation_date, data.inoculation_method,
             data.spawn_source, data.current_phase, data.growth_form, data.pinning_tek),
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
