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

_NUMBER = r"\d+(?:\.\d+)?"
# "650g" · "2.5 lbs" · "1/2 cup" · "30-50 plugs per log" · "10-20% by volume"
_AMOUNT_RE = re.compile(
    rf"^(?P<num>{_NUMBER})(?:\s*/\s*(?P<den>{_NUMBER}))?"
    rf"(?:\s*[-–]\s*(?P<hi>{_NUMBER}))?\s*(?P<unit>.*)$"
)


def _parse_amount(raw: str) -> tuple[float | None, float | None, str]:
    """Parse a quantity string into (value, range_high, unit).

    value is None for non-numeric strings ("as needed", "as bulk"); a leading
    fraction ("1/2 cup") is evaluated; a range ("30-50 plugs") sets range_high.
    """
    raw = raw.strip()
    m = _AMOUNT_RE.match(raw)
    if not m:
        return (None, None, raw)
    value = float(m.group("num"))
    if m.group("den"):
        den = float(m.group("den"))
        value = value / den if den else value
    hi = float(m.group("hi")) if m.group("hi") else None
    unit = m.group("unit").strip() or "units"
    return (value, hi, unit)


def _parse_quantity(raw: str) -> tuple[float, str]:
    """Parse a human-readable quantity string into (numeric_value, unit).

    Handles forms like "650g", "2.5 lbs", "1/2 cup", "2 quarts", "as needed".
    Returns (0.0, raw) for unparsable strings so they pass through.
    """
    value, _hi, unit = _parse_amount(raw)
    if value is None:
        return (0.0, raw.strip())
    return (value, unit)


def _unit_key(unit: str) -> str:
    """Normalized first token of a unit ("kg dry" → "kg", "% by weight" → "%")."""
    if unit.startswith("%"):
        return "%"
    tokens = unit.split()
    return tokens[0].lower().strip(".,;:()") if tokens else ""


def _unit_kind(unit: str) -> str:
    """'mass' | 'volume' — scaled with the batch; 'percent' — a share of the dry
    mass, never scaled; 'passthrough' — ratios (parts), depths (inch),
    counts/dimensions (log, plugs per log, 4x4 sheet) and anything unknown."""
    key = _unit_key(unit)
    if key in _KG_CONVERSIONS:
        return "mass"
    if key in _VOLUME_TO_KG:
        return "volume"
    if key == "%":
        return "percent"
    return "passthrough"


def _fmt_number(x: float) -> str:
    """1 decimal at or above 1, 2 below (3 if it would round to zero)."""
    r = round(x, 1) if x >= 1 else round(x, 2)
    if r == 0 and x > 0:
        r = round(x, 3)
    return f"{r:.3f}".rstrip("0").rstrip(".")


def _scale_amount(raw: str, scale: float, target_dry_kg: float) -> str:
    """Render one ingredient for the target batch according to its unit class."""
    value, hi, unit = _parse_amount(raw)
    if value is None:
        return raw.strip()  # "as needed", "as bulk", ...
    kind = _unit_kind(unit)
    if kind in ("mass", "volume"):
        if hi is None:
            return f"{_fmt_number(value * scale)} {unit}"
        return f"{_fmt_number(value * scale)}-{_fmt_number(hi * scale)} {unit}"
    if kind == "percent" and "volume" not in unit.lower():
        # A percentage is a share of the batch's dry mass: keep it as written
        # and add the weight it works out to for this batch.
        grams = value / 100.0 * target_dry_kg * 1000.0
        if hi is None:
            return f"{raw.strip()} (~{_fmt_number(grams)} g)"
        grams_hi = hi / 100.0 * target_dry_kg * 1000.0
        return f"{raw.strip()} (~{_fmt_number(grams)}-{_fmt_number(grams_hi)} g)"
    return raw.strip()


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

    The recipe's weight/volume quantities are treated as a baseline for a
    reference batch.  We compute that batch's dry weight, derive a scale
    factor from the target volume, and apply it to every weight/volume
    ingredient.  Percentages (a share of the dry mass), ratios ("3 parts"),
    depths ("1 inch" casing) and counts/dimensions ("1 log") do not grow
    with the batch and are never multiplied; a percentage is annotated with
    the weight it comes to for this batch.

    Returns a dict with scaled ingredients, water, spawn, and sterilization info.
    """
    # We use the base density model: target_dry_weight = volume * 0.3 kg.
    target_dry_kg = volume_liters * BASE_DENSITY_KG_PER_LITER

    # Reference dry weight of the recipe as written (weight/volume units only).
    ref_total_kg = 0.0
    for qty_str in recipe.ingredients.values():
        value, hi, unit = _parse_amount(qty_str)
        if value is not None:
            ref_total_kg += _to_kg(value if hi is None else (value + hi) / 2, unit)

    # Scale factor: target / reference.  Guard against zero-ref.
    if ref_total_kg > 0:
        scale = target_dry_kg / ref_total_kg
    else:
        scale = 1.0

    scaled_ingredients: dict[str, str] = {
        name: _scale_amount(qty_str, scale, target_dry_kg)
        for name, qty_str in recipe.ingredients.items()
    }

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

# Keyed by _unit_key(): the unit's first token, so "kg dry" is a weight.
_KG_CONVERSIONS: dict[str, float] = {
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "kg": 1.0,
    "kgs": 1.0,
    "lbs": 0.4536,
    "lb": 0.4536,
    "pound": 0.4536,
    "pounds": 0.4536,
    "oz": 0.02835,
}

# Volume-based ingredients get rough dry-weight estimates (~0.35 kg/L bulk)
_VOLUME_TO_KG: dict[str, float] = {
    "cup": 0.12,
    "cups": 0.12,
    "quart": 0.35,
    "quarts": 0.35,
    "qt": 0.35,
    "gallon": 1.4,
    "gallons": 1.4,
    "gal": 1.4,
    "liter": 0.35,
    "liters": 0.35,
    "litre": 0.35,
    "litres": 0.35,
    "l": 0.35,
    "ml": 0.00035,
    "tablespoon": 0.0052,
    "tablespoons": 0.0052,
    "tbsp": 0.0052,
    "teaspoon": 0.0017,
    "teaspoons": 0.0017,
    "tsp": 0.0017,
}


def _to_kg(value: float, unit: str) -> float:
    """Best-effort conversion of a weight/volume amount to dry kilograms.

    Percentages, ratios, depths, counts and unknown units weigh nothing here:
    they are not scaled, so they must not skew the recipe's reference weight.
    """
    key = _unit_key(unit)
    if key in _KG_CONVERSIONS:
        return value * _KG_CONVERSIONS[key]
    if key in _VOLUME_TO_KG:
        return value * _VOLUME_TO_KG[key]
    return 0.0
