"""Seasonal grow planner API endpoints."""

from fastapi import APIRouter, Query

from .service import get_recommendations, get_calendar_data, get_session_warnings

router = APIRouter()


@router.get("/recommend")
async def recommend(
    outdoor_temp_f: float = Query(..., description="Current outdoor temperature in Fahrenheit"),
    outdoor_humidity: float = Query(..., description="Current outdoor relative humidity (0-100)"),
    category: str | None = Query(None, description="Filter by category: gourmet, medicinal, active"),
):
    """Rank species by compatibility with current outdoor conditions."""
    return await get_recommendations(outdoor_temp_f, outdoor_humidity, category)


@router.get("/calendar")
async def calendar():
    """Monthly species compatibility calendar based on historical weather."""
    return await get_calendar_data()


@router.get("/warnings/{session_id}")
async def warnings(session_id: int):
    """Check current + forecast weather against a session's species requirements."""
    return await get_session_warnings(session_id)
