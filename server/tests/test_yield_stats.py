"""Tests for yield statistics + biological efficiency (Task 7)."""

from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import (
    create_session,
    add_harvest,
    complete_session,
    get_session_stats,
    _parse_volume_to_liters,
)


def _make_session(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="cubensis_golden_teacher")
    defaults.update(overrides)
    return SessionCreate(**defaults)


# ── Volume parsing ──────────────────────────────────────────────


def test_parse_volume_quarts():
    assert round(_parse_volume_to_liters("5 quarts"), 2) == 4.73


def test_parse_volume_liters():
    assert _parse_volume_to_liters("10 liters") == 10.0


def test_parse_volume_gallons():
    assert round(_parse_volume_to_liters("2 gallons"), 2) == 7.57


def test_parse_volume_none():
    assert _parse_volume_to_liters(None) is None


def test_parse_volume_unparseable():
    assert _parse_volume_to_liters("a bunch") is None


# ── Stats with no harvests ──────────────────────────────────────


async def test_stats_no_harvests():
    s = await create_session(_make_session())
    stats = await get_session_stats(s["id"])
    assert stats is not None
    assert stats["session_id"] == s["id"]
    assert stats["flush_yields"] == []
    assert stats["flush_decline_pct"] == []
    assert stats["total_wet_yield_g"] == 0.0
    assert stats["total_dry_yield_g"] == 0.0
    assert stats["flush_count"] == 0
    assert stats["biological_efficiency"] is None
    assert stats["species_avg_yield_g"] is None
    assert stats["species_best_yield_g"] is None
    assert stats["species_session_count"] == 0


# ── Stats with multiple flushes ─────────────────────────────────


async def test_stats_multiple_flushes():
    s = await create_session(_make_session(substrate_volume="5 quarts"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0, dry_weight_g=20.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=140.0, dry_weight_g=14.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=3, wet_weight_g=80.0, dry_weight_g=8.0))

    stats = await get_session_stats(s["id"])
    assert stats["flush_count"] == 3
    assert stats["total_wet_yield_g"] == 420.0
    assert stats["total_dry_yield_g"] == 42.0

    # Flush yields
    assert len(stats["flush_yields"]) == 3
    assert stats["flush_yields"][0]["wet_weight_g"] == 200.0
    assert stats["flush_yields"][1]["wet_weight_g"] == 140.0
    assert stats["flush_yields"][2]["wet_weight_g"] == 80.0

    # Decline: flush 1→2 = 30%, flush 2→3 ≈ 42.9%
    assert len(stats["flush_decline_pct"]) == 2
    assert stats["flush_decline_pct"][0] == 30.0
    assert stats["flush_decline_pct"][1] == 42.9

    # Biological Efficiency: 420 / (5 * 0.946353 * 300) * 100 ≈ 29.6
    assert stats["biological_efficiency"] is not None
    assert 29.0 <= stats["biological_efficiency"] <= 30.0


# ── Species averages ────────────────────────────────────────────


async def test_species_averages():
    species = "pleurotus_ostreatus"

    # Create two completed sessions with different yields
    s1 = await create_session(_make_session(name="Grow 1", species_profile_id=species))
    await add_harvest(s1["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0))
    await complete_session(s1["id"])

    s2 = await create_session(_make_session(name="Grow 2", species_profile_id=species))
    await add_harvest(s2["id"], HarvestCreate(flush_number=1, wet_weight_g=500.0))
    await complete_session(s2["id"])

    # Stats for s2 should include species averages from both completed sessions
    stats = await get_session_stats(s2["id"])
    assert stats["species_session_count"] == 2
    assert stats["species_avg_yield_g"] == 400.0
    assert stats["species_best_yield_g"] == 500.0


# ── 404 for nonexistent session ─────────────────────────────────


async def test_stats_nonexistent_session():
    stats = await get_session_stats(99999)
    assert stats is None


# ── HTTP endpoint tests ─────────────────────────────────────────


def test_stats_endpoint(client):
    r = client.post("/api/sessions", json={
        "name": "Stats Grow",
        "species_profile_id": "cubensis_golden_teacher",
        "substrate_volume": "10 liters",
    })
    session_id = r.json()["id"]

    client.post(f"/api/sessions/{session_id}/harvest", json={
        "flush_number": 1, "wet_weight_g": 250.0, "dry_weight_g": 25.0,
    })

    r = client.get(f"/api/sessions/{session_id}/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_wet_yield_g"] == 250.0
    assert data["flush_count"] == 1
    # BE: 250 / (10 * 300) * 100 ≈ 8.3
    assert 8.0 <= data["biological_efficiency"] <= 9.0


def test_stats_endpoint_404(client):
    r = client.get("/api/sessions/99999/stats")
    assert r.status_code == 404
