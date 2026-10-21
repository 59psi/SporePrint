"""Tests for session report generation (Markdown + CSV). An unknown session's
reports: tests/test_sessions.py::test_every_route_on_an_unknown_session_is_404."""

import csv
import io
import json

from app.contamination.service import record_event
from app.db import get_db
from app.sessions.models import SessionCreate, HarvestCreate, PhaseAdvance
from app.sessions.service import (
    add_harvest,
    advance_phase,
    create_session,
    generate_session_report_csv,
    generate_session_report_md,
)
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import create_profile, seed_builtins


def _make_session_data(**overrides):
    defaults = dict(name="Report Test", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


async def test_md_report_lists_the_grows_contamination():
    """Contamination is recorded in contamination_events (vision, identify, a
    manual mark); the report read session_events, where no detection ever
    lands, so every report read as a clean grow."""
    s = await create_session(_make_session_data(name="Contam"))
    await record_event(source="vision", session_id=s["id"], contamination_type="trichoderma",
                       confidence=0.86, notes="green | spreading\nfast", detected_at=1_790_000_000.0)
    await record_event(source="manual", session_id=s["id"], contamination_type=None,
                       detected_at=1_790_003_600.0)
    md = await generate_session_report_md(s["id"])
    section = md.split("## Contamination Events", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| 20")]
    assert len(rows) == 2
    assert "trichoderma" in rows[0] and "vision" in rows[0] and "86%" in rows[0]
    assert "green \\| spreading fast" in rows[0]  # one table cell
    assert "unspecified" in rows[1] and "manual" in rows[1]
    assert "Contamination detected (2 event(s))" in md


async def test_md_report_compares_flushes_with_a_custom_profile_too():
    """The flush-count advice walked the built-in list only, so a custom
    strain never got it."""
    await seed_builtins()
    blue = next(p for p in BUILTIN_PROFILES if p.id == "blue_oyster")
    await create_profile(blue.model_copy(update={"id": "my_strain", "flush_count_typical": 4}))
    s = await create_session(_make_session_data(name="Mine", species_profile_id="my_strain"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    md = await generate_session_report_md(s["id"])
    assert "Fewer flushes (1) than typical for this species (4)" in md


async def test_md_report_with_harvest():
    """Markdown report for a session with harvests should contain yield table."""
    s = await create_session(_make_session_data(name="MD Test"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0, dry_weight_g=20.0))
    md = await generate_session_report_md(s["id"])
    assert md.startswith("# SporePrint Grow Report")
    assert "MD Test" in md
    assert "## Yield Per Flush" in md
    assert "| #1 | 200.0 | 20.0 |" in md


async def test_md_report_recommends_from_efficiency_flush_decline_and_colonization_time():
    """5 quarts giving 300 g then 100 g is ~28 % biological efficiency and a
    67 % drop after flush 1; 25 days of colonization is long."""
    s = await create_session(_make_session_data(name="Slow", substrate_volume="5 quarts"))
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = exited_at - ? "
            "WHERE session_id = ? AND phase = 'substrate_colonization'", (25 * 86400, s["id"]))
        await db.commit()
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=100.0))

    md = await generate_session_report_md(s["id"])
    recommendations = md.split("## Recommendations for Next Grow", 1)[1]
    assert "Low biological efficiency" in recommendations
    assert "Sharp yield decline after flush 1" in recommendations
    assert "Extended colonization (25 days)" in recommendations
    timeline = md.split("## Phase Timeline", 1)[1].split("\n## ", 1)[0]
    assert "| Substrate Colonization |" in timeline and "| 25.0 days |" in timeline
    assert "| Fruiting |" in timeline and "| ongoing |" in timeline


async def test_csv_report_has_one_row_per_harvest():
    s = await create_session(_make_session_data(name="CSV Test"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=100.0, dry_weight_g=10.0))
    rows = list(csv.DictReader(io.StringIO(await generate_session_report_csv(s["id"]))))
    assert [(r["session_id"], r["session_name"], r["flush_number"], r["wet_weight_g"], r["dry_weight_g"])
            for r in rows] == [(str(s["id"]), "CSV Test", "1", "150.0", ""),
                               (str(s["id"]), "CSV Test", "2", "100.0", "10.0")]


async def test_md_report_lists_the_newest_analyses_by_their_summary():
    """The stored JSON was printed raw and cut at 300 characters (always
    before `summary`, which the prompt asks for last), and the rows were read
    unordered, so the ten listed were the grow's oldest."""
    s = await create_session(_make_session_data(name="Vision"))
    base = 1_790_000_000.0
    async with get_db() as db:
        for i in range(12):
            analysis = {
                "health_assessment": "healthy",
                "confidence": 0.9,
                "growth_stage": "pinning",
                "morphology_notes": "x" * 400,
                "summary": f"Summary number {i}.",
            }
            await db.execute(
                "INSERT INTO vision_frames (session_id, node_id, timestamp, file_path, analysis_claude) "
                "VALUES (?, ?, ?, ?, ?)",
                (s["id"], "cam-01", base + i * 3600, f"f{i}.jpg", json.dumps(analysis)),
            )
        # Not an analysis the report can show.
        await db.execute(
            "INSERT INTO vision_frames (session_id, node_id, timestamp, file_path, analysis_claude) "
            "VALUES (?, ?, ?, ?, ?)",
            (s["id"], "cam-01", base + 99 * 3600, "bad.jpg", "not json"),
        )
        await db.commit()

    md = await generate_session_report_md(s["id"])
    section = md.split("## Vision Analysis Summaries", 1)[1].split("\n## ", 1)[0]
    items = [line for line in section.splitlines() if line[:1].isdigit()]
    assert len(items) == 10
    assert "Summary number 2." in items[0] and "Summary number 11." in items[-1]
    assert "Summary number 1." not in section
    assert items[-1].endswith("healthy: Summary number 11.")
    assert "{" not in section


def test_the_report_routes_download_markdown_and_csv(client):
    s = client.post("/api/sessions", json={"name": "Download", "species_profile_id": "blue_oyster"}).json()
    client.post(f"/api/sessions/{s['id']}/harvest", json={"flush_number": 1, "wet_weight_g": 120.0})
    for ext, media_type, first_line in (("md", "text/markdown", "# SporePrint Grow Report"),
                                        ("csv", "text/csv", "session_id,session_name")):
        r = client.get(f"/api/sessions/{s['id']}/report.{ext}")
        assert r.status_code == 200, ext
        assert r.headers["content-type"].startswith(media_type)
        assert r.headers["content-disposition"] == f"attachment; filename=sporeprint-session-{s['id']}.{ext}"
        assert r.text.startswith(first_line)
