"""Tests for weather service — virtual sensors, caching, dew point calculation."""

import time
from unittest.mock import AsyncMock, patch

from app.weather.service import (
    get_current_weather,
    _dew_point,
    _cache,
    _cache_ts,
)
import app.weather.service as weather_svc


def _reset_weather_cache():
    weather_svc._cache = {}
    weather_svc._cache_ts = 0


def test_dew_point_calculation():
    dp = _dew_point(75.0, 50.0)
    assert 54 < dp < 58  # ~55.6°F for 75°F at 50% RH


def test_dew_point_high_humidity():
    dp = _dew_point(75.0, 95.0)
    assert 72 < dp < 75  # close to air temp at high RH


def test_dew_point_zero_humidity():
    dp = _dew_point(75.0, 0.0)
    # Should not crash, returns fallback
    assert isinstance(dp, float)


def test_get_current_weather_empty_cache():
    _reset_weather_cache()
    assert get_current_weather() is None


def test_get_current_weather_returns_cached():
    _reset_weather_cache()
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
    _reset_weather_cache()
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
