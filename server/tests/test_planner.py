"""Tests for the seasonal grow planner — scoring, recommendations, calendar, warnings."""

import time

from app.species.models import GrowPhase, PhaseParams, SpeciesProfile
from app.species.service import seed_builtins, get_all_profiles
from app.planner.service import (
    score_species_match,
    get_recommendations,
    get_calendar_data,
    get_session_warnings,
    aggregate_daily_weather,
    INSULATION_BUFFER_F,
)


def _make_profile(**overrides) -> SpeciesProfile:
    """Helper to build a SpeciesProfile for scoring tests."""
    defaults = dict(
        id="test_oyster",
        common_name="Test Oyster",
        scientific_name="Pleurotus testii",
        category="gourmet",
        substrate_types=["straw"],
        colonization_visual_description="White mycelium",
        contamination_risk_notes="Watch for trich",
        pinning_trigger_description="Cold shock + FAE",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high", light_hours_on=0,
                light_hours_off=24, light_spectrum="none", fae_mode="none",
                expected_duration_days=(10, 14),
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
                light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
                expected_duration_days=(5, 7),
            ),
        },
        flush_count_typical=3,
        yield_notes="Good yielder",
        tags=["beginner", "fast"],
    )
    defaults.update(overrides)
    return SpeciesProfile(**defaults)


# --- Unit tests for score_species_match ---

def test_score_good_match():
    """Outdoor temp that puts estimated chamber right in the fruiting sweet spot."""
    profile = _make_profile()
    # Fruiting range is 55-65 F. Target mid = 60 F.
    # With 15 F insulation buffer, outdoor 45 F -> chamber ~60 F (perfect).
    result = score_species_match(profile, outdoor_temp_f=45.0, outdoor_humidity=88.0)
    assert result["score"] >= 80
    assert result["temp_score"] == 50  # within optimal
    assert result["humidity_score"] == 30  # close to target
    assert result["ease_score"] == 20  # beginner tag
    assert result["warnings"] == []


def test_score_poor_match_too_hot():
    """Very hot outdoor temp should yield low score and warnings."""
    profile = _make_profile()
    # Outdoor 85 F -> chamber ~100 F, way above 55-65 fruiting range
    result = score_species_match(profile, outdoor_temp_f=85.0, outdoor_humidity=30.0)
    assert result["score"] < 40
    assert result["temp_score"] == 0  # way too hot
    assert len(result["warnings"]) > 0
    assert "too hot" in result["warnings"][0].lower()


def test_score_poor_match_too_cold():
    """Very cold outdoor temp should yield low score and warnings."""
    profile = _make_profile()
    # Outdoor -10 F -> chamber ~5 F, way below 55-65 range
    result = score_species_match(profile, outdoor_temp_f=-10.0, outdoor_humidity=50.0)
    assert result["score"] < 40
    assert result["temp_score"] == 0
    assert len(result["warnings"]) > 0
    assert "too cold" in result["warnings"][0].lower()


def test_score_moderate_match():
    """Temperature in buffer zone — not perfect, not terrible."""
    profile = _make_profile()
    # Outdoor 55 F -> chamber ~70 F, just above fruiting max 65 F
    result = score_species_match(profile, outdoor_temp_f=55.0, outdoor_humidity=85.0)
    assert 30 <= result["score"] <= 80
    assert result["temp_score"] in (15, 30)  # buffer or manageable


def test_score_ease_intermediate():
    """Intermediate tag should give ease_score of 10."""
    profile = _make_profile(tags=["intermediate", "slow"])
    result = score_species_match(profile, outdoor_temp_f=45.0, outdoor_humidity=88.0)
    assert result["ease_score"] == 10


def test_score_ease_advanced():
    """Advanced species with no beginner/intermediate tag get ease_score 0."""
    profile = _make_profile(tags=["advanced", "slow"])
    result = score_species_match(profile, outdoor_temp_f=45.0, outdoor_humidity=88.0)
    assert result["ease_score"] == 0


def test_score_includes_species_info():
    """Result dict should contain species identification fields."""
    profile = _make_profile()
    result = score_species_match(profile, outdoor_temp_f=45.0, outdoor_humidity=88.0)
    assert result["species_id"] == "test_oyster"
    assert result["common_name"] == "Test Oyster"
    assert result["category"] == "gourmet"
    assert "est_chamber_temp_f" in result
    assert "fruiting_range_f" in result


# --- Integration tests using built-in species ---

async def test_recommend_returns_sorted_with_builtins():
    """Recommend endpoint should return all built-in species sorted by score."""
    await seed_builtins()
    results = await get_recommendations(outdoor_temp_f=50.0, outdoor_humidity=70.0)
    assert len(results) > 0

    # Should be sorted descending by score
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


async def test_recommend_category_filter():
    """Category filter should only return species of that category."""
    await seed_builtins()
    gourmet = await get_recommendations(outdoor_temp_f=50.0, outdoor_humidity=70.0, category="gourmet")
    assert all(r["category"] == "gourmet" for r in gourmet)

    medicinal = await get_recommendations(outdoor_temp_f=50.0, outdoor_humidity=70.0, category="medicinal")
    assert all(r["category"] == "medicinal" for r in medicinal)

    all_species = await get_recommendations(outdoor_temp_f=50.0, outdoor_humidity=70.0)
    assert len(all_species) > len(gourmet)


async def test_calendar_empty_without_history():
    """Calendar should return empty list when no weather_history data exists."""
    result = await get_calendar_data()
    assert result == []


async def test_calendar_returns_data_with_history():
    """Calendar returns monthly data when weather_history has entries."""
    from app.db import get_db

    await seed_builtins()

    # Insert some weather_history rows
    async with get_db() as db:
        for month in range(1, 4):  # Jan, Feb, Mar
            date_str = f"2025-{month:02d}-15"
            # Cooler in winter, warmer toward spring
            temp = 30.0 + month * 10
            await db.execute(
                """INSERT INTO weather_history
                   (date, outdoor_temp_avg_f, outdoor_humidity_avg)
                   VALUES (?, ?, ?)""",
                (date_str, temp, 60.0),
            )
        await db.commit()

    result = await get_calendar_data()
    assert len(result) == 3
    assert result[0]["month"] == 1
    assert result[0]["month_name"] == "January"
    assert len(result[0]["top_species"]) > 0
    assert len(result[0]["top_species"]) <= 10
    # Top species should be sorted by score
    species_scores = [s["score"] for s in result[0]["top_species"]]
    assert species_scores == sorted(species_scores, reverse=True)


async def test_warnings_session_not_found():
    """Warnings for nonexistent session should return info level."""
    result = await get_session_warnings(99999)
    assert result["level"] == "info"
    assert "not found" in result["message"].lower()


async def test_warnings_with_session(monkeypatch):
    """Warnings endpoint should work with a valid session and weather data."""
    import app.weather.service as wsvc
    from app.db import get_db
    from app.species.service import seed_builtins

    await seed_builtins()

    # Create a session
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO sessions (name, species_profile_id, current_phase, status)
               VALUES (?, ?, ?, ?)""",
            ("Test Grow", "blue_oyster", "fruiting", "active"),
        )
        session_id = cursor.lastrowid
        await db.commit()

    # Set up weather cache with warm conditions
    wsvc._cache = {"outdoor_temp_f": 75.0, "outdoor_humidity": 60}
    wsvc._cache_ts = time.time()
    wsvc._forecast_cache = []
    wsvc._forecast_cache_ts = time.time()

    result = await get_session_warnings(session_id)
    assert result["session_id"] == session_id
    assert result["level"] in ("ok", "info", "warning", "critical")
    assert "message" in result
    assert "forecast_warnings" in result


async def test_warnings_critical_heat(monkeypatch):
    """Extreme heat should trigger critical warning."""
    import app.weather.service as wsvc
    from app.db import get_db

    await seed_builtins()

    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO sessions (name, species_profile_id, current_phase, status)
               VALUES (?, ?, ?, ?)""",
            ("Hot Grow", "blue_oyster", "fruiting", "active"),
        )
        session_id = cursor.lastrowid
        await db.commit()

    # Blue oyster fruiting max is 65 F. Outdoor 80 F -> chamber ~95 F -> critical
    wsvc._cache = {"outdoor_temp_f": 80.0, "outdoor_humidity": 50}
    wsvc._cache_ts = time.time()
    wsvc._forecast_cache = []
    wsvc._forecast_cache_ts = time.time()

    result = await get_session_warnings(session_id)
    assert result["level"] == "critical"


async def test_aggregate_daily_weather_idempotent():
    """Running aggregation twice should not create duplicate rows."""
    from app.db import get_db

    # Insert a weather reading for yesterday
    from datetime import datetime, timedelta, timezone
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    ts = yesterday.replace(hour=12).timestamp()

    async with get_db() as db:
        await db.execute(
            """INSERT INTO weather_readings (timestamp, provider, temp_f, humidity)
               VALUES (?, ?, ?, ?)""",
            (ts, "test", 72.0, 55.0),
        )
        await db.commit()

    await aggregate_daily_weather()
    await aggregate_daily_weather()  # second call should be no-op

    async with get_db() as db:
        date_str = yesterday.strftime("%Y-%m-%d")
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM weather_history WHERE date = ?", (date_str,)
        )
        row = await cursor.fetchone()
        assert dict(row)["cnt"] == 1


# --- API endpoint tests ---

async def test_recommend_endpoint(client):
    """GET /api/planner/recommend returns sorted species list."""
    r = client.get("/api/planner/recommend?outdoor_temp_f=50&outdoor_humidity=70")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    # Should be sorted by score descending
    scores = [d["score"] for d in data]
    assert scores == sorted(scores, reverse=True)


async def test_recommend_endpoint_with_category(client):
    """GET /api/planner/recommend with category filter."""
    r = client.get("/api/planner/recommend?outdoor_temp_f=50&outdoor_humidity=70&category=gourmet")
    assert r.status_code == 200
    data = r.json()
    assert all(d["category"] == "gourmet" for d in data)


async def test_calendar_endpoint(client):
    """GET /api/planner/calendar returns data (possibly empty)."""
    r = client.get("/api/planner/calendar")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


async def test_warnings_endpoint(client):
    """GET /api/planner/warnings/{session_id} returns warning structure."""
    r = client.get("/api/planner/warnings/99999")
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == "info"
    assert "forecast_warnings" in data
