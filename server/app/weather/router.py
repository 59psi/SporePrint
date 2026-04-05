from fastapi import APIRouter

from .service import get_current_weather, get_forecast, get_weather_history

router = APIRouter()


@router.get("/current")
async def current_weather():
    weather = get_current_weather()
    if not weather:
        return {"status": "unavailable", "message": "Weather data not available. Configure SPOREPRINT_WEATHER_API_KEY, _LAT, _LON."}
    return weather


@router.get("/forecast")
async def forecast():
    return await get_forecast()


@router.get("/history")
async def weather_history(hours: int = 24):
    return await get_weather_history(hours)
