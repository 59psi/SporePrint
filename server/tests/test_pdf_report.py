from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import create_session, add_harvest, generate_session_report


def _make_session_data(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="cubensis_golden_teacher")
    defaults.update(overrides)
    return SessionCreate(**defaults)


async def test_pdf_report_with_harvest_starts_with_pdf_header():
    """PDF report for a session with harvests should start with %PDF bytes."""
    s = await create_session(_make_session_data(name="PDF Test"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0, dry_weight_g=15.0))

    pdf_bytes = await generate_session_report(s["id"])
    assert pdf_bytes is not None
    assert pdf_bytes[:4] == b"%PDF"


async def test_pdf_report_nonexistent_session():
    """PDF report for nonexistent session should return None."""
    result = await generate_session_report(99999)
    assert result is None


async def test_pdf_report_session_without_harvest():
    """PDF report should work even without harvests."""
    s = await create_session(_make_session_data(name="No Harvest"))
    pdf_bytes = await generate_session_report(s["id"])
    assert pdf_bytes is not None
    assert pdf_bytes[:4] == b"%PDF"
