"""Tests for session report generation (Markdown + CSV)."""

from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import create_session, add_harvest, generate_session_report_md, generate_session_report_csv


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
