"""Transcript telemetry summaries, vision-summary bounding, and missing data.

srv-rest#1: the per-phase telemetry summary filtered `WHERE session_id = ?`,
but ingest never tagged rows with a session, and retention moves anything older
than 7 days into telemetry_rollups (which has no session_id). Every summary
came back {}.

srv-rest#12: analyze_with_claude sent every Claude vision summary, which on a
long grow (one per 15 min) overflows the model's context window.

srv-rest#26: a deleted species profile crashed the markdown export, and an
unknown session id raised a 500 instead of a 404.
"""

import json
import time

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.db import get_db
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import advance_phase, complete_session, create_session
from app.species.service import seed_builtins
from app.transcript import service as transcript_service
from app.transcript.service import export_json, export_markdown

DAY = 86400


async def _raw(node, sensor, value, ts, session_id=None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, node, sensor, value, session_id),
        )
        await db.commit()


async def _rollup(node, sensor, resolution, ts, avg, mn, mx, count):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, "
            "avg_value, min_value, max_value, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, node, sensor, resolution, avg, mn, mx, count),
        )
        await db.commit()


async def _set_phase_window(session_id, entered, exited):
    """Rewrite the (single) phase row so tests control the window."""
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ?, exited_at = ? WHERE session_id = ?",
            (entered, exited, session_id),
        )
        await db.commit()


async def _single_phase_summary(session_id):
    data = await export_json(session_id)
    assert len(data["phase_telemetry"]) == 1
    return data["phase_telemetry"][0]["telemetry_summary"]


# ── srv-rest#1 ───────────────────────────────────────────────────


async def test_summary_uses_session_tagged_raw_rows():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Tagged", species_profile_id="blue_oyster"))
    now = time.time()
    await _set_phase_window(s["id"], now - 3600, None)
    for v in (60.0, 62.0, 64.0):
        await _raw("climate-01", "temp_f", v, now - 1800, session_id=s["id"])

    summary = await _single_phase_summary(s["id"])
    assert summary["temp_f"] == {"min": 60.0, "max": 64.0, "avg": 62.0, "count": 3}


async def test_summary_includes_rolled_up_history_for_old_phases():
    """A 30-day-old phase lives only in rollups (no session_id there)."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="Shiitake", species_profile_id="blue_oyster"))
    now = time.time()
    entered, exited = now - 40 * DAY, now - 20 * DAY
    await _set_phase_window(s["id"], entered, exited)
    # A session-tagged raw row from later in the grow identifies the node.
    await _raw("climate-01", "temp_f", 70.0, now - 60, session_id=s["id"])
    # The phase window's data: a 5-min rollup and an hourly rollup.
    await _rollup("climate-01", "temp_f", "5min", now - 25 * DAY, 72.0, 71.0, 74.0, 10)
    await _rollup("climate-01", "temp_f", "hourly", now - 35 * DAY, 66.0, 60.0, 68.0, 30)
    # Another node's data in the same window must not leak in.
    await _rollup("other-node", "temp_f", "hourly", now - 35 * DAY, 99.0, 99.0, 99.0, 30)

    summary = await _single_phase_summary(s["id"])
    assert summary["temp_f"]["min"] == 60.0
    assert summary["temp_f"]["max"] == 74.0
    assert summary["temp_f"]["count"] == 40
    assert summary["temp_f"]["avg"] == round((72.0 * 10 + 66.0 * 30) / 40, 1)


async def test_summary_uses_chamber_nodes_when_nothing_is_tagged():
    await seed_builtins()
    chamber = await create_chamber(ChamberCreate(name="Tent", node_ids=["tent-sensor"]))
    s = await create_session(SessionCreate(name="Chambered", species_profile_id="blue_oyster",
                                           chamber_id=chamber["id"]))
    now = time.time()
    await _set_phase_window(s["id"], now - 3600, None)
    await _raw("tent-sensor", "humidity", 90.0, now - 600)
    await _raw("closet-node", "humidity", 40.0, now - 600)

    summary = await _single_phase_summary(s["id"])
    assert summary["humidity"]["avg"] == 90.0
    assert summary["humidity"]["count"] == 1


async def test_summary_falls_back_to_all_nodes_in_single_closet():
    """No chamber and no surviving tagged rows (old, completed grow)."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="Old grow", species_profile_id="blue_oyster"))
    now = time.time()
    await _set_phase_window(s["id"], now - 60 * DAY, now - 45 * DAY)
    await _rollup("climate-01", "co2_ppm", "hourly", now - 50 * DAY, 800.0, 600.0, 1100.0, 12)

    summary = await _single_phase_summary(s["id"])
    assert summary["co2_ppm"] == {"min": 600.0, "max": 1100.0, "avg": 800.0, "count": 12}


async def test_summary_is_bounded_by_phase_window():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Window", species_profile_id="blue_oyster"))
    now = time.time()
    await _set_phase_window(s["id"], now - 3600, now - 1800)
    await _raw("climate-01", "temp_f", 65.0, now - 2000, session_id=s["id"])
    await _raw("climate-01", "temp_f", 90.0, now - 100, session_id=s["id"])  # after exit

    summary = await _single_phase_summary(s["id"])
    assert summary["temp_f"]["count"] == 1
    assert summary["temp_f"]["max"] == 65.0


async def test_completed_session_last_phase_does_not_run_to_now():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Done", species_profile_id="blue_oyster"))
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    await complete_session(s["id"])
    # Telemetry recorded after completion belongs to the next grow.
    await _raw("climate-01", "temp_f", 99.0, time.time() + 5)
    data = await export_json(s["id"])
    for pt in data["phase_telemetry"]:
        assert "temp_f" not in pt["telemetry_summary"]


# ── srv-rest#26 ──────────────────────────────────────────────────


async def test_export_json_unknown_session_returns_none():
    assert await export_json(987654) is None
    assert await export_markdown(987654) is None


async def test_markdown_survives_missing_species_profile():
    s = await create_session(SessionCreate(name="Orphan", species_profile_id="deletedcustom"))
    md = await export_markdown(s["id"])
    assert md.startswith("# Session: Orphan")
    assert "deletedcustom" in md


def test_transcript_endpoint_404_for_unknown_session(client):
    for fmt in ("json", "markdown"):
        r = client.get("/api/transcript/sessions/987654/transcript", params={"format": fmt})
        assert r.status_code == 404


def test_analyze_endpoint_404_for_unknown_session(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "claude_api_key", "sk-test")
    r = client.post("/api/transcript/sessions/987654/analyze")
    assert r.status_code == 404


# ── srv-rest#12 ──────────────────────────────────────────────────


def _frame(ts, assessment, summary="x" * 200):
    return {"id": int(ts), "timestamp": ts,
            "analysis_claude": {"health_assessment": assessment, "summary": summary}}


def test_vision_summaries_are_bounded_for_long_grows():
    start = 1_700_000_000.0
    # 90 days of healthy analyses every 15 minutes = 8640 frames.
    frames = [_frame(start + i * 900, "healthy") for i in range(90 * 96)]
    # A contamination scare on day 40 and a concern on day 70.
    frames.append(_frame(start + 40 * DAY + 450, "contaminated"))
    frames.append(_frame(start + 70 * DAY + 450, "concern"))
    frames.sort(key=lambda f: f["timestamp"])

    selected = transcript_service._select_vision_summaries(frames)

    assert len(selected) <= transcript_service._MAX_VISION_SUMMARIES
    assessments = [s["claude_assessment"] for s in selected]
    assert "contaminated" in assessments and "concern" in assessments
    # Chronological, and the most recent analysis is always kept.
    ts = [s["timestamp"] for s in selected]
    assert ts == sorted(ts)
    assert ts[-1] == frames[-1]["timestamp"]
    # Serialized size stays far below a model context window.
    assert len(json.dumps(selected)) < 200_000


def test_vision_summaries_keep_one_healthy_per_day():
    start = 1_700_000_000.0
    frames = [_frame(start + i * 900, "healthy") for i in range(3 * 96)]
    selected = transcript_service._select_vision_summaries(frames)
    days = {int(s["timestamp"] // DAY) for s in selected}
    assert len(selected) == len(days)


def test_vision_summaries_skip_errors_and_non_dicts():
    frames = [
        {"id": 1, "timestamp": 1.0, "analysis_claude": {"error": "boom"}},
        {"id": 2, "timestamp": 2.0, "analysis_claude": "not-a-dict"},
        {"id": 3, "timestamp": 3.0, "analysis_claude": None},
        _frame(4.0, "healthy", "fine"),
    ]
    selected = transcript_service._select_vision_summaries(frames)
    assert [s["timestamp"] for s in selected] == [4.0]


def test_vision_summaries_over_cap_with_mostly_flagged_days_keeps_newest():
    start = 1_700_000_000.0
    frames = [_frame(start + d * DAY, "concern") for d in range(300)]
    frames.append(_frame(start + 300 * DAY, "healthy", "recovered"))
    selected = transcript_service._select_vision_summaries(frames)
    assert len(selected) == transcript_service._MAX_VISION_SUMMARIES
    assert selected[-1]["claude_summary"] == "recovered"
    assert all(s["claude_assessment"] == "concern" for s in selected[:-1])
    ts = [s["timestamp"] for s in selected]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


async def test_analyze_sends_bounded_vision_summaries(monkeypatch):
    await seed_builtins()
    s = await create_session(SessionCreate(name="Long", species_profile_id="blue_oyster"))
    start = time.time() - 60 * DAY
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO vision_frames (session_id, node_id, timestamp, file_path, analysis_claude) "
            "VALUES (?, ?, ?, ?, ?)",
            [(s["id"], "cam-01", start + i * 900, f"/tmp/f{i}.jpg",
              json.dumps({"health_assessment": "healthy", "summary": "Looks good " * 10}))
             for i in range(60 * 96)],
        )
        await db.commit()

    captured = {}

    class _Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)

            class _Block:
                text = '{"overall_score": 80, "summary": "ok"}'

            class _Resp:
                content = [_Block()]

            return _Resp()

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    from app.config import settings
    monkeypatch.setattr(settings, "claude_api_key", "sk-test")
    monkeypatch.setattr(transcript_service.anthropic, "AsyncAnthropic", _Client)

    result = await transcript_service.analyze_with_claude(s["id"])
    assert result.get("overall_score") == 80
    content = captured["messages"][0]["content"]
    payload = json.loads(content.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
    assert len(payload["vision_summaries"]) <= transcript_service._MAX_VISION_SUMMARIES
    assert payload["vision_summary_stats"]["total_analyses"] == 60 * 96
