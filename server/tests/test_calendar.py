from app.sessions.models import SessionCreate
from app.sessions.service import create_session, generate_ical


def _make_session_data(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


async def test_empty_calendar_is_valid_vcalendar():
    """An empty calendar should still produce valid VCALENDAR output."""
    ical_data = await generate_ical()
    assert "BEGIN:VCALENDAR" in ical_data
    assert "END:VCALENDAR" in ical_data
    assert "PRODID" in ical_data


async def test_calendar_with_sessions_includes_events():
    """Calendar with sessions should include session name and start event."""
    await create_session(_make_session_data(name="Blue Oyster Run"))
    ical_data = await generate_ical()
    assert "BEGIN:VCALENDAR" in ical_data
    assert "Blue Oyster Run" in ical_data
    assert "Session Started" in ical_data
