import logging
import time
from collections.abc import Awaitable, Callable

from ..db import get_db
from .models import ContaminationEventCreate

log = logging.getLogger(__name__)

# Called with each newly recorded event row. The cloud connector registers one
# to send it to the cloud (app.cloud.session_sync); this module never imports
# the cloud package.
ContaminationListener = Callable[[dict], Awaitable[None]]
_recorded_listeners: list[ContaminationListener] = []


def add_contamination_listener(listener: ContaminationListener) -> None:
    """Register `listener` for newly recorded events (idempotent)."""
    if listener not in _recorded_listeners:
        _recorded_listeners.append(listener)


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
    event = await get_event(event_id)
    for listener in list(_recorded_listeners):
        try:
            await listener(event)
        except Exception as e:  # a sync failure must never fail the record itself
            log.warning("contamination listener failed for event %s: %s", event_id, e)
    return event


async def get_event(event_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM contamination_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_events(
    session_id: int | None = None,
    chamber_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Newest-first list of contamination events, optionally filtered.

    Capped (default 200) — the table grows for the life of the install.
    """
    query = "SELECT * FROM contamination_events WHERE 1=1"
    params: list = []
    if session_id is not None:
        query += " AND session_id = ?"
        params.append(session_id)
    if chamber_id is not None:
        query += " AND chamber_id = ?"
        params.append(chamber_id)
    query += " ORDER BY detected_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))

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
