"""Grow sessions and contamination events → cloud.

The cloud fills its sessions, analytics, planner, chamber tiles and
contamination history from these, so without them a grow run on the Pi never
shows up there. Every change to a session (app.sessions.service's change
listener) sends that session's snapshot (``session_sync``), and every
contamination event the Pi records (app.contamination.service's listener)
is sent as it is recorded (``contamination_event``). Anything that could not
be sent is kept and resent on reconnect, and every connect also backfills
recent sessions and then recent events, so grows from before the link
existed reach the cloud as well.

The cloud keys each row by this Pi's local ids (``pi_session_id`` /
``pi_harvest_id`` / ``pi_event_id``) together with the authenticated device,
so a resend updates the same row.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from ..config import settings
from ..contamination import service as contamination_service
from ..db import get_db
from ..sessions import service as sessions_service
from ..species.service import get_profile
from . import service as cloud_service

log = logging.getLogger(__name__)

# Every connect resends the active sessions plus those created in the last
# year, newest first, capped.
BACKFILL_WINDOW_DAYS = 365
BACKFILL_MAX = 200

CONTAMINATION_BACKFILL_MAX = 500

# Pi detection sources → the cloud's contamination_events.detection_source.
_CLOUD_SOURCES = {"vision": "claude", "identify": "claude", "manual": "manual"}

# Sessions / contamination events not yet delivered.
_pending: set[int] = set()
_pending_contamination: set[int] = set()
# Sends started from the change listener (kept so they are not collected).
_inflight: set[asyncio.Task] = set()


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts is not None else None


async def build_session_snapshot(session_id: int) -> dict | None:
    """The ``session_sync`` payload for one session, or None if it is gone."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        session = dict(row)
        cursor = await db.execute(
            "SELECT id, flush_number, wet_weight_g, dry_weight_g, quality_rating, timestamp "
            "FROM harvests WHERE session_id = ? ORDER BY timestamp, id",
            (session_id,),
        )
        harvests = [dict(r) for r in await cursor.fetchall()]
        # The phase the session is in now (or ended in).
        cursor = await db.execute(
            "SELECT entered_at FROM phase_history WHERE session_id = ? "
            "ORDER BY entered_at DESC, id DESC LIMIT 1",
            (session_id,),
        )
        phase_row = await cursor.fetchone()
        chamber = None
        if session.get("chamber_id") is not None:
            cursor = await db.execute("SELECT name FROM chambers WHERE id = ?", (session["chamber_id"],))
            chamber_row = await cursor.fetchone()
            chamber = chamber_row["name"] if chamber_row else None

    profile = await get_profile(session["species_profile_id"])
    phase_params = profile.phases.get(session["current_phase"]) if profile else None
    ratings = [h["quality_rating"] for h in harvests if h["quality_rating"] is not None]
    return {
        "pi_session_id": session["id"],
        "species_profile_id": session["species_profile_id"],
        "species_name": profile.common_name if profile else session["species_profile_id"],
        "substrate": session.get("substrate"),
        "status": session["status"],
        "current_phase": session["current_phase"],
        "started_at": _iso(session.get("created_at")),
        "completed_at": _iso(session.get("completed_at")),
        "total_wet_yield_g": session.get("total_wet_yield_g") or 0,
        "total_dry_yield_g": session.get("total_dry_yield_g") or 0,
        "flush_count": len({h["flush_number"] for h in harvests}),
        "quality_rating": sum(ratings) / len(ratings) if ratings else None,
        "metadata": {
            "name": session.get("name"),
            "chamber": chamber,
            "species": (
                {"binomial": profile.scientific_name, "common": profile.common_name} if profile else None
            ),
            "phase_entered_at": _iso(phase_row["entered_at"]) if phase_row else None,
            "phase_days_expected": phase_params.expected_duration_days[1] if phase_params else None,
        },
        "harvests": [
            {
                "pi_harvest_id": h["id"],
                "flush_number": h["flush_number"],
                "wet_weight_g": h["wet_weight_g"],
                "dry_weight_g": h["dry_weight_g"],
                "quality_rating": h["quality_rating"],
                "harvested_at": _iso(h["timestamp"]),
            }
            for h in harvests
        ],
    }


def contamination_payload(event: dict) -> dict:
    """The ``contamination_event`` payload for one recorded event row."""
    return {
        "pi_event_id": event["id"],
        "pi_session_id": event.get("session_id"),
        "source": _CLOUD_SOURCES.get(event.get("source"), "local_cnn"),
        "classification": event.get("contamination_type"),
        "confidence": event.get("confidence"),
        "notes": event.get("notes"),
        "detected_at": _iso(event.get("detected_at")),
    }


async def sync_contamination_event(event: dict) -> bool:
    """Send one event now; keep its id for the next connect if that fails."""
    if await cloud_service.forward_contamination_event(contamination_payload(event)):
        _pending_contamination.discard(event["id"])
        return True
    if settings.cloud_url:
        _pending_contamination.add(event["id"])
    return False


async def _on_contamination_recorded(event: dict) -> None:
    if not settings.cloud_url:
        return  # no cloud configured: the first connect after pairing backfills
    task = asyncio.create_task(_send_contamination_quietly(event))
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _send_contamination_quietly(event: dict) -> None:
    try:
        await sync_contamination_event(event)
    except Exception as e:  # noqa: BLE001 — retried on the next connect
        _pending_contamination.add(event["id"])
        log.warning("Cloud: contamination event %s sync failed: %s", event.get("id"), e)


async def sync_session(session_id: int) -> bool:
    """Send one session now; keep it for the next connect if that fails."""
    snapshot = await build_session_snapshot(session_id)
    if snapshot is None:
        _pending.discard(session_id)
        return True
    if await cloud_service.forward_session_sync(snapshot):
        _pending.discard(session_id)
        return True
    # Remember it for the next connect, unless no cloud is configured at all
    # (a later pairing restarts the connector, whose first connect backfills).
    if settings.cloud_url:
        _pending.add(session_id)
    return False


async def _on_session_changed(session_id: int) -> None:
    if not settings.cloud_url:
        return  # no cloud configured: the first connect after pairing backfills
    # Off the request path: the change is committed; the send can take a moment.
    task = asyncio.create_task(_send_quietly(session_id))
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _send_quietly(session_id: int) -> None:
    try:
        await sync_session(session_id)
    except Exception as e:  # noqa: BLE001 — retried on the next connect
        _pending.add(session_id)
        log.warning("Cloud: session %s sync failed: %s", session_id, e)


async def _backfill_ids() -> list[int]:
    since = time.time() - BACKFILL_WINDOW_DAYS * 86400
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM sessions WHERE status = 'active' OR created_at >= ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (since, BACKFILL_MAX),
        )
        return [r["id"] for r in await cursor.fetchall()]


async def on_cloud_connect() -> None:
    """Catch the cloud up: sessions changed while offline, then recent ones."""
    task = asyncio.create_task(_catch_up())
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _contamination_backfill_rows() -> list[dict]:
    since = time.time() - BACKFILL_WINDOW_DAYS * 86400
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM contamination_events WHERE detected_at >= ? "
            "ORDER BY detected_at DESC, id DESC LIMIT ?",
            (since, CONTAMINATION_BACKFILL_MAX),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        missing = _pending_contamination - {r["id"] for r in rows}
        for event_id in sorted(missing, reverse=True):
            cursor = await db.execute("SELECT * FROM contamination_events WHERE id = ?", (event_id,))
            row = await cursor.fetchone()
            if row is None:
                _pending_contamination.discard(event_id)
            else:
                rows.append(dict(row))
    return rows


async def _catch_up() -> None:
    # Sessions first: an event links to its session's cloud row.
    ids = await _backfill_ids()
    ids += sorted(_pending - set(ids), reverse=True)
    sent = 0
    for session_id in ids:
        try:
            if not await sync_session(session_id):
                return  # link dropped mid-way; the next connect starts over
            sent += 1
        except Exception as e:  # noqa: BLE001 — one bad session must not stop the rest
            log.warning("Cloud: session %s sync failed: %s", session_id, e)
    events = 0
    for event in await _contamination_backfill_rows():
        try:
            if not await sync_contamination_event(event):
                return
            events += 1
        except Exception as e:  # noqa: BLE001
            log.warning("Cloud: contamination event %s sync failed: %s", event.get("id"), e)
    if sent or events:
        log.info("Cloud: synced %d grow session(s), %d contamination event(s)", sent, events)


async def wait_idle() -> None:
    """Wait for in-flight sends (tests, shutdown)."""
    while _inflight:
        await asyncio.gather(*list(_inflight), return_exceptions=True)


def attach() -> None:
    """Wire session changes, recorded contamination and cloud connects to the
    sync (idempotent)."""
    sessions_service.add_session_change_listener(_on_session_changed)
    contamination_service.add_contamination_listener(_on_contamination_recorded)
    cloud_service.add_connect_listener(on_cloud_connect)
