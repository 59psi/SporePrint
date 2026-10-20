import asyncio
import logging
import time
from collections import Counter, defaultdict
from datetime import date, datetime

from ..config import settings
from ..db import get_db
from ..health.service import update_task
from ..notifications.service import notify_warning, notify_critical
from ..sessions.service import list_sessions, phase_params_for
from ..species.models import PhaseParams, SpeciesProfile
from ..species.service import get_profile
from .prediction import get_model_status, predict_indoor_conditions
from .providers import as_finite, provider_cascade

log = logging.getLogger(__name__)

# Module-level cache
_cache: dict = {}
_cache_ts: float = 0
_forecast_cache: list[dict] = []
_forecast_cache_ts: float = 0


_providers = None
_providers_key = None

# Forecast alerts are re-evaluated on every poll (default 10 min). The same
# forecast event (session + kind + forecast day) pages at most once per window;
# the window must exceed the poll interval or it never dedups at all.
_FORECAST_ALERT_DEDUP_SECONDS = 6 * 3600
# How far ahead the forecast alerts look.
_FORECAST_ALERT_HORIZON_SECONDS = 72 * 3600
# A forecast hour is current until the hour it covers is over; older ones are
# elapsed (providers return the day from 00:00).
_FORECAST_HOUR_SECONDS = 3600

# A predicted closet temperature against the phase's [temp_min_f, temp_max_f],
# in °F beyond the band: past the danger margin pages CRITICAL, past the
# advisory margin sends a WARNING, and just outside the band the automation's
# own cooling / heating copes. The forecast alerts and GET /api/weather/impact
# share these bands (_forecast_band).
_FORECAST_DANGER_MARGIN_F = 10.0
_FORECAST_ADVISORY_MARGIN_F = 5.0


def poll_interval_minutes() -> int:
    """The weather poll interval in minutes, never below one.

    A SPOREPRINT_WEATHER_POLL_MINUTES (or Settings) value of 0 or less made the
    loop re-poll back to back (provider rate limits, a burst of writes on the
    SD card) and judged every fresh reading stale, so no outdoor value reached
    the rules.
    """
    return max(1, settings.weather_poll_minutes)


def local_date(ts: float) -> date:
    """The operator's calendar day a timestamp falls on: the host's TZ, which
    compose passes to the server. Today's forecast high/low and the daily
    forecast summaries share this day boundary."""
    return datetime.fromtimestamp(ts).date()


def _get_providers() -> list:
    """The provider cascade (providers.provider_cascade: the chosen provider
    first, the others as failover), rebuilt when the chosen provider or the
    API key changes."""
    global _providers, _providers_key
    key = (settings.weather_provider, settings.weather_api_key)
    if _providers is None or _providers_key != key:
        _providers = provider_cascade(settings.weather_provider, settings.weather_api_key)
        _providers_key = key
    return _providers


async def start_weather_polling(sio):
    """Background task: poll weather providers with cascading failover.

    Waits for lat/lon to be configured (via .env or Settings UI), then polls.
    Re-reads settings each cycle so UI changes take effect without restart.
    Reports running / idle / error to the task registry (GET
    /api/health/detail/tasks); a poll every provider failed is an error.
    """
    while True:
        interval = poll_interval_minutes() * 60
        try:
            # Wait for lat/lon to be configured (via .env or Settings UI)
            if not settings.weather_lat or not settings.weather_lon:
                await asyncio.sleep(30)  # Check again in 30s
                continue

            update_task("weather_polling", "running")
            providers = _get_providers()

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
                # Kept in memory only: the alerts, the impact analysis and the
                # rules read this cache, and the prediction model trains on
                # weather_readings, so nothing would read a stored copy.
                await _update_forecast_cache(forecast, forecast_provider)
            else:
                log.warning("All weather providers failed for forecast")

            # Check for dangerous conditions and notify
            if forecast:
                await _check_forecast_alerts(current, forecast)

            if current or forecast:
                update_task("weather_polling", "idle")
            else:
                update_task("weather_polling", "error", error="every weather provider failed")

        except asyncio.CancelledError:
            return
        except Exception as e:
            update_task("weather_polling", "error", error=str(e))
            log.error("Weather poll failed: %s", e)

        await asyncio.sleep(interval)


async def _update_current_cache(weather: dict, provider_name: str):
    global _cache, _cache_ts
    weather["timestamp"] = time.time()
    weather["provider"] = provider_name

    # Compute TODAY's forecast high/low (the operator's local calendar day,
    # local_date — host TZ, UTC in the Docker image unless compose passes TZ).
    # The old filter's upper bound was the end of TOMORROW with no lower bound,
    # so a hot tomorrow drove the "Pre-cool for Hot Forecast" rule all through
    # a mild today.
    if _forecast_cache:
        today = local_date(time.time())
        today_temps = [
            e["temp_f"] for e in _forecast_cache
            if e.get("temp_f") is not None and e.get("timestamp") is not None
            and local_date(e["timestamp"]) == today
        ]
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


def _forecast_band(temp: float, params: PhaseParams) -> tuple[str, str] | None:
    """(tier, direction) of a predicted closet temperature against a phase's band.

    tier is "danger" past _FORECAST_DANGER_MARGIN_F (the alerts page CRITICAL),
    "advisory" past _FORECAST_ADVISORY_MARGIN_F (a WARNING) or "outside" just
    outside [temp_min_f, temp_max_f]; direction is "hot" or "cold". None
    inside the band.
    """
    if temp > params.temp_max_f:
        beyond, direction = temp - params.temp_max_f, "hot"
    elif temp < params.temp_min_f:
        beyond, direction = params.temp_min_f - temp, "cold"
    else:
        return None
    if beyond > _FORECAST_DANGER_MARGIN_F:
        return "danger", direction
    if beyond > _FORECAST_ADVISORY_MARGIN_F:
        return "advisory", direction
    return "outside", direction


async def _grow_targets(sessions: list[dict]) -> list[tuple[dict, SpeciesProfile, PhaseParams]]:
    """(session, profile, setpoints in force) for each grow a closet forecast concerns.

    Every active session, not only the newest one: with two chambers the
    older grow was never checked. Its setpoints are the ones the engine runs
    (sessions.service.phase_params_for), so a rest phase is measured against
    the fruiting envelope it borrows; cold storage and complete have no
    species setpoints and are skipped, and so is a species the closet does
    not grow (chamber_cultivable False, which the engine does not manage).
    """
    targets = []
    for session in sessions:
        profile = await get_profile(session["species_profile_id"])
        if profile is None or not profile.chamber_cultivable:
            continue
        params = phase_params_for(profile, session["current_phase"], session.get("growth_form"))
        if params is not None:
            targets.append((session, profile, params))
    return targets


async def _check_forecast_alerts(current: dict | None, forecast: list[dict]):
    """Scan the next 72h for predicted closet conditions dangerous to the active grows.

    Alerts only when a weather→closet model has been trained: the outdoor
    forecast alone says nothing about an indoor closet, so comparing raw
    outdoor temps to closet setpoints produced bogus CRITICALs for the first
    week of every install (and all winter for tropical species). Hours already
    elapsed are skipped (Open-Meteo returns hours from 00:00 today), and each
    event is deduped per session/kind/day for longer than the poll interval.
    The model is site-wide, so one set of predictions is checked against every
    active grow's own setpoints, each grow paging at most once per poll.
    """
    targets = await _grow_targets(await list_sessions(status="active"))
    if not targets:
        return

    now = time.time()
    upcoming = [
        e for e in forecast
        if now - _FORECAST_HOUR_SECONDS < (e.get("timestamp") or 0)
        <= now + _FORECAST_ALERT_HORIZON_SECONDS
    ]
    if not upcoming:
        return

    predictions = await predict_indoor_conditions(upcoming)
    if not predictions:
        log.debug("Forecast alerts skipped: no weather→closet prediction model yet")
        return

    named = len(targets) > 1
    for session, profile, params in targets:
        try:
            await _alert_grow_forecast(session, profile, params, predictions, now, named=named)
        except Exception as e:  # one grow's failed page must not skip the others
            log.warning("Forecast alert for session %s failed: %s", session.get("id"), e)


async def _alert_grow_forecast(session: dict, profile: SpeciesProfile, params: PhaseParams,
                               predictions: list[dict], now: float, *, named: bool) -> None:
    """At most one forecast alert for one grow per poll.

    CRITICAL first across the whole horizon, so an earlier advisory can't mask
    a later danger. With several grows active the title names the session.
    """
    session_id = session.get("id")
    phase_label = session["current_phase"].replace("_", " ")
    grow = f"{profile.common_name} ({session.get('name')})" if named else profile.common_name

    banded = []
    for entry in predictions:
        temp = entry.get("predicted_indoor_temp_f")
        if temp is None:
            continue
        band = _forecast_band(temp, params)
        if band is None:
            continue
        ts = entry.get("forecast_time") or 0
        banded.append((band, temp, max(0, (ts - now) / 3600), int(ts // 86400)))

    for (tier, direction), temp, hours_out, day in banded:
        if tier != "danger":
            continue
        if direction == "hot":
            await notify_critical(
                f"CRITICAL: {grow} heat danger in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F exceeds {phase_label} "
                f"max ({params.temp_max_f}°F) by {temp - params.temp_max_f:.0f}°F. "
                f"Consider pausing session or adding active cooling.",
                tags=["thermometer", "warning"],
                dedup_key=f"wx-heat-{session_id}-{day}",
                dedup_seconds=_FORECAST_ALERT_DEDUP_SECONDS,
            )
        else:
            await notify_critical(
                f"CRITICAL: {grow} cold danger in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F below {phase_label} "
                f"min ({params.temp_min_f}°F) by {params.temp_min_f - temp:.0f}°F.",
                tags=["thermometer", "warning"],
                dedup_key=f"wx-cold-{session_id}-{day}",
                dedup_seconds=_FORECAST_ALERT_DEDUP_SECONDS,
            )
        return

    for (tier, direction), temp, hours_out, day in banded:
        if tier != "advisory":
            continue
        if direction == "hot":
            await notify_warning(
                f"Heat advisory: {grow} in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F may exceed {phase_label} "
                f"max ({params.temp_max_f}°F). Pre-cooling recommended.",
                dedup_key=f"wx-heatwarn-{session_id}-{day}",
                dedup_seconds=_FORECAST_ALERT_DEDUP_SECONDS,
            )
        else:
            await notify_warning(
                f"Cold advisory: {grow} in {hours_out:.0f}h",
                f"Predicted closet temp {temp:.0f}°F may drop below {phase_label} "
                f"min ({params.temp_min_f}°F). Heating recommended.",
                dedup_key=f"wx-coldwarn-{session_id}-{day}",
                dedup_seconds=_FORECAST_ALERT_DEDUP_SECONDS,
            )
        return


# ── Forecast impact (GET /api/weather/impact) ──────────────────────────────


def summarize_daily(forecast: list[dict], now: float | None = None) -> list[dict]:
    """The hourly forecast as one summary per local calendar day, today on.

    Days are local_date's, the same boundary as today's forecast_high_f /
    forecast_low_f (UTC days put a US evening's hours on the next day, and
    the hours a provider returns from 00:00 GMT on a day already past).
    Hours with no temperature are skipped, and the humidity averages only
    the hours that report one (50 % when none does).
    """
    today = local_date(time.time() if now is None else now)
    days: dict[date, list[tuple[float, float | None, str]]] = defaultdict(list)
    for entry in forecast:
        ts = entry.get("timestamp")
        temp = as_finite(entry.get("temp_f"))
        if ts is None or temp is None:
            continue
        day = local_date(ts)
        if day >= today:
            days[day].append((temp, as_finite(entry.get("humidity")),
                              entry.get("condition") or "Unknown"))

    summaries = []
    for day in sorted(days):
        hours = days[day]
        temps = [temp for temp, _, _ in hours]
        humidities = [hum for _, hum, _ in hours if hum is not None]
        dominant_condition = Counter(cond for _, _, cond in hours).most_common(1)[0][0]
        summaries.append({
            "date": day.isoformat(),
            "day_name": day.strftime("%a"),
            "high_f": round(max(temps), 1),
            "low_f": round(min(temps), 1),
            "avg_humidity": round(sum(humidities) / len(humidities), 0) if humidities else 50.0,
            "condition": dominant_condition,
        })
    return summaries


async def get_forecast_impact() -> dict:
    """The 7-day outlook by local day, the predicted closet conditions, and
    their impact on every active grow (GET /api/weather/impact)."""
    forecast = get_forecast_cached()
    if not forecast:
        return {"forecast": [], "predictions": [], "impacts": [],
                "model_status": await get_model_status()}

    now = time.time()
    # Elapsed hours (the cache starts at 00:00 GMT) are not a forecast: they
    # read as "danger in -6h".
    upcoming = [e for e in forecast if (e.get("timestamp") or 0) > now - _FORECAST_HOUR_SECONDS]
    predictions = await predict_indoor_conditions(upcoming)
    daily = summarize_daily(forecast, now)
    return {
        "forecast": daily,
        "predictions": predictions,
        "impacts": await _forecast_impacts(daily, predictions, now),
        "model_status": await get_model_status(),
    }


async def _forecast_impacts(daily: list[dict], predictions: list[dict], now: float) -> list[dict]:
    """Impact items for every active grow, each labelled with its session and
    chamber: from the predicted closet temperatures once a model exists, else
    a rough read of the outdoor daily forecast."""
    sessions = await list_sessions(status="active")
    if not sessions:
        return [{"type": "info", "message": "No active session — forecast impact analysis unavailable."}]

    impacts = []
    for session, profile, params in await _grow_targets(sessions):
        items = (_predicted_impacts(session, profile, params, predictions, now) if predictions
                 else _outdoor_impacts(session, profile, params, daily))
        label = {"session_id": session["id"], "session_name": session.get("name"),
                 "chamber_id": session.get("chamber_id")}
        impacts.extend({**item, **label} for item in items)
    return impacts


def _predicted_impacts(session: dict, profile: SpeciesProfile, params: PhaseParams,
                       predictions: list[dict], now: float) -> list[dict]:
    """One grow's impact from the predicted closet temperatures, in the bands
    the forecast alerts page on: hours the alerts would page CRITICAL for are
    a danger, advisory or out-of-band hours a warning, too cold as well as
    too hot."""
    grow = f"{profile.common_name} {session['current_phase'].replace('_', ' ')}"
    banded: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for pred in predictions:
        temp = pred.get("predicted_indoor_temp_f")
        if temp is None:
            continue
        band = _forecast_band(temp, params)
        if band is not None:
            banded[band].append(pred)

    impacts = []
    for direction in ("hot", "cold"):
        danger = banded[("danger", direction)]
        near = banded[("advisory", direction)] + banded[("outside", direction)]
        if danger:
            hours_out = max(0.0, (danger[0]["forecast_time"] - now) / 3600)
            if direction == "hot":
                worst = max(d["predicted_indoor_temp_f"] for d in danger)
                message = (
                    f"Predicted closet temp reaches {worst:.0f}°F in {hours_out:.0f}h — "
                    f"exceeds {grow} max ({params.temp_max_f}°F) by "
                    f"{worst - params.temp_max_f:.0f}°F. {len(danger)} hours of dangerous "
                    f"conditions forecast. Pre-cooling will activate. Consider pausing "
                    f"cold-species sessions."
                )
            else:
                worst = min(d["predicted_indoor_temp_f"] for d in danger)
                message = (
                    f"Predicted closet temp drops to {worst:.0f}°F in {hours_out:.0f}h — "
                    f"below {grow} min ({params.temp_min_f}°F) by "
                    f"{params.temp_min_f - worst:.0f}°F. {len(danger)} hours of dangerous "
                    f"conditions forecast. Heating will be needed."
                )
            impacts.append({"type": "danger", "day": "", "message": message})
        elif near:
            message = (
                f"{len(near)} hours of elevated closet temperatures predicted. "
                f"Automation will increase cooling duty cycle."
                if direction == "hot" else
                f"{len(near)} hours of low closet temperatures predicted. Heating may be needed."
            )
            impacts.append({"type": "warning", "day": "", "message": message})

    if not impacts:
        impacts.append({
            "type": "good",
            "day": "",
            "message": f"Predicted closet conditions stay within {grow} targets for the next 7 days.",
        })
    return impacts


def _outdoor_impacts(session: dict, profile: SpeciesProfile, params: PhaseParams,
                     daily: list[dict]) -> list[dict]:
    """One grow's impact before a weather→closet model exists: the outdoor
    daily highs and lows against its setpoints, labelled as outdoor readings."""
    phase_label = session["current_phase"].replace("_", " ")
    impacts = []
    for entry in daily:
        if entry["high_f"] > params.temp_max_f + _FORECAST_DANGER_MARGIN_F:
            impacts.append({
                "type": "danger",
                "day": entry["day_name"],
                "message": f"{entry['day_name']}: Outdoor high {entry['high_f']}°F — likely exceeds "
                           f"{profile.common_name} {phase_label} "
                           f"max ({params.temp_max_f}°F). Active cooling critical.",
            })
        elif entry["high_f"] > params.temp_max_f:
            impacts.append({
                "type": "warning",
                "day": entry["day_name"],
                "message": f"{entry['day_name']}: Outdoor high {entry['high_f']}°F — may push closet "
                           f"above {profile.common_name} target ({params.temp_max_f}°F). "
                           f"Pre-cooling recommended.",
            })
        elif entry["low_f"] < params.temp_min_f:
            impacts.append({
                "type": "warning",
                "day": entry["day_name"],
                "message": f"{entry['day_name']}: Outdoor low {entry['low_f']}°F — closet may drop "
                           f"below {profile.common_name} minimum ({params.temp_min_f}°F). "
                           f"Heating may be needed.",
            })
    if not impacts:
        impacts.append({
            "type": "good",
            "day": "",
            "message": f"7-day outlook is within {profile.common_name} {phase_label} targets.",
        })
    return impacts


def get_current_weather() -> dict | None:
    """Return cached weather data, or None if stale/unavailable."""
    if not _cache:
        return None
    if time.time() - _cache_ts > poll_interval_minutes() * 60 * 2:
        return None
    return _cache


def get_forecast_cached() -> list[dict]:
    """Return cached 7-day forecast."""
    if not _forecast_cache:
        return []
    if time.time() - _forecast_cache_ts > poll_interval_minutes() * 60 * 2:
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
