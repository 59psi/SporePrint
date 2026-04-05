from fastapi import APIRouter, HTTPException

from .models import SpeciesProfile
from . import service

router = APIRouter()


@router.get("")
async def list_profiles():
    profiles = await service.get_all_profiles()
    return [p.model_dump() for p in profiles]


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    profile = await service.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Species profile not found")
    return profile.model_dump()


@router.post("")
async def create_profile(profile: SpeciesProfile):
    return (await service.create_profile(profile)).model_dump()


@router.put("/{profile_id}")
async def update_profile(profile_id: str, profile: SpeciesProfile):
    result = await service.update_profile(profile_id, profile)
    if not result:
        raise HTTPException(404, "Species profile not found")
    return result.model_dump()


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    deleted = await service.delete_profile(profile_id)
    if not deleted:
        raise HTTPException(400, "Cannot delete built-in profile or profile not found")
    return {"status": "deleted"}
