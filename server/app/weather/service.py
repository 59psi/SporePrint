import asyncio
import logging
import time

from ..config import settings
from ..db import get_db
from .providers import get_provider

log = logging.getLogger(__name__)

# Module-level cache
_cache: dict = {}
_cache_ts: float = 0
_forecast_cache: list[dict] = []
_forecast_cache_ts: float = 0


async def start_weather_polling(sio):
    """Background task: poll weather provider and cache + store results."""
    if not settings.weather_lat or not settings.weather_lon:
        log.info("Weather disabled — set SPOREPRINT_WEATHER_LAT and _LON to enable")
        return

    provider = get_provider(settings.weather_provider, settings.weather_api_key)
    interval = settings.weather_poll_minutes * 60
    log.info(
        "Weather polling started: %s provider, every %dm, lat=%s lon=%s",
        provider.name, settings.weather_poll_minutes, settings.weather_lat, settings.weather_lon,
    )

    while True:
        try:
            # Fetch current conditions
            current = await provider.fetch_current(settings.weather_lat, settings.weather_lon)
            if current:
                await _update_current_cache(current, provider.name)
                if sio:
                    await sio.emit("weather", current)

            # Fetch 7-day forecast
            forecast = await provider.fetch_forecast(settings.weather_lat, settings.weather_lon)
            if forecast:
                await _update_forecast_cache(forecast, provider.name)
                await _store_forecast(forecast, provider.name)
                await _prune_old_forecasts()

            # Check for dangerous conditions and notify
            if forecast:
                await _check_forecast_alerts(current, forecast)

        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error("Weather poll failed: %s", e)

        await asyncio.sleep(interval)


async def _update_current_cache(weather: dict, provider_name: str):
    global _cache, _cache_ts
    weather["timestamp"] = time.time()
    weather["provider"] = provider_name

    # Compute forecast high/low from cached forecast
    if _forecast_cache:
        now = time.time()
        today_end = now - (now % 86400) + 86400
        today_temps = [e["temp_f"] for e in _forecast_cache if e["timestamp"] < today_end + 86400]
        if today_temps:
            weather["forecast_high_f"] = round(max(today_temps), 1)
            weather["forecast_low_f"] = round(min(today_temps), 1)

    _cache = weather
    _cache_ts = time.time()

    # Store to DB
    async with get_db() as db:
        await db.execute(
            """INSERT INTO weather_readings
               (timestamp, provider, temp_f, humidity, dew_point_f, wind_mph, pressure_mb,
                condition, forecast_high_f, forecast_low_f)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                weather["timestamp"], provider_name,
                weather["outdoor_temp_f"], weather["outdoor_humidity"],
                weather.get("outdoor_dew_point_f"), weather.get("outdoor_wind_mph"),
                weather.get("outdoor_pressure_mb"), weather.get("outdoor_condition"),
                weather.get("forecast_high_f"), weather.get("forecast_low_f"),
            ),
        )
        await db.commit()

    log.info(
        "Weather updated [%s]: %.1f°F, %d%% RH, forecast high %s°F",
        provider_name, weather["outdoor_temp_f"], weather["outdoor_humidity"],
        weather.get("forecast_high_f", "?"),
    )


async def _update_forecast_cache(forecast: list[dict], provider_name: str):
    global _forecast_cache, _forecast_cache_ts
    _forecast_cache = forecast
    _forecast_cache_ts = time.time()


async def _store_forecast(forecast: list[dict], provider_name: str):
    """Store forecast entries to DB for prediction training."""
    now = time.time()
    async with get_db() as db:
        # Delete previous forecasts for this provider (keep only latest fetch)
        await db.execute(
            "DELETE FROM weather_forecasts WHERE provider = ? AND fetched_at < ?",
            (provider_name, now - 3600),  # keep last hour of fetches
        )
        rows = [
            (now, entry["timestamp"], entry["temp_f"], entry.get("humidity"),
             entry.get("wind_mph"), entry.get("condition"), provider_name)
            for entry in forecast
        ]
        await db.executemany(
            """INSERT INTO weather_forecasts
               (fetched_at, forecast_time, temp_f, humidity, wind_mph, condition, provider)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()


async def _prune_old_forecasts():
    """Remove forecast entries older than 30 days."""
    cutoff = time.time() - 30 * 86400
    async with get_db() as db:
        await db.execute("DELETE FROM weather_forecasts WHERE forecast_time < ?", (cutoff,))
        await db.commit()


async def _check_forecast_alerts(current: dict | None, forecast: list[dict]):
    """Scan next 72h for conditions dangerous to active session species."""
    from ..notifications.service import notify_warning, notify_critical

    # Get active session + species profile
    session = await _get_active_session()
    if not session:
        return

    from ..species.service import get_profile
    profile = await get_profile(session["species_profile_id"])
    if not profile:
        return

    from ..species.models import GrowPhase
    current_phase = session["current_phase"]
    try:
        phase_params = profile.phases.get(GrowPhase(current_phase))
    except (ValueError, KeyError):
        return
    if not phase_params:
        return

    # Try to predict indoor conditions, fall back to outdoor forecast
    from .prediction import predict_indoor_conditions
    predictions = await predict_indoor_conditions(forecast[:72])  # next 72 hours

    now = time.time()
    max_horizon = now + 72 * 3600

    for entry in (predictions or forecast[:72]):
        ts = entry.get("forecast_time") or entry.get("timestamp", 0)
        if ts > max_horizon:
            break

        temp = entry.get("predicted_indoor_temp_f") or entry.get("temp_f", 72)
        hours_out = max(0, (ts - now) / 3600)

        # Check if temp exceeds species targets
        if temp > phase_params.temp_max_f + 10:
            await notify_critical(
                f"CRITICAL: {profile.common_name} heat danger in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F exceeds {current_phase.replace('_', ' ')} "
                f"max ({phase_params.temp_max_f}°F) by {temp - phase_params.temp_max_f:.0f}°F. "
                f"Consider pausing session or adding active cooling.",
                tags=["thermometer", "warning"],
            )
            return  # One alert per poll cycle

        if temp > phase_params.temp_max_f + 5:
            await notify_warning(
                f"Heat advisory: {profile.common_name} in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F may exceed {current_phase.replace('_', ' ')} "
                f"max ({phase_params.temp_max_f}°F). Pre-cooling recommended.",
                dedup_key=f"heat-warn-{int(ts / 3600)}",
            )
            return

        if temp < phase_params.temp_min_f - 10:
            await notify_critical(
                f"CRITICAL: {profile.common_name} cold danger in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F below {current_phase.replace('_', ' ')} "
                f"min ({phase_params.temp_min_f}°F) by {phase_params.temp_min_f - temp:.0f}°F.",
                tags=["thermometer", "warning"],
            )
            return


async def _get_active_session() -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


def get_current_weather() -> dict | None:
    """Return cached weather data, or None if stale/unavailable."""
    if not _cache:
        return None
    if time.time() - _cache_ts > settings.weather_poll_minutes * 60 * 2:
        return None
    return _cache


def get_forecast_cached() -> list[dict]:
    """Return cached 7-day forecast."""
    if not _forecast_cache:
        return []
    if time.time() - _forecast_cache_ts > settings.weather_poll_minutes * 60 * 2:
        return []
    return _forecast_cache


async def get_weather_history(hours: int = 24) -> list[dict]:
    cutoff = time.time() - hours * 3600
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM weather_readings WHERE timestamp > ? ORDER BY timestamp",
            (cutoff,),
        )
        return [dict(r) for r in await cursor.fetchall()]
