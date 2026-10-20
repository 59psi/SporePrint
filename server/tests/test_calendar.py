import os
import time
from datetime import date, datetime, timezone

import pytest
from icalendar import Calendar

from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session, generate_ical
from app.species.service import seed_builtins


def _make_session_data(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


@pytest.fixture()
def pacific_time():
    """The Pi's zone (setup.sh hands the host's TZ to the container)."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


async def test_projection_without_an_inoculation_date_starts_on_the_local_day(pacific_time):
    """A grow started at 18:00 Pacific (01:00 UTC the next day) with no
    inoculation date was anchored on the UTC date: every expected date a day
    late. It starts on the day the operator started it."""
    await seed_builtins()
    session = await create_session(_make_session_data(name="Evening Grow"))
    started = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc).timestamp()  # 18:00 PDT, Oct 16
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (started, session["id"]))
        await db.commit()
    cal = Calendar.from_ical(await generate_ical())
    by_uid = {str(ev["uid"]): ev for ev in cal.walk("VEVENT")}
    prim = by_uid[f"session-{session['id']}-expected-primordia_induction@sporeprint"]
    assert prim.get("dtstart").dt == date(2026, 10, 28)  # Oct 16 + 12 days of colonization


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


def test_no_event_ends_where_it_starts(client):
    """The start, phase, harvest and end events carried a DTEND equal to
    their DTSTART, which RFC 5545 forbids (DTEND must be later): strict
    calendar clients dropped them. A moment has no DTEND."""
    s = client.post("/api/sessions", json={"name": "Moments", "species_profile_id": "blue_oyster"}).json()
    client.post(f"/api/sessions/{s['id']}/phase", json={"phase": "primordia_induction"})
    client.post(f"/api/sessions/{s['id']}/harvest", json={"flush_number": 1, "wet_weight_g": 100})
    client.post("/api/sessions", json={"name": "Running", "species_profile_id": "blue_oyster"})
    client.post(f"/api/sessions/{s['id']}/complete")
    r = client.get("/api/sessions/calendar.ics")
    assert r.status_code == 200
    events = list(Calendar.from_ical(r.text).walk("VEVENT"))
    assert len(events) >= 6
    for ev in events:
        if ev.get("dtend") is not None:
            assert ev.get("dtend").dt > ev.get("dtstart").dt, ev.get("summary")


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


async def test_expected_dates_skip_pre_substrate_phases_the_session_never_ran():
    """A session that starts at substrate_colonization (the default)
    must not have its projection pushed out by the optional agar -> LC -> grain
    phases the species profile also lists.

    cubensis_golden_teacher lists agar(10d) + liquid_culture(16d) + grain(12d)
    before substrate_colonization(10d) -> primordia(8d) -> fruiting(10d). A
    substrate-start session inoculated 2026-06-01 is expected to reach primordia
    on 06-11 and fruiting on 06-19, with harvest (end of fruiting) on 06-29 —
    not ~38 days later.
    """
    await seed_builtins()
    session = await create_session(_make_session_data(
        name="GT Tub",
        species_profile_id="cubensis_golden_teacher",
        inoculation_date="2026-06-01",
    ))
    sid = session["id"]

    cal = Calendar.from_ical(await generate_ical())
    by_uid = {str(ev["uid"]): ev for ev in cal.walk("VEVENT")}

    def start(uid_phase):
        return by_uid[f"session-{sid}-expected-{uid_phase}@sporeprint"].get("dtstart").dt

    assert start("primordia_induction") == date(2026, 6, 11)
    assert start("fruiting") == date(2026, 6, 19)
    assert start("harvest") == date(2026, 6, 29)


async def test_expected_dates_for_agar_start_session_include_early_phases():
    """A session that genuinely starts at agar keeps the full timeline."""
    await seed_builtins()
    session = await create_session(_make_session_data(
        name="GT From Agar",
        species_profile_id="cubensis_golden_teacher",
        inoculation_date="2026-06-01",
        current_phase="agar",
    ))
    sid = session["id"]

    cal = Calendar.from_ical(await generate_ical())
    by_uid = {str(ev["uid"]): ev for ev in cal.walk("VEVENT")}

    # agar 10d -> LC starts 06-11.
    lc = by_uid[f"session-{sid}-expected-liquid_culture@sporeprint"]
    assert lc.get("dtstart").dt == date(2026, 6, 11)
