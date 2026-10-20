import json

import pytest

import app.sessions.service as sessions_service
from app.db import get_db
from app.sessions.models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate
from app.sessions.service import (
    InvalidPhaseError,
    SessionConflictError,
    create_session,
    list_sessions,
    get_session,
    advance_phase,
    add_note,
    add_harvest,
    get_events,
    abort_session,
    complete_session,
    update_session,
)
from app.species.service import seed_builtins


def _make_session_data(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


# ── PATCH: an explicit null clears a field ────────────────────────


async def test_patch_null_clears_a_field_and_omitting_it_keeps_it():
    """With COALESCE(?, col) a null could never clear anything: once
    growth_form was set, the form-specific setpoints were there for good."""
    s = await create_session(_make_session_data(
        species_profile_id="reishi", growth_form="antler", shelf_number=3, pinning_tek="x"))
    kept = await update_session(s["id"], SessionUpdate(substrate="oak"))
    assert (kept["growth_form"], kept["shelf_number"], kept["pinning_tek"]) == ("antler", 3, "x")
    cleared = await update_session(s["id"], SessionUpdate.model_validate(
        {"growth_form": None, "shelf_number": None, "pinning_tek": None, "name": None}))
    assert (cleared["growth_form"], cleared["shelf_number"], cleared["pinning_tek"]) == (None, None, None)
    assert cleared["name"] == "Test Grow" and cleared["substrate"] == "oak"


def test_patch_endpoint_clears_with_null(client):
    s = client.post("/api/sessions", json={
        "name": "R", "species_profile_id": "reishi", "growth_form": "conk"}).json()
    r = client.patch(f"/api/sessions/{s['id']}", json={"growth_form": None})
    assert r.status_code == 200 and r.json()["growth_form"] is None
    assert client.patch("/api/sessions/99999", json={"growth_form": None}).status_code == 404


# ── species filters match every spelling ──────────────────────────


async def test_species_filter_and_averages_match_every_spelling():
    """Sessions store 'lions-mane' while the species list hands out
    'lions_mane': the filter found nothing, and rows stored before 5.0 in the
    other spelling were left out of the species averages."""
    await seed_builtins()
    s = await create_session(_make_session_data(name="New", species_profile_id="lions_mane"))
    assert s["species_profile_id"] == "lions-mane"
    for spelling in ("lions_mane", "lions-mane"):
        assert [r["id"] for r in await list_sessions(species=spelling)] == [s["id"]]
    async with get_db() as db:  # two completed grows, one in each spelling
        for sid, wet in (("lions_mane", 500.0), ("lions-mane", 300.0)):
            await db.execute(
                "INSERT INTO sessions (name, species_profile_id, status, total_wet_yield_g) "
                "VALUES ('old', ?, 'completed', ?)", (sid, wet))
        await db.commit()
    stats = await sessions_service.get_session_stats(s["id"])
    assert stats["species_session_count"] == 2
    assert stats["species_avg_yield_g"] == 400.0


# ── phases a grow can start and change in ─────────────────────────


async def test_a_session_cannot_start_complete():
    with pytest.raises(InvalidPhaseError, match="complete"):
        await create_session(_make_session_data(current_phase="complete"))


async def test_a_phase_change_made_meanwhile_is_not_overwritten(monkeypatch):
    """Two advances at once both read the same phase to leave: the second
    must not overwrite the first (nor log the exit step twice)."""
    await seed_builtins()
    s = await create_session(_make_session_data(container_type="grow_bag"))
    real_get_profile = sessions_service.get_profile

    async def _racing_get_profile(species_id):
        async with get_db() as db:  # another request advances it first
            await db.execute("UPDATE sessions SET current_phase = 'fruiting' WHERE id = ?", (s["id"],))
            await db.commit()
        return await real_get_profile(species_id)

    monkeypatch.setattr(sessions_service, "get_profile", _racing_get_profile)
    with pytest.raises(SessionConflictError, match="changed"):
        await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    after = await get_session(s["id"])
    assert after["current_phase"] == "fruiting"
    assert [ph["phase"] for ph in after["phase_history"]] == ["substrate_colonization"]


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


async def test_phase_change_event_names_the_phase_readably():
    # 2026-10 audit: the event read "Phase advanced to primordia_induction"
    # (raw enum) in the timeline, the chamber feed and the transcript, while
    # the reminder beside it said "Leaving browning".
    s = await create_session(_make_session_data())
    await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    [ev] = [e for e in await get_events(s["id"]) if e["type"] == "phase_change"]
    assert ev["description"] == "Phase advanced to primordia induction"
    assert json.loads(ev["data"]) == {"phase": "primordia_induction"}


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


def test_create_with_an_unknown_chamber_is_a_422_not_a_500(client):
    # The Pi UI once posted chamber_id 0; the FOREIGN KEY failure came back as
    # a bare 500 "Internal Server Error" and left the form saying nothing useful.
    for bad in (0, 999):
        resp = client.post("/api/sessions", json={
            "name": "G", "species_profile_id": "blue-oyster", "chamber_id": bad,
        })
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == f"chamber {bad} not found"
    assert client.get("/api/sessions").json() == []
    chamber = client.post("/api/chambers", json={"name": "Closet A"}).json()
    created = client.post("/api/sessions", json={
        "name": "G", "species_profile_id": "blue-oyster", "chamber_id": chamber["id"],
    })
    assert created.status_code == 200
    assert created.json()["chamber_id"] == chamber["id"]


async def test_remote_session_start_reports_an_unknown_chamber():
    from app.sessions.service import UnknownChamberError, handle_remote_command

    with pytest.raises(UnknownChamberError, match="chamber 42 not found"):
        await handle_remote_command("session_start", {
            "name": "G", "species_profile_id": "blue_oyster", "chamber_id": 42,
        })
    assert await list_sessions() == []


# ── Unknown sessions and out-of-range harvests ──────────────────


def test_note_and_harvest_for_an_unknown_session_are_404_not_500(client):
    note = client.post("/api/sessions/9999/note", json={"text": "pins!"})
    harvest = client.post("/api/sessions/9999/harvest", json={"flush_number": 1, "wet_weight_g": 10})
    assert (note.status_code, harvest.status_code) == (404, 404)  # FOREIGN KEY 500s


async def test_note_and_harvest_services_return_none_for_an_unknown_session():
    assert await add_note(9999, NoteCreate(text="x")) is None
    assert await add_harvest(9999, HarvestCreate(flush_number=1)) is None


@pytest.mark.parametrize("body", [
    {"flush_number": 0, "wet_weight_g": 100},
    {"flush_number": 51, "wet_weight_g": 100},
    {"flush_number": 1, "wet_weight_g": -500},
    {"flush_number": 1, "dry_weight_g": -1},
    {"flush_number": 1, "quality_rating": 11},
    {"flush_number": 1, "quality_rating": -1},
])
def test_out_of_range_harvests_are_422(client, body):
    """A negative weight was subtracted from the session's yield total for
    good (there is no harvest edit or delete), flush 0 counted as a flush."""
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    r = client.post(f"/api/sessions/{s['id']}/harvest", json=body)
    assert r.status_code == 422, body
    after = client.get(f"/api/sessions/{s['id']}").json()
    assert after["total_wet_yield_g"] == 0 and after["total_dry_yield_g"] == 0


def test_in_range_harvest_is_accepted(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    r = client.post(f"/api/sessions/{s['id']}/harvest", json={
        "flush_number": 50, "wet_weight_g": 0, "dry_weight_g": 0.0, "quality_rating": 10})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("weight", [0, -5])
def test_a_non_positive_drying_weight_is_422(client, weight):
    """-5 g on a 100 g harvest read as 105 % moisture loss and announced
    'Drying Complete'."""
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    h = client.post(f"/api/sessions/{s['id']}/harvest",
                    json={"flush_number": 1, "wet_weight_g": 100}).json()
    r = client.post(f"/api/sessions/{s['id']}/harvest/{h['id']}/drying-log",
                    json={"weight_g": weight})
    assert r.status_code == 422
