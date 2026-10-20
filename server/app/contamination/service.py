import logging
import math
import time
from collections.abc import Awaitable, Callable

from ..db import check_references, get_db
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


async def insert_event(
    db,
    *,
    source: str,
    session_id: int | None = None,
    chamber_id: int | None = None,
    contamination_type: str | None = None,
    confidence: float | None = None,
    frame_id: int | None = None,
    notes: str | None = None,
    detected_at: float | None = None,
) -> int:
    """Insert a contamination event inside the caller's open transaction (no
    commit) and return its id. Once the caller has committed,
    publish_event(id) hands the row to the recorded-event listeners."""
    ts = detected_at if detected_at is not None else time.time()
    cursor = await db.execute(
        """INSERT INTO contamination_events
           (session_id, chamber_id, detected_at, source, contamination_type,
            confidence, frame_id, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, chamber_id, ts, source, contamination_type,
         confidence, frame_id, notes),
    )
    return cursor.lastrowid


async def publish_event(event_id: int) -> dict:
    """The committed event row, after telling the recorded-event listeners."""
    event = await get_event(event_id)
    for listener in list(_recorded_listeners):
        try:
            await listener(event)
        except Exception as e:  # a sync failure must never fail the record itself
            log.warning("contamination listener failed for event %s: %s", event_id, e)
    return event


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
    async with get_db() as db:
        event_id = await insert_event(
            db, source=source, session_id=session_id, chamber_id=chamber_id,
            contamination_type=contamination_type, confidence=confidence,
            frame_id=frame_id, notes=notes, detected_at=detected_at,
        )
        await db.commit()
    return await publish_event(event_id)


async def check_event_references(
    *, session_id: int | None = None, chamber_id: int | None = None,
) -> None:
    """Raise db.UnknownReferenceError for an unknown session or chamber an
    event would be linked to (before the identify route spends a Claude call
    on an upload whose event could not be stored)."""
    async with get_db() as db:
        await check_references(
            db, session_id=("sessions", session_id), chamber_id=("chambers", chamber_id),
        )


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
    """Log a manual mark. Raises db.UnknownReferenceError for an unknown
    session, chamber or frame (the route's 422; the insert failed on the
    foreign key with a 500)."""
    async with get_db() as db:
        await check_references(
            db, session_id=("sessions", data.session_id),
            chamber_id=("chambers", data.chamber_id),
            frame_id=("vision_frames", data.frame_id),
        )
        event_id = await insert_event(
            db,
            source="manual",
            session_id=data.session_id,
            chamber_id=data.chamber_id,
            contamination_type=data.contamination_type,
            confidence=data.confidence,
            frame_id=data.frame_id,
            notes=data.notes,
        )
        await db.commit()
    return await publish_event(event_id)


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


def as_confidence(value) -> float | None:
    """A model-reported confidence as 0.0-1.0, or None when it is not a finite
    number. A percentage-style value ("85") reads as 0.85. Shared by the
    vision detections and the photo identify, so both store one scale."""
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(conf):
        return None
    if 1.0 < conf <= 100.0:  # percentage-style ("85")
        conf /= 100.0
    return max(0.0, min(conf, 1.0))


def detection_from_identify(result) -> dict | None:
    """Type + confidence of an identify response IF it is a positive
    detection, else None. Never raises.

    The identify contract: `contamination_detected` is a JSON boolean and the
    first entry of `contaminants` carries `classification` + `confidence`
    (0.0-1.0). An off-contract reply degrades instead of failing a paid
    identification with a 500: only true (or the string "true") is a
    detection — a string "false" is truthy — the first object entry of the
    list is read (a bare name string counts as its classification), and the
    confidence is put on the 0-1 scale (as_confidence).
    """
    if not isinstance(result, dict):
        return None
    detected = result.get("contamination_detected")
    if isinstance(detected, str):
        detected = detected.strip().lower() == "true"
    if detected is not True:
        return None
    contaminants = result.get("contaminants")
    if isinstance(contaminants, (dict, str)):
        contaminants = [contaminants]
    elif not isinstance(contaminants, list):
        contaminants = []
    first = next((c for c in contaminants if isinstance(c, dict)), None)
    if first is None:
        name = next((c for c in contaminants if isinstance(c, str) and c.strip()), None)
        first = {"classification": name} if name else {}
    classification = first.get("classification")
    return {
        "contamination_type": (classification.strip() or None)
        if isinstance(classification, str) else None,
        "confidence": as_confidence(first.get("confidence")),
    }
