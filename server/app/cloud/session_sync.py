"""Grow sessions and contamination events → cloud.

The cloud fills its sessions, analytics, planner, chamber tiles and
contamination history from these, so without them a grow run on the Pi never
shows up there. Every change to a session (app.sessions.service's change
listener) sends that session's snapshot (``session_sync``), and every
contamination event the Pi records (app.contamination.service's listener)
is sent as it is recorded (``contamination_event``).

A send counts only once the relay acknowledges it: a current relay answers
``{"ok": true}`` after writing the row and ``{"ok": false}`` when it did not,
and a socket that died without a FIN takes emits it never delivers. Until
then the change waits in the ``cloud_sync_pending`` table, so it survives a
restart and goes out on the next connect, however old the session is.

Every connect also re-checks the recent sessions, then the recent events
(grows from before the link existed reach the cloud this way), but sends only
those whose snapshot differs from the one the cloud last acknowledged in this
process: the first connect after boot sends them all once, a reconnect only
what changed. A new connect replaces a catch-up still running from the last.

One send per session at a time: a change made while that session's snapshot
is in flight goes out, freshly built, once the first is acknowledged, so the
cloud never ends on an older snapshot. An event goes out after its session:
the cloud links an event to its session's row, so a session the cloud has not
acknowledged yet is sent first.

The cloud keys each row by this Pi's local ids (``pi_session_id`` /
``pi_harvest_id`` / ``pi_event_id``) together with the authenticated device,
so a resend updates the same row.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from ..config import settings
from ..contamination import service as contamination_service
from ..db import get_db
from ..sessions import service as sessions_service
from ..species.service import get_profile
from . import service as cloud_service

log = logging.getLogger(__name__)

# Every connect re-checks the active sessions plus those created in the last
# year, newest first, capped.
BACKFILL_WINDOW_DAYS = 365
BACKFILL_MAX = 200

CONTAMINATION_BACKFILL_MAX = 500

# Pi detection sources → the cloud's contamination_events.detection_source.
_CLOUD_SOURCES = {"vision": "claude", "identify": "claude", "manual": "manual"}

# cloud_sync_pending.kind
SESSION = "session"
CONTAMINATION = "contamination"

# Delivery outcomes (_send_once, _deliver). FAILED: not delivered (link down,
# no acknowledgement, or the relay did not store it); the item stays in the
# outbox. COALESCED: a send of the item was in flight and will go again.
SENT, UNCHANGED, GONE, FAILED, COALESCED = "sent", "unchanged", "gone", "failed", "coalesced"

# Digest of the payload the cloud last acknowledged, by (kind, local id), and
# the cloud link (url, device id) those acknowledgements came from.
_delivered: dict[tuple[str, int], str] = {}
_delivered_for: tuple[str, str] | None = None
# Items with a send in flight, and those changed again meanwhile (the value:
# that change also put the item in the outbox).
_sending: set[tuple[str, int]] = set()
_dirty: dict[tuple[str, int], bool] = {}
# Sends and catch-ups started here (kept so they are not collected).
_inflight: set[asyncio.Task] = set()
_catch_up_task: asyncio.Task | None = None

PayloadBuilder = Callable[[], Awaitable[dict | None]]


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
    # The setpoints the phase runs on: a rest (or a pinning phase folded into
    # fruiting) has its stand-in's window, where a direct lookup had none.
    phase_params = sessions_service.phase_params_for(
        profile, session["current_phase"], session.get("growth_form"))
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


# ── the outbox (cloud_sync_pending) ─────────────────────────────────

async def _queue(kind: str, local_id: int) -> None:
    """Keep `local_id` in the outbox until the cloud acknowledges it."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO cloud_sync_pending (kind, local_id, queued_at) VALUES (?, ?, ?) "
            "ON CONFLICT(kind, local_id) DO NOTHING",
            (kind, local_id, time.time()),
        )
        await db.commit()


async def _unqueue(kind: str, local_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "DELETE FROM cloud_sync_pending WHERE kind = ? AND local_id = ?", (kind, local_id))
        await db.commit()


async def pending_ids(kind: str) -> list[int]:
    """The outbox's ids of `kind`, newest first."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT local_id FROM cloud_sync_pending WHERE kind = ? ORDER BY local_id DESC",
            (kind,),
        )
        return [r["local_id"] for r in await cursor.fetchall()]


# ── one item ─────────────────────────────────────────────────────────

def _digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _delivered_digests() -> dict[tuple[str, int], str]:
    """The acknowledged digests, forgotten once the Pi is linked to another
    cloud or device (which has none of these rows)."""
    global _delivered_for
    link = (settings.cloud_url, settings.cloud_device_id)
    if _delivered_for != link:
        _delivered.clear()
        _delivered_for = link
    return _delivered


async def _session_on_cloud(session_id: int) -> bool:
    """Send an event's session first unless the cloud already acknowledged
    it: the cloud links an event to its session's row, and keeps an event
    whose session it does not have yet unlinked. False when the session
    could not be confirmed now."""
    if (SESSION, session_id) in _delivered_digests():
        return True
    outcome = await _deliver(SESSION, session_id, _session_builder(session_id), queued=False)
    return outcome in (SENT, UNCHANGED, GONE)


async def _send_once(kind: str, local_id: int, payload: dict | None, *, queued: bool) -> str:
    """Send `payload` unless the cloud already acknowledged exactly this one.
    `queued`: the item is in the outbox, cleared once it needs no send."""
    key = (kind, local_id)
    delivered = _delivered_digests()
    settled = True  # the cloud needs nothing more of this item for now
    if payload is None:  # gone from this Pi: nothing left to send
        delivered.pop(key, None)
        outcome = GONE
    else:
        digest = _digest(payload)
        if delivered.get(key) == digest:
            outcome = UNCHANGED
        else:
            if kind == CONTAMINATION and payload.get("pi_session_id") is not None:
                settled = await _session_on_cloud(payload["pi_session_id"])
            forward = (cloud_service.forward_session_sync if kind == SESSION
                       else cloud_service.forward_contamination_event)
            if not await forward(payload):
                return FAILED
            if settled:
                delivered[key] = digest
            # else: stored, maybe without its session link; kept for the
            # next connect, which sends sessions first.
            outcome = SENT
    if queued and settled:
        await _unqueue(kind, local_id)
    return outcome


async def _deliver(kind: str, local_id: int, build: PayloadBuilder, *, queued: bool) -> str:
    """Bring the cloud up to date on one item, one send at a time per item.

    A call that finds a send of the same item in flight only marks it: that
    send goes again with a freshly built payload once it is acknowledged, so
    the newest state is always the last one sent (COALESCED).
    """
    key = (kind, local_id)
    if key in _sending:
        _dirty[key] = _dirty.get(key, False) or queued
        return COALESCED
    _sending.add(key)
    try:
        while True:
            outcome = await _send_once(kind, local_id, await build(), queued=queued)
            if outcome == FAILED or key not in _dirty:
                return outcome
            queued = _dirty.pop(key)
    finally:
        _sending.discard(key)
        _dirty.pop(key, None)


def _session_builder(session_id: int) -> PayloadBuilder:
    async def build() -> dict | None:
        return await build_session_snapshot(session_id)
    return build


def _event_builder(event: dict) -> PayloadBuilder:
    async def build() -> dict | None:
        return contamination_payload(event)
    return build


async def _no_payload() -> None:
    """The builder of an item deleted from this Pi."""
    return None


# ── changes as they happen ──────────────────────────────────────────

def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _send_change(kind: str, local_id: int, build: PayloadBuilder) -> None:
    try:
        await _queue(kind, local_id)
    except Exception as e:  # noqa: BLE001 — still try to send it now
        log.warning("Cloud: could not queue %s %s for sync: %s", kind, local_id, e)
    try:
        await _deliver(kind, local_id, build, queued=True)
    except Exception as e:  # noqa: BLE001 — still queued for the next connect
        log.warning("Cloud: %s %s sync failed: %s", kind, local_id, e)


async def _on_contamination_recorded(event: dict) -> None:
    if not settings.cloud_url:
        return  # no cloud configured: the first connect after pairing backfills
    _spawn(_send_change(CONTAMINATION, event["id"], _event_builder(event)))


async def _on_session_changed(session_id: int) -> None:
    if not settings.cloud_url:
        return  # no cloud configured: the first connect after pairing backfills
    # Off the request path: the change is committed; the send can take a moment.
    _spawn(_send_change(SESSION, session_id, _session_builder(session_id)))


# ── catching up on connect ──────────────────────────────────────────

async def _backfill_ids() -> list[int]:
    since = time.time() - BACKFILL_WINDOW_DAYS * 86400
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM sessions WHERE status = 'active' OR created_at >= ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (since, BACKFILL_MAX),
        )
        return [r["id"] for r in await cursor.fetchall()]


async def _contamination_backfill_rows(queued: list[int]) -> list[dict]:
    """Recent events, then queued ones beyond them (a queued id with no row
    left comes back as {"id": id} alone, to be cleared)."""
    since = time.time() - BACKFILL_WINDOW_DAYS * 86400
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM contamination_events WHERE detected_at >= ? "
            "ORDER BY detected_at DESC, id DESC LIMIT ?",
            (since, CONTAMINATION_BACKFILL_MAX),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        seen = {r["id"] for r in rows}
        for event_id in queued:
            if event_id in seen:
                continue
            cursor = await db.execute("SELECT * FROM contamination_events WHERE id = ?", (event_id,))
            row = await cursor.fetchone()
            rows.append(dict(row) if row is not None else {"id": event_id, "gone": True})
    return rows


def _link_is_up() -> bool:
    return bool(cloud_service.get_cloud_status()["connected"])


async def _catch_up(replacing: asyncio.Task | None = None) -> None:
    if replacing is not None:
        # Let the cancelled catch-up unwind first: until it has, its sends
        # still look in flight and this one would skip them.
        await asyncio.gather(replacing, return_exceptions=True)
    # Sessions first: an event links to its session's cloud row.
    queued = set(await pending_ids(SESSION))
    ids = await _backfill_ids()
    ids += sorted(queued - set(ids), reverse=True)
    sent = 0
    for session_id in ids:
        try:
            outcome = await _deliver(SESSION, session_id, _session_builder(session_id),
                                     queued=session_id in queued)
        except Exception as e:  # noqa: BLE001 — one bad session must not stop the rest
            log.warning("Cloud: session %s sync failed: %s", session_id, e)
            continue
        if outcome == FAILED and not _link_is_up():
            return  # link dropped mid-way; the next connect starts over
        if outcome == SENT:
            sent += 1
    queued_events = await pending_ids(CONTAMINATION)
    queued = set(queued_events)
    events = 0
    for event in await _contamination_backfill_rows(queued_events):
        build = _no_payload if event.get("gone") else _event_builder(event)
        try:
            outcome = await _deliver(CONTAMINATION, event["id"], build,
                                     queued=event["id"] in queued)
        except Exception as e:  # noqa: BLE001
            log.warning("Cloud: contamination event %s sync failed: %s", event.get("id"), e)
            continue
        if outcome == FAILED and not _link_is_up():
            return
        if outcome == SENT:
            events += 1
    if sent or events:
        log.info("Cloud: synced %d grow session(s), %d contamination event(s)", sent, events)


async def on_cloud_connect() -> None:
    """Catch the cloud up: what changed while offline, then recent rows.

    A catch-up still running belongs to a connection that is gone (it would
    only wait out its acknowledgements), so it is replaced."""
    global _catch_up_task
    previous = _catch_up_task
    if previous is not None and not previous.done():
        previous.cancel()
    else:
        previous = None
    _catch_up_task = asyncio.create_task(_catch_up(previous))
    _inflight.add(_catch_up_task)
    _catch_up_task.add_done_callback(_inflight.discard)


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
