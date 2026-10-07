import itertools

import pytest

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


_NOT_CULTIVABLE = {p.id for p in BUILTIN_PROFILES if not p.chamber_cultivable}


@pytest.mark.parametrize("env", ["indoor_closet", "indoor_tent"])
def test_indoor_recommendations_exclude_non_chamber_cultivable_species(env):
    """srv-rest#30: chaga (a ~10-year sclerotium on living birch) was ranked #4
    for an indoor closet with the reason 'Suitable for closet growing'."""
    assert "chaga" in _NOT_CULTIVABLE
    results = recommend(
        BUILTIN_PROFILES,
        experience="advanced",
        environment=env,
        temp_range="warm",
        substrates=["all"],
        goal="research",
        commitment="dedicated_hobbyist",
        limit=len(BUILTIN_PROFILES),
    )
    assert not _NOT_CULTIVABLE & {r["species_id"] for r in results}


def test_outdoor_recommendations_may_include_reference_species():
    results = recommend(
        BUILTIN_PROFILES,
        experience="advanced",
        environment="outdoor_beds",
        temp_range="warm",
        substrates=["all"],
        goal="research",
        commitment="dedicated_hobbyist",
        limit=len(BUILTIN_PROFILES),
    )
    assert "giant_puffball" in {r["species_id"] for r in results}


# ── Controlled categories are opt-in (as on the cloud's wizard) ─────────

_ACTIVE = {p.id for p in BUILTIN_PROFILES if p.category == "active"}
_ANSWERS = dict(experience="advanced", environment="indoor_tent", temp_range="warm",
                substrates=["all"], goal="research", commitment="dedicated_hobbyist")


def test_active_species_are_left_out_by_default():
    assert _ACTIVE, "no active profiles: drop these tests or the category"
    results = recommend(BUILTIN_PROFILES, **_ANSWERS, limit=len(BUILTIN_PROFILES))
    assert results and not _ACTIVE & {r["species_id"] for r in results}


def test_every_answer_the_dashboard_can_send_leaves_them_out():
    """The dashboard's five questions map onto these values (WizardPage's
    *_MAP tables, env fixed at indoor_tent); none ranks an active species
    unless the operator opts in."""
    for level, temp, sub, goal, commit in itertools.product(
        ("first_time", "some_experience", "advanced"), ("cool", "moderate", "warm"),
        ("sawdust", "straw", "all"), ("culinary", "medicinal", "both"),
        ("set_and_forget", "daily_attention", "dedicated_hobbyist"),
    ):
        results = recommend(BUILTIN_PROFILES, experience=level, environment="indoor_tent", temp_range=temp,
                            substrates=[sub], goal=goal, commitment=commit)
        assert not _ACTIVE & {r["species_id"] for r in results}, (level, temp, sub, goal, commit)


def test_include_active_opts_them_in():
    results = recommend(BUILTIN_PROFILES, **_ANSWERS, include_active=True, limit=len(BUILTIN_PROFILES))
    assert _ACTIVE <= {r["species_id"] for r in results}


def test_the_endpoint_takes_the_opt_in(client):
    query = ("/api/species/recommend?level=advanced&env=indoor_tent&temp_range=warm"
             "&substrate=all&goal=research&commitment=dedicated_hobbyist")
    default = client.get(query)
    assert default.status_code == 200
    assert default.json() and not _ACTIVE & {r["species_id"] for r in default.json()}
    opted = client.get(query + "&include_active=true")
    assert opted.status_code == 200 and len(opted.json()) == 5
    # For a research goal the opted-in pool ranks an active species in the top 5.
    assert _ACTIVE & {r["species_id"] for r in opted.json()}
