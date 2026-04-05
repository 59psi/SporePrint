import asyncio
import logging
import math
import time

import httpx

from ..config import settings
from ..db import get_db

log = logging.getLogger(__name__)

# Module-level cache
_cache: dict = {}
_cache_ts: float = 0


async def start_weather_polling(sio):
    """Background task: poll OpenWeatherMap and cache + store results."""
    if not settings.weather_api_key or not settings.weather_lat or not settings.weather_lon:
        log.info("Weather integration disabled — set SPOREPRINT_WEATHER_API_KEY, _LAT, _LON to enable")
        return

    interval = settings.weather_poll_minutes * 60
    log.info(
        "Weather polling started: every %dm for lat=%s lon=%s",
        settings.weather_poll_minutes, settings.weather_lat, settings.weather_lon,
    )

    while True:
        try:
            weather = await _fetch_weather()
            if weather:
                await _store_reading(weather)
                if sio:
                    await sio.emit("weather", weather)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error("Weather poll failed: %s", e)

        await asyncio.sleep(interval)


async def _fetch_weather() -> dict | None:
    """Fetch current weather + today's forecast from OpenWeatherMap."""
    global _cache, _cache_ts

    base = "https://api.openweathermap.org/data/2.5"
    params = {
        "lat": settings.weather_lat,
        "lon": settings.weather_lon,
        "appid": settings.weather_api_key,
        "units": "imperial",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Current conditions
            r = await client.get(f"{base}/weather", params=params)
            r.raise_for_status()
            current = r.json()

            # 5-day forecast (for today's high/low)
            r = await client.get(f"{base}/forecast", params=params)
            r.raise_for_status()
            forecast = r.json()

        # Extract today's high/low from the forecast entries
        now = time.time()
        today_end = now - (now % 86400) + 86400  # midnight tonight UTC
        today_temps = [
            entry["main"]["temp"]
            for entry in forecast.get("list", [])
            if entry["dt"] < today_end + 86400  # include tomorrow for look-ahead
        ]

        main = current["main"]
        wind = current.get("wind", {})
        condition = current.get("weather", [{}])[0].get("main", "Unknown")

        weather = {
            "timestamp": now,
            "outdoor_temp_f": round(main["temp"], 1),
            "outdoor_humidity": main.get("humidity", 0),
            "outdoor_dew_point_f": round(_dew_point(main["temp"], main.get("humidity", 50)), 1),
            "outdoor_wind_mph": round(wind.get("speed", 0), 1),
            "outdoor_pressure_mb": main.get("pressure", 0),
            "outdoor_condition": condition,
            "forecast_high_f": round(max(today_temps), 1) if today_temps else None,
            "forecast_low_f": round(min(today_temps), 1) if today_temps else None,
        }

        _cache = weather
        _cache_ts = now
        log.info(
            "Weather updated: %.1f°F, %d%% RH, forecast high %.1f°F",
            weather["outdoor_temp_f"], weather["outdoor_humidity"],
            weather.get("forecast_high_f") or 0,
        )
        return weather

    except Exception as e:
        log.error("OpenWeatherMap fetch failed: %s", e)
        return None


def get_current_weather() -> dict | None:
    """Return cached weather data as virtual sensor dict, or None if stale/unavailable."""
    if not _cache:
        return None
    # Consider stale after 2x poll interval
    if time.time() - _cache_ts > settings.weather_poll_minutes * 60 * 2:
        return None
    return _cache


async def get_forecast() -> list[dict]:
    """Fetch and return the next 24h of forecast entries."""
    if not settings.weather_api_key or not settings.weather_lat:
        return []

    params = {
        "lat": settings.weather_lat,
        "lon": settings.weather_lon,
        "appid": settings.weather_api_key,
        "units": "imperial",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.openweathermap.org/data/2.5/forecast", params=params)
            r.raise_for_status()
            data = r.json()

        now = time.time()
        return [
            {
                "timestamp": entry["dt"],
                "temp_f": entry["main"]["temp"],
                "humidity": entry["main"]["humidity"],
                "condition": entry["weather"][0]["main"] if entry.get("weather") else "Unknown",
                "wind_mph": entry.get("wind", {}).get("speed", 0),
            }
            for entry in data.get("list", [])
            if entry["dt"] < now + 86400
        ]
    except Exception as e:
        log.error("Forecast fetch failed: %s", e)
        return []


async def get_weather_history(hours: int = 24) -> list[dict]:
    """Return stored weather readings from the database."""
    cutoff = time.time() - hours * 3600
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM weather_readings WHERE timestamp > ? ORDER BY timestamp",
            (cutoff,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def _store_reading(weather: dict):
    async with get_db() as db:
        await db.execute(
            """INSERT INTO weather_readings
               (timestamp, temp_f, humidity, dew_point_f, wind_mph, pressure_mb,
                condition, forecast_high_f, forecast_low_f)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                weather["timestamp"],
                weather["outdoor_temp_f"],
                weather["outdoor_humidity"],
                weather["outdoor_dew_point_f"],
                weather["outdoor_wind_mph"],
                weather["outdoor_pressure_mb"],
                weather["outdoor_condition"],
                weather.get("forecast_high_f"),
                weather.get("forecast_low_f"),
            ),
        )
        await db.commit()


def _dew_point(temp_f: float, rh: float) -> float:
    """Approximate dew point in °F using Magnus formula."""
    temp_c = (temp_f - 32) * 5 / 9
    a, b = 17.27, 237.7
    try:
        gamma = (a * temp_c) / (b + temp_c) + math.log(max(rh, 1) / 100)
        dp_c = (b * gamma) / (a - gamma)
        return dp_c * 9 / 5 + 32
    except (ValueError, ZeroDivisionError):
        return temp_f - 10
