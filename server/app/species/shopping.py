"""Shopping List Generator — creates a categorized shopping list for a grow.

Given a species profile and grow parameters, produces a list of items
grouped by category (substrate, spawn, containers, supplies) with
quantities scaled for the requested number of grows and container size.
"""

from __future__ import annotations

from .models import SpeciesProfile
from .substrate import BASE_DENSITY_KG_PER_LITER, _parse_quantity, _format_quantity


def generate_shopping_list(
    profile: SpeciesProfile,
    grows: int = 1,
    container_liters: float = 5.0,
) -> dict:
    """Build a categorized shopping list for a species grow.

    Uses the first (optimal) substrate recipe from the profile.
    Returns species info, recipe name, and items grouped by category.
    """
    if not profile.substrate_recipes:
        return None

    recipe = profile.substrate_recipes[0]

    # Calculate dry substrate weight for scaling
    dry_substrate_g = container_liters * BASE_DENSITY_KG_PER_LITER * 1000  # grams
    total_dry_substrate_g = dry_substrate_g * grows

    items = []

    # Substrate ingredients — scale from recipe baseline
    ref_total_g = 0.0
    parsed = []
    for name, qty_str in recipe.ingredients.items():
        value, unit = _parse_quantity(qty_str)
        parsed.append((name, value, unit))
        # rough conversion to grams for reference total
        if unit.lower() in ("g",):
            ref_total_g += value
        elif unit.lower() in ("kg",):
            ref_total_g += value * 1000
        else:
            ref_total_g += value * 100  # rough estimate for non-weight units

    if ref_total_g > 0:
        scale = (total_dry_substrate_g / ref_total_g)
    else:
        scale = float(grows)

    for name, value, unit in parsed:
        if value == 0.0:
            items.append({"name": name, "quantity": unit, "category": "substrate"})
        else:
            scaled_value = round(value * scale, 1)
            items.append({
                "name": name,
                "quantity": _format_quantity(scaled_value, unit),
                "category": "substrate",
            })

    # Spawn
    spawn_g = round(total_dry_substrate_g * (recipe.spawn_rate_percent / 100.0), 1)
    items.append({
        "name": "Grain spawn",
        "quantity": _format_quantity(spawn_g, "g"),
        "category": "spawn",
    })

    # Containers
    items.append({
        "name": f"Monotub / grow container ({container_liters}L)",
        "quantity": f"{grows}",
        "category": "containers",
    })
    items.append({
        "name": "Liner (trash bag)",
        "quantity": f"{grows}",
        "category": "containers",
    })

    # Supplies — always needed
    items.append({
        "name": "Isopropyl alcohol (70%)",
        "quantity": "1 bottle",
        "category": "supplies",
    })
    items.append({
        "name": "Spray bottle",
        "quantity": "1",
        "category": "supplies",
    })
    items.append({
        "name": "Nitrile gloves",
        "quantity": "1 box",
        "category": "supplies",
    })

    # Pressure cooker needed if sterilization requires it
    if "sterilize" in recipe.sterilization_method.lower() or "pressure" in recipe.sterilization_method.lower():
        items.append({
            "name": "Pressure cooker (23+ quart)",
            "quantity": "1",
            "category": "supplies",
        })

    return {
        "species_id": profile.id,
        "common_name": profile.common_name,
        "recipe_name": recipe.name,
        "grows": grows,
        "container_liters": container_liters,
        "items": items,
    }
