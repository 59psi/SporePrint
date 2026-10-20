from fastapi import APIRouter, HTTPException, Query as Q

from ..sessions.service import get_active_session_for_chambers
from .models import ChamberCreate, ChamberUpdate, MaintenanceCreate, MaintenanceComplete
from . import service

router = APIRouter()


async def _with_resolved_session(chamber: dict) -> dict:
    """The chamber row plus `resolved_session_id`: the grow the Pi runs in the
    chamber, by the rule the automation drives its nodes with
    (sessions.service.get_active_session_for_chambers: the grow bound to it,
    else the one active_session_id links, else the newest grow bound to no
    chamber), or None. `active_session_id` is only the link, so a dashboard
    reading it alone showed a chamber as idle while its nodes ran a grow."""
    session = await get_active_session_for_chambers([chamber["id"]])
    return {**chamber, "resolved_session_id": session["id"] if session else None}


@router.post("")
async def create_chamber(data: ChamberCreate):
    return await service.create_chamber(data)


@router.get("")
async def list_chambers():
    return [await _with_resolved_session(c) for c in await service.list_chambers()]


@router.get("/compare")
async def compare(ids: str = Q(..., description="Comma-separated chamber IDs")):
    try:
        chamber_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "ids must be comma-separated chamber ids")
    if not chamber_ids:
        raise HTTPException(422, "ids must name at least one chamber")
    return await service.compare_chambers(chamber_ids)


@router.get("/{chamber_id}")
async def get_chamber(chamber_id: int):
    chamber = await service.get_chamber(chamber_id)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return await _with_resolved_session(chamber)


@router.patch("/{chamber_id}")
async def update_chamber(chamber_id: int, data: ChamberUpdate):
    try:
        chamber = await service.update_chamber(chamber_id, data)
    except (service.SessionBoundElsewhereError, service.ChamberBusyError) as e:
        raise HTTPException(409, str(e))
    except service.SessionLinkError as e:
        raise HTTPException(422, str(e))
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return chamber


@router.delete("/{chamber_id}")
async def delete_chamber(chamber_id: int):
    try:
        deleted = await service.delete_chamber(chamber_id)
    except service.ChamberInUseError as e:
        raise HTTPException(409, str(e))
    if not deleted:
        raise HTTPException(404, "Chamber not found")
    return {"deleted": True}


# ── Lifecycle: derived stats, photos, maintenance ───────────────


@router.get("/{chamber_id}/stats")
async def chamber_stats(chamber_id: int):
    stats = await service.get_chamber_stats(chamber_id)
    if stats is None:
        raise HTTPException(404, "Chamber not found")
    return stats


@router.get("/{chamber_id}/photos")
async def chamber_photos(chamber_id: int, limit: int = Q(50, ge=1, le=500)):
    photos = await service.get_chamber_photos(chamber_id, limit)
    if photos is None:
        raise HTTPException(404, "Chamber not found")
    return photos


@router.get("/{chamber_id}/maintenance")
async def list_chamber_maintenance(chamber_id: int, limit: int = 200):
    chamber = await service.get_chamber(chamber_id)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return await service.list_maintenance(chamber_id, limit=limit)


@router.post("/{chamber_id}/maintenance")
async def schedule_chamber_maintenance(chamber_id: int, data: MaintenanceCreate):
    chamber = await service.get_chamber(chamber_id)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return await service.schedule_maintenance(chamber_id, data)


@router.post("/{chamber_id}/maintenance/{mid}/complete")
async def complete_chamber_maintenance(
    chamber_id: int, mid: int, data: MaintenanceComplete | None = None
):
    notes = data.notes if data else None
    result = await service.complete_maintenance(chamber_id, mid, notes)
    if result is None:
        raise HTTPException(404, "Maintenance entry not found")
    return result
