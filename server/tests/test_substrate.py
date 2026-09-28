import re

import pytest

from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins, get_profile
from app.species.substrate import calculate_all_recipes, calculate_recipe

_PROFILES = {p.id: p for p in BUILTIN_PROFILES}


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
    profile = await get_profile("blue_oyster")
    assert profile is not None
    assert len(profile.substrate_recipes) > 0

    results = calculate_all_recipes(profile.substrate_recipes, 3.0)
    assert len(results) == len(profile.substrate_recipes)
    for recipe in results:
        assert recipe["target_volume_liters"] == 3.0
        assert recipe["spawn_weight_g"] > 0


# ── srv-rest#21: unit classes (percent / ratio / depth / fraction) ─────


def _recipe(species_id, name=None):
    profile = _PROFILES[species_id]
    for r in profile.substrate_recipes:
        if name is None or r.name == name:
            return r
    raise AssertionError(f"{species_id} has no recipe {name!r}")


def _leading_pct(text):
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*%", text)
    return float(m.group(1)) if m else None


def test_percentages_are_never_scaled_across_all_builtin_recipes():
    for profile in BUILTIN_PROFILES:
        for recipe in profile.substrate_recipes:
            out = calculate_recipe(recipe, 10.0)["ingredients"]
            src_total = out_total = 0.0
            for name, raw in recipe.ingredients.items():
                pct = _leading_pct(raw)
                if pct is None:
                    continue
                assert _leading_pct(out[name]) == pct, (profile.id, recipe.name, name, out[name])
                src_total += pct
                out_total += _leading_pct(out[name])
            assert out_total == src_total, (profile.id, recipe.name)


def test_percent_ingredient_gets_weight_from_target_dry_mass():
    # hericium_coralloides: 60% sawdust of a 10 L batch (0.3 kg/L dry) = 1800 g.
    out = calculate_recipe(_recipe("hericium_coralloides", "J Fungi 2025 Formula"), 10.0)["ingredients"]
    assert out["hardwood sawdust"].startswith("60%")
    assert "1800 g" in out["hardwood sawdust"]


def test_button_gypsum_percent_and_casing_depth_unscaled():
    out = calculate_recipe(_recipe("button_mushroom"), 10.0)["ingredients"]
    assert out["gypsum"].startswith("5% by weight")
    assert out["peat moss casing"] == "1 inch"
    assert out["vermiculite casing"] == "1 inch"


def test_fraction_quantity_is_parsed_as_a_fraction():
    recipe = _recipe("panaeolus_cyanescens", "Pasteurized Manure Mix")
    out5 = calculate_recipe(recipe, 5.0)["ingredients"]
    out10 = calculate_recipe(recipe, 10.0)["ingredients"]
    assert "/2" not in out10["gypsum"]
    # Scales in proportion with the rest of the recipe.
    g5 = float(out5["gypsum"].split()[0])
    g10 = float(out10["gypsum"].split()[0])
    assert g10 == pytest.approx(2 * g5, rel=0.05)
    # 1/2 cup against 5 quarts of manure keeps its ratio.
    manure10 = float(out10["aged horse manure"].split()[0])
    assert g10 / manure10 == pytest.approx(0.5 / 5, rel=0.05)


def test_kg_dry_unit_is_a_weight():
    # milky_mushroom: the recipe is all "5 kg dry" straw → 10 L = 3 kg dry.
    out = calculate_recipe(_recipe("milky_mushroom"), 10.0)["ingredients"]
    assert out["paddy straw (2-4cm)"] == "3 kg dry"


def test_volume_and_small_units_keep_their_ratios():
    # cordyceps: 2 cups rice / 200 ml broth / 1 tablespoon yeast.
    out = calculate_recipe(_recipe("cordyceps_militaris"), 1.0)["ingredients"]
    rice = float(out["brown rice"].split()[0])
    broth = float(out["potato dextrose broth"].split()[0])
    assert rice > 0 and broth > 0
    assert (rice / 2) == pytest.approx(broth / 200, rel=0.05)


def test_ranges_counts_and_dimensions_pass_through():
    out = calculate_recipe(_recipe("shiitake", "Hardwood Log Cultivation"), 10.0)["ingredients"]
    assert out["plug spawn"] == "30-50 plugs per log"
    assert out["fresh hardwood log (oak/maple)"] == "3-6 inch diameter x 3-4 feet"
    out = calculate_recipe(_recipe("fomes_fomentarius", "Supplemented Hardwood (fruiting route)"), 10.0)["ingredients"]
    assert out["wheat bran"] == "15-20 parts"
