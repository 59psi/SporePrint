from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins, get_profile
from app.species.shopping import container_kind, generate_shopping_list
from app.species.substrate import calculate_recipe


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


# ── srv-rest#22: shopping list agrees with the substrate calculator ──────


def test_blue_oyster_straw_matches_substrate_calculator():
    """Non-gram units used to count as 100 g each: 5 lbs straw → '15 lbs' on the
    list vs '3.3 lbs' from the calculator for the same 5 L grow."""
    profile = next(p for p in BUILTIN_PROFILES if p.id == "blue_oyster")
    result = generate_shopping_list(profile, grows=1, container_liters=5.0)
    straw = next(i for i in result["items"] if i["name"] == "chopped wheat/oat straw")
    assert straw["quantity"] == "3.3 lbs"


def test_every_builtin_shopping_list_matches_calculator():
    for profile in BUILTIN_PROFILES:
        if not profile.substrate_recipes:
            continue
        result = generate_shopping_list(profile, grows=3, container_liters=4.0)
        expected = calculate_recipe(profile.substrate_recipes[0], 12.0)["ingredients"]
        got = {i["name"]: i["quantity"] for i in result["items"] if i["category"] == "substrate"}
        assert got == expected, profile.id


# ── 2026-10 audit: the container comes from the recipe ──────────────────


def _profile(pid):
    return next(p for p in BUILTIN_PROFILES if p.id == pid)


def _containers(pid, grows=2, liters=5.0):
    result = generate_shopping_list(_profile(pid), grows=grows, container_liters=liters)
    return {i["name"]: i["quantity"] for i in result["items"] if i["category"] == "containers"}


def test_sawdust_block_species_get_filter_patch_bags_not_a_lined_monotub():
    # Shiitake + Lion's Mane (supplemented hardwood, pressure-sterilized) came
    # out as "Monotub / grow container (5.0L) ×2" plus a trash-bag liner.
    for pid in ("shiitake", "lions_mane"):
        assert container_kind(_profile(pid).substrate_recipes[0]) == "bag", pid
        assert _containers(pid) == {"Filter-patch grow bag (5.0L)": "2"}, pid
    bag = next(
        i for i in generate_shopping_list(_profile("shiitake"))["items"]
        if i["name"].startswith("Filter-patch grow bag")
    )
    assert bag["supplier_links"], "grow-bag suppliers"


def test_pasteurized_bulk_keeps_the_lined_monotub():
    for pid in ("cubensis_golden_teacher", "blue_oyster"):  # CVG, straw
        assert _containers(pid) == {
            "Monotub / grow container (5.0L)": "2",
            "Liner (trash bag)": "2",
        }, pid


def test_grain_rice_and_outdoor_recipes():
    assert _containers("cordyceps_militaris") == {"Wide-mouth jars with filter lids (5.0L per grow)": "2"}
    kinds = {
        p.substrate_recipes[0].name: container_kind(p.substrate_recipes[0])
        for p in BUILTIN_PROFILES if p.substrate_recipes
    }
    assert kinds["Rye Grain (Sclerotia Production)"] == "jar"
    assert kinds["Hardwood Log Cultivation"] == "none"
    assert kinds["Hardwood Chip Bed"] == "none"
    # every recipe resolves, and only an outdoor bed / log lists no vessel
    for profile in BUILTIN_PROFILES:
        if not profile.substrate_recipes:
            continue
        got = _containers(profile.id)
        assert bool(got) == (container_kind(profile.substrate_recipes[0]) != "none"), profile.id
