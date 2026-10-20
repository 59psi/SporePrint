from fastapi import APIRouter

from .prediction import get_model_status
from .service import (
    get_current_weather,
    get_forecast_cached,
    get_forecast_impact,
    get_weather_history,
)

router = APIRouter()


@router.get("/current")
async def current_weather():
    weather = get_current_weather()
    if not weather:
        return {"status": "unavailable", "message": "Weather data not available. Configure SPOREPRINT_WEATHER_LAT and SPOREPRINT_WEATHER_LON."}
    return weather


@router.get("/forecast")
async def forecast():
    return get_forecast_cached()


@router.get("/history")
async def weather_history(hours: int = 24):
    return await get_weather_history(hours)


@router.get("/impact")
async def forecast_impact():
    """7-day forecast by local day, predicted closet conditions and their
    impact on every active grow."""
    return await get_forecast_impact()


@router.get("/model")
async def model_status():
    return await get_model_status()
