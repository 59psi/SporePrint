"""Tests for session report generation (Markdown + CSV)."""

import json

from app.contamination.service import record_event
from app.db import get_db
from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import create_session, add_harvest, generate_session_report_md, generate_session_report_csv
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import create_profile, seed_builtins


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


def _make_session_data(**overrides):
    defaults = dict(name="Report Test", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


async def test_md_report_with_harvest():
    """Markdown report for a session with harvests should contain yield table."""
    s = await create_session(_make_session_data(name="MD Test"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0, dry_weight_g=20.0))
    md = await generate_session_report_md(s["id"])
    assert md is not None
    assert "# SporePrint Grow Report" in md
    assert "MD Test" in md
    assert "200.0" in md
    assert "## Yield Per Flush" in md


async def test_md_report_nonexistent_session():
    md = await generate_session_report_md(99999)
    assert md is None


async def test_md_report_session_without_harvest():
    s = await create_session(_make_session_data(name="No Harvest"))
    md = await generate_session_report_md(s["id"])
    assert md is not None
    assert "# SporePrint Grow Report" in md


async def test_csv_report_with_harvest():
    s = await create_session(_make_session_data(name="CSV Test"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=100.0))
    csv_data = await generate_session_report_csv(s["id"])
    assert csv_data is not None
    assert "session_id" in csv_data
    assert "150.0" in csv_data
    assert "100.0" in csv_data


async def test_csv_report_nonexistent():
    assert await generate_session_report_csv(99999) is None


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
