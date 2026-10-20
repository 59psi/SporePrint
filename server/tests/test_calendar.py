from datetime import date, datetime, timezone

import pytest
from icalendar import Calendar

from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session, generate_ical
from app.species.service import seed_builtins
from tests._pi_c2_helpers import pacific_time  # noqa: F401  (fixture)


def _make_session_data(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


async def _events_by_uid() -> dict:
    cal = Calendar.from_ical(await generate_ical())
    return {str(ev["uid"]): ev for ev in cal.walk("VEVENT")}


async def test_projection_without_an_inoculation_date_starts_on_the_local_day(pacific_time):  # noqa: F811
    """A grow started at 18:00 Pacific (01:00 UTC the next day) with no
    inoculation date was anchored on the UTC date: every expected date a day
    late. It starts on the day the operator started it."""
    await seed_builtins()
    session = await create_session(_make_session_data(name="Evening Grow"))
    started = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc).timestamp()  # 18:00 PDT, Oct 16
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (started, session["id"]))
        await db.commit()
    prim = (await _events_by_uid())[f"session-{session['id']}-expected-primordia_induction@sporeprint"]
    assert prim.get("dtstart").dt == date(2026, 10, 28)  # Oct 16 + 12 days of colonization


def test_no_event_ends_where_it_starts(client):
    """The start, phase, harvest and end events carried a DTEND equal to
    their DTSTART, which RFC 5545 forbids (DTEND must be later): strict
    calendar clients dropped them. A moment has no DTEND."""
    empty = client.get("/api/sessions/calendar.ics")
    assert empty.status_code == 200 and "PRODID" in empty.text
    assert list(Calendar.from_ical(empty.text).walk("VEVENT")) == []

    s = client.post("/api/sessions", json={"name": "Moments", "species_profile_id": "blue_oyster"}).json()
    client.post(f"/api/sessions/{s['id']}/phase", json={"phase": "primordia_induction"})
    client.post(f"/api/sessions/{s['id']}/harvest", json={"flush_number": 1, "wet_weight_g": 100})
    client.post("/api/sessions", json={"name": "Running", "species_profile_id": "blue_oyster"})
    # A grow on a species with no profile has nothing to project, but its own events stay.
    client.post("/api/sessions", json={"name": "Mystery", "species_profile_id": "no_such_species"})
    client.post(f"/api/sessions/{s['id']}/complete")
    r = client.get("/api/sessions/calendar.ics")
    assert r.status_code == 200
    events = list(Calendar.from_ical(r.text).walk("VEVENT"))
    summaries = [str(ev.get("summary")) for ev in events]
    assert len(events) >= 6
    assert {"Moments — Session Started", "Mystery — Session Started"} <= set(summaries)
    assert [x for x in summaries if x.startswith("Mystery") and "Expected" in x] == []
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
    by_uid = await _events_by_uid()

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


# cubensis_golden_teacher lists agar (10 d) + liquid culture (16 d) + grain
# (12 d) before substrate colonization (10 d) -> primordia (8 d) -> fruiting
# (10 d).
@pytest.mark.parametrize(("start_phase", "expected"), [
    # A substrate start must not be pushed out ~38 days by the optional
    # early phases the profile also lists.
    ("substrate_colonization", {"primordia_induction": date(2026, 6, 11), "fruiting": date(2026, 6, 19),
                                "harvest": date(2026, 6, 29)}),
    # A grow that genuinely starts at agar keeps the full timeline.
    ("agar", {"liquid_culture": date(2026, 6, 11)}),
], ids=["substrate-start", "agar-start"])
async def test_expected_dates_start_from_the_phase_the_grow_started_in(start_phase, expected):
    await seed_builtins()
    session = await create_session(_make_session_data(
        name="GT Tub", species_profile_id="cubensis_golden_teacher",
        inoculation_date="2026-06-01", current_phase=start_phase,
    ))
    by_uid = await _events_by_uid()
    starts = {phase: by_uid[f"session-{session['id']}-expected-{phase}@sporeprint"].get("dtstart").dt
              for phase in expected}
    assert starts == expected
