"""Shopping List Generator — creates a categorized shopping list for a grow.

Given a species profile and grow parameters, produces a list of items
grouped by category (substrate, spawn, containers, supplies) with
quantities scaled for the requested number of grows and container size.
"""

from __future__ import annotations

from .models import SpeciesProfile
from .substrate import BASE_DENSITY_KG_PER_LITER, _parse_quantity, _format_quantity


# ── Supplier links by item category / keyword ─────────────────────
_SUPPLIER_LINKS: dict[str, list[str]] = {
    "grain spawn": [
        "https://northspore.com",
        "https://fungi.com",
    ],
    "plug spawn": [
        "https://northspore.com",
        "https://fungi.com",
    ],
    "straw": [
        "Available at local feed stores or garden centers",
    ],
    "sawdust": [
        "Available at local feed stores or garden centers",
    ],
    "hardwood": [
        "Available at local feed stores or garden centers",
    ],
    "coco coir": [
        "Available at local garden centers or home improvement stores",
    ],
    "vermiculite": [
        "Available at local garden centers or home improvement stores",
    ],
    "gypsum": [
        "Available at local garden centers or home improvement stores",
    ],
    "grow bag": [
        "https://unicornbags.com",
        "https://shroomsupply.com",
    ],
    "monotub": [
        "Available at home improvement stores (large storage tubs)",
    ],
    "liner": [
        "Available at any grocery or home improvement store",
    ],
    "isopropyl alcohol": [
        "Available at any pharmacy",
    ],
    "nitrile gloves": [
        "Available at any pharmacy",
    ],
    "pressure cooker": [
        "Available at kitchen supply stores",
    ],
    "spray bottle": [
        "Available at any home improvement or dollar store",
    ],
    "soy hull": [
        "https://northspore.com",
        "https://shroomsupply.com",
    ],
    "wheat bran": [
        "Available at local feed stores or bulk food suppliers",
    ],
    "brown rice": [
        "Available at any grocery store",
    ],
    "manure": [
        "Available at local garden centers or farm supply stores",
    ],
    "cheese wax": [
        "Available at homebrewing or cheesemaking supply stores",
    ],
}


def _find_supplier_links(item_name: str) -> list[str]:
    """Match supplier links based on keywords in the item name."""
    name_lower = item_name.lower()
    for keyword, links in _SUPPLIER_LINKS.items():
        if keyword in name_lower:
            return links
    return []


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
        item = {"name": name, "category": "substrate",
                "supplier_links": _find_supplier_links(name)}
        if value == 0.0:
            item["quantity"] = unit
        else:
            item["quantity"] = _format_quantity(round(value * scale, 1), unit)
        items.append(item)

    # Spawn
    spawn_name = "Grain spawn"
    spawn_g = round(total_dry_substrate_g * (recipe.spawn_rate_percent / 100.0), 1)
    items.append({
        "name": spawn_name,
        "quantity": _format_quantity(spawn_g, "g"),
        "category": "spawn",
        "supplier_links": _find_supplier_links(spawn_name),
    })

    # Containers
    monotub_name = f"Monotub / grow container ({container_liters}L)"
    items.append({
        "name": monotub_name,
        "quantity": f"{grows}",
        "category": "containers",
        "supplier_links": _find_supplier_links(monotub_name),
    })
    liner_name = "Liner (trash bag)"
    items.append({
        "name": liner_name,
        "quantity": f"{grows}",
        "category": "containers",
        "supplier_links": _find_supplier_links(liner_name),
    })

    # Supplies — always needed
    alcohol_name = "Isopropyl alcohol (70%)"
    items.append({
        "name": alcohol_name,
        "quantity": "1 bottle",
        "category": "supplies",
        "supplier_links": _find_supplier_links(alcohol_name),
    })
    items.append({
        "name": "Spray bottle",
        "quantity": "1",
        "category": "supplies",
        "supplier_links": _find_supplier_links("Spray bottle"),
    })
    gloves_name = "Nitrile gloves"
    items.append({
        "name": gloves_name,
        "quantity": "1 box",
        "category": "supplies",
        "supplier_links": _find_supplier_links(gloves_name),
    })

    # Pressure cooker needed if sterilization requires it
    if "sterilize" in recipe.sterilization_method.lower() or "pressure" in recipe.sterilization_method.lower():
        pc_name = "Pressure cooker (23+ quart)"
        items.append({
            "name": pc_name,
            "quantity": "1",
            "category": "supplies",
            "supplier_links": _find_supplier_links(pc_name),
        })

    return {
        "species_id": profile.id,
        "common_name": profile.common_name,
        "recipe_name": recipe.name,
        "grows": grows,
        "container_liters": container_liters,
        "items": items,
    }
