"""Tests for yield statistics + biological efficiency."""

import time

import pytest

from app.db import get_db
from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import (
    create_session,
    add_harvest,
    complete_session,
    get_session_stats,
    _parse_volume_to_liters,
)


def _make_session(**overrides):
    defaults = dict(name="Test Grow", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


# Biological efficiency: wet grams per 300 g of dry substrate per litre, as a percent.
def _be(wet_g, liters):
    return round(wet_g / (liters * 300) * 100, 1)


# ── Volume parsing ──────────────────────────────────────────────


@pytest.mark.parametrize(("text", "liters"), [
    ("5 quarts", 4.7318),
    ("10 liters", 10.0),
    ("2 gallons", 7.5708),
    (".5 gal", 1.8927),
    ("1,5 l", 1.5),                 # a decimal comma
    ("12 x 1.5 L", 18.0),           # a count of containers
    ("3×2 l bags", 6.0),
    (None, None),
    ("a bunch", None),
    # '[\\d.]+' took a lone '.', and float('.') turned /stats, the report and
    # the session list into 500s.
    ("approx. L", None), ("1.5.2 l", None), ("2.5. L", None), ("1..5 L", None),
    ("Std. qt jar", None), ("... gallon bag", None), ("5 lbs", None),
])
def test_parse_volume_to_liters(text, liters):
    parsed = _parse_volume_to_liters(text)
    assert parsed == (None if liters is None else pytest.approx(liters, rel=1e-3))


def test_parse_volume_is_linear_on_a_long_run_of_digits():
    """The pattern backtracked quadratically: 20,000 digits took seconds on
    the event loop."""
    started = time.perf_counter()
    assert _parse_volume_to_liters("9" * 200_000) is None
    assert _parse_volume_to_liters("." * 200_000 + "1 L") is None
    assert time.perf_counter() - started < 1.0


async def test_an_unreadable_volume_gives_no_efficiency_not_an_error():
    s = await create_session(_make_session(substrate_volume="approx. L"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    assert (await get_session_stats(s["id"]))["biological_efficiency"] is None


def test_an_overlong_volume_is_422(client):
    r = client.post("/api/sessions", json={
        "name": "V", "species_profile_id": "blue_oyster", "substrate_volume": "9" * 101})
    assert r.status_code == 422


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
    assert [f["wet_weight_g"] for f in stats["flush_yields"]] == [200.0, 140.0, 80.0]
    # Decline: flush 1→2 = 30%, flush 2→3 ≈ 42.9%
    assert stats["flush_decline_pct"] == [30.0, 42.9]
    assert stats["biological_efficiency"] == _be(420, 5 * 0.946353)


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


# ── When the newest harvest was logged ──────────────────────────


async def test_stats_report_when_the_newest_harvest_was_logged():
    """The dashboard numbers a grow's next flush from its newest harvest's
    time; the stats carry it, so the dashboard need not read the grow's
    whole event history to find it."""
    s = await create_session(_make_session())
    assert (await get_session_stats(s["id"]))["last_harvest_at"] is None
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=120.0))
    async with get_db() as db:
        # The newest by time, whatever its flush number.
        await db.execute(
            "UPDATE harvests SET timestamp = ? WHERE session_id = ? AND flush_number = 1",
            (1_700_000_500.0, s["id"]),
        )
        await db.execute(
            "UPDATE harvests SET timestamp = ? WHERE session_id = ? AND flush_number = 2",
            (1_700_000_100.0, s["id"]),
        )
        await db.commit()
    assert (await get_session_stats(s["id"]))["last_harvest_at"] == 1_700_000_500.0


# ── HTTP endpoint tests ─────────────────────────────────────────


def test_session_rows_carry_the_stats_biological_efficiency(client):
    """sessions.biological_efficiency is never written, so every GET
    /api/sessions row carried null while /stats computed a value."""
    r = client.post("/api/sessions", json={
        "name": "BE Grow", "species_profile_id": "blue_oyster",
        "substrate_volume": "5 quarts",
    })
    session_id = r.json()["id"]
    assert r.json()["biological_efficiency"] == 0.0  # volume known, nothing harvested
    client.post(f"/api/sessions/{session_id}/harvest", json={
        "flush_number": 1, "wet_weight_g": 400.0})
    client.post(f"/api/sessions/{session_id}/harvest", json={
        "flush_number": 2, "wet_weight_g": 150.0})

    stats = client.get(f"/api/sessions/{session_id}/stats").json()
    assert (stats["total_wet_yield_g"], stats["flush_count"]) == (550.0, 2)
    stats_be = stats["biological_efficiency"]
    assert stats_be == _be(550, 5 * 0.946353)
    listed = next(s for s in client.get("/api/sessions").json() if s["id"] == session_id)
    assert listed["biological_efficiency"] == stats_be
    assert client.get(f"/api/sessions/{session_id}").json()["biological_efficiency"] == stats_be


def test_a_session_without_a_volume_has_no_biological_efficiency(client):
    r = client.post("/api/sessions", json={"name": "No volume", "species_profile_id": "blue_oyster"})
    assert r.json()["biological_efficiency"] is None
    listed = client.get("/api/sessions").json()
    assert all(s["biological_efficiency"] is None for s in listed)
