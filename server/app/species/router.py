from fastapi import APIRouter, HTTPException, Query

from .models import SpeciesProfile
from . import service
from .wizard import recommend
from .substrate import calculate_all_recipes
from .shopping import generate_shopping_list

router = APIRouter()


@router.get("")
async def list_profiles():
    profiles = await service.get_all_profiles()
    return [p.model_dump() for p in profiles]


@router.get("/recommend")
async def recommend_species(
    level: str = Query(description="Experience level: first_time | some_experience | advanced"),
    env: str = Query(description="Environment: indoor_closet | indoor_tent | outdoor_beds | logs"),
    temp_range: str = Query(description="Temperature range: cool | moderate | warm"),
    substrate: list[str] = Query(description="Available substrates: straw, sawdust, grain, manure, all"),
    goal: str = Query(description="Goal: culinary | medicinal | both | research"),
    commitment: str = Query(description="Commitment: set_and_forget | daily_attention | dedicated_hobbyist"),
):
    profiles = await service.get_all_profiles()
    results = recommend(
        profiles,
        experience=level,
        environment=env,
        temp_range=temp_range,
        substrates=substrate,
        goal=goal,
        commitment=commitment,
    )
    return results


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


@router.get("/{species_id}/shopping-list")
async def shopping_list(
    species_id: str,
    grows: int = Query(1, ge=1, description="Number of grows"),
    container_liters: float = Query(5.0, gt=0, description="Container volume in liters"),
):
    profile = await service.get_profile(species_id)
    if not profile:
        raise HTTPException(404, "Species profile not found")
    result = generate_shopping_list(profile, grows=grows, container_liters=container_liters)
    if not result:
        raise HTTPException(404, "No substrate recipes available for this species")
    return result


@router.get("/{species_id}/substrate")
async def substrate_calculator(
    species_id: str,
    volume_liters: float = Query(gt=0, description="Target substrate volume in liters"),
):
    profile = await service.get_profile(species_id)
    if not profile:
        raise HTTPException(404, "Species profile not found")
    if not profile.substrate_recipes:
        raise HTTPException(404, "No substrate recipes available for this species")
    recipes = calculate_all_recipes(profile.substrate_recipes, volume_liters)
    return {
        "species_id": species_id,
        "common_name": profile.common_name,
        "volume_liters": volume_liters,
        "recipes": recipes,
    }
