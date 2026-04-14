"""Substrate Calculator — scales substrate recipes to a target volume.

Given a species_id and volume in liters, returns exact ingredient weights,
water volume, spawn weight, and sterilization instructions for each of
the species' substrate recipes.
"""

from __future__ import annotations

import re

from .models import SubstrateRecipe

# Base density: approximately 0.3 kg dry substrate per liter of final volume
BASE_DENSITY_KG_PER_LITER = 0.3


def _parse_quantity(raw: str) -> tuple[float, str]:
    """Parse a human-readable quantity string into (numeric_value, unit).

    Handles forms like "650g", "2.5 lbs", "1 cup", "2 quarts", "as needed".
    Returns (0.0, raw) for unparsable strings so they pass through.
    """
    raw = raw.strip()
    if raw.lower() in ("as needed", "to taste", "as required"):
        return (0.0, raw)

    m = re.match(r"^([\d.]+)\s*(.*)$", raw)
    if not m:
        return (0.0, raw)

    value = float(m.group(1))
    unit = m.group(2).strip() or "units"
    return (value, unit)


def _format_quantity(value: float, unit: str) -> str:
    """Format a numeric value + unit back to a readable string."""
    if value == 0.0:
        return unit  # passthrough for "as needed"
    if value == int(value):
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def calculate_recipe(
    recipe: SubstrateRecipe,
    volume_liters: float,
) -> dict:
    """Scale a single SubstrateRecipe to the requested volume.

    The recipe's original ingredient quantities are treated as a baseline
    for a reference volume.  We compute the total base weight from the
    recipe, derive a scale factor from the target volume, and apply it
    uniformly to all numeric ingredients.

    Returns a dict with scaled ingredients, water, spawn, and sterilization info.
    """
    # Compute reference total weight from ingredients to derive scale factor.
    # We use the base density model: target_dry_weight = volume * 0.3 kg.
    target_dry_kg = volume_liters * BASE_DENSITY_KG_PER_LITER

    # Sum up the reference weight of all numeric ingredients to get a
    # reference total.  We convert common units to kg for comparison.
    ref_total_kg = 0.0
    parsed: list[tuple[str, float, str]] = []
    for name, qty_str in recipe.ingredients.items():
        value, unit = _parse_quantity(qty_str)
        parsed.append((name, value, unit))
        ref_total_kg += _to_kg(value, unit)

    # Scale factor: target / reference.  Guard against zero-ref.
    if ref_total_kg > 0:
        scale = target_dry_kg / ref_total_kg
    else:
        scale = 1.0

    # Scale each ingredient
    scaled_ingredients: dict[str, str] = {}
    for name, value, unit in parsed:
        if value == 0.0:
            scaled_ingredients[name] = unit  # "as needed"
        else:
            scaled_ingredients[name] = _format_quantity(
                round(value * scale, 1), unit
            )

    # Water volume
    water_liters = round(volume_liters * recipe.water_liters_per_liter_substrate, 2)

    # Spawn weight (based on spawn_rate_percent of dry substrate weight)
    spawn_kg = round(target_dry_kg * (recipe.spawn_rate_percent / 100.0), 3)
    spawn_g = round(spawn_kg * 1000, 1)

    return {
        "recipe_name": recipe.name,
        "suitability": recipe.suitability,
        "target_volume_liters": volume_liters,
        "ingredients": scaled_ingredients,
        "water_liters": water_liters,
        "spawn_weight_g": spawn_g,
        "spawn_rate_percent": recipe.spawn_rate_percent,
        "sterilization": {
            "method": recipe.sterilization_method,
            "time_minutes": recipe.sterilization_time_min,
            "temp_f": recipe.sterilization_temp_f,
        },
        "notes": recipe.notes,
    }


def calculate_all_recipes(
    recipes: list[SubstrateRecipe],
    volume_liters: float,
) -> list[dict]:
    """Scale all recipes for a species to the requested volume."""
    return [calculate_recipe(r, volume_liters) for r in recipes]


# ── Unit conversion helpers ─────────────────────────────────────────

_KG_CONVERSIONS: dict[str, float] = {
    "g": 0.001,
    "kg": 1.0,
    "lbs": 0.4536,
    "lb": 0.4536,
    "oz": 0.02835,
}

# Volume-based ingredients get rough dry-weight estimates
_VOLUME_TO_KG: dict[str, float] = {
    "cup": 0.12,
    "cups": 0.12,
    "quart": 0.35,
    "quarts": 0.35,
    "gallon": 1.4,
    "gallons": 1.4,
    "liter": 0.35,
    "liters": 0.35,
}


def _to_kg(value: float, unit: str) -> float:
    """Best-effort conversion of a value+unit to kilograms."""
    unit_lower = unit.lower().rstrip("s.")

    # Direct weight conversions
    for suffix, factor in _KG_CONVERSIONS.items():
        if unit_lower == suffix or unit_lower == suffix.rstrip("s"):
            return value * factor

    # Volume-based approximations
    for vol_unit, kg_per in _VOLUME_TO_KG.items():
        if unit_lower == vol_unit or unit_lower == vol_unit.rstrip("s"):
            return value * kg_per

    # Unknown unit — treat as ~0.1 kg per unit as a rough guess
    if value > 0:
        return value * 0.1
    return 0.0
