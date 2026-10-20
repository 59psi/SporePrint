"""Tests for the seasonal grow planner — scoring, recommendations, calendar, warnings.

The nightly weather aggregation is in test_planner_aggregation.py."""

import time
from datetime import datetime, timedelta

import pytest

import app.weather.service as weather_svc
from app.db import get_db
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import advance_phase, create_session
from app.species.service import seed_builtins
from app.planner.service import (
    score_species_match,
    get_calendar_data,
    get_session_warnings,
)
from tests._builders import custom_profile

DAY = 86_400


def _make_profile(**overrides):
    """Fruiting at 55-65 °F (target 60 °F) and 85-92 % RH (target 88.5 %)."""
    return custom_profile(**{"id": "test_oyster", "common_name": "Test Oyster",
                             "tags": ["beginner", "fast"], **overrides})


# --- score_species_match: the chamber is ~15 °F above outdoors ---


@pytest.mark.parametrize(("outdoor_f", "outdoor_rh", "temp_score", "humidity_score", "warning"), [
    (45.0, 88.0, 50, 30, None),             # chamber ~60 °F: the sweet spot
    (55.0, 85.0, 30, 30, "may run warm"),   # ~70 °F: one range-width out
    (35.0, 88.0, 30, 30, "may run cool"),   # ~50 °F
    (62.0, 70.0, 15, 15, "too hot"),        # ~77 °F: manageable, past max + 10
    (85.0, 30.0, 0, 5, "too hot"),          # ~100 °F
    (-10.0, 50.0, 0, 5, "too cold"),        # ~5 °F
], ids=["sweet-spot", "warm", "cool", "manageable-hot", "far-too-hot", "far-too-cold"])
def test_score_bands_and_warnings(outdoor_f, outdoor_rh, temp_score, humidity_score, warning):
    result = score_species_match(_make_profile(), outdoor_temp_f=outdoor_f, outdoor_humidity=outdoor_rh)
    assert (result["temp_score"], result["humidity_score"], result["ease_score"]) == (
        temp_score, humidity_score, 20)
    assert result["score"] == temp_score + humidity_score + 20
    assert result["est_chamber_temp_f"] == outdoor_f + 15
    if warning is None:
        assert result["warnings"] == []
    else:
        [message] = result["warnings"]
        assert warning in message.lower()
    assert (result["species_id"], result["common_name"], result["category"], result["fruiting_range_f"]) == (
        "test_oyster", "Test Oyster", "gourmet", "55-65")


def test_ease_follows_the_difficulty_tag():
    ease = {tags: score_species_match(_make_profile(tags=list(tags)), 45.0, 88.0)["ease_score"]
            for tags in (("beginner", "fast"), ("intermediate", "slow"), ("advanced", "slow"))}
    assert ease == {("beginner", "fast"): 20, ("intermediate", "slow"): 10, ("advanced", "slow"): 0}


# --- recommendations and the calendar ---


def test_recommendations_come_best_first_and_filter_by_category(client):
    r = client.get("/api/planner/recommend?outdoor_temp_f=50&outdoor_humidity=70")
    assert r.status_code == 200
    every = r.json()
    scores = [d["score"] for d in every]
    assert scores and scores == sorted(scores, reverse=True)
    for category in ("gourmet", "medicinal"):
        narrowed = client.get(
            f"/api/planner/recommend?outdoor_temp_f=50&outdoor_humidity=70&category={category}").json()
        assert narrowed and {d["category"] for d in narrowed} == {category}
        assert len(narrowed) < len(every)


async def test_calendar_returns_data_with_history():
    """Calendar returns monthly data when weather_history has entries."""
    await seed_builtins()

    async with get_db() as db:
        for month in range(1, 4):  # Jan, Feb, Mar
            # Cooler in winter, warmer toward spring
            await db.execute(
                "INSERT INTO weather_history (date, outdoor_temp_avg_f, outdoor_humidity_avg) VALUES (?, ?, ?)",
                (f"2025-{month:02d}-15", 30.0 + month * 10, 60.0),
            )
        await db.commit()

    result = await get_calendar_data()
    assert [(m["month"], m["month_name"]) for m in result] == [
        (1, "January"), (2, "February"), (3, "March")]
    assert 0 < len(result[0]["top_species"]) <= 10
    # Top species should be sorted by score
    species_scores = [s["score"] for s in result[0]["top_species"]]
    assert species_scores == sorted(species_scores, reverse=True)


# --- session warnings (blue oyster fruits at 55-65 °F) ---


def _weather(monkeypatch, current=None, forecast=(), age=0.0):
    monkeypatch.setattr(weather_svc, "_cache", current or {})
    monkeypatch.setattr(weather_svc, "_cache_ts", time.time() - age)
    monkeypatch.setattr(weather_svc, "_forecast_cache", list(forecast))
    monkeypatch.setattr(weather_svc, "_forecast_cache_ts", time.time() - age)


async def _grow(phase="fruiting", species="blue_oyster"):
    await seed_builtins()
    return await create_session(SessionCreate(name="Grow", species_profile_id=species, current_phase=phase))


@pytest.mark.parametrize(("outdoor_f", "level", "says"), [
    (80.0, "critical", "far exceeds"),   # chamber ~95 °F
    (55.0, "warning", "running warm"),   # ~70 °F
    (45.0, "ok", "look good"),           # ~60 °F
    (35.0, "warning", "running cool"),   # ~50 °F
    (20.0, "critical", "far below"),     # ~35 °F
], ids=["far-too-hot", "warm", "ok", "cool", "far-too-cold"])
async def test_current_weather_sets_the_warning_level(outdoor_f, level, says, monkeypatch):
    s = await _grow()
    _weather(monkeypatch, current={"outdoor_temp_f": outdoor_f, "outdoor_humidity": 50})
    result = await get_session_warnings(s["id"])
    assert (result["session_id"], result["level"], result["forecast_warnings"]) == (s["id"], level, [])
    assert says in result["message"]


async def test_a_week_of_hot_days_ahead_escalates_to_a_warning(monkeypatch):
    s = await _grow()
    now = time.time()
    _weather(monkeypatch, forecast=[{"timestamp": now + d * DAY, "temp_f": 70.0} for d in range(1, 5)])
    result = await get_session_warnings(s["id"])
    assert [w["issue"] for w in result["forecast_warnings"]] == ["hot"] * 4
    assert result["level"] == "warning"
    assert result["message"].startswith("4 of the next 7 days")


async def test_warnings_for_a_rest_session_use_the_fruiting_envelope(monkeypatch):
    """Rest borrows the fruiting envelope the engine runs it on; the warnings
    answered "No parameters for phase 'rest'" and stayed silent."""
    s = await _grow()
    await advance_phase(s["id"], PhaseAdvance(phase="rest"))
    _weather(monkeypatch, current={"outdoor_temp_f": 80.0, "outdoor_humidity": 50})
    assert (await get_session_warnings(s["id"]))["level"] == "critical"


async def test_no_warning_without_setpoints_to_judge_by(monkeypatch):
    _weather(monkeypatch, current={"outdoor_temp_f": 80.0, "outdoor_humidity": 50})
    jar = await _grow("cold_storage")
    unknown = await _grow(species="no_such_species")
    assert (await get_session_warnings(jar["id"]))["message"] == "No parameters for phase 'cold_storage'."
    assert (await get_session_warnings(unknown["id"]))["message"] == "Species profile not found."
    for sid in (jar["id"], unknown["id"]):
        assert (await get_session_warnings(sid))["level"] == "info"


def test_warnings_endpoint_for_an_unknown_session(client):
    r = client.get("/api/planner/warnings/99999")
    assert r.status_code == 200
    assert r.json() == {"level": "info", "message": "Session not found.", "forecast_warnings": []}


async def test_stale_weather_is_not_reported_as_current(monkeypatch):
    """Once the providers stop answering, the last reading ages out (the
    rules' get_current_weather): the warnings read it unchecked and called a
    days-old outdoor temperature 'Current ... Immediate action needed'."""
    s = await _grow()
    _weather(monkeypatch, current={"outdoor_temp_f": 80.0, "outdoor_humidity": 50},
             forecast=[{"timestamp": time.time() + 7200, "temp_f": 95.0}], age=3 * DAY)

    result = await get_session_warnings(s["id"])
    assert result["level"] == "ok"
    assert "Current outdoor temp" not in result["message"]
    assert result["forecast_warnings"] == []

    monkeypatch.setattr(weather_svc, "_cache_ts", time.time())
    assert (await get_session_warnings(s["id"]))["level"] == "critical"


async def test_forecast_warnings_skip_null_hours_and_use_the_local_day(pacific_time, monkeypatch):
    """A null forecast temperature made the day average raise TypeError (a
    500), and an evening hour was filed under the next UTC day."""
    s = await _grow()
    evening = (datetime.now() + timedelta(days=1)).replace(hour=20, minute=0, second=0,
                                                           microsecond=0)
    _weather(monkeypatch, forecast=[
        {"timestamp": evening.timestamp(), "temp_f": None, "humidity": 50},
        {"timestamp": evening.timestamp() + 3600, "temp_f": 80.0, "humidity": None},
    ])

    [warning] = (await get_session_warnings(s["id"]))["forecast_warnings"]
    assert warning["date"] == evening.date().isoformat()
    assert warning["day"] == evening.strftime("%a")
    assert warning["issue"] == "hot"
