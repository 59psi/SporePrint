from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins, get_profile
from app.species.shopping import container_kind, generate_shopping_list
from app.species.substrate import calculate_recipe


async def test_a_seeded_profiles_list_has_every_category_and_scales_with_grows():
    """The route builds the list from the profile as seeded in the DB: it
    carries substrate, spawn and containers, and the spawn scales with the
    number of grows. (An unknown species is the route's 404, test_species.py.)"""
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    one = generate_shopping_list(profile, grows=1, container_liters=5.0)
    three = generate_shopping_list(profile, grows=3, container_liters=5.0)
    assert (one["species_id"], one["grows"], three["grows"]) == ("blue_oyster", 1, 3)
    assert {"substrate", "spawn", "containers"} <= {item["category"] for item in one["items"]}
    spawn = [next(i["quantity"] for i in r["items"] if i["category"] == "spawn") for r in (one, three)]
    assert spawn == ["150 g", "450 g"]


# ── shopping list agrees with the substrate calculator ───────────────────


def test_blue_oyster_straw_matches_substrate_calculator():
    """Non-gram units used to count as 100 g each: 5 lbs straw → '15 lbs' on the
    list vs '3.3 lbs' from the calculator for the same 5 L grow."""
    profile = next(p for p in BUILTIN_PROFILES if p.id == "blue_oyster")
    result = generate_shopping_list(profile, grows=1, container_liters=5.0)
    straw = next(i for i in result["items"] if i["name"] == "chopped wheat/oat straw")
    assert straw["quantity"] == "3.3 lbs"


def test_every_builtin_shopping_list_matches_calculator():
    """The list's substrate is the calculator's batch for every grow combined;
    a per-grow count or dimension the calculator leaves as written carries
    the number of grows."""
    for profile in BUILTIN_PROFILES:
        if not profile.substrate_recipes:
            continue
        result = generate_shopping_list(profile, grows=3, container_liters=4.0)
        expected = calculate_recipe(profile.substrate_recipes[0], 12.0)["ingredients"]
        got = {i["name"]: i["quantity"] for i in result["items"] if i["category"] == "substrate"}
        assert got.keys() == expected.keys(), profile.id
        for name, quantity in got.items():
            assert quantity in (expected[name], f"{expected[name]} per grow × 3"), (profile.id, name)


# ── per-grow counts and the inoculant line ──────────────────────────────


def _substrate_and_spawn(pid, grows=1, liters=5.0):
    result = generate_shopping_list(_profile(pid), grows=grows, container_liters=liters)
    return {i["name"]: i["quantity"] for i in result["items"] if i["category"] in ("substrate", "spawn")}


def test_per_grow_counts_carry_the_number_of_grows():
    """5 cubic feet of chips and a cardboard sheet are one bed's worth: three
    beds used to list the same 5 cubic feet as one."""
    three = _substrate_and_spawn("wine_cap", grows=3)
    assert three["hardwood wood chips"] == "5 cubic feet per grow × 3"
    assert three["cardboard"] == "4x4 foot sheet per grow × 3"
    assert _substrate_and_spawn("wine_cap")["hardwood wood chips"] == "5 cubic feet"
    log = _substrate_and_spawn("chicken_of_the_woods", grows=3)
    assert log["fresh oak log"] == "6-12 inch diameter x 3-4 feet per grow × 3"
    # A rate, a ratio or a depth reads the same for any number of grows.
    assert log["plug spawn"] == "30-50 plugs per log"
    ratios = generate_shopping_list(_profile("lyophyllum_decastes"), grows=3)["items"]
    assert {i["name"]: i["quantity"] for i in ratios}["rice bran"] == "3 parts"


def test_no_grain_spawn_line_where_the_recipe_takes_none():
    """giant_puffball (0 %: a spore slurry) used to list 'Grain spawn: g'; a
    100 % grain jar listed 1.5 kg of grain spawn for 5 L of grain; a log grown
    from plugs listed grain spawn beside them."""
    for pid in ("giant_puffball", "pestalotiopsis_microspora", "chicken_of_the_woods"):
        items = generate_shopping_list(_profile(pid), grows=1, container_liters=5.0)["items"]
        assert not [i for i in items if i["name"] == "Grain spawn"], pid
        assert all(i["quantity"].strip() != "g" for i in items), pid
    # A jar culture takes a culture, at the recipe's rate.
    assert _substrate_and_spawn("cordyceps_militaris")["Spawn or liquid culture"] == "150 g"
    assert _substrate_and_spawn("blue_oyster", grows=2)["Grain spawn"] == "300 g"


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


def test_absurd_sizes_are_422_not_500(client):
    """inf passed gt=0 and overflowed the arithmetic into a 500."""
    for query in ("container_liters=inf", "container_liters=1e308", "container_liters=1001", "grows=101"):
        r = client.get(f"/api/species/blue_oyster/shopping-list?{query}")
        assert r.status_code == 422, (query, r.text)
    for query in ("volume_liters=inf", "volume_liters=1e308"):
        r = client.get(f"/api/species/blue_oyster/substrate?{query}")
        assert r.status_code == 422, (query, r.text)
    assert client.get("/api/species/blue_oyster/shopping-list?grows=100&container_liters=1000").status_code == 200
    assert client.get("/api/species/blue_oyster/substrate?volume_liters=1000").status_code == 200
