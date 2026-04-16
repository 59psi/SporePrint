import asyncio
import logging
import time

from ..config import settings
from ..db import get_db
from ..notifications.service import notify_warning, notify_critical
from ..sessions.service import get_active_session
from ..species.models import GrowPhase
from ..species.service import get_profile
from .prediction import predict_indoor_conditions
from .providers import OpenMeteoProvider, NWSProvider, OpenWeatherMapProvider

log = logging.getLogger(__name__)

# Module-level cache
_cache: dict = {}
_cache_ts: float = 0
_forecast_cache: list[dict] = []
_forecast_cache_ts: float = 0


_providers = None
_providers_key = None


def _build_provider_cascade() -> list:
    """Build ordered list of weather providers for failover."""
    providers = [OpenMeteoProvider()]  # Always available (free, no key)
    providers.append(NWSProvider())     # Free, US-only
    if settings.weather_api_key:
        providers.append(OpenWeatherMapProvider(settings.weather_api_key))
    return providers


def _get_providers() -> list:
    """Return cached providers list, rebuilding only when the API key changes."""
    global _providers, _providers_key
    key = settings.weather_api_key
    if _providers is None or _providers_key != key:
        _providers = _build_provider_cascade()
        _providers_key = key
    return _providers


async def start_weather_polling(sio):
    """Background task: poll weather providers with cascading failover.

    Waits for lat/lon to be configured (via .env or Settings UI), then polls.
    Re-reads settings each cycle so UI changes take effect without restart.
    """
    while True:
        try:
            # Wait for lat/lon to be configured (via .env or Settings UI)
            if not settings.weather_lat or not settings.weather_lon:
                await asyncio.sleep(30)  # Check again in 30s
                continue

            providers = _get_providers()
            interval = settings.weather_poll_minutes * 60

            current = None
            current_provider = None
            for provider in providers:
                try:
                    current = await asyncio.wait_for(
                        provider.fetch_current(settings.weather_lat, settings.weather_lon),
                        timeout=15,
                    )
                    if current:
                        current_provider = provider.name
                        break
                except asyncio.TimeoutError:
                    log.warning("Weather provider %s timed out (current)", provider.name)
                except Exception as e:
                    log.warning("Weather provider %s failed (current): %s", provider.name, e)

            if current:
                log.debug(
                    "Weather from %s: %.1f°F, %d%% RH",
                    current_provider,
                    current.get("outdoor_temp_f", 0),
                    current.get("outdoor_humidity", 0),
                )
                await _update_current_cache(current, current_provider)
                if sio:
                    await sio.emit("weather", current)
            else:
                log.warning("All weather providers failed for current conditions")

            forecast = None
            forecast_provider = None
            for provider in providers:
                try:
                    forecast = await asyncio.wait_for(
                        provider.fetch_forecast(settings.weather_lat, settings.weather_lon),
                        timeout=15,
                    )
                    if forecast:
                        forecast_provider = provider.name
                        break
                except asyncio.TimeoutError:
                    log.warning("Weather provider %s timed out (forecast)", provider.name)
                except Exception as e:
                    log.warning("Weather provider %s failed (forecast): %s", provider.name, e)

            if forecast:
                await _update_forecast_cache(forecast, forecast_provider)
                await _store_forecast(forecast, forecast_provider)
                await _prune_old_forecasts()
            else:
                log.warning("All weather providers failed for forecast")

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
    session = await get_active_session()
    if not session:
        return

    profile = await get_profile(session["species_profile_id"])
    if not profile:
        return

    current_phase = session["current_phase"]
    try:
        phase_params = profile.phases.get(GrowPhase(current_phase))
    except (ValueError, KeyError):
        return
    if not phase_params:
        return

    predictions = await predict_indoor_conditions(forecast[:72])

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


def get_cached_weather() -> dict | None:
    """Return the latest cached weather reading."""
    return _cache if _cache else None


def get_cached_forecast() -> list[dict]:
    """Return the latest cached forecast entries."""
    return _forecast_cache
