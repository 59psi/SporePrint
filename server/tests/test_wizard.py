from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins, get_all_profiles
from app.species.wizard import recommend


async def test_beginner_culinary_recommends_blue_oyster():
    """A first-time grower wanting culinary species should get blue_oyster.

    Blue oyster fruits at 55-65F so we use 'cool' temp range.
    """
    await seed_builtins()
    profiles = await get_all_profiles()
    results = recommend(
        profiles,
        experience="first_time",
        environment="indoor_closet",
        temp_range="cool",
        substrates=["straw"],
        goal="culinary",
        commitment="set_and_forget",
    )
    assert len(results) == 5
    species_ids = [r["species_id"] for r in results]
    assert "blue_oyster" in species_ids


async def test_advanced_research_returns_results():
    """An advanced grower with research goal should still get results."""
    await seed_builtins()
    profiles = await get_all_profiles()
    results = recommend(
        profiles,
        experience="advanced",
        environment="indoor_tent",
        temp_range="warm",
        substrates=["all"],
        goal="research",
        commitment="dedicated_hobbyist",
    )
    assert len(results) == 5
    for r in results:
        assert "species_id" in r
        assert "score" in r
        assert "reasons" in r
        assert "tldr" in r
        assert r["score"] >= 0


async def test_scores_sorted_descending():
    """Results must be sorted by score from highest to lowest."""
    await seed_builtins()
    profiles = await get_all_profiles()
    results = recommend(
        profiles,
        experience="some_experience",
        environment="indoor_tent",
        temp_range="cool",
        substrates=["sawdust", "straw"],
        goal="culinary",
        commitment="daily_attention",
    )
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


async def test_result_shape():
    """Each result should have the expected fields."""
    await seed_builtins()
    profiles = await get_all_profiles()
    results = recommend(
        profiles,
        experience="first_time",
        environment="indoor_closet",
        temp_range="moderate",
        substrates=["straw"],
        goal="culinary",
        commitment="set_and_forget",
    )
    for r in results:
        assert isinstance(r["species_id"], str)
        assert isinstance(r["common_name"], str)
        assert isinstance(r["scientific_name"], str)
        assert isinstance(r["category"], str)
        assert isinstance(r["score"], int)
        assert isinstance(r["reasons"], list)
        assert isinstance(r["tldr"], str)
        assert 0 <= r["score"] <= 100


async def test_medicinal_goal_favors_medicinal_category():
    """Medicinal goal should rank medicinal species higher."""
    await seed_builtins()
    profiles = await get_all_profiles()
    results = recommend(
        profiles,
        experience="some_experience",
        environment="indoor_tent",
        temp_range="warm",
        substrates=["sawdust", "grain"],
        goal="medicinal",
        commitment="dedicated_hobbyist",
    )
    # At least one medicinal species should appear in the top 5
    categories = [r["category"] for r in results]
    assert "medicinal" in categories
