"""Tests for chamber lifecycle — derived stats, photos, maintenance."""

import json
import time

from app.chambers.models import ChamberCreate, MaintenanceCreate
from app.chambers.service import (
    create_chamber,
    get_chamber_stats,
    get_chamber_photos,
    list_maintenance,
    schedule_maintenance,
    complete_maintenance,
    get_maintenance,
)
import app.contamination.service as contamination_service
from app.contamination.service import record_event
from app.db import get_db
from app.sessions.models import HarvestCreate, SessionCreate
from app.sessions.service import add_harvest, complete_session, create_session


async def _session_in_chamber(chamber_id, name="Grow", status=None):
    s = await create_session(SessionCreate(
        name=name, species_profile_id="blue_oyster", chamber_id=chamber_id,
    ))
    if status == "completed":
        await complete_session(s["id"])
    return s


async def _insert_frame(node_id, ts, path):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO vision_frames (node_id, timestamp, file_path) VALUES (?, ?, ?)",
            (node_id, ts, path),
        )
        await db.commit()


# ── Derived stats ───────────────────────────────────────────────


async def test_stats_empty_chamber():
    c = await create_chamber(ChamberCreate(name="Empty"))
    stats = await get_chamber_stats(c["id"])
    assert stats["lifetime_grows"] == 0
    assert stats["completed_grows"] == 0
    assert stats["contaminated_grows"] == 0
    assert stats["contamination_rate"] == 0.0
    assert stats["total_wet_yield_g"] == 0.0


async def test_stats_grows_and_yield():
    c = await create_chamber(ChamberCreate(name="Active"))
    s1 = await _session_in_chamber(c["id"], "G1", status="completed")
    await _session_in_chamber(c["id"], "G2")  # still active

    await add_harvest(s1["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0, dry_weight_g=30.0))
    await add_harvest(s1["id"], HarvestCreate(flush_number=2, wet_weight_g=150.0, dry_weight_g=15.0))

    stats = await get_chamber_stats(c["id"])
    assert stats["lifetime_grows"] == 2
    assert stats["completed_grows"] == 1
    assert stats["total_wet_yield_g"] == 450.0
    assert stats["total_dry_yield_g"] == 45.0


async def test_stats_contamination_rate():
    c = await create_chamber(ChamberCreate(name="Contam"))
    # One grow at a time per chamber: G1 ended before G2 started.
    s1 = await _session_in_chamber(c["id"], "G1", status="completed")
    await _session_in_chamber(c["id"], "G2")
    # A contamination event ties session 1 to a contaminated grow.
    await record_event(source="manual", session_id=s1["id"], chamber_id=c["id"],
                       contamination_type="trichoderma")

    stats = await get_chamber_stats(c["id"])
    assert stats["lifetime_grows"] == 2
    assert stats["contaminated_grows"] == 1
    assert stats["contamination_rate"] == 0.5
    assert stats["contamination_event_count"] == 1


def test_marking_a_grow_contaminated_counts_everywhere(client, monkeypatch):
    """The Sessions page's "mark contaminated" only aborted the grow: chamber
    stats, experiments and the event log never saw it (the Sessions KPI did).
    The route ends the grow and logs the contamination in one step."""
    published: list[dict] = []

    async def _listener(event):
        published.append(event)

    monkeypatch.setattr(contamination_service, "_recorded_listeners", [_listener])
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    lost = client.post("/api/sessions", json={
        "name": "Lost", "species_profile_id": "blue_oyster", "chamber_id": chamber["id"],
    }).json()

    r = client.post(f"/api/sessions/{lost['id']}/contaminated",
                    json={"contamination_type": "trichoderma", "notes": "green at the edges"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "aborted"  # the terminal status the cloud knows
    [event] = client.get(f"/api/contamination/events?session_id={lost['id']}").json()
    assert (event["source"], event["chamber_id"], event["contamination_type"], event["notes"]) == (
        "manual", chamber["id"], "trichoderma", "green at the edges")
    assert [e["id"] for e in published] == [event["id"]]  # the cloud sync hears of it
    stats = client.get(f"/api/chambers/{chamber['id']}/stats").json()
    assert (stats["contaminated_grows"], stats["contamination_rate"]) == (1, 1.0)
    events = client.get(f"/api/sessions/{lost['id']}/events").json()
    [ended] = [e for e in events if e["type"] == "session_aborted"]
    assert "contaminated (trichoderma)" in ended["description"]


def test_marking_contaminated_needs_no_body_and_404s_an_unknown_session(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    r = client.post(f"/api/sessions/{s['id']}/contaminated")
    assert r.status_code == 200 and r.json()["status"] == "aborted"
    [event] = client.get(f"/api/contamination/events?session_id={s['id']}").json()
    assert event["contamination_type"] is None and event["chamber_id"] is None
    assert client.post("/api/sessions/9999/contaminated").status_code == 404
    assert len(client.get("/api/contamination/events").json()) == 1


async def test_stats_yield_isolated_per_chamber():
    """Harvests from another chamber's sessions must not leak into stats."""
    c1 = await create_chamber(ChamberCreate(name="A"))
    c2 = await create_chamber(ChamberCreate(name="B"))
    s1 = await _session_in_chamber(c1["id"], "G1")
    s2 = await _session_in_chamber(c2["id"], "G2")
    await add_harvest(s1["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    await add_harvest(s2["id"], HarvestCreate(flush_number=1, wet_weight_g=999.0))

    stats = await get_chamber_stats(c1["id"])
    assert stats["total_wet_yield_g"] == 100.0


async def test_stats_unknown_chamber():
    assert await get_chamber_stats(9999) is None


# ── Photos (derived from vision_frames) ─────────────────────────


async def test_photos_unknown_chamber():
    assert await get_chamber_photos(9999) is None


async def test_photos_no_nodes():
    c = await create_chamber(ChamberCreate(name="No nodes"))
    assert await get_chamber_photos(c["id"]) == []


async def test_photos_newest_first_and_mapped_to_nodes():
    c = await create_chamber(ChamberCreate(name="Cam", node_ids=["cam-01", "climate-01"]))
    now = time.time()
    await _insert_frame("cam-01", now - 100, "old.jpg")
    await _insert_frame("cam-01", now - 10, "new.jpg")
    await _insert_frame("other-99", now, "unrelated.jpg")  # not a chamber node

    photos = await get_chamber_photos(c["id"])
    assert [p["file_path"] for p in photos] == ["new.jpg", "old.jpg"]


async def test_photos_limit():
    c = await create_chamber(ChamberCreate(name="Many", node_ids=["cam-01"]))
    now = time.time()
    for i in range(5):
        await _insert_frame("cam-01", now - i, f"f{i}.jpg")
    photos = await get_chamber_photos(c["id"], limit=2)
    assert len(photos) == 2


async def test_photos_return_the_analyses_as_objects(client):
    """The same frame shape as GET /api/vision/frames (_deserialize_frame):
    the analyses used to come back as JSON strings."""
    c = await create_chamber(ChamberCreate(name="Cam", node_ids=["cam-01"]))
    analysis = {"health_assessment": "healthy", "summary": "Pins forming."}
    async with get_db() as db:
        await db.execute(
            "INSERT INTO vision_frames (node_id, timestamp, file_path, analysis_claude) "
            "VALUES (?, ?, ?, ?)",
            ("cam-01", time.time(), "a.jpg", json.dumps(analysis)),
        )
        await db.commit()
    [photo] = await get_chamber_photos(c["id"])
    assert photo["analysis_claude"] == analysis
    assert photo["analysis_local"] is None
    body = client.get(f"/api/chambers/{c['id']}/photos").json()
    assert body[0]["analysis_claude"] == client.get(
        "/api/vision/frames", params={"node_id": "cam-01"}).json()[0]["analysis_claude"]


# ── Maintenance ─────────────────────────────────────────────────


async def test_schedule_and_list_maintenance():
    c = await create_chamber(ChamberCreate(name="Maint"))
    await schedule_maintenance(c["id"], MaintenanceCreate(kind="clean", due_at=time.time() + 86400, notes="PCO clean"))
    await schedule_maintenance(c["id"], MaintenanceCreate(kind="calibrate", notes="sensor recal"))

    entries = await list_maintenance(c["id"])
    assert len(entries) == 2
    # Newest first
    assert entries[0]["kind"] == "calibrate"
    assert entries[0]["completed_at"] is None


async def test_complete_maintenance():
    c = await create_chamber(ChamberCreate(name="Maint2"))
    m = await schedule_maintenance(c["id"], MaintenanceCreate(kind="inspect"))
    assert m["completed_at"] is None

    done = await complete_maintenance(c["id"], m["id"], notes="looked good")
    assert done["completed_at"] is not None
    assert done["notes"] == "looked good"


async def test_complete_maintenance_unknown():
    c = await create_chamber(ChamberCreate(name="Maint3"))
    assert await complete_maintenance(c["id"], 9999) is None


# ── API endpoints ───────────────────────────────────────────────


def test_stats_endpoint_404(client):
    assert client.get("/api/chambers/9999/stats").status_code == 404


def test_photos_endpoint_404(client):
    assert client.get("/api/chambers/9999/photos").status_code == 404


def test_maintenance_endpoints(client):
    cid = client.post("/api/chambers", json={"name": "Endpoint Maint"}).json()["id"]

    resp = client.post(f"/api/chambers/{cid}/maintenance", json={"kind": "repair", "notes": "fan swap"})
    assert resp.status_code == 200
    mid = resp.json()["id"]

    resp = client.get(f"/api/chambers/{cid}/maintenance")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.post(f"/api/chambers/{cid}/maintenance/{mid}/complete", json={})
    assert resp.status_code == 200
    assert resp.json()["completed_at"] is not None


def test_maintenance_invalid_kind_422(client):
    cid = client.post("/api/chambers", json={"name": "Bad Kind"}).json()["id"]
    resp = client.post(f"/api/chambers/{cid}/maintenance", json={"kind": "explode"})
    assert resp.status_code == 422


def test_maintenance_unknown_chamber_404(client):
    resp = client.post("/api/chambers/9999/maintenance", json={"kind": "clean"})
    assert resp.status_code == 404
    assert client.get("/api/chambers/9999/maintenance").status_code == 404


def test_maintenance_complete_unknown_404(client):
    cid = client.post("/api/chambers", json={"name": "C"}).json()["id"]
    resp = client.post(f"/api/chambers/{cid}/maintenance/9999/complete", json={})
    assert resp.status_code == 404
