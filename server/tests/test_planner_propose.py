"""Tests for the species-derived dated cycle proposer (planner V1-2).

Separate from test_planner.py (weather-compat scorer) and test_planner_events.py
(manual event CRUD): this covers propose_cycle / propose_cycle_for_species, the
/propose[.ics] endpoints, and the iCal phase-timeline projection.
"""

from datetime import date

from app.species.models import GrowPhase, PhaseParams, SpeciesProfile
from app.species.service import seed_builtins
from app.planner.service import propose_cycle, propose_cycle_for_species
from app.planner.ical import cycle_to_ical


def _make_profile(**overrides) -> SpeciesProfile:
    """A 3-phase gourmet profile (colonization -> primordia -> fruiting)."""
    defaults = dict(
        id="test_oyster",
        common_name="Test Oyster",
        scientific_name="Pleurotus testii",
        category="gourmet",
        substrate_types=["straw"],
        colonization_visual_description="White mycelium",
        contamination_risk_notes="Watch for trich",
        pinning_trigger_description="Cold shock + FAE",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high", light_hours_on=0,
                light_hours_off=24, light_spectrum="none", fae_mode="passive",
                expected_duration_days=(10, 14),
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=55, humidity_min=90, humidity_max=95,
                co2_max_ppm=500, co2_tolerance="low", light_hours_on=12,
                light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
                expected_duration_days=(3, 5),
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
                light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
                expected_duration_days=(5, 7),
            ),
        },
        flush_count_typical=3,
        yield_notes="Good yielder",
        tags=["beginner"],
    )
    defaults.update(overrides)
    return SpeciesProfile(**defaults)


# --- proposer: phases + durations ---

def test_propose_cycle_phases_in_canonical_order():
    """Cycle carries the species' phases in canonical grow order."""
    cycle = propose_cycle(_make_profile(), date(2026, 7, 16))
    assert [p.phase for p in cycle.phases] == [
        "substrate_colonization", "primordia_induction", "fruiting",
    ]
    assert [p.label for p in cycle.phases] == [
        "Substrate Colonization", "Primordia Induction", "Fruiting",
    ]


def test_propose_cycle_durations_are_rounded_midpoints():
    """duration_days is the rounded midpoint of expected_duration_days; range is kept."""
    cycle = propose_cycle(_make_profile(), date(2026, 7, 16))
    assert [p.duration_days for p in cycle.phases] == [12, 4, 6]  # mid(10,14), (3,5), (5,7)
    assert [(p.min_days, p.max_days) for p in cycle.phases] == [(10, 14), (3, 5), (5, 7)]


# --- proposer: dated + monotonic ---

def test_propose_cycle_dates_chain_from_inoculation():
    """Phases start at the inoculation date and are contiguous."""
    start = date(2026, 7, 16)
    cycle = propose_cycle(_make_profile(), start)

    assert cycle.start_date == start
    assert cycle.phases[0].start_date == start  # colonization begins at inoculation
    assert cycle.phases[0].end_date == date(2026, 7, 28)  # +12
    assert cycle.phases[1].start_date == date(2026, 7, 28)  # contiguous
    assert cycle.phases[1].end_date == date(2026, 8, 1)  # +4
    assert cycle.phases[2].start_date == date(2026, 8, 1)  # contiguous
    assert cycle.phases[2].end_date == date(2026, 8, 7)  # +6

    assert cycle.harvest_date == date(2026, 8, 7)  # end of fruiting
    assert cycle.end_date == date(2026, 8, 7)
    assert cycle.total_days == 22


def test_propose_cycle_dates_are_strictly_monotonic():
    """Both phase starts and phase ends strictly increase — no overlaps, no zero-length."""
    cycle = propose_cycle(_make_profile(), date(2026, 7, 16))
    starts = [p.start_date for p in cycle.phases]
    ends = [p.end_date for p in cycle.phases]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert ends == sorted(ends) and len(set(ends)) == len(ends)
    # Each phase's end is strictly after its own start.
    assert all(p.end_date > p.start_date for p in cycle.phases)


def test_propose_cycle_carries_setpoints():
    """Each phase carries the species' temp/RH/CO2/light setpoints."""
    fruiting = propose_cycle(_make_profile(), date(2026, 7, 16)).phases[-1]
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
    phases = [p.phase for p in propose_cycle(profile, date(2026, 7, 16)).phases]
    assert "cold_storage" not in phases
    assert "complete" not in phases
    assert phases == ["substrate_colonization", "primordia_induction", "fruiting"]


def test_propose_cycle_without_fruiting_has_no_harvest():
    """A profile with no fruiting phase yields harvest_date None but still dates phases."""
    profile = _make_profile()
    del profile.phases[GrowPhase.FRUITING]
    cycle = propose_cycle(profile, date(2026, 7, 16))
    assert cycle.harvest_date is None
    assert [p.phase for p in cycle.phases] == ["substrate_colonization", "primordia_induction"]
    assert cycle.end_date == date(2026, 8, 1)


# --- proposer: by species id ---

async def test_propose_cycle_for_unknown_species_is_none():
    assert await propose_cycle_for_species("does_not_exist", date(2026, 7, 16)) is None


async def test_propose_cycle_for_builtin_blue_oyster():
    """A real builtin species proposes the expected dated cycle end-to-end."""
    await seed_builtins()
    cycle = await propose_cycle_for_species("blue_oyster", date(2026, 7, 16))
    assert cycle is not None
    assert cycle.species_id == "blue_oyster"
    assert cycle.scientific_name == "Pleurotus ostreatus var. columbinus"
    assert [p.phase for p in cycle.phases] == [
        "substrate_colonization", "primordia_induction", "fruiting",
    ]
    assert [p.duration_days for p in cycle.phases] == [12, 4, 6]
    assert cycle.harvest_date == date(2026, 8, 7)
    # Whole-cycle dates are monotonic non-decreasing.
    chain = [cycle.start_date] + [p.end_date for p in cycle.phases]
    assert chain == sorted(chain)


# --- iCal phase-timeline projection ---

def test_cycle_to_ical_one_event_per_phase_plus_harvest():
    cycle = propose_cycle(_make_profile(), date(2026, 7, 16))
    ics = cycle_to_ical(cycle)
    assert "BEGIN:VCALENDAR" in ics
    assert ics.count("BEGIN:VEVENT") == len(cycle.phases) + 1  # phases + harvest


def test_cycle_to_ical_uids_are_deterministic_and_unique():
    """Every event has a stable, collision-free UID (the V1-1 id-fix spirit)."""
    ics = cycle_to_ical(propose_cycle(_make_profile(), date(2026, 7, 16)))
    assert "proposal-test_oyster-2026-07-16-fruiting@sporeprint" in ics
    assert "proposal-test_oyster-2026-07-16-harvest@sporeprint" in ics
    uids = [ln for ln in ics.splitlines() if ln.startswith("UID:")]
    assert len(uids) == len(set(uids))


# --- API endpoints ---

def test_propose_endpoint(client):
    r = client.get("/api/planner/propose?species=blue_oyster&start=2026-07-16")
    assert r.status_code == 200
    data = r.json()
    assert data["species_id"] == "blue_oyster"
    assert [p["phase"] for p in data["phases"]] == [
        "substrate_colonization", "primordia_induction", "fruiting",
    ]
    assert data["phases"][0]["start_date"] == "2026-07-16"
    assert data["harvest_date"] == "2026-08-07"
    assert data["total_days"] == 22


def test_propose_endpoint_defaults_start_to_today(client):
    """Omitting start still proposes a cycle anchored at today."""
    from datetime import date as _d
    r = client.get("/api/planner/propose?species=blue_oyster")
    assert r.status_code == 200
    assert r.json()["start_date"] == _d.today().isoformat()


def test_propose_endpoint_unknown_species_404(client):
    r = client.get("/api/planner/propose?species=not_a_species&start=2026-07-16")
    assert r.status_code == 404


def test_propose_endpoint_bad_date_422(client):
    r = client.get("/api/planner/propose?species=blue_oyster&start=07/16/2026")
    assert r.status_code == 422


def test_propose_ics_endpoint(client):
    r = client.get("/api/planner/propose.ics?species=blue_oyster&start=2026-07-16")
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    assert "BEGIN:VCALENDAR" in r.text
    assert "blue_oyster-plan.ics" in r.headers.get("content-disposition", "")
