import json

import pytest

import app.sessions.service as sessions_service
from app.db import get_db
from app.sessions.models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate
from app.sessions.service import (
    InvalidPhaseError,
    SessionConflictError,
    UnknownChamberError,
    create_session,
    handle_remote_command,
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


async def test_list_sessions_filter_status():
    s = await create_session(_make_session_data())
    await complete_session(s["id"])
    await create_session(_make_session_data(name="Active"))
    assert len(await list_sessions()) == 2
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
    # The event read "Phase advanced to primordia_induction" (raw enum) in
    # the timeline, the chamber feed and the transcript, while the reminder
    # beside it said "Leaving browning".
    s = await create_session(_make_session_data())
    await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    [ev] = [e for e in await get_events(s["id"]) if e["type"] == "phase_change"]
    assert ev["description"] == "Phase advanced to primordia induction"
    assert json.loads(ev["data"]) == {"phase": "primordia_induction"}


async def test_harvests_accumulate_into_the_session_totals():
    s = await create_session(_make_session_data())
    h = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0, dry_weight_g=15.0))
    assert (h["flush_number"], h["wet_weight_g"], h["dry_weight_g"]) == (1, 150.0, 15.0)
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=80.0, dry_weight_g=8.0))
    updated = await get_session(s["id"])
    assert (updated["total_wet_yield_g"], updated["total_dry_yield_g"]) == (230.0, 23.0)


@pytest.mark.parametrize(("end", "status", "phase"), [
    (abort_session, "aborted", "substrate_colonization"),
    (complete_session, "completed", "complete"),
], ids=["abort", "complete"])
async def test_ending_a_grow_stamps_it_and_closes_its_open_phase(end, status, phase):
    s = await create_session(_make_session_data())
    ended = await end(s["id"])
    assert (ended["status"], ended["current_phase"]) == (status, phase)
    assert ended["completed_at"] is not None
    assert all(ph["exited_at"] is not None for ph in ended["phase_history"])


async def test_an_end_that_loses_a_race_to_another_end_changes_nothing(monkeypatch):
    """Two ends at once both read an active grow: the one that commits second
    must not rewrite the outcome (nor log a second end)."""
    s = await create_session(_make_session_data())
    real_nodes_run_by = sessions_service._nodes_run_by

    async def _completed_meanwhile(session_id):
        async with get_db() as db:  # another request completes it first
            await db.execute("UPDATE sessions SET status = 'completed', current_phase = 'complete' "
                             "WHERE id = ?", (session_id,))
            await db.commit()
        return await real_nodes_run_by(session_id)

    monkeypatch.setattr(sessions_service, "_nodes_run_by", _completed_meanwhile)
    with pytest.raises(SessionConflictError, match="already ended"):
        await abort_session(s["id"])
    assert (await get_session(s["id"]))["status"] == "completed"
    assert "session_aborted" not in [e["type"] for e in await get_events(s["id"])]


def test_an_ended_grow_cannot_be_ended_another_way(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    assert client.post(f"/api/sessions/{s['id']}/abort").status_code == 200
    r = client.post(f"/api/sessions/{s['id']}/complete")
    assert r.status_code == 409 and "aborted" in r.json()["detail"]
    assert client.get(f"/api/sessions/{s['id']}").json()["status"] == "aborted"


async def test_get_events():
    s = await create_session(_make_session_data())
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    note = await add_note(s["id"], NoteCreate(text="Test note", tags=["visual"]))
    assert note["text"] == "Test note"
    events = await get_events(s["id"])
    types = [e["type"] for e in events]
    assert "session_created" in types
    assert "phase_change" in types
    assert "note_added" in types


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
    with pytest.raises(UnknownChamberError, match="chamber 42 not found"):
        await handle_remote_command("session_start", {
            "name": "G", "species_profile_id": "blue_oyster", "chamber_id": 42,
        })
    assert await list_sessions() == []


# ── Unknown sessions and out-of-range harvests ──────────────────

# Every per-session route, against a session that does not exist. Several
# (note, harvest) were FOREIGN KEY 500s; each must be the router's 404.
_UNKNOWN_SESSION_ROUTES = [
    ("GET", "/api/sessions/9999", None),
    ("PATCH", "/api/sessions/9999", {"growth_form": None}),
    ("POST", "/api/sessions/9999/note", {"text": "pins!"}),
    ("POST", "/api/sessions/9999/harvest", {"flush_number": 1, "wet_weight_g": 10}),
    ("GET", "/api/sessions/9999/report.md", None),
    ("GET", "/api/sessions/9999/report.csv", None),
    ("GET", "/api/sessions/9999/stats", None),
    ("POST", "/api/sessions/9999/harvest/1/drying-log", {"weight_g": 50.0}),
    ("GET", "/api/sessions/9999/harvest/1/drying", None),
    ("POST", "/api/sessions/9999/abort", None),
    ("POST", "/api/sessions/9999/contaminated", None),
    ("POST", "/api/sessions/9999/complete", None),
]


def test_every_route_on_an_unknown_session_is_404(client):
    answers = {(method, path): client.request(method, path, json=body).status_code
               for method, path, body in _UNKNOWN_SESSION_ROUTES}
    assert answers == {(method, path): 404 for method, path, _ in _UNKNOWN_SESSION_ROUTES}
    # Nothing was written for the grow that is not there.
    assert client.get("/api/sessions").json() == []
    assert client.get("/api/contamination/events").json() == []


# A negative weight was subtracted from the session's yield total for good
# (there is no harvest edit or delete), flush 0 counted as a flush, and -5 g
# on a 100 g harvest read as 105 % moisture loss and announced 'Drying Complete'.
_OUT_OF_RANGE_HARVESTS = [
    {"flush_number": 0, "wet_weight_g": 100},
    {"flush_number": 51, "wet_weight_g": 100},
    {"flush_number": 1, "wet_weight_g": -500},
    {"flush_number": 1, "dry_weight_g": -1},
    {"flush_number": 1, "quality_rating": 11},
    {"flush_number": 1, "quality_rating": -1},
]


def test_out_of_range_harvest_and_drying_inputs_are_422(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    for body in _OUT_OF_RANGE_HARVESTS:
        r = client.post(f"/api/sessions/{s['id']}/harvest", json=body)
        assert r.status_code == 422, body
        after = client.get(f"/api/sessions/{s['id']}").json()
        assert (after["total_wet_yield_g"], after["total_dry_yield_g"]) == (0, 0), body
    # The edges are in range.
    r = client.post(f"/api/sessions/{s['id']}/harvest", json={
        "flush_number": 50, "wet_weight_g": 0, "dry_weight_g": 0.0, "quality_rating": 10})
    assert r.status_code == 200, r.text
    h = client.post(f"/api/sessions/{s['id']}/harvest",
                    json={"flush_number": 1, "wet_weight_g": 100}).json()
    for weight in (0, -5):
        r = client.post(f"/api/sessions/{s['id']}/harvest/{h['id']}/drying-log", json={"weight_g": weight})
        assert r.status_code == 422, weight
    assert client.get(f"/api/sessions/{s['id']}/harvest/{h['id']}/drying").json()["entries"] == []
