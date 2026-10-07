"""Auto contamination/harvest detection actually fires on camera ingest (H4-1).

The local CNN (`analyze_frame_local`) is a permanent stub — it scores every
ingested frame "healthy" 0.0 — so auto contamination/harvest detection never
ran on ingest: green mold and overdue flushes went unflagged unless an operator
manually hit `POST /frames/{id}/analyze`. The fix runs the REAL detector
(`analyze_frame_claude`, which already routes contamination + the harvest-window
signal through the alert + cloud-forward plumbing) as a background task on
ingest, cost-gated so Anthropic spend stays bounded:

  - only with a Claude key present (BYOK — the Pi's AI paygate),
  - only for a frame tied to an active grow session, and
  - at most once per session per cadence window.

These tests pin the gating and the wire-up.
"""

import json
import re
import time
from unittest.mock import AsyncMock

import pytest

import app.vision.router as vrouter
from app.config import settings
from app.db import get_db
from app.vision import service
from app.vision.service import (
    _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS,
    _claim_auto_analysis_slot,
    get_frame_by_id,
    insert_frame,
    maybe_schedule_auto_analysis,
)


@pytest.fixture(autouse=True)
def _reset_auto_analysis_state():
    """The throttle table + task set are module-global; isolate each test."""
    service._last_auto_analysis.clear()
    service._last_auto_phase.clear()
    service._auto_analysis_tasks.clear()
    yield
    service._last_auto_analysis.clear()
    service._last_auto_phase.clear()
    service._auto_analysis_tasks.clear()


async def _make_active_session(phase: str = "fruiting") -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, status, current_phase) "
            "VALUES (?, ?, 'active', ?)",
            ("Auto Ingest Test", "blue-oyster", phase),
        )
        await db.commit()
        return cur.lastrowid


async def _insert_frame_with_file(tmp_path, session_id: int, node_id: str = "cam-01"):
    p = tmp_path / f"{node_id}_{int(time.time() * 1000)}.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-body")
    frame_id = await insert_frame(
        session_id=session_id,
        node_id=node_id,
        timestamp=time.time(),
        file_path=str(p),
        resolution="1600x1200",
        flash_used=1,
    )
    return frame_id, str(p)


# ── throttle logic (pure) ───────────────────────────────────────────────────


def test_default_auto_cadence_matches_spec_six_hours():
    """srv-rest#32: spec §6 — Claude Vision runs every 6h (+ on demand), not on
    every 15-minute capture (~24x the specified API spend on a BYOK key)."""
    assert _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS == 6 * 3600


def test_claim_slot_throttles_per_session_and_expires():
    base = 1_000_000.0
    # first frame for the session claims the slot
    assert _claim_auto_analysis_slot(1, now=base) is True
    # subsequent frames inside the cadence window are refused
    assert _claim_auto_analysis_slot(1, now=base + 60) is False
    assert _claim_auto_analysis_slot(1, now=base + _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS - 1) is False
    # a different session throttles independently
    assert _claim_auto_analysis_slot(2, now=base + 60) is True
    # once the window elapses, the session is eligible again
    assert _claim_auto_analysis_slot(1, now=base + _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS) is True


def test_phase_transition_bypasses_the_cadence_window():
    """Spec §6: Claude Vision also runs on phase transitions. With the 6h
    cadence, the first frame after a phase change is analysed straight away
    (once) instead of waiting out the window."""
    base = 1_000_000.0
    assert _claim_auto_analysis_slot(1, now=base, phase="primordia_induction") is True
    assert _claim_auto_analysis_slot(1, now=base + 60, phase="primordia_induction") is False
    assert _claim_auto_analysis_slot(1, now=base + 120, phase="fruiting") is True
    assert _claim_auto_analysis_slot(1, now=base + 180, phase="fruiting") is False


async def test_first_frame_after_phase_change_is_analysed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    sid = await _make_active_session(phase="primordia_induction")
    mock = AsyncMock(return_value={"health_assessment": "healthy", "summary": "ok"})
    monkeypatch.setattr(service, "analyze_frame_claude", mock)

    async def ingest():
        fid, fpath = await _insert_frame_with_file(tmp_path, sid)
        return await maybe_schedule_auto_analysis(
            frame_id=fid, session_id=sid, node_id="cam-01", file_path=fpath
        )

    t1 = await ingest()
    assert t1 is not None
    await t1
    assert await ingest() is None  # same phase, inside the window

    async with get_db() as db:
        await db.execute("UPDATE sessions SET current_phase = 'fruiting' WHERE id = ?", (sid,))
        await db.commit()
    t3 = await ingest()
    assert t3 is not None, "phase transition must trigger an analysis"
    await t3
    assert await ingest() is None  # back on the cadence
    assert mock.await_count == 2


# ── scheduling on ingest ────────────────────────────────────────────────────


async def test_ingest_schedules_and_persists_when_byok_and_untrottled(tmp_path, monkeypatch):
    """BYOK key + active session + fresh window ⇒ the real detector runs and
    its result is persisted onto the frame row."""
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    sid = await _make_active_session()
    frame_id, fpath = await _insert_frame_with_file(tmp_path, sid)

    analysis = {
        "health_assessment": "contaminated",
        "contamination_detected": {
            "type": "trichoderma",
            "confidence": 0.92,
            "description": "green mold spreading across the cake",
        },
        "summary": "Green mold present — inspect immediately.",
    }
    mock = AsyncMock(return_value=analysis)
    monkeypatch.setattr(service, "analyze_frame_claude", mock)

    task = await maybe_schedule_auto_analysis(
        frame_id=frame_id, session_id=sid, node_id="cam-01", file_path=fpath
    )
    assert task is not None, "an ingested frame should schedule analysis when gating allows"
    await task  # let the background analysis complete

    mock.assert_awaited_once()
    passed_frame = mock.await_args.args[0]
    assert passed_frame["id"] == frame_id
    assert passed_frame["session_id"] == sid
    assert passed_frame["node_id"] == "cam-01"
    assert passed_frame["file_path"] == fpath

    # The real detector's output is persisted so the frame row + the harvest
    # corroboration query (which reads analysis_claude) can see it.
    row = await get_frame_by_id(frame_id)
    assert row["analysis_claude"] is not None
    assert json.loads(row["analysis_claude"]) == analysis


async def test_second_frame_within_window_is_not_scheduled(tmp_path, monkeypatch):
    """Throttle: a second frame for the same session inside the cadence window
    does NOT schedule another (paid) analysis."""
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    sid = await _make_active_session()
    fid1, fpath1 = await _insert_frame_with_file(tmp_path, sid)
    fid2, fpath2 = await _insert_frame_with_file(tmp_path, sid)

    mock = AsyncMock(return_value={"health_assessment": "healthy", "summary": "ok"})
    monkeypatch.setattr(service, "analyze_frame_claude", mock)

    t1 = await maybe_schedule_auto_analysis(
        frame_id=fid1, session_id=sid, node_id="cam-01", file_path=fpath1
    )
    assert t1 is not None
    await t1

    t2 = await maybe_schedule_auto_analysis(
        frame_id=fid2, session_id=sid, node_id="cam-01", file_path=fpath2
    )
    assert t2 is None, "second frame within the cadence window must be throttled"

    mock.assert_awaited_once()  # only the first frame reached Claude


async def test_free_tier_without_claude_key_is_not_scheduled(tmp_path, monkeypatch):
    """No Claude key (free / no BYOK) ⇒ no analysis, and the throttle slot is
    left untouched so it fires immediately once a key is added."""
    monkeypatch.setattr(settings, "claude_api_key", "")
    sid = await _make_active_session()
    frame_id, fpath = await _insert_frame_with_file(tmp_path, sid)

    mock = AsyncMock(return_value={"summary": "should never run"})
    monkeypatch.setattr(service, "analyze_frame_claude", mock)

    task = await maybe_schedule_auto_analysis(
        frame_id=frame_id, session_id=sid, node_id="cam-01", file_path=fpath
    )
    assert task is None
    mock.assert_not_awaited()
    assert sid not in service._last_auto_analysis


async def test_frame_without_active_session_is_not_scheduled(monkeypatch):
    """No active grow session ⇒ nothing to monitor, so no paid analysis."""
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    mock = AsyncMock(return_value={"summary": "should never run"})
    monkeypatch.setattr(service, "analyze_frame_claude", mock)

    task = await maybe_schedule_auto_analysis(
        frame_id=123, session_id=None, node_id="cam-01", file_path="/tmp/x.jpg"
    )
    assert task is None
    mock.assert_not_awaited()


# ── router wire-up ──────────────────────────────────────────────────────────


def test_ingest_endpoint_invokes_auto_analysis(client, monkeypatch, tmp_path):
    """POST /api/vision/frame must hand every ingested frame to the auto-analysis
    scheduler (which then applies the cost gate)."""
    monkeypatch.setattr(settings, "vision_storage", str(tmp_path / "frames"))
    recorder = AsyncMock(return_value=None)
    monkeypatch.setattr(vrouter, "maybe_schedule_auto_analysis", recorder)

    r = client.post(
        "/api/vision/frame",
        content=b"\xff\xd8\xff\xe0fake-jpeg-body",
        headers={
            "Content-Type": "image/jpeg",
            "X-Node-Id": "cam-01",
            "X-Timestamp": "1752300000",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["frame_id"] == body["frame_id"]
    assert kwargs["node_id"] == "cam-01"
    assert kwargs["session_id"] is None  # fresh DB → no active session
    # Stored names are unique per frame (srv-rest#7): node + ts + random suffix.
    assert re.search(r"cam-01_1752300000_[0-9a-f]{12}\.jpg$", kwargs["file_path"])
