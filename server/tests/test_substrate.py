import pytest

from app.species.service import seed_builtins, get_profile
from app.species.substrate import calculate_all_recipes


async def test_blue_oyster_returns_recipes_with_positive_values():
    """Blue oyster substrate calc should return recipes with positive quantities."""
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None
    assert len(profile.substrate_recipes) > 0

    results = calculate_all_recipes(profile.substrate_recipes, 5.0)
    assert len(results) > 0
    for recipe in results:
        assert recipe["target_volume_liters"] == 5.0
        assert recipe["water_liters"] > 0
        assert recipe["spawn_weight_g"] > 0
        assert recipe["spawn_rate_percent"] > 0
        assert recipe["sterilization"]["method"]
        assert recipe["sterilization"]["time_minutes"] > 0
        assert len(recipe["ingredients"]) > 0


async def test_nonexistent_species_has_no_profile():
    """get_profile should return None for a nonexistent species."""
    await seed_builtins()
    profile = await get_profile("nonexistent_species")
    assert profile is None


async def test_volume_scaling_is_proportional():
    """10L should produce ~2x the substrate weight of 5L."""
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None

    results_5 = calculate_all_recipes(profile.substrate_recipes, 5.0)
    results_10 = calculate_all_recipes(profile.substrate_recipes, 10.0)

    assert len(results_5) == len(results_10)
    for r5, r10 in zip(results_5, results_10):
        # Water should scale proportionally
        assert abs(r10["water_liters"] - r5["water_liters"] * 2) < 0.01
        # Spawn weight should scale proportionally
        assert abs(r10["spawn_weight_g"] - r5["spawn_weight_g"] * 2) < 0.1


async def test_recipe_output_shape():
    """Each recipe result should have the expected structure."""
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None

    results = calculate_all_recipes(profile.substrate_recipes, 5.0)
    for recipe in results:
        assert "recipe_name" in recipe
        assert "suitability" in recipe
        assert "target_volume_liters" in recipe
        assert "ingredients" in recipe
        assert "water_liters" in recipe
        assert "spawn_weight_g" in recipe
        assert "spawn_rate_percent" in recipe
        assert "sterilization" in recipe
        assert "notes" in recipe
        assert "method" in recipe["sterilization"]
        assert "time_minutes" in recipe["sterilization"]
        assert "temp_f" in recipe["sterilization"]


async def test_different_species_substrate():
    """Test substrate calculation for a species with different recipes."""
    await seed_builtins()
    profile = await get_profile("cubensis_golden_teacher")
    assert profile is not None
    assert len(profile.substrate_recipes) > 0

    results = calculate_all_recipes(profile.substrate_recipes, 3.0)
    assert len(results) == len(profile.substrate_recipes)
    for recipe in results:
        assert recipe["target_volume_liters"] == 3.0
        assert recipe["spawn_weight_g"] > 0
