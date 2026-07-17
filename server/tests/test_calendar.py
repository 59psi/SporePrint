from datetime import date

from icalendar import Calendar

from app.sessions.models import SessionCreate
from app.sessions.service import create_session, generate_ical
from app.species.service import seed_builtins


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


async def test_expected_phase_events_anchored_at_inoculation_via_propose_cycle():
    """Active-session projection is driven by planner.propose_cycle, anchored at
    the session's inoculation date — not 'now' / created_at — and laid out from
    the species' real per-phase durations.

    blue_oyster: substrate_colonization(12d) -> primordia_induction(4d) ->
    fruiting(6d). Anchored at 2026-06-01 the projected phase starts are
    2026-06-13 / 2026-06-17, with the harvest (end of fruiting) on 2026-06-23.
    """
    await seed_builtins()  # species_profiles must be populated for get_profile
    # The stored id is hyphenated (create_session canonicalizes); get_profile
    # resolves it. Inoculation date is well before "now" so anchoring is
    # unambiguous — a created_at anchor would land these events in July.
    session = await create_session(_make_session_data(
        name="Anchored Grow",
        species_profile_id="blue_oyster",
        inoculation_date="2026-06-01",
        current_phase="substrate_colonization",
    ))
    sid = session["id"]

    cal = Calendar.from_ical(await generate_ical())
    by_uid = {str(ev["uid"]): ev for ev in cal.walk("VEVENT")}

    prim = by_uid[f"session-{sid}-expected-primordia_induction@sporeprint"]
    fruit = by_uid[f"session-{sid}-expected-fruiting@sporeprint"]
    harvest = by_uid[f"session-{sid}-expected-harvest@sporeprint"]

    assert prim.get("dtstart").dt == date(2026, 6, 13)   # 06-01 + 12 (colonization)
    assert fruit.get("dtstart").dt == date(2026, 6, 17)  # + 4 (primordia)
    assert harvest.get("dtstart").dt == date(2026, 6, 23)  # + 6 (fruiting)

    # VEVENT summary contract preserved.
    assert str(prim["summary"]).endswith("Primordia Induction (Expected)")
    assert str(fruit["summary"]).endswith("Fruiting (Expected)")
    assert str(harvest["summary"]).endswith("Expected Harvest")

    # The current phase is not re-emitted as an "expected" event (only phases
    # still ahead of it are projected).
    assert f"session-{sid}-expected-substrate_colonization@sporeprint" not in by_uid
