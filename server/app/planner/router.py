"""Seasonal grow planner API endpoints."""

from fastapi import APIRouter, HTTPException, Query

from .models import PlannedEventCreate, PlannedEventUpdate
from .service import (
    get_recommendations,
    get_calendar_data,
    get_session_warnings,
    list_planned_events,
    create_planned_event,
    update_planned_event,
    delete_planned_event,
)

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


# ── Planned events (month-calendar CRUD) ────────────────────────


@router.get("/events")
async def list_events(
    from_: str | None = Query(None, alias="from", description="Inclusive start (YYYY-MM-DD)"),
    to: str | None = Query(None, alias="to", description="Inclusive end (YYYY-MM-DD)"),
):
    """Planned grow events in an inclusive date range, sorted by date."""
    return await list_planned_events(from_, to)


@router.post("/events")
async def create_event(data: PlannedEventCreate):
    """Create a planned grow event."""
    return await create_planned_event(data)


@router.put("/events/{event_id}")
async def update_event(event_id: int, data: PlannedEventUpdate):
    """Update a planned event (incl. `date` — the drag-reschedule)."""
    updated = await update_planned_event(event_id, data)
    if not updated:
        raise HTTPException(404, "Planned event not found")
    return updated


@router.delete("/events/{event_id}")
async def delete_event(event_id: int):
    """Delete a planned event."""
    deleted = await delete_planned_event(event_id)
    if not deleted:
        raise HTTPException(404, "Planned event not found")
    return {"deleted": True}


# ── Proposed cycle + iCal phase-timeline projection (V1-2) ───────

from datetime import date  # noqa: E402

from fastapi import Response  # noqa: E402

from .ical import cycle_to_ical  # noqa: E402
from .service import propose_cycle_for_species  # noqa: E402


@router.get("/propose")
async def propose(
    species: str = Query(..., description="Species profile id, e.g. 'blue_oyster'"),
    start: date | None = Query(None, description="Inoculation date (YYYY-MM-DD); defaults to today"),
):
    """Propose a species-derived dated per-phase grow cycle from an inoculation date."""
    cycle = await propose_cycle_for_species(species, start or date.today())
    if cycle is None:
        raise HTTPException(404, f"Unknown species '{species}'")
    return cycle


@router.get("/propose.ics")
async def propose_ics(
    species: str = Query(..., description="Species profile id, e.g. 'blue_oyster'"),
    start: date | None = Query(None, description="Inoculation date (YYYY-MM-DD); defaults to today"),
):
    """The proposed cycle as an iCal feed — one all-day event per phase + harvest."""
    cycle = await propose_cycle_for_species(species, start or date.today())
    if cycle is None:
        raise HTTPException(404, f"Unknown species '{species}'")
    return Response(
        content=cycle_to_ical(cycle),
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename={species}-plan.ics"},
    )
