from app.sessions.models import SessionCreate, PhaseAdvance, NoteCreate, HarvestCreate
from app.sessions.service import (
    create_session,
    list_sessions,
    get_session,
    advance_phase,
    add_note,
    add_harvest,
    get_events,
    abort_session,
    complete_session,
)


def _make_session_data(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="cubensis_golden_teacher")
    defaults.update(overrides)
    return SessionCreate(**defaults)


async def test_create_session():
    s = await create_session(_make_session_data())
    assert s["id"] is not None
    assert s["name"] == "Test Grow"
    assert s["status"] == "active"
    assert s["current_phase"] == "substrate_colonization"
    assert len(s["phase_history"]) == 1
    assert s["phase_history"][0]["phase"] == "substrate_colonization"


async def test_list_sessions():
    await create_session(_make_session_data(name="Grow 1"))
    await create_session(_make_session_data(name="Grow 2"))
    sessions = await list_sessions()
    assert len(sessions) == 2


async def test_list_sessions_filter_status():
    s = await create_session(_make_session_data())
    await complete_session(s["id"])
    await create_session(_make_session_data(name="Active"))
    active = await list_sessions(status="active")
    assert len(active) == 1
    assert active[0]["name"] == "Active"


async def test_advance_phase():
    s = await create_session(_make_session_data())
    updated = await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    assert updated["current_phase"] == "primordia_induction"
    assert len(updated["phase_history"]) == 2
    # Old phase should have exited_at
    assert updated["phase_history"][0]["exited_at"] is not None
    # New phase should not
    assert updated["phase_history"][1]["exited_at"] is None


async def test_add_note():
    s = await create_session(_make_session_data())
    note = await add_note(s["id"], NoteCreate(text="Looking healthy", tags=["visual"]))
    assert note["text"] == "Looking healthy"


async def test_add_harvest():
    s = await create_session(_make_session_data())
    h = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0, dry_weight_g=15.0))
    assert h["flush_number"] == 1
    assert h["wet_weight_g"] == 150.0
    # Check session totals updated
    updated = await get_session(s["id"])
    assert updated["total_wet_yield_g"] == 150.0
    assert updated["total_dry_yield_g"] == 15.0


async def test_multiple_harvests_accumulate():
    s = await create_session(_make_session_data())
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=80.0))
    updated = await get_session(s["id"])
    assert updated["total_wet_yield_g"] == 180.0


async def test_abort_session():
    s = await create_session(_make_session_data())
    aborted = await abort_session(s["id"])
    assert aborted["status"] == "aborted"
    assert aborted["completed_at"] is not None
    # Phase should be closed
    assert all(ph["exited_at"] is not None for ph in aborted["phase_history"])


async def test_complete_session():
    s = await create_session(_make_session_data())
    completed = await complete_session(s["id"])
    assert completed["status"] == "completed"
    assert completed["current_phase"] == "complete"
    assert completed["completed_at"] is not None


async def test_get_events():
    s = await create_session(_make_session_data())
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    await add_note(s["id"], NoteCreate(text="Test note"))
    events = await get_events(s["id"])
    types = [e["type"] for e in events]
    assert "session_created" in types
    assert "phase_change" in types
    assert "note_added" in types


async def test_full_lifecycle():
    s = await create_session(_make_session_data())
    s = await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    await add_note(s["id"], NoteCreate(text="Pins forming"))
    s = await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0, dry_weight_g=20.0))
    s = await complete_session(s["id"])
    assert s["status"] == "completed"
    assert s["total_wet_yield_g"] == 200.0
    assert len(s["phase_history"]) == 3
