"""Tests for the species-derived dated cycle proposer.

Separate from test_planner.py (weather-compat scorer) and test_planner_events.py
(manual event CRUD): this covers propose_cycle, the /propose[.ics] endpoints,
and the iCal phase-timeline projection.
"""

from datetime import date, timedelta

from icalendar import Calendar

from app.species.models import GrowPhase, PhaseParams
from app.planner.service import propose_cycle
from app.planner.ical import cycle_to_ical
from tests._builders import COLONIZATION, FRUITING, PRIMORDIA, custom_profile

START = date(2026, 7, 16)


def _make_profile(**overrides):
    """A 3-phase gourmet profile: colonization (10-14 d) -> primordia (3-5 d)
    -> fruiting (5-7 d)."""
    phases = {GrowPhase.SUBSTRATE_COLONIZATION: COLONIZATION,
              GrowPhase.PRIMORDIA_INDUCTION: PRIMORDIA, GrowPhase.FRUITING: FRUITING}
    return custom_profile(**{"id": "test_oyster", "common_name": "Test Oyster", "phases": phases,
                             **overrides})


# --- proposer: phases, durations, dates ---


def test_propose_cycle_lays_the_species_phases_out_in_grow_order():
    """Canonical order, labelled; each phase lasts the rounded midpoint of its
    expected range (the range is kept)."""
    cycle = propose_cycle(_make_profile(), START)
    assert [p.phase for p in cycle.phases] == [
        "substrate_colonization", "primordia_induction", "fruiting",
    ]
    assert [p.label for p in cycle.phases] == [
        "Substrate Colonization", "Primordia Induction", "Fruiting",
    ]
    assert [p.duration_days for p in cycle.phases] == [12, 4, 6]  # mid(10,14), (3,5), (5,7)
    assert [(p.min_days, p.max_days) for p in cycle.phases] == [(10, 14), (3, 5), (5, 7)]


def test_propose_cycle_dates_chain_from_inoculation():
    """Phases start at the inoculation date and are contiguous, each ending
    strictly after it starts."""
    cycle = propose_cycle(_make_profile(), START)

    assert cycle.start_date == START
    assert [(p.start_date, p.end_date) for p in cycle.phases] == [
        (date(2026, 7, 16), date(2026, 7, 28)),   # +12
        (date(2026, 7, 28), date(2026, 8, 1)),    # +4
        (date(2026, 8, 1), date(2026, 8, 7)),     # +6
    ]
    assert cycle.harvest_date == date(2026, 8, 7)  # end of fruiting
    assert cycle.end_date == date(2026, 8, 7)
    assert cycle.total_days == 22


def test_propose_cycle_carries_setpoints():
    """Each phase carries the species' temp/RH/CO2/light setpoints."""
    fruiting = propose_cycle(_make_profile(), START).phases[-1]
    assert fruiting.phase == "fruiting"
    assert fruiting.setpoints.temp_min_f == 55
    assert fruiting.setpoints.temp_max_f == 65
    assert fruiting.setpoints.humidity_min == 85
    assert fruiting.setpoints.co2_max_ppm == 700
    assert fruiting.setpoints.light_spectrum == "daylight_6500k"
    assert fruiting.setpoints.fae_mode == "continuous"


def test_propose_cycle_skips_cold_storage_and_complete():
    """The fridge-hold fork and terminal 'complete' never appear on the timeline."""
    profile = _make_profile()
    profile.phases[GrowPhase.COLD_STORAGE] = PhaseParams(
        temp_min_f=35, temp_max_f=40, humidity_min=80, humidity_max=90,
        co2_max_ppm=5000, co2_tolerance="high", light_hours_on=0, light_hours_off=24,
        light_spectrum="none", fae_mode="none", expected_duration_days=(30, 60),
    )
    phases = [p.phase for p in propose_cycle(profile, START).phases]
    assert phases == ["substrate_colonization", "primordia_induction", "fruiting"]


def test_propose_cycle_without_fruiting_has_no_harvest():
    """A profile with no fruiting phase yields harvest_date None but still dates phases."""
    profile = _make_profile()
    del profile.phases[GrowPhase.FRUITING]
    cycle = propose_cycle(profile, START)
    assert cycle.harvest_date is None
    assert [p.phase for p in cycle.phases] == ["substrate_colonization", "primordia_induction"]
    assert cycle.end_date == date(2026, 8, 1)


# --- iCal phase-timeline projection ---


def test_cycle_to_ical_uids_are_deterministic_and_unique():
    """Every event has a stable, collision-free UID."""
    ics = cycle_to_ical(propose_cycle(_make_profile(), START))
    assert "proposal-test_oyster-2026-07-16-fruiting@sporeprint" in ics
    assert "proposal-test_oyster-2026-07-16-harvest@sporeprint" in ics
    uids = [ln for ln in ics.splitlines() if ln.startswith("UID:")]
    assert len(uids) == len(set(uids))


def test_cycle_to_ical_has_one_event_per_phase_plus_harvest_each_ending_after_it_starts():
    """RFC 5545: DTEND is exclusive and strictly later than DTSTART. The
    harvest marker ended on the day it started, which strict clients drop."""
    cycle = propose_cycle(_make_profile(), START)
    events = Calendar.from_ical(cycle_to_ical(cycle)).walk("VEVENT")
    assert len(events) == len(cycle.phases) + 1
    for ev in events:
        assert ev.decoded("dtend") > ev.decoded("dtstart"), ev.get("summary")
    harvest = next(ev for ev in events if "Expected Harvest" in str(ev.get("summary")))
    assert harvest.decoded("dtstart") == cycle.harvest_date
    assert harvest.decoded("dtend") == cycle.harvest_date + timedelta(days=1)


def test_cycle_to_ical_escapes_the_calendar_name():
    """A custom profile's common name is free text: a newline in it failed
    the whole feed, and a comma came out unescaped in X-WR-CALNAME."""
    cycle = propose_cycle(_make_profile(common_name="Oyster, blue\nstrain"), START)
    ics = cycle_to_ical(cycle)
    assert "X-WR-CALNAME:SporePrint plan — Oyster\\, blue\\nstrain" in ics
    assert len(Calendar.from_ical(ics).walk("VEVENT")) == len(cycle.phases) + 1


# --- API endpoints ---


def test_propose_endpoint_dates_a_builtin_species(client):
    r = client.get("/api/planner/propose?species=blue_oyster&start=2026-07-16")
    assert r.status_code == 200
    data = r.json()
    assert data["species_id"] == "blue_oyster"
    assert data["scientific_name"] == "Pleurotus ostreatus var. columbinus"
    assert [(p["phase"], p["duration_days"]) for p in data["phases"]] == [
        ("substrate_colonization", 12), ("primordia_induction", 4), ("fruiting", 6),
    ]
    assert data["phases"][0]["start_date"] == "2026-07-16"
    assert data["harvest_date"] == "2026-08-07"
    assert data["total_days"] == 22


def test_propose_endpoint_defaults_start_to_today(client):
    """Omitting start still proposes a cycle anchored at today."""
    r = client.get("/api/planner/propose?species=blue_oyster")
    assert r.status_code == 200
    assert r.json()["start_date"] == date.today().isoformat()


def test_propose_endpoints_refuse_an_unknown_species_or_a_bad_date(client):
    for route in ("propose", "propose.ics"):
        assert client.get(f"/api/planner/{route}?species=not_a_species&start=2026-07-16").status_code == 404
        assert client.get(f"/api/planner/{route}?species=blue_oyster&start=07/16/2026").status_code == 422


def test_propose_ics_endpoint(client):
    r = client.get("/api/planner/propose.ics?species=blue_oyster&start=2026-07-16")
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    assert "BEGIN:VCALENDAR" in r.text
    assert "blue_oyster-plan.ics" in r.headers.get("content-disposition", "")
