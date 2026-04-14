from fastapi import APIRouter, HTTPException

from .models import ChamberCreate, ChamberUpdate
from . import service

router = APIRouter()


@router.post("")
async def create_chamber(data: ChamberCreate):
    return await service.create_chamber(data)


@router.get("")
async def list_chambers():
    return await service.list_chambers()


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
