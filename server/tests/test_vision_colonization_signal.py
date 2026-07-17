"""Vision raises the "colonization complete" milestone — ready to fruit.

Contamination + the harvest-window signal were already wired; full colonization
of a grain jar / substrate bag / agar plate was never detected, so the operator
got no "ready to fruit" cue. This covers the new path: the pure threshold/phase
signal (`colonization_signal`) and the deduped detection→event wiring
(`_maybe_colonization_alert`) that emits a `colonization_complete` session_event
+ ntfy + cloud forward when coverage crosses the completion threshold.
"""

import json
from unittest.mock import AsyncMock

from app.db import get_db
from app.vision import service
from app.vision.service import (
    _COLONIZATION_COMPLETE_PERCENT,
    _maybe_colonization_alert,
    colonization_signal,
)


# ── pure signal: phase + threshold ──────────────────────────────────────────


def test_no_signal_outside_colonization_phase():
    for phase in ("primordia_induction", "fruiting", "cold_storage", "complete"):
        assert colonization_signal(phase, 100) == (False, None)


def test_no_signal_below_threshold():
    assert colonization_signal("substrate_colonization", 80) == (False, None)
    assert colonization_signal("grain_colonization", _COLONIZATION_COMPLETE_PERCENT - 1) == (False, None)


def test_signal_fires_at_and_above_threshold():
    ok, reason = colonization_signal("substrate_colonization", _COLONIZATION_COMPLETE_PERCENT)
    assert ok and reason
    ok, reason = colonization_signal("agar", 100)
    assert ok and "colonized" in reason


def test_missing_or_nonnumeric_percent_is_safe():
    assert colonization_signal("agar", None) == (False, None)
    assert colonization_signal("agar", "n/a") == (False, None)


# ── detection → event wiring (dedup) ────────────────────────────────────────


async def _make_session(phase: str = "substrate_colonization") -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, status, current_phase) "
            "VALUES (?, ?, 'active', ?)",
            ("Colonization Test", "blue-oyster", phase),
        )
        await db.commit()
        return cur.lastrowid


async def _colonization_events(session_id: int) -> list[dict]:
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM session_events WHERE session_id = ? AND type = 'colonization_complete'",
            (session_id,),
        )).fetchall()
    return [dict(r) for r in rows]


async def test_full_colonization_emits_event_notify_and_forward(monkeypatch):
    sid = await _make_session()
    notify = AsyncMock()
    forward = AsyncMock()
    monkeypatch.setattr(service, "notify_warning", notify)
    monkeypatch.setattr("app.cloud.service.forward_event", forward)

    frame = {"id": 7, "session_id": sid, "node_id": "cam-01"}
    result = {"colonization_percent": 98, "surface": "bag", "summary": "fully run"}
    await _maybe_colonization_alert(frame, result, "Blue Oyster")

    events = await _colonization_events(sid)
    assert len(events) == 1
    data = json.loads(events[0]["data"])
    assert data["colonization_percent"] == 98
    assert data["surface"] == "bag"
    assert data["frame_id"] == 7

    notify.assert_awaited_once()
    forward.assert_awaited_once()
    fwd_event, fwd_payload = forward.await_args.args
    assert fwd_event == "colonization_complete"
    assert fwd_payload["session_id"] == sid
    assert fwd_payload["surface"] == "bag"


async def test_below_threshold_emits_nothing(monkeypatch):
    sid = await _make_session()
    notify = AsyncMock()
    forward = AsyncMock()
    monkeypatch.setattr(service, "notify_warning", notify)
    monkeypatch.setattr("app.cloud.service.forward_event", forward)

    await _maybe_colonization_alert(
        {"id": 1, "session_id": sid, "node_id": "cam-01"},
        {"colonization_percent": 60, "surface": "jar"},
        "Blue Oyster",
    )

    assert await _colonization_events(sid) == []
    notify.assert_not_awaited()
    forward.assert_not_awaited()


async def test_second_completion_is_deduped_within_window(monkeypatch):
    sid = await _make_session()
    notify = AsyncMock()
    forward = AsyncMock()
    monkeypatch.setattr(service, "notify_warning", notify)
    monkeypatch.setattr("app.cloud.service.forward_event", forward)

    frame = {"id": 1, "session_id": sid, "node_id": "cam-01"}
    result = {"colonization_percent": 100, "surface": "agar"}
    await _maybe_colonization_alert(frame, result, "Blue Oyster")
    # A later fully-colonized frame for the same session must not re-fire.
    await _maybe_colonization_alert(
        {"id": 2, "session_id": sid, "node_id": "cam-01"}, result, "Blue Oyster"
    )

    assert len(await _colonization_events(sid)) == 1
    notify.assert_awaited_once()
    forward.assert_awaited_once()
