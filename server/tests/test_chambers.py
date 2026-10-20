import time

import pytest

import app.sessions.service as sessions_service
from app.chambers.models import ChamberCreate, ChamberUpdate
from app.chambers.service import (
    ChamberBusyError,
    ChamberInUseError,
    create_chamber,
    get_chamber,
    list_chambers,
    update_chamber,
    delete_chamber,
    compare_chambers,
)
from app.db import get_db
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import (
    advance_phase,
    complete_session,
    create_session,
    get_active_session_for_node,
)
from tests._builders import insert_reading


def _make_chamber(**overrides):
    defaults = dict(name="Fruiting Chamber A")
    defaults.update(overrides)
    return ChamberCreate(**defaults)


async def _make_session(name="Test Grow"):
    return await create_session(SessionCreate(
        name=name,
        species_profile_id="blue_oyster",
    ))


# ── CRUD ───────────────────────────────────────────────────────


async def test_chamber_round_trip_and_partial_update():
    c = await create_chamber(_make_chamber(description="Important chamber", node_ids=["climate-01"]))
    assert (c["name"], c["node_ids"], c["automation_rule_ids"], c["active_session_id"]) == (
        "Fruiting Chamber A", ["climate-01"], [], None)
    assert await get_chamber(c["id"]) == c
    # A PATCH changes only the fields it names.
    updated = await update_chamber(c["id"], ChamberUpdate(automation_rule_ids=[1, 2]))
    assert (updated["name"], updated["description"], updated["node_ids"], updated["automation_rule_ids"]) == (
        "Fruiting Chamber A", "Important chamber", ["climate-01"], [1, 2])
    updated = await update_chamber(c["id"], ChamberUpdate(name="Renamed", node_ids=["climate-01", "cam-01"]))
    assert (updated["name"], updated["node_ids"]) == ("Renamed", ["climate-01", "cam-01"])
    assert await delete_chamber(c["id"]) is True
    assert await get_chamber(c["id"]) is None


async def test_an_unknown_chamber_reads_updates_and_deletes_as_nothing():
    assert await get_chamber(9999) is None
    assert await update_chamber(9999, ChamberUpdate(name="Nope")) is None
    assert await delete_chamber(9999) is False


def test_chamber_routes_answer_404_for_an_unknown_chamber(client):
    assert client.get("/api/chambers/9999").status_code == 404
    assert client.patch("/api/chambers/9999", json={"name": "Nope"}).status_code == 404
    assert client.delete("/api/chambers/9999").status_code == 404


async def test_list_chambers_newest_first():
    await create_chamber(_make_chamber(name="First"))
    await create_chamber(_make_chamber(name="Second"))
    assert [c["name"] for c in await list_chambers()] == ["Second", "First"]


async def test_delete_chamber_with_history_detaches_it():
    """A chamber that ever hosted a session (or has maintenance,
    contamination or planned events) used to raise FOREIGN KEY constraint
    failed. History outlives the chamber with chamber_id = NULL."""
    c = await create_chamber(_make_chamber())
    session = await create_session(SessionCreate(
        name="Grow", species_profile_id="blue_oyster", chamber_id=c["id"],
    ))
    await complete_session(session["id"])
    async with get_db() as db:
        await db.execute(
            "INSERT INTO chamber_maintenance (chamber_id, kind) VALUES (?, 'clean')", (c["id"],)
        )
        await db.execute(
            "INSERT INTO contamination_events (session_id, chamber_id, source) VALUES (?, ?, 'manual')",
            (session["id"], c["id"]),
        )
        await db.execute(
            "INSERT INTO planned_events (title, kind, date, chamber_id) VALUES ('Spawn', 'spawn', '2026-10-01', ?)",
            (c["id"],),
        )
        await db.commit()

    assert await delete_chamber(c["id"]) is True
    assert await get_chamber(c["id"]) is None

    async with get_db() as db:
        row = await (await db.execute(
            "SELECT chamber_id FROM sessions WHERE id = ?", (session["id"],))).fetchone()
        assert row["chamber_id"] is None
        for table in ("contamination_events", "planned_events"):
            row = await (await db.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE chamber_id IS NULL")).fetchone()
            assert row["n"] == 1
        row = await (await db.execute("SELECT COUNT(*) AS n FROM chamber_maintenance")).fetchone()
        assert row["n"] == 0


def test_delete_chamber_endpoint_with_session_is_not_500(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    session = client.post("/api/sessions", json={
        "name": "G", "species_profile_id": "blue_oyster", "chamber_id": chamber["id"],
    }).json()
    assert client.post(f"/api/sessions/{session['id']}/complete").status_code == 200
    r = client.delete(f"/api/chambers/{chamber['id']}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}


async def test_delete_chamber_running_a_grow_is_refused():
    """Detaching a live grow made it the newest session bound to no chamber:
    an idle chamber's nodes (and every unlisted node) then ran its setpoints."""
    a = await create_chamber(_make_chamber(name="A", node_ids=["climate-a"]))
    await create_chamber(_make_chamber(name="B", node_ids=["climate-b"]))
    grow = await create_session(SessionCreate(
        name="A grow", species_profile_id="blue_oyster", chamber_id=a["id"],
    ))
    assert await get_active_session_for_node("climate-b") is None

    with pytest.raises(ChamberInUseError, match="complete or abort"):
        await delete_chamber(a["id"])

    assert await get_chamber(a["id"]) is not None
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT chamber_id FROM sessions WHERE id = ?", (grow["id"],))).fetchone()
    assert row["chamber_id"] == a["id"]
    assert await get_active_session_for_node("climate-b") is None


async def test_delete_chamber_linked_to_a_live_grow_is_refused():
    """A fridge chamber linked to a jar in cold storage (bound to the closet
    it grew in) is in use until the link is dropped."""
    closet = await create_chamber(_make_chamber(name="Closet", node_ids=["climate-1"]))
    fridge = await create_chamber(_make_chamber(name="Fridge", node_ids=["fridge-1"]))
    jar = await create_session(SessionCreate(
        name="Jar", species_profile_id="blue_oyster", current_phase="grain_colonization",
        container_type="grain_jar", chamber_id=closet["id"],
    ))
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await update_chamber(fridge["id"], ChamberUpdate(active_session_id=jar["id"]))
    with pytest.raises(ChamberInUseError, match="unlink"):
        await delete_chamber(fridge["id"])
    await update_chamber(fridge["id"], ChamberUpdate(active_session_id=None))
    assert await delete_chamber(fridge["id"]) is True


def test_delete_chamber_endpoint_running_a_grow_is_409(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    session = client.post("/api/sessions", json={
        "name": "G", "species_profile_id": "blue_oyster", "chamber_id": chamber["id"],
    }).json()
    r = client.delete(f"/api/chambers/{chamber['id']}")
    assert r.status_code == 409
    assert str(session["id"]) in r.json()["detail"]
    assert client.get(f"/api/chambers/{chamber['id']}").status_code == 200


async def test_delete_chamber_resyncs_the_sessions_it_detaches(monkeypatch):
    """The cloud snapshot names a session's chamber: detaching history must
    reach the session-change listeners."""
    changed: list[int] = []

    async def _listener(session_id):
        changed.append(session_id)

    monkeypatch.setattr(sessions_service, "_session_change_listeners", [_listener])
    c = await create_chamber(_make_chamber())
    grow = await create_session(SessionCreate(
        name="Grow", species_profile_id="blue_oyster", chamber_id=c["id"],
    ))
    await complete_session(grow["id"])
    changed.clear()
    assert await delete_chamber(c["id"]) is True
    assert changed == [grow["id"]]


# ── Session assignment ─────────────────────────────────────────


async def test_reassign_session():
    s1 = await _make_session("Grow 1")
    s2 = await _make_session("Grow 2")
    c = await create_chamber(_make_chamber())
    linked = await update_chamber(c["id"], ChamberUpdate(active_session_id=s1["id"]))
    assert linked["active_session_id"] == s1["id"]
    # The chamber still runs Grow 1 (linking bound it): a second grow is
    # refused, or both would be bound to it and the newer would take it over.
    with pytest.raises(ChamberBusyError, match="Grow 1"):
        await update_chamber(c["id"], ChamberUpdate(active_session_id=s2["id"]))
    assert (await get_chamber(c["id"]))["active_session_id"] == s1["id"]
    await complete_session(s1["id"])
    updated = await update_chamber(c["id"], ChamberUpdate(active_session_id=s2["id"]))
    assert updated["active_session_id"] == s2["id"]
    # Linking the grow the chamber already runs is no conflict.
    again = await update_chamber(c["id"], ChamberUpdate(active_session_id=s2["id"]))
    assert again["active_session_id"] == s2["id"]


def test_linking_a_second_grow_to_a_busy_chamber_is_409(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    first = client.post("/api/sessions", json={
        "name": "Tub", "species_profile_id": "blue_oyster", "chamber_id": chamber["id"]}).json()
    second = client.post("/api/sessions", json={"name": "Jar", "species_profile_id": "blue_oyster"}).json()
    r = client.patch(f"/api/chambers/{chamber['id']}", json={"active_session_id": second["id"]})
    assert r.status_code == 409, r.text
    assert "Tub" in r.json()["detail"]
    assert client.get(f"/api/chambers/{chamber['id']}").json()["active_session_id"] == first["id"]


# ── Comparison ────────────────────────────────────────────────


async def test_compare_chambers_aggregates_each_chambers_last_day():
    """Per chamber, per sensor: avg / min / max / count over the last 24 h of
    every node it lists (two nodes reporting one sensor are one series: the
    per-node loop kept only the last node's stats); older readings, other
    nodes and unknown ids are left out, and the requested order is kept."""
    a = await create_chamber(_make_chamber(name="A", node_ids=["n0a", "n0b", "n0a"]))
    b = await create_chamber(_make_chamber(name="B", node_ids=["climate-02"]))
    empty = await create_chamber(_make_chamber(name="Empty", node_ids=["climate-99"]))
    now = time.time()
    await insert_reading("n0a", "temp_f", 60.0, now - 100)
    await insert_reading("n0b", "temp_f", 80.0, now - 50)
    await insert_reading("n0a", "humidity", 85.0, now - 100)
    await insert_reading("n0a", "temp_f", 99.0, now - 100_000)  # ~28 h ago
    await insert_reading("elsewhere", "temp_f", 99.0, now - 50)
    await insert_reading("climate-02", "temp_f", 68.0, now - 100)

    results = await compare_chambers([b["id"], 9999, a["id"], empty["id"]])
    assert [(r["chamber_id"], r["chamber_name"]) for r in results] == [
        (b["id"], "B"), (a["id"], "A"), (empty["id"], "Empty")]
    by_name = {r["chamber_name"]: r for r in results}
    assert by_name["A"]["telemetry"] == {
        "temp_f": {"avg": 70.0, "min": 60.0, "max": 80.0, "readings": 2},
        "humidity": {"avg": 85.0, "min": 85.0, "max": 85.0, "readings": 1},
    }
    assert by_name["A"]["node_ids"] == ["n0a", "n0b", "n0a"]
    assert by_name["B"]["telemetry"]["temp_f"]["avg"] == 68.0
    assert by_name["Empty"]["telemetry"] == {}


def test_compare_endpoint_rejects_malformed_ids(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    assert client.get("/api/chambers/compare?ids=1,abc").status_code == 422
    assert client.get("/api/chambers/compare?ids=,").status_code == 422
    r = client.get(f"/api/chambers/compare?ids={chamber['id']},")
    assert r.status_code == 200
    assert [c["chamber_id"] for c in r.json()] == [chamber["id"]]
