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


async def test_create_chamber():
    c = await create_chamber(_make_chamber())
    assert c["id"] is not None
    assert c["name"] == "Fruiting Chamber A"
    assert c["node_ids"] == []
    assert c["automation_rule_ids"] == []
    assert c["active_session_id"] is None


async def test_create_chamber_with_nodes():
    c = await create_chamber(_make_chamber(node_ids=["climate-01", "relay-01"]))
    assert c["node_ids"] == ["climate-01", "relay-01"]


async def test_list_chambers():
    await create_chamber(_make_chamber(name="Chamber A"))
    await create_chamber(_make_chamber(name="Chamber B"))
    chambers = await list_chambers()
    assert len(chambers) == 2


async def test_list_chambers_order():
    a = await create_chamber(_make_chamber(name="First"))
    b = await create_chamber(_make_chamber(name="Second"))
    chambers = await list_chambers()
    # Most recent first
    assert chambers[0]["name"] == "Second"
    assert chambers[1]["name"] == "First"


async def test_get_chamber():
    c = await create_chamber(_make_chamber())
    fetched = await get_chamber(c["id"])
    assert fetched["id"] == c["id"]
    assert fetched["name"] == c["name"]


async def test_get_chamber_not_found():
    result = await get_chamber(9999)
    assert result is None


async def test_update_chamber_name():
    c = await create_chamber(_make_chamber())
    updated = await update_chamber(c["id"], ChamberUpdate(name="Renamed"))
    assert updated["name"] == "Renamed"


async def test_update_chamber_nodes():
    c = await create_chamber(_make_chamber(node_ids=["climate-01"]))
    updated = await update_chamber(c["id"], ChamberUpdate(node_ids=["climate-01", "relay-01", "cam-01"]))
    assert updated["node_ids"] == ["climate-01", "relay-01", "cam-01"]


async def test_update_chamber_preserves_existing():
    c = await create_chamber(_make_chamber(
        name="Keep This",
        description="Important chamber",
        node_ids=["climate-01"],
    ))
    updated = await update_chamber(c["id"], ChamberUpdate(automation_rule_ids=[1, 2]))
    assert updated["name"] == "Keep This"
    assert updated["description"] == "Important chamber"
    assert updated["node_ids"] == ["climate-01"]
    assert updated["automation_rule_ids"] == [1, 2]


async def test_update_chamber_not_found():
    result = await update_chamber(9999, ChamberUpdate(name="Nope"))
    assert result is None


async def test_delete_chamber():
    c = await create_chamber(_make_chamber())
    assert await delete_chamber(c["id"]) is True
    assert await get_chamber(c["id"]) is None


async def test_delete_chamber_not_found():
    assert await delete_chamber(9999) is False


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


async def test_assign_session_to_chamber():
    session = await _make_session()
    c = await create_chamber(_make_chamber())
    updated = await update_chamber(c["id"], ChamberUpdate(active_session_id=session["id"]))
    assert updated["active_session_id"] == session["id"]


async def test_reassign_session():
    s1 = await _make_session("Grow 1")
    s2 = await _make_session("Grow 2")
    c = await create_chamber(_make_chamber())
    await update_chamber(c["id"], ChamberUpdate(active_session_id=s1["id"]))
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


async def _insert_telemetry(node_id: str, sensor: str, value: float, ts: float | None = None):
    ts = ts or time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            (ts, node_id, sensor, value),
        )
        await db.commit()


async def test_compare_chambers_basic():
    """Compare two chambers with telemetry data."""
    c1 = await create_chamber(_make_chamber(name="Chamber A", node_ids=["climate-01"]))
    c2 = await create_chamber(_make_chamber(name="Chamber B", node_ids=["climate-02"]))

    now = time.time()
    await _insert_telemetry("climate-01", "temp_f", 72.0, now - 100)
    await _insert_telemetry("climate-01", "temp_f", 78.0, now - 50)
    await _insert_telemetry("climate-01", "humidity", 85.0, now - 100)

    await _insert_telemetry("climate-02", "temp_f", 68.0, now - 100)
    await _insert_telemetry("climate-02", "humidity", 92.0, now - 100)

    results = await compare_chambers([c1["id"], c2["id"]])
    assert len(results) == 2

    # Chamber A
    a = results[0]
    assert a["chamber_id"] == c1["id"]
    assert a["chamber_name"] == "Chamber A"
    assert "temp_f" in a["telemetry"]
    assert a["telemetry"]["temp_f"]["avg"] == 75.0
    assert a["telemetry"]["temp_f"]["min"] == 72.0
    assert a["telemetry"]["temp_f"]["max"] == 78.0
    assert a["telemetry"]["temp_f"]["readings"] == 2
    assert a["telemetry"]["humidity"]["readings"] == 1

    # Chamber B
    b = results[1]
    assert b["chamber_id"] == c2["id"]
    assert b["telemetry"]["temp_f"]["avg"] == 68.0
    assert b["telemetry"]["humidity"]["avg"] == 92.0


async def test_compare_chambers_skips_missing():
    """Missing chamber IDs are silently skipped."""
    c1 = await create_chamber(_make_chamber(name="Only One"))
    results = await compare_chambers([c1["id"], 9999])
    assert len(results) == 1
    assert results[0]["chamber_name"] == "Only One"


async def test_compare_chambers_no_telemetry():
    """Chamber with nodes but no readings returns empty telemetry."""
    c1 = await create_chamber(_make_chamber(name="Empty", node_ids=["climate-99"]))
    results = await compare_chambers([c1["id"]])
    assert len(results) == 1
    assert results[0]["telemetry"] == {}


async def test_compare_chambers_ignores_old_data():
    """Telemetry older than 24h is not included."""
    c1 = await create_chamber(_make_chamber(name="Old Data", node_ids=["climate-01"]))

    old_ts = time.time() - 100000  # ~28 hours ago
    await _insert_telemetry("climate-01", "temp_f", 99.0, old_ts)

    results = await compare_chambers([c1["id"]])
    assert len(results) == 1
    assert results[0]["telemetry"] == {}


async def test_compare_chambers_aggregates_every_node_of_a_chamber():
    """Two nodes reporting the same sensor are one series: the per-node loop
    kept only the last node's stats."""
    c = await create_chamber(_make_chamber(name="Two nodes", node_ids=["n0a", "n0b", "n0a"]))
    now = time.time()
    await _insert_telemetry("n0a", "temp_f", 60.0, now - 100)
    await _insert_telemetry("n0b", "temp_f", 80.0, now - 50)
    await _insert_telemetry("elsewhere", "temp_f", 99.0, now - 50)

    [result] = await compare_chambers([c["id"]])
    assert result["telemetry"]["temp_f"] == {"avg": 70.0, "min": 60.0, "max": 80.0, "readings": 2}
    assert result["node_ids"] == ["n0a", "n0b", "n0a"]


async def test_compare_chambers_keeps_the_requested_order():
    a = await create_chamber(_make_chamber(name="A"))
    b = await create_chamber(_make_chamber(name="B"))
    results = await compare_chambers([b["id"], 9999, a["id"]])
    assert [r["chamber_name"] for r in results] == ["B", "A"]


def test_compare_endpoint_rejects_malformed_ids(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    assert client.get("/api/chambers/compare?ids=1,abc").status_code == 422
    assert client.get("/api/chambers/compare?ids=,").status_code == 422
    r = client.get(f"/api/chambers/compare?ids={chamber['id']},")
    assert r.status_code == 200
    assert [c["chamber_id"] for c in r.json()] == [chamber["id"]]
