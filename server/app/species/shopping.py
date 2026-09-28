"""Shopping List Generator — creates a categorized shopping list for a grow.

Given a species profile and grow parameters, produces a list of items
grouped by category (substrate, spawn, containers, supplies) with
quantities scaled for the requested number of grows and container size.
"""

from __future__ import annotations

from .models import SpeciesProfile
from .substrate import BASE_DENSITY_KG_PER_LITER, _format_quantity, calculate_recipe


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
        "Available at local feed stores",
        "https://www.amazon.com/s?k=wheat+straw+bale",
    ],
    "sawdust": [
        "Available at local feed stores or garden centers",
        "https://www.amazon.com/s?k=hardwood+sawdust+pellets",
    ],
    "hardwood": [
        "Available at local feed stores or garden centers",
        "https://www.amazon.com/s?k=hardwood+fuel+pellets",
    ],
    "coco coir": [
        "https://www.amazon.com/s?k=coco+coir+brick",
        "Available at garden centers",
    ],
    "vermiculite": [
        "https://www.amazon.com/s?k=vermiculite+gardening",
        "Available at garden centers",
    ],
    "gypsum": [
        "https://www.amazon.com/s?k=gypsum+powder+garden",
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
        "https://www.amazon.com/s?k=isopropyl+alcohol+70",
        "Available at any pharmacy",
    ],
    "nitrile gloves": [
        "https://www.amazon.com/s?k=nitrile+gloves+disposable",
        "Available at any pharmacy",
    ],
    "pressure cooker": [
        "https://www.amazon.com/s?k=pressure+cooker+23+quart",
    ],
    "spray bottle": [
        "https://www.amazon.com/s?k=fine+mist+spray+bottle",
    ],
    "soy hull": [
        "https://northspore.com",
        "https://shroomsupply.com",
    ],
    "wheat bran": [
        "https://www.amazon.com/s?k=wheat+bran+bulk",
        "Available at local feed stores or bulk food suppliers",
    ],
    "brown rice": [
        "https://www.amazon.com/s?k=brown+rice+flour",
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

    # Substrate ingredients — the substrate calculator's own scaling for the
    # combined volume of every grow, so the two endpoints always agree (this
    # used to weigh every non-gram unit as 100 g, over-stating lb recipes ~4.5x).
    scaled = calculate_recipe(recipe, container_liters * grows)["ingredients"]
    for name, quantity in scaled.items():
        items.append({
            "name": name,
            "category": "substrate",
            "quantity": quantity,
            "supplier_links": _find_supplier_links(name),
        })

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
