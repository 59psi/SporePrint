import time

from ..db import get_db
from .models import ContaminationEventCreate


async def record_event(
    *,
    source: str,
    session_id: int | None = None,
    chamber_id: int | None = None,
    contamination_type: str | None = None,
    confidence: float | None = None,
    frame_id: int | None = None,
    notes: str | None = None,
    detected_at: float | None = None,
) -> dict:
    """Insert a contamination event and return the persisted row."""
    ts = detected_at if detected_at is not None else time.time()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO contamination_events
               (session_id, chamber_id, detected_at, source, contamination_type,
                confidence, frame_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, chamber_id, ts, source, contamination_type,
             confidence, frame_id, notes),
        )
        await db.commit()
        event_id = cursor.lastrowid
    return await get_event(event_id)


async def get_event(event_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM contamination_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_events(
    session_id: int | None = None, chamber_id: int | None = None
) -> list[dict]:
    """Newest-first list of contamination events, optionally filtered."""
    query = "SELECT * FROM contamination_events WHERE 1=1"
    params: list = []
    if session_id is not None:
        query += " AND session_id = ?"
        params.append(session_id)
    if chamber_id is not None:
        query += " AND chamber_id = ?"
        params.append(chamber_id)
    query += " ORDER BY detected_at DESC, id DESC"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]


async def create_manual_event(data: ContaminationEventCreate) -> dict:
    return await record_event(
        source="manual",
        session_id=data.session_id,
        chamber_id=data.chamber_id,
        contamination_type=data.contamination_type,
        confidence=data.confidence,
        frame_id=data.frame_id,
        notes=data.notes,
    )


async def set_root_cause(event_id: int, root_cause: str) -> dict | None:
    """Stamp root_cause + timestamp on an event. Returns None if unknown id."""
    existing = await get_event(event_id)
    if not existing:
        return None
    async with get_db() as db:
        await db.execute(
            "UPDATE contamination_events "
            "SET root_cause = ?, root_cause_recorded_at = ? WHERE id = ?",
            (root_cause, time.time(), event_id),
        )
        await db.commit()
    return await get_event(event_id)


def detection_from_identify(result: dict) -> dict | None:
    """Extract type + confidence from an identify response IF it is a positive
    detection (contamination_detected == True), else None.

    Reads the identify contract's shape: the first entry of `contaminants`
    carries `classification` + `confidence`.
    """
    if not isinstance(result, dict) or not result.get("contamination_detected"):
        return None
    contaminants = result.get("contaminants") or []
    first = contaminants[0] if contaminants else {}
    return {
        "contamination_type": first.get("classification"),
        "confidence": first.get("confidence"),
    }
