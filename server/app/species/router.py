from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .models import SpeciesProfile
from . import service
from .wizard import recommend
from .substrate import calculate_all_recipes
from .shopping import generate_shopping_list

router = APIRouter()

# Upper bounds for the calculators' query parameters: past them nothing is a
# real grow, and a float like inf (which gt=0 lets through) overflowed the
# arithmetic into a 500.
MAX_CONTAINER_LITERS = 1000.0
MAX_GROWS = 100


@router.get("")
async def list_profiles():
    # Rendered once per profile change (species.service caches it).
    return Response(content=await service.profiles_listing_json(), media_type="application/json")


@router.get("/recommend")
async def recommend_species(
    level: str = Query(description="Experience level: first_time | some_experience | advanced"),
    env: str = Query(description="Environment: indoor_closet | indoor_tent | outdoor_beds | logs"),
    temp_range: str = Query(description="Temperature range: cool | moderate | warm"),
    substrate: list[str] = Query(description="Available substrates: straw, sawdust, grain, manure, all"),
    goal: str = Query(description="Goal: culinary | medicinal | both | research"),
    commitment: str = Query(description="Commitment: set_and_forget | daily_attention | dedicated_hobbyist"),
    include_active: bool = Query(
        False,
        description="Also rank species in the controlled 'active' category (left out by default)",
    ),
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
        include_active=include_active,
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
    try:
        return (await service.create_profile(profile)).model_dump()
    except service.ProfileExistsError as e:
        raise HTTPException(409, str(e))
    except service.InvalidProfileError as e:
        raise HTTPException(422, str(e))


@router.put("/{profile_id}")
async def update_profile(profile_id: str, profile: SpeciesProfile):
    try:
        result = await service.update_profile(profile_id, profile)
    except service.BuiltinProfileReadOnly as e:
        raise HTTPException(409, str(e))
    except service.InvalidProfileError as e:
        raise HTTPException(422, str(e))
    if not result:
        raise HTTPException(404, "Species profile not found")
    return result.model_dump()


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    try:
        deleted = await service.delete_profile(profile_id)
    except service.ProfileInUseError as e:
        raise HTTPException(409, str(e))
    if not deleted:
        raise HTTPException(400, "Cannot delete built-in profile or profile not found")
    return {"status": "deleted"}


@router.get("/{species_id}/shopping-list")
async def shopping_list(
    species_id: str,
    grows: int = Query(1, ge=1, le=MAX_GROWS, description="Number of grows"),
    container_liters: float = Query(
        5.0, gt=0, le=MAX_CONTAINER_LITERS, description="Container volume in liters"),
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
    volume_liters: float = Query(
        gt=0, le=MAX_CONTAINER_LITERS, description="Target substrate volume in liters"),
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
