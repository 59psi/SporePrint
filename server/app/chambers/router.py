from fastapi import APIRouter, HTTPException, Query as Q

from .models import ChamberCreate, ChamberUpdate, MaintenanceCreate, MaintenanceComplete
from . import service

router = APIRouter()


@router.post("")
async def create_chamber(data: ChamberCreate):
    return await service.create_chamber(data)


@router.get("")
async def list_chambers():
    return await service.list_chambers()


@router.get("/compare")
async def compare(ids: str = Q(..., description="Comma-separated chamber IDs")):
    chamber_ids = [int(x) for x in ids.split(",")]
    return await service.compare_chambers(chamber_ids)


@router.get("/{chamber_id}")
async def get_chamber(chamber_id: int):
    chamber = await service.get_chamber(chamber_id)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return chamber


@router.patch("/{chamber_id}")
async def update_chamber(chamber_id: int, data: ChamberUpdate):
    chamber = await service.update_chamber(chamber_id, data)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return chamber


@router.delete("/{chamber_id}")
async def delete_chamber(chamber_id: int):
    deleted = await service.delete_chamber(chamber_id)
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
async def list_chamber_maintenance(chamber_id: int):
    chamber = await service.get_chamber(chamber_id)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    return await service.list_maintenance(chamber_id)


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
