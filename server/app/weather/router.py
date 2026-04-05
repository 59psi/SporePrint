import time
from collections import defaultdict

from fastapi import APIRouter

from ..sessions.service import get_active_session
from ..species.models import GrowPhase
from ..species.service import get_profile
from .prediction import predict_indoor_conditions, get_model_status
from .service import get_current_weather, get_forecast_cached, get_weather_history

router = APIRouter()


@router.get("/current")
async def current_weather():
    weather = get_current_weather()
    if not weather:
        return {"status": "unavailable", "message": "Weather data not available. Configure SPOREPRINT_WEATHER_LAT and _LON."}
    return weather


@router.get("/forecast")
async def forecast():
    return get_forecast_cached()


@router.get("/history")
async def weather_history(hours: int = 24):
    return await get_weather_history(hours)


@router.get("/impact")
async def forecast_impact():
    """Return 7-day forecast with predicted indoor conditions and impact analysis."""
    forecast = get_forecast_cached()
    if not forecast:
        return {"forecast": [], "predictions": [], "impacts": [], "model_status": await get_model_status()}

    predictions = await predict_indoor_conditions(forecast)

    # Generate impact analysis
    impacts = await _analyze_impacts(forecast, predictions)

    return {
        "forecast": _summarize_daily(forecast),
        "predictions": predictions,
        "impacts": impacts,
        "model_status": await get_model_status(),
    }


@router.get("/model")
async def model_status():
    return await get_model_status()


def _summarize_daily(forecast: list[dict]) -> list[dict]:
    """Group hourly forecast into daily summaries."""
    days: dict[int, list[dict]] = defaultdict(list)
    for entry in forecast:
        day_key = int(entry["timestamp"] / 86400)
        days[day_key].append(entry)

    summaries = []
    for day_key in sorted(days):
        entries = days[day_key]
        temps = [e["temp_f"] for e in entries]
        humidities = [e.get("humidity", 50) for e in entries]
        # Pick the most common condition
        conditions = [e.get("condition", "Unknown") for e in entries]
        dominant_condition = max(set(conditions), key=conditions.count)

        day_ts = day_key * 86400
        t = time.gmtime(day_ts)
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        summaries.append({
            "date": time.strftime("%Y-%m-%d", t),
            "day_name": day_names[t.tm_wday],
            "high_f": round(max(temps), 1),
            "low_f": round(min(temps), 1),
            "avg_humidity": round(sum(humidities) / len(humidities), 0),
            "condition": dominant_condition,
        })

    return summaries


async def _analyze_impacts(forecast: list[dict], predictions: list[dict]) -> list[dict]:
    """Compare predicted indoor conditions against active session species targets."""
    session = await get_active_session()
    if not session:
        return [{"type": "info", "message": "No active session — forecast impact analysis unavailable."}]
    profile = await get_profile(session["species_profile_id"])
    if not profile:
        return []

    try:
        phase_params = profile.phases.get(GrowPhase(session["current_phase"]))
    except (ValueError, KeyError):
        return []
    if not phase_params:
        return []

    impacts = []
    now = time.time()

    if not predictions:
        # No model yet — analyze forecast directly
        for entry in _summarize_daily(forecast):
            if entry["high_f"] > phase_params.temp_max_f + 10:
                impacts.append({
                    "type": "danger",
                    "day": entry["day_name"],
                    "message": f"{entry['day_name']}: Outdoor high {entry['high_f']}°F — likely exceeds "
                               f"{profile.common_name} {session['current_phase'].replace('_', ' ')} "
                               f"max ({phase_params.temp_max_f}°F). Active cooling critical.",
                })
            elif entry["high_f"] > phase_params.temp_max_f:
                impacts.append({
                    "type": "warning",
                    "day": entry["day_name"],
                    "message": f"{entry['day_name']}: Outdoor high {entry['high_f']}°F — may push closet "
                               f"above {profile.common_name} target ({phase_params.temp_max_f}°F). "
                               f"Pre-cooling recommended.",
                })
            elif entry["low_f"] < phase_params.temp_min_f:
                impacts.append({
                    "type": "warning",
                    "day": entry["day_name"],
                    "message": f"{entry['day_name']}: Outdoor low {entry['low_f']}°F — closet may drop "
                               f"below {profile.common_name} minimum ({phase_params.temp_min_f}°F). "
                               f"Heating may be needed.",
                })
        if not impacts:
            impacts.append({
                "type": "good",
                "day": "",
                "message": f"7-day outlook is within {profile.common_name} "
                           f"{session['current_phase'].replace('_', ' ')} targets.",
            })
        return impacts

    # With prediction model — use predicted indoor temps
    danger_hours = []
    warning_hours = []
    for pred in predictions:
        temp = pred.get("predicted_indoor_temp_f", 72)
        if temp > phase_params.temp_max_f + 5:
            danger_hours.append(pred)
        elif temp > phase_params.temp_max_f:
            warning_hours.append(pred)

    if danger_hours:
        first = danger_hours[0]
        hours_out = (first["forecast_time"] - now) / 3600
        worst = max(d["predicted_indoor_temp_f"] for d in danger_hours)
        impacts.append({
            "type": "danger",
            "day": "",
            "message": f"Predicted closet temp reaches {worst:.0f}°F in {hours_out:.0f}h — "
                       f"exceeds {profile.common_name} {session['current_phase'].replace('_', ' ')} "
                       f"max ({phase_params.temp_max_f}°F) by {worst - phase_params.temp_max_f:.0f}°F. "
                       f"{len(danger_hours)} hours of dangerous conditions forecast. "
                       f"Pre-cooling will activate. Consider pausing cold-species sessions.",
        })

    if warning_hours and not danger_hours:
        impacts.append({
            "type": "warning",
            "day": "",
            "message": f"{len(warning_hours)} hours of elevated closet temperatures predicted. "
                       f"Automation will increase cooling duty cycle.",
        })

    if not impacts:
        impacts.append({
            "type": "good",
            "day": "",
            "message": f"Predicted closet conditions stay within {profile.common_name} "
                       f"{session['current_phase'].replace('_', ' ')} targets for the next 7 days.",
        })

    return impacts
