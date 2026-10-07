"""Session record fidelity (audit srv-auto#27, srv-auto#28, srv-rest#13)."""

import csv
import io
import time
import warnings

import pytest

import app.sessions.service as sessions_service
from app.db import get_db
from app.sessions.models import HarvestCreate, PhaseAdvance, SessionCreate
from app.sessions.service import (
    add_harvest,
    advance_phase,
    check_phase_reminders,
    create_session,
    generate_session_report_csv,
    list_sessions,
)
from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins

_PROFILES = {p.id: p for p in BUILTIN_PROFILES}


# ── srv-auto#28: phase_history.params_snapshot ─────────────────────


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


# ── srv-auto#27: CSV timestamps ────────────────────────────────────


async def test_csv_export_timestamps_are_tz_aware_and_warning_free():
    s = await create_session(SessionCreate(name="G", species_profile_id="blue_oyster"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        out = await generate_session_report_csv(s["id"])
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0]["timestamp"].endswith("+00:00")


# ── srv-rest#13: pink-oyster post-harvest + phase reminders ────────


@pytest.fixture()
def pink_calls(monkeypatch):
    calls = []

    async def _fake():
        calls.append(True)

    monkeypatch.setattr(sessions_service, "pink_oyster_harvest", _fake)
    return calls


@pytest.mark.parametrize("species_id", ["pink_oyster", "pink-oyster"])
async def test_pink_oyster_harvest_sends_process_immediately_notice(species_id, pink_calls):
    s = await create_session(SessionCreate(name="Pink", species_profile_id=species_id))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=250.0))
    assert pink_calls == [True]


async def test_other_species_harvest_sends_no_pink_notice(pink_calls):
    s = await create_session(SessionCreate(name="Blue", species_profile_id="blue_oyster"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=250.0))
    assert pink_calls == []


@pytest.fixture()
def reminder_calls(monkeypatch):
    calls = []

    async def _fake(session_name, phase, days_in_phase, expected_max):
        calls.append((session_name, phase, days_in_phase, expected_max))

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
    assert reminder_calls == [("Slow", "substrate_colonization", 20, 14)]


async def test_phase_reminder_quiet_within_expected_window(reminder_calls):
    await seed_builtins()
    await create_session(SessionCreate(name="OnTime", species_profile_id="blue_oyster"))
    assert await check_phase_reminders() == 0
    assert reminder_calls == []
