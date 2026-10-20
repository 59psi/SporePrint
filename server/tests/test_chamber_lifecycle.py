"""Tests for chamber lifecycle — derived stats, photos, maintenance."""

import json
import time

from app.chambers.models import ChamberCreate
from app.chambers.service import (
    create_chamber,
    get_chamber_stats,
    get_chamber_photos,
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


async def test_stats_count_the_chambers_own_grows_and_yield():
    """Harvests from another chamber's sessions must not leak into stats."""
    c = await create_chamber(ChamberCreate(name="Active"))
    other = await create_chamber(ChamberCreate(name="Other"))
    s1 = await _session_in_chamber(c["id"], "G1", status="completed")
    await _session_in_chamber(c["id"], "G2")  # still active
    s3 = await _session_in_chamber(other["id"], "G3")

    await add_harvest(s1["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0, dry_weight_g=30.0))
    await add_harvest(s1["id"], HarvestCreate(flush_number=2, wet_weight_g=150.0, dry_weight_g=15.0))
    await add_harvest(s3["id"], HarvestCreate(flush_number=1, wet_weight_g=999.0))

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


def test_marking_contaminated_needs_no_body(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    r = client.post(f"/api/sessions/{s['id']}/contaminated")
    assert r.status_code == 200 and r.json()["status"] == "aborted"
    [event] = client.get(f"/api/contamination/events?session_id={s['id']}").json()
    assert event["contamination_type"] is None and event["chamber_id"] is None
    assert len(client.get("/api/contamination/events").json()) == 1


# ── Photos (derived from vision_frames) ─────────────────────────


async def test_photos_no_nodes():
    c = await create_chamber(ChamberCreate(name="No nodes"))
    assert await get_chamber_photos(c["id"]) == []


async def test_photos_are_the_chambers_nodes_frames_newest_first_up_to_the_limit():
    c = await create_chamber(ChamberCreate(name="Cam", node_ids=["cam-01", "climate-01"]))
    now = time.time()
    await _insert_frame("cam-01", now - 100, "old.jpg")
    await _insert_frame("cam-01", now - 10, "new.jpg")
    await _insert_frame("other-99", now, "unrelated.jpg")  # not a chamber node

    assert [p["file_path"] for p in await get_chamber_photos(c["id"])] == ["new.jpg", "old.jpg"]
    assert [p["file_path"] for p in await get_chamber_photos(c["id"], limit=1)] == ["new.jpg"]


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


def test_maintenance_is_scheduled_listed_newest_first_and_completed(client):
    cid = client.post("/api/chambers", json={"name": "Maint"}).json()["id"]
    due = time.time() + 86400
    assert client.post(f"/api/chambers/{cid}/maintenance",
                       json={"kind": "clean", "due_at": due, "notes": "PCO clean"}).status_code == 200
    resp = client.post(f"/api/chambers/{cid}/maintenance", json={"kind": "calibrate", "notes": "sensor recal"})
    assert resp.status_code == 200
    mid = resp.json()["id"]

    listed = client.get(f"/api/chambers/{cid}/maintenance").json()
    assert [(m["kind"], m["completed_at"]) for m in listed] == [("calibrate", None), ("clean", None)]

    resp = client.post(f"/api/chambers/{cid}/maintenance/{mid}/complete", json={"notes": "looked good"})
    assert resp.status_code == 200
    assert resp.json()["completed_at"] is not None and resp.json()["notes"] == "looked good"
    # A completion with no body keeps the entry's notes.
    first = listed[1]["id"]
    resp = client.post(f"/api/chambers/{cid}/maintenance/{first}/complete")
    assert resp.status_code == 200 and resp.json()["notes"] == "PCO clean"

    assert client.post(f"/api/chambers/{cid}/maintenance", json={"kind": "explode"}).status_code == 422


def test_lifecycle_routes_answer_404_for_an_unknown_chamber_or_entry(client):
    cid = client.post("/api/chambers", json={"name": "C"}).json()["id"]
    assert client.get("/api/chambers/9999/stats").status_code == 404
    assert client.get("/api/chambers/9999/photos").status_code == 404
    assert client.get("/api/chambers/9999/maintenance").status_code == 404
    assert client.post("/api/chambers/9999/maintenance", json={"kind": "clean"}).status_code == 404
    assert client.post(f"/api/chambers/{cid}/maintenance/9999/complete", json={}).status_code == 404
