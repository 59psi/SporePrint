"""Session record fidelity: phase-entry setpoints, CSV timestamps, harvest
notices and phase reminders."""

import csv
import io
import time
import warnings

import pytest

import app.sessions.service as sessions_service
from app.config import settings
from app.db import get_db
from app.notifications import service as notifications
from app.sessions.models import HarvestCreate, PhaseAdvance, SessionCreate
from app.sessions.service import (
    add_harvest,
    advance_phase,
    check_phase_reminders,
    create_session,
    generate_session_report_csv,
    list_sessions,
    phase_params_for,
)
from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import create_profile, seed_builtins

_PROFILES = {p.id: p for p in BUILTIN_PROFILES}


# ── phase_history.params_snapshot ──────────────────────────────────


async def test_create_session_snapshots_starting_phase_params():
    await seed_builtins()
    s = await create_session(SessionCreate(name="G", species_profile_id="blue_oyster"))
    [row] = s["phase_history"]
    snap = row["params_snapshot"]
    expected = _PROFILES["blue_oyster"].phases
    col = expected[GrowPhase.SUBSTRATE_COLONIZATION]
    assert snap["temp_min_f"] == col.temp_min_f
    assert snap["co2_max_ppm"] == col.co2_max_ppm
    assert list(snap["expected_duration_days"]) == list(col.expected_duration_days)


async def test_advance_phase_snapshots_new_phase_params():
    await seed_builtins()
    s = await create_session(SessionCreate(name="G", species_profile_id="blue-oyster"))
    s = await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    fruiting_row = s["phase_history"][-1]
    assert fruiting_row["phase"] == "fruiting"
    fr = _PROFILES["blue_oyster"].phases[GrowPhase.FRUITING]
    assert fruiting_row["params_snapshot"]["co2_max_ppm"] == fr.co2_max_ppm
    assert fruiting_row["params_snapshot"]["humidity_min"] == fr.humidity_min


async def test_advance_phase_unknown_session_returns_none():
    # Used to raise a FOREIGN KEY IntegrityError (500) instead of the router's 404.
    assert await advance_phase(9999, PhaseAdvance(phase="fruiting")) is None


async def test_snapshot_is_none_for_phase_the_profile_lacks():
    await seed_builtins()
    s = await create_session(SessionCreate(name="G", species_profile_id="blue_oyster"))
    s = await advance_phase(s["id"], PhaseAdvance(phase="cold_storage"))
    assert s["phase_history"][-1]["params_snapshot"] is None


async def test_list_sessions_phase_history_snapshot_decoded():
    await seed_builtins()
    await create_session(SessionCreate(name="G", species_profile_id="blue_oyster"))
    [s] = await list_sessions(include_phase_history=True)
    assert isinstance(s["phase_history"][0]["params_snapshot"], dict)


async def test_rest_snapshot_records_the_fruiting_envelope_in_the_dark():
    """A rest phase the profile does not define runs on the fruiting envelope
    with the lights off; its snapshot used to be NULL."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="G", species_profile_id="blue_oyster",
                                           current_phase="fruiting"))
    s = await advance_phase(s["id"], PhaseAdvance(phase="rest"))
    snap = s["phase_history"][-1]["params_snapshot"]
    fr = _PROFILES["blue_oyster"].phases[GrowPhase.FRUITING]
    assert (snap["temp_min_f"], snap["temp_max_f"]) == (fr.temp_min_f, fr.temp_max_f)
    assert snap["light_hours_on"] == 0
    assert snap["light_spectrum"] == "none"


def test_phase_params_for_resolves_the_setpoints_in_force():
    blue = _PROFILES["blue_oyster"]
    rest = phase_params_for(blue, "rest")
    assert rest.temp_max_f == blue.phases[GrowPhase.FRUITING].temp_max_f
    assert (rest.light_hours_on, rest.light_hours_off) == (0, 24)
    assert blue.phases[GrowPhase.FRUITING].light_hours_on == 12  # the profile is untouched
    # Pinning folded into fruiting borrows fruiting's setpoints.
    pink = _PROFILES["pink_oyster"]
    assert phase_params_for(pink, "primordia_induction") == pink.phases[GrowPhase.FRUITING]
    # The session's growth form re-selects the phase (antler holds CO2 up).
    reishi = _PROFILES["reishi"]
    assert (phase_params_for(reishi, "fruiting", "antler")
            == reishi.phases[GrowPhase.PRIMORDIA_INDUCTION])
    assert phase_params_for(reishi, "fruiting") == reishi.phases[GrowPhase.FRUITING]
    # No species setpoints: the fridge, a finished grow, no profile.
    assert phase_params_for(blue, "cold_storage") is None
    assert phase_params_for(blue, "complete") is None
    assert phase_params_for(None, "fruiting") is None


# ── CSV timestamps ─────────────────────────────────────────────────


async def test_csv_export_timestamps_are_tz_aware_and_warning_free():
    s = await create_session(SessionCreate(name="G", species_profile_id="blue_oyster"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        out = await generate_session_report_csv(s["id"])
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0]["timestamp"].endswith("+00:00")


# ── pink-oyster post-harvest + phase reminders ─────────────────────


@pytest.fixture()
def pink_calls(monkeypatch):
    calls = []

    async def _fake(species_name, notice, dedup_key=None):
        calls.append((species_name, notice))

    monkeypatch.setattr(sessions_service, "harvest_notice", _fake)
    return calls


@pytest.mark.parametrize("species_id", ["pink_oyster", "pink-oyster"])
async def test_pink_oyster_harvest_sends_process_immediately_notice(species_id, pink_calls):
    await seed_builtins()
    s = await create_session(SessionCreate(name="Pink", species_profile_id=species_id))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=250.0))
    assert len(pink_calls) == 1
    name, notice = pink_calls[0]
    assert name == "Pink Oyster" and "refrigerated" in notice


async def test_other_species_harvest_sends_no_pink_notice(pink_calls):
    await seed_builtins()
    s = await create_session(SessionCreate(name="Blue", species_profile_id="blue_oyster"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=250.0))
    assert pink_calls == []


@pytest.mark.parametrize("species_id", ["paddy_straw", "shaggy_mane"])
async def test_every_species_that_cannot_wait_gets_the_notice(species_id, pink_calls):
    """The notice was a pink-oyster special case: paddy straw and shaggy mane,
    whose profiles say the same, never got one."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="Now", species_profile_id=species_id))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=250.0))
    assert [name for name, _ in pink_calls] == [
        next(p.common_name for p in BUILTIN_PROFILES if p.id == species_id)]


async def test_a_custom_profile_carries_or_inherits_the_notice(pink_calls):
    await seed_builtins()
    pink = next(p for p in BUILTIN_PROFILES if p.id == "pink_oyster")
    # Its own notice ...
    await create_profile(pink.model_copy(update={
        "id": "my_pink", "common_name": "My Pink", "harvest_notice": "Cook it tonight."}))
    # ... or, cloned before profiles carried one, the built-in species' own.
    await create_profile(pink.model_copy(update={
        "id": "old_pink", "common_name": "Old Pink", "harvest_notice": "",
        "scientific_name": "Pleurotus djamor var. roseus"}))
    for sid in ("my_pink", "old_pink"):
        s = await create_session(SessionCreate(name=sid, species_profile_id=sid))
        await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    assert pink_calls == [("My Pink", "Cook it tonight."), ("Old Pink", pink.harvest_notice)]


@pytest.fixture()
def reminder_calls(monkeypatch):
    calls = []

    async def _fake(session_id, session_name, phase, days_in_phase, expected_max):
        calls.append((session_id, session_name, phase, days_in_phase, expected_max))

    monkeypatch.setattr(sessions_service, "phase_reminder", _fake)
    return calls


async def test_phase_reminder_fires_when_phase_overruns_expected_max(reminder_calls):
    await seed_builtins()
    s = await create_session(SessionCreate(name="Slow", species_profile_id="blue_oyster"))
    # blue_oyster substrate colonization expects 10-14 days; entered 20 days ago.
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ? WHERE session_id = ?",
            (time.time() - 20 * 86400, s["id"]),
        )
        await db.commit()
    sent = await check_phase_reminders()
    assert sent == 1
    assert reminder_calls == [(s["id"], "Slow", "substrate_colonization", 20, 14)]


async def test_two_overrun_sessions_of_one_name_each_get_their_reminder(monkeypatch):
    """Sessions are named after their species, so the reminder is collapsed
    per session: keyed by name, the second grow's was dropped every day."""
    posted: list[dict] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, timeout=None):
            posted.append(json)

            class _Ok:
                def raise_for_status(self):
                    return None

            return _Ok()

    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    monkeypatch.setattr(notifications.httpx, "AsyncClient", _Client)
    await seed_builtins()
    for _ in range(2):
        await create_session(SessionCreate(name="Blue Oyster", species_profile_id="blue_oyster"))
    async with get_db() as db:
        await db.execute("UPDATE phase_history SET entered_at = ?",
                         (time.time() - 40 * 86400,))
        await db.commit()
    assert await check_phase_reminders() == 2
    assert [p["title"] for p in posted] == ["Phase check — Blue Oyster"] * 2


async def test_phase_reminder_quiet_within_expected_window(reminder_calls):
    await seed_builtins()
    await create_session(SessionCreate(name="OnTime", species_profile_id="blue_oyster"))
    assert await check_phase_reminders() == 0
    assert reminder_calls == []


async def _enter_phase_days_ago(session_id: int, phase: str, days: int) -> None:
    await advance_phase(session_id, PhaseAdvance(phase=phase))
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (time.time() - days * 86400, session_id),
        )
        await db.commit()


async def test_a_long_rest_on_the_fruiting_stand_in_gets_its_reminder(reminder_calls):
    """71 of 74 profiles define no rest: the engine runs it on fruiting's
    envelope, but the reminder looked the phase up directly and never fired."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="Resting", species_profile_id="blue_oyster",
                                           current_phase="fruiting"))
    await _enter_phase_days_ago(s["id"], "rest", 9)  # blue oyster fruiting: 5-7 d
    assert await check_phase_reminders() == 1
    assert reminder_calls == [(s["id"], "Resting", "rest", 9, 7)]


async def test_pinning_folded_into_fruiting_gets_its_reminder(reminder_calls):
    await seed_builtins()
    s = await create_session(SessionCreate(name="Pink", species_profile_id="pink_oyster"))
    await _enter_phase_days_ago(s["id"], "primordia_induction", 8)  # fruiting's 5-7 d
    assert await check_phase_reminders() == 1
    assert reminder_calls[0][2:] == ("primordia_induction", 8, 7)
