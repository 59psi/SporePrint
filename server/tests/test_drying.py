"""Tests for harvest drying tracker (Task 8)."""

from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import (
    create_session,
    add_harvest,
    add_drying_log,
    get_drying_progress,
)


def _make_session(**overrides):
    defaults = dict(name="Drying Test", species_profile_id="cubensis_golden_teacher")
    defaults.update(overrides)
    return SessionCreate(**defaults)


# ── Full drying flow (service layer) ────────────────────────────


async def test_full_drying_flow():
    s = await create_session(_make_session())
    h = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    harvest_id = h["id"]
    session_id = s["id"]

    # Log progressive weight loss: 200 → 150 → 50 → 18g
    p1 = await add_drying_log(session_id, harvest_id, 150.0)
    assert p1 is not None
    assert p1["fresh_weight_g"] == 200.0
    assert p1["current_weight_g"] == 150.0
    assert p1["moisture_loss_pct"] == 25.0
    assert p1["target_reached"] is False
    assert len(p1["entries"]) == 1

    p2 = await add_drying_log(session_id, harvest_id, 50.0)
    assert p2["current_weight_g"] == 50.0
    assert p2["moisture_loss_pct"] == 75.0
    assert p2["target_reached"] is False
    assert len(p2["entries"]) == 2

    # 18g = 91% moisture loss → cracker dry
    p3 = await add_drying_log(session_id, harvest_id, 18.0)
    assert p3["current_weight_g"] == 18.0
    assert p3["moisture_loss_pct"] == 91.0
    assert p3["target_reached"] is True
    assert p3["dry_wet_ratio"] == 0.09
    assert len(p3["entries"]) == 3


async def test_get_drying_progress():
    s = await create_session(_make_session())
    h = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))

    # Before any drying logs, progress shows fresh weight
    progress = await get_drying_progress(s["id"], h["id"])
    assert progress is not None
    assert progress["harvest_id"] == h["id"]
    assert progress["flush_number"] == 1
    assert progress["fresh_weight_g"] == 100.0
    assert progress["current_weight_g"] == 100.0
    assert progress["moisture_loss_pct"] == 0.0
    assert progress["target_reached"] is False
    assert progress["entries"] == []

    # Add one entry and check
    await add_drying_log(s["id"], h["id"], 60.0)
    progress = await get_drying_progress(s["id"], h["id"])
    assert progress["current_weight_g"] == 60.0
    assert progress["moisture_loss_pct"] == 40.0


# ── 404 for nonexistent harvest ─────────────────────────────────


async def test_drying_log_nonexistent_harvest():
    s = await create_session(_make_session())
    result = await add_drying_log(s["id"], 99999, 50.0)
    assert result is None


async def test_drying_progress_nonexistent_harvest():
    s = await create_session(_make_session())
    result = await get_drying_progress(s["id"], 99999)
    assert result is None


async def test_drying_log_wrong_session():
    """Harvest exists but belongs to a different session."""
    s1 = await create_session(_make_session(name="Session 1"))
    s2 = await create_session(_make_session(name="Session 2"))
    h = await add_harvest(s1["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))

    # Try to log drying against s2 — should fail
    result = await add_drying_log(s2["id"], h["id"], 50.0)
    assert result is None


# ── HTTP endpoint tests ─────────────────────────────────────────


def test_drying_log_endpoint(client):
    # Create session + harvest
    r = client.post("/api/sessions", json={
        "name": "Drying API Test",
        "species_profile_id": "cubensis_golden_teacher",
    })
    session_id = r.json()["id"]

    r = client.post(f"/api/sessions/{session_id}/harvest", json={
        "flush_number": 1, "wet_weight_g": 200.0,
    })
    harvest_id = r.json()["id"]

    # POST drying log entry
    r = client.post(
        f"/api/sessions/{session_id}/harvest/{harvest_id}/drying-log",
        json={"weight_g": 150.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["current_weight_g"] == 150.0
    assert data["moisture_loss_pct"] == 25.0

    # GET drying progress
    r = client.get(f"/api/sessions/{session_id}/harvest/{harvest_id}/drying")
    assert r.status_code == 200
    data = r.json()
    assert data["current_weight_g"] == 150.0
    assert len(data["entries"]) == 1


def test_drying_endpoint_404(client):
    r = client.post(
        "/api/sessions/1/harvest/99999/drying-log",
        json={"weight_g": 50.0},
    )
    assert r.status_code == 404

    r = client.get("/api/sessions/1/harvest/99999/drying")
    assert r.status_code == 404
