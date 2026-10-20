"""Tests for weather service — virtual sensors, caching, API endpoints."""

import asyncio
import time

import pytest

from app import settings_service
from app.config import settings
from app.db import get_db
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


# ── the poll loop ──────────────────────────────────────────────────────────


class _FakeProvider:
    name = "fake"

    def __init__(self, forecast: list[dict]):
        self.forecast = forecast

    async def fetch_current(self, lat, lon):
        return {"outdoor_temp_f": 60.0, "outdoor_humidity": 50, "outdoor_dew_point_f": 41.0,
                "outdoor_wind_mph": 3.0, "outdoor_pressure_mb": 1013.0,
                "outdoor_condition": "Clear"}

    async def fetch_forecast(self, lat, lon):
        return self.forecast


async def _one_poll(monkeypatch, minutes: int, provider: _FakeProvider) -> list[float]:
    """Run the poll loop once; the sleeps it asked for."""
    monkeypatch.setattr(settings, "weather_poll_minutes", minutes)
    monkeypatch.setattr(settings, "weather_lat", "40.7")
    monkeypatch.setattr(settings, "weather_lon", "-74.0")
    monkeypatch.setattr(weather_svc, "_get_providers", lambda: [provider])
    slept: list[float] = []

    async def stop_after_the_first_poll(seconds):
        slept.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(weather_svc.asyncio, "sleep", stop_after_the_first_poll)
    with pytest.raises(asyncio.CancelledError):
        await weather_svc.start_weather_polling(None)
    return slept


@pytest.mark.parametrize("minutes", [0, -5])
async def test_a_poll_interval_below_one_minute_waits_a_minute(monkeypatch, minutes):
    """0 or a negative interval made the loop re-poll back to back."""
    assert await _one_poll(monkeypatch, minutes, _FakeProvider([])) == [60]


def test_a_fresh_reading_is_not_stale_with_a_zero_interval(monkeypatch):
    """A 0 interval made every reading stale at once, so no outdoor value
    reached the rules."""
    monkeypatch.setattr(settings, "weather_poll_minutes", 0)
    weather_svc._cache = {"outdoor_temp_f": 85.0}
    weather_svc._cache_ts = time.time()
    weather_svc._forecast_cache = [{"timestamp": time.time() + 3600, "temp_f": 80.0}]
    weather_svc._forecast_cache_ts = time.time()
    assert get_current_weather() is not None
    assert weather_svc.get_forecast_cached() != []


async def test_a_poll_keeps_the_forecast_in_memory_only(monkeypatch):
    """Every poll deleted and re-inserted the whole hourly forecast in
    weather_forecasts, a table nothing reads."""
    forecast = [{"timestamp": time.time() + 3600 * i, "temp_f": 60.0 + i, "humidity": 50,
                 "wind_mph": 2.0, "condition": "Clear"} for i in range(1, 25)]
    await _one_poll(monkeypatch, 10, _FakeProvider(forecast))
    assert weather_svc._forecast_cache == forecast
    async with get_db() as db:
        row = await (await db.execute("SELECT COUNT(*) AS n FROM weather_forecasts")).fetchone()
    assert row["n"] == 0


# ── weather settings ───────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["0", "-5", "1.5", "abc"])
async def test_a_poll_interval_that_is_not_a_whole_minute_or_more_is_refused(value):
    before = settings.weather_poll_minutes
    with pytest.raises(ValueError):
        await settings_service.set_setting("weather_poll_minutes", value)
    assert settings.weather_poll_minutes == before
    assert (await settings_service.get_all_settings())["weather_poll_minutes"]["source"] != "user"


def test_put_of_a_zero_poll_interval_is_a_400(client):
    r = client.put("/api/settings/weather_poll_minutes", json={"value": "0"})
    assert r.status_code == 400


async def test_the_weather_provider_must_be_a_registered_one(monkeypatch):
    monkeypatch.setattr(settings, "weather_provider", settings.weather_provider)
    with pytest.raises(ValueError):
        await settings_service.set_setting("weather_provider", "openweather")
    await settings_service.set_setting("weather_provider", "nws")
    assert settings.weather_provider == "nws"
