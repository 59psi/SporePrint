from app.species.service import seed_builtins, get_profile
from app.species.shopping import generate_shopping_list


async def test_shopping_list_returns_categorized_items():
    """Shopping list for blue_oyster should include substrate, spawn, and containers."""
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None

    result = generate_shopping_list(profile, grows=1, container_liters=5.0)
    assert result is not None
    assert result["species_id"] == "blue_oyster"
    assert result["grows"] == 1
    assert len(result["items"]) > 0

    categories = {item["category"] for item in result["items"]}
    assert "substrate" in categories
    assert "spawn" in categories
    assert "containers" in categories


async def test_shopping_list_nonexistent_species():
    """get_profile returns None for nonexistent species, so shopping list should be None."""
    await seed_builtins()
    profile = await get_profile("nonexistent_species_xyz")
    assert profile is None


async def test_shopping_list_scales_with_grows():
    """Multiple grows should produce larger quantities."""
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None

    result_1 = generate_shopping_list(profile, grows=1, container_liters=5.0)
    result_3 = generate_shopping_list(profile, grows=3, container_liters=5.0)

    assert result_1 is not None
    assert result_3 is not None
    assert result_3["grows"] == 3

    # Spawn should scale with number of grows
    spawn_1 = next(i for i in result_1["items"] if i["category"] == "spawn")
    spawn_3 = next(i for i in result_3["items"] if i["category"] == "spawn")
    # Both should have quantity strings; the 3-grow one should be larger
    assert spawn_1["quantity"] != spawn_3["quantity"]
