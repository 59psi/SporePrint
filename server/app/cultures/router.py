from fastapi import APIRouter, HTTPException

from .models import CultureCreate, CultureUpdate
from . import service

router = APIRouter()


@router.post("")
async def create_culture(data: CultureCreate):
    return await service.create_culture(data)


@router.get("")
async def list_cultures(species: str | None = None, status: str | None = None):
    return await service.list_cultures(species, status)


@router.get("/{culture_id}")
async def get_culture(culture_id: int):
    culture = await service.get_culture(culture_id)
    if not culture:
        raise HTTPException(404, "Culture not found")
    return culture


@router.patch("/{culture_id}")
async def update_culture(culture_id: int, data: CultureUpdate):
    culture = await service.update_culture(culture_id, data)
    if not culture:
        raise HTTPException(404, "Culture not found")
    return culture


@router.delete("/{culture_id}")
async def delete_culture(culture_id: int):
    deleted = await service.delete_culture(culture_id)
    if not deleted:
        raise HTTPException(404, "Culture not found")
    return {"deleted": True}


@router.get("/{culture_id}/lineage")
async def get_lineage(culture_id: int):
    tree = await service.get_lineage_tree(culture_id)
    if not tree:
        raise HTTPException(404, "Culture not found")
    return tree
