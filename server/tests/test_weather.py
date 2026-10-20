"""The weather service: the cached reading, the routes, the poll loop and the
weather settings.

* The cached reading is served until two poll intervals pass, then the
  outdoor values stop reaching the rules; an interval under a minute reads as
  one minute (it used to re-poll back to back and make every reading stale
  at once).
* The routes serve the cached reading, the stored history, the forecast and
  the model status, or say the weather is unavailable.
* A poll keeps the forecast in memory only.
* The interval must be a whole number of minutes, one or more, and the
  provider a registered one.
"""

import asyncio
import time

import pytest

from app import settings_service
from app.config import settings
from app.db import get_db
from app.weather.service import get_current_weather
import app.weather.service as weather_svc


def test_a_cached_reading_is_served_until_two_poll_intervals_pass(monkeypatch):
    monkeypatch.setattr(settings, "weather_poll_minutes", 10)
    assert get_current_weather() is None  # nothing polled yet
    monkeypatch.setattr(weather_svc, "_cache", {"outdoor_temp_f": 85.0})
    monkeypatch.setattr(weather_svc, "_cache_ts", time.time() - 19 * 60)
    assert get_current_weather() == {"outdoor_temp_f": 85.0}
    monkeypatch.setattr(weather_svc, "_cache_ts", time.time() - 21 * 60)
    assert get_current_weather() is None


def test_weather_routes_serve_the_cached_reading_or_say_it_is_unavailable(client):
    assert client.get("/api/weather/current").json()["status"] == "unavailable"
    assert client.get("/api/weather/forecast").json() == []
    assert client.get("/api/weather/history").json() == []

    asyncio.run(weather_svc._update_current_cache(
        {"outdoor_temp_f": 61.0, "outdoor_humidity": 70}, "nws"))
    current = client.get("/api/weather/current").json()
    assert (current["outdoor_temp_f"], current["provider"]) == (61.0, "nws")
    [stored] = client.get("/api/weather/history").json()
    assert (stored["temp_f"], stored["humidity"], stored["provider"]) == (61.0, 70, "nws")
    model = client.get("/api/weather/model")
    assert model.status_code == 200 and isinstance(model.json(), dict)


# ── the poll loop ──────────────────────────────────────────────────────────


class _FakeProvider:
    def __init__(self, forecast: list[dict], name: str = "fake"):
        self.forecast = forecast
        self.name = name

    async def fetch_current(self, lat, lon):
        return {"outdoor_temp_f": 60.0, "outdoor_humidity": 50, "outdoor_dew_point_f": 41.0,
                "outdoor_wind_mph": 3.0, "outdoor_pressure_mb": 1013.0,
                "outdoor_condition": "Clear"}

    async def fetch_forecast(self, lat, lon):
        return self.forecast


async def _one_poll(monkeypatch, minutes: int, *providers: _FakeProvider) -> list[float]:
    """Run the poll loop once over ``providers`` (in failover order); the
    sleeps it asked for."""
    monkeypatch.setattr(settings, "weather_poll_minutes", minutes)
    monkeypatch.setattr(settings, "weather_lat", "40.7")
    monkeypatch.setattr(settings, "weather_lon", "-74.0")
    monkeypatch.setattr(weather_svc, "_get_providers", lambda: list(providers))
    slept: list[float] = []

    async def stop_after_the_first_poll(seconds):
        slept.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(weather_svc.asyncio, "sleep", stop_after_the_first_poll)
    with pytest.raises(asyncio.CancelledError):
        await weather_svc.start_weather_polling(None)
    return slept


@pytest.mark.parametrize("minutes", [0, -5])
async def test_a_poll_interval_under_a_minute_reads_as_one_minute(monkeypatch, minutes):
    """0 or a negative interval made the loop re-poll back to back, and made
    every reading stale at once, so no outdoor value reached the rules."""
    forecast = [{"timestamp": time.time() + 3600, "temp_f": 80.0, "humidity": 50,
                 "wind_mph": 2.0, "condition": "Clear"}]
    assert await _one_poll(monkeypatch, minutes, _FakeProvider(forecast)) == [60]
    assert get_current_weather()["outdoor_temp_f"] == 60.0
    assert weather_svc.get_forecast_cached() == forecast


@pytest.mark.parametrize("backup_has_one", [True, False], ids=["backup-has-it", "none-has-it"])
async def test_an_empty_forecast_falls_over_to_the_next_provider(monkeypatch, backup_has_one):
    forecast = [{"timestamp": time.time() + 3600, "temp_f": 70.0, "humidity": 55,
                 "wind_mph": 1.0, "condition": "Clear"}]
    first = _FakeProvider([], name="first")
    backup = _FakeProvider(forecast if backup_has_one else [], name="backup")
    await _one_poll(monkeypatch, 10, first, backup)
    # The current reading lands either way; the forecast is the backup's, or
    # stays empty when no provider has one.
    assert get_current_weather()["provider"] == "first"
    assert weather_svc.get_forecast_cached() == (forecast if backup_has_one else [])


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
