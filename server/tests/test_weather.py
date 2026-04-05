"""Tests for weather service — virtual sensors, caching, API endpoints."""

import time

from app.weather.service import get_current_weather
import app.weather.service as weather_svc


def test_get_current_weather_empty_cache():
    assert get_current_weather() is None


def test_get_current_weather_returns_cached():
    weather_svc._cache = {
        "outdoor_temp_f": 85.0,
        "outdoor_humidity": 60,
        "forecast_high_f": 92.0,
    }
    weather_svc._cache_ts = time.time()
    result = get_current_weather()
    assert result is not None
    assert result["outdoor_temp_f"] == 85.0


def test_get_current_weather_stale_cache(monkeypatch):
    weather_svc._cache = {"outdoor_temp_f": 85.0}
    weather_svc._cache_ts = time.time() - 9999  # very stale
    monkeypatch.setattr("app.config.settings.weather_poll_minutes", 10)
    result = get_current_weather()
    assert result is None


async def test_weather_api_endpoint(client):
    """GET /api/weather/current returns data or unavailable message."""
    r = client.get("/api/weather/current")
    assert r.status_code == 200
    data = r.json()
    # Without API key configured, should return unavailable
    assert "status" in data or "outdoor_temp_f" in data


async def test_weather_history_empty(client):
    r = client.get("/api/weather/history")
    assert r.status_code == 200
    assert r.json() == []


async def test_weather_forecast_empty(client):
    """Without API key, forecast returns empty list."""
    r = client.get("/api/weather/forecast")
    assert r.status_code == 200
    assert r.json() == []
