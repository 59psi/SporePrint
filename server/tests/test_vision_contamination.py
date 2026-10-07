"""Vision-pipeline contamination handling + Claude request/persistence contract.

srv-rest#4  — any object in `contamination_detected` (even {type: "none",
              confidence: 0}) paged a CRITICAL; no confidence threshold.
srv-rest#11 — detections were never written to contamination_events, so the
              Contamination page, RCA flow and chamber contamination rates
              only ever saw manual/identify rows.
srv-rest#8  — every frame was declared to Claude as image/jpeg, so PNG/WebP
              frames were rejected by the API.
srv-rest#33 — a failed manual re-analyze overwrote the frame's good stored
              analysis with an {"error": ...} blob.
"""

import json
import time
from unittest.mock import AsyncMock

import pytest

import app.vision.router as vrouter
from app.config import settings
from app.db import get_db
from app.vision import service
from app.vision.service import analyze_frame_claude, contamination_signal, insert_frame


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]
        self.stop_reason = "end_turn"


def _fake_anthropic(responses: list[dict], capture: list[dict]):
    """AsyncAnthropic stand-in: returns `responses` in order, records create() kwargs."""

    class _Messages:
        async def create(self, **kwargs):
            capture.append(kwargs)
            return _FakeMessage(json.dumps(responses[min(len(capture), len(responses)) - 1]))

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    return _Client


@pytest.fixture()
def spies(monkeypatch):
    alert = AsyncMock()
    warning = AsyncMock()
    forward = AsyncMock()
    monkeypatch.setattr(service, "contamination_alert", alert)
    monkeypatch.setattr(service, "notify_warning", warning)
    monkeypatch.setattr("app.cloud.service.forward_event", forward)
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    return {"alert": alert, "warning": warning, "forward": forward}


async def _session_with_chamber() -> tuple[int, int]:
    async with get_db() as db:
        cur = await db.execute("INSERT INTO chambers (name) VALUES ('Closet A')")
        chamber_id = cur.lastrowid
        cur = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, status, current_phase, chamber_id) "
            "VALUES ('contam', 'blue-oyster', 'active', 'substrate_colonization', ?)",
            (chamber_id,),
        )
        await db.commit()
        return cur.lastrowid, chamber_id


async def _frame(tmp_path, session_id, body=b"\xff\xd8\xff\xe0jpeg", name="f.jpg") -> dict:
    p = tmp_path / f"{time.time_ns()}_{name}"
    p.write_bytes(body)
    fid = await insert_frame(session_id=session_id, node_id="cam-01", timestamp=time.time(),
                             file_path=str(p), resolution="", flash_used=1)
    return {"id": fid, "session_id": session_id, "node_id": "cam-01", "file_path": str(p)}


async def _vision_events(session_id: int) -> list[dict]:
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM contamination_events WHERE session_id = ? AND source = 'vision'",
            (session_id,),
        )).fetchall()
    return [dict(r) for r in rows]


# ── contamination_signal (pure) ────────────────────────────────────────────


def test_signal_ignores_none_and_low_confidence():
    assert contamination_signal({"contamination_detected": None})[0] is None
    assert contamination_signal({"contamination_detected": {"type": "none", "confidence": 0}})[0] is None
    assert contamination_signal({"contamination_detected": {"type": "N/A", "confidence": 0.9}})[0] is None
    assert contamination_signal({"contamination_detected": {"type": "trichoderma", "confidence": 0.1}})[0] is None
    assert contamination_signal("not a dict")[0] is None


def test_signal_unnamed_confident_detection_still_pages():
    """A confident detection Claude didn't name is still contamination."""
    tier, ctype, _ = contamination_signal({"contamination_detected": {"confidence": 0.8}})
    assert (tier, ctype) == ("critical", "unknown")


def test_signal_tiers():
    tier, ctype, conf = contamination_signal(
        {"contamination_detected": {"type": "trichoderma", "confidence": 0.9}})
    assert (tier, ctype, conf) == ("critical", "trichoderma", 0.9)
    assert contamination_signal(
        {"contamination_detected": {"type": "cobweb", "confidence": 0.45}})[0] == "warning"
    # percentage-style confidences are normalised
    assert contamination_signal(
        {"contamination_detected": {"type": "cobweb", "confidence": 85}})[2] == 0.85


# ── analyze_frame_claude wiring ─────────────────────────────────────────────


async def test_none_type_detection_does_not_page(tmp_path, monkeypatch, spies):
    sid, _ = await _session_with_chamber()
    capture: list[dict] = []
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic", _fake_anthropic(
        [{"health_assessment": "healthy", "contamination_detected": {"type": "none", "confidence": 0}}],
        capture))
    await analyze_frame_claude(await _frame(tmp_path, sid))
    spies["alert"].assert_not_awaited()
    spies["forward"].assert_not_awaited()
    assert await _vision_events(sid) == []


async def test_confident_detection_pages_records_event_and_dedups(tmp_path, monkeypatch, spies):
    sid, chamber_id = await _session_with_chamber()
    capture: list[dict] = []
    detection = {"health_assessment": "contaminated",
                 "contamination_detected": {"type": "trichoderma", "confidence": 0.92}}
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic",
                        _fake_anthropic([detection, detection], capture))

    frame = await _frame(tmp_path, sid)
    await analyze_frame_claude(frame)

    spies["alert"].assert_awaited_once()
    spies["forward"].assert_awaited_once()
    assert spies["forward"].await_args.args[0] == "contamination_alert"
    events = await _vision_events(sid)
    assert len(events) == 1
    ev = events[0]
    # The alert names the recorded event, so the cloud writes it once (from
    # the event sync), not again from the alert.
    assert spies["forward"].await_args.args[1]["pi_event_id"] == ev["id"]
    assert ev["contamination_type"] == "trichoderma"
    assert ev["confidence"] == 0.92
    assert ev["frame_id"] == frame["id"]
    assert ev["chamber_id"] == chamber_id

    # The same contamination seen again on the next analysis is not re-paged.
    await analyze_frame_claude(await _frame(tmp_path, sid))
    spies["alert"].assert_awaited_once()
    spies["forward"].assert_awaited_once()
    assert len(await _vision_events(sid)) == 1


async def test_borderline_detection_is_a_warning_only(tmp_path, monkeypatch, spies):
    sid, _ = await _session_with_chamber()
    capture: list[dict] = []
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic", _fake_anthropic(
        [{"contamination_detected": {"type": "cobweb", "confidence": 0.45}}], capture))
    await analyze_frame_claude(await _frame(tmp_path, sid))
    spies["alert"].assert_not_awaited()
    spies["forward"].assert_not_awaited()
    spies["warning"].assert_awaited_once()
    assert await _vision_events(sid) == []


async def test_png_frame_is_declared_as_png(tmp_path, monkeypatch, spies):
    sid, _ = await _session_with_chamber()
    capture: list[dict] = []
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic", _fake_anthropic(
        [{"health_assessment": "healthy"}], capture))
    # Legacy rows saved PNG bytes under a .jpg name — the bytes decide.
    frame = await _frame(tmp_path, sid, body=b"\x89PNG\r\n\x1a\nbody", name="legacy.jpg")
    await analyze_frame_claude(frame)
    image = capture[0]["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/png"


# ── manual re-analyze must not clobber a good analysis ──────────────────────


def test_failed_reanalyze_keeps_previous_analysis(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "vision_storage", str(tmp_path / "frames"))
    r = client.post(
        "/api/vision/frame",
        content=b"\xff\xd8\xff\xe0jpeg",
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    frame_id = r.json()["frame_id"]

    good = {"health_assessment": "healthy", "summary": "fine"}
    monkeypatch.setattr(vrouter, "analyze_frame_claude", AsyncMock(return_value=good))
    assert client.post(f"/api/vision/frames/{frame_id}/analyze").json() == good

    monkeypatch.setattr(vrouter, "analyze_frame_claude",
                        AsyncMock(return_value={"error": "rate limited"}))
    r = client.post(f"/api/vision/frames/{frame_id}/analyze")
    assert r.json()["error"] == "rate limited"  # the UI still sees the failure

    stored = client.get(f"/api/vision/frames/{frame_id}").json()["analysis_claude"]
    assert json.loads(stored) == good
