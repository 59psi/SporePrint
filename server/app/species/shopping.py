"""Shopping List Generator — creates a categorized shopping list for a grow.

Given a species profile and grow parameters, produces a list of items
grouped by category (substrate, spawn, containers, supplies) with
quantities scaled for the requested number of grows and container size.
"""

from __future__ import annotations

import re

from .models import SpeciesProfile, SubstrateRecipe
from .substrate import (
    BASE_DENSITY_KG_PER_LITER,
    _format_quantity,
    _parse_amount,
    _unit_kind,
    calculate_recipe,
)


# ── Supplier links by item category / keyword ─────────────────────
_SUPPLIER_LINKS: dict[str, list[str]] = {
    "grain spawn": [
        "https://northspore.com",
        "https://fungi.com",
    ],
    "liquid culture": [
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


# The vessel a recipe is grown in, from the recipe itself (the list used to
# give every species a monotub + trash-bag liner — two sawdust-block species
# came out as "Monotub ×2" instead of filter-patch bags):
#   • outdoor beds and logs need no container;
#   • grain, brown-rice, agar and bottle cultures go in jars / dishes;
#   • any other pressure-sterilized bulk substrate (supplemented sawdust,
#     masters mix, chips, hulls) is sterilized, inoculated and fruited in a
#     filter-patch grow bag — no tub, no liner;
#   • pasteurized bulk (CVG, manure, straw) goes in a lined monotub.
_OUTDOOR_RECIPE = re.compile(r"\b(?:outdoor|log|bed)\b", re.I)
_JAR_RECIPE = re.compile(r"\b(?:grain|brown rice|agar|bottle)\b", re.I)


def container_kind(recipe: SubstrateRecipe) -> str:
    """What a grow on this recipe sits in: "none", "jar", "bag" or "tub"."""
    if _OUTDOOR_RECIPE.search(recipe.name):
        return "none"
    if _JAR_RECIPE.search(recipe.name):
        return "jar"
    if "pressure" in recipe.sterilization_method.lower():
        return "bag"
    return "tub"


def _container_items(recipe: SubstrateRecipe, grows: int, container_liters: float) -> list[dict]:
    kind = container_kind(recipe)
    if kind == "none":
        return []
    if kind == "jar":
        names = [f"Wide-mouth jars with filter lids ({container_liters}L per grow)"]
    elif kind == "bag":
        names = [f"Filter-patch grow bag ({container_liters}L)"]
    else:
        names = [f"Monotub / grow container ({container_liters}L)", "Liner (trash bag)"]
    return [
        {
            "name": name,
            "quantity": f"{grows}",
            "category": "containers",
            "supplier_links": _find_supplier_links(name),
        }
        for name in names
    ]


def _find_supplier_links(item_name: str) -> list[str]:
    """Match supplier links based on keywords in the item name."""
    name_lower = item_name.lower()
    for keyword, links in _SUPPLIER_LINKS.items():
        if keyword in name_lower:
            return links
    return []


# A passthrough quantity (one the calculator does not scale) that is one
# grow's worth of something countable or bulky: a log, a 4x4 sheet, 5 cubic
# feet of chips. A list for N grows needs N of them. Ratios ("3 parts"),
# depths ("1 inch"), rates ("30-50 plugs per log") and descriptions read the
# same for any number of grows.
_PER_GROW_UNIT = re.compile(r"\b(?:cubic|logs?|sheets?|bales?|blocks?|bricks?|diameter)\b", re.I)


def _for_grows(raw: str, quantity: str, grows: int) -> str:
    """`quantity` (the calculator's rendering of the recipe's `raw` amount)
    for `grows` grows: a per-grow count or dimension is marked with the
    number of grows; anything else is already scaled, or needs no scaling."""
    value, _hi, unit = _parse_amount(raw)
    if grows <= 1 or value is None or _unit_kind(unit) != "passthrough":
        return quantity
    if " per " in f" {unit.lower()} " or not _PER_GROW_UNIT.search(unit):
        return quantity
    return f"{quantity} per grow × {grows}"


# An ingredient that is the inoculant itself ("plug spawn", "spore slurry").
_INOCULANT = re.compile(r"\b(?:spawn|spores?|slurry|inocul(?:um|ant)s?|cultures?)\b", re.I)


def _spawn_item(recipe: SubstrateRecipe, total_dry_substrate_g: float) -> dict | None:
    """The inoculant line for the batch, or None.

    None for a recipe that takes no spawn (0 %: inoculated with a spore
    slurry), for one whose grain is the substrate itself (100 %: a grain or
    BRF jar, inoculated with spores or a liquid culture), and for one that
    lists its own inoculant (plug spawn for logs): "Grain spawn: g", 1.5 kg
    of grain spawn for a 5 L grain jar, or grain spawn beside a log's plugs
    read as real purchases. A jar culture (brown rice, agar, bottles) takes a
    culture rather than grain spawn.
    """
    rate = recipe.spawn_rate_percent
    if rate <= 0 or rate >= 100 or any(_INOCULANT.search(n) for n in recipe.ingredients):
        return None
    name = "Spawn or liquid culture" if container_kind(recipe) == "jar" else "Grain spawn"
    spawn_g = round(total_dry_substrate_g * (rate / 100.0), 1)
    return {
        "name": name,
        "quantity": _format_quantity(spawn_g, "g"),
        "category": "spawn",
        "supplier_links": _find_supplier_links(name),
    }


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
            "quantity": _for_grows(recipe.ingredients[name], quantity, grows),
            "supplier_links": _find_supplier_links(name),
        })

    # Spawn
    if spawn := _spawn_item(recipe, total_dry_substrate_g):
        items.append(spawn)

    # Containers — the recipe's own vessel (container_kind)
    items.extend(_container_items(recipe, grows, container_liters))

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
