import re

import pytest

from app.db import get_db
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import (
    BuiltinProfileReadOnly,
    seed_builtins,
    get_all_profiles,
    get_profile,
    create_profile,
    update_profile,
    delete_profile,
)


def _make_custom_profile(**overrides):
    defaults = dict(
        id="custom_test",
        common_name="Test Species",
        scientific_name="Testus testii",
        category="gourmet",
        substrate_types=["straw"],
        colonization_visual_description="White mycelium",
        contamination_risk_notes="Watch for trich",
        pinning_trigger_description="Cold shock",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high", light_hours_on=0,
                light_hours_off=24, light_spectrum="none", fae_mode="none",
                expected_duration_days=(10, 14),
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
                light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
                expected_duration_days=(5, 7),
            ),
        },
        flush_count_typical=3,
        yield_notes="Test yield",
    )
    defaults.update(overrides)
    return SpeciesProfile(**defaults)


async def test_seed_builtins():
    await seed_builtins()
    profiles = await get_all_profiles()
    assert len(profiles) == len(BUILTIN_PROFILES)


async def test_seed_builtins_idempotent():
    await seed_builtins()
    await seed_builtins()
    profiles = await get_all_profiles()
    assert len(profiles) == len(BUILTIN_PROFILES)


async def test_get_profile():
    await seed_builtins()
    profile = await get_profile("blue_oyster")
    assert profile is not None
    assert profile.common_name == "Blue Oyster"
    assert profile.category == "gourmet"
    assert GrowPhase.FRUITING in profile.phases


async def test_get_profile_not_found():
    result = await get_profile("nonexistent")
    assert result is None


async def test_create_custom_profile():
    custom = _make_custom_profile()
    created = await create_profile(custom)
    assert created.id == "custom_test"
    fetched = await get_profile("custom_test")
    assert fetched is not None
    assert fetched.common_name == "Test Species"


async def test_update_profile():
    custom = _make_custom_profile()
    await create_profile(custom)
    updated_data = _make_custom_profile(common_name="Updated Name")
    result = await update_profile("custom_test", updated_data)
    assert result.common_name == "Updated Name"
    fetched = await get_profile("custom_test")
    assert fetched.common_name == "Updated Name"


async def test_delete_custom_profile():
    custom = _make_custom_profile()
    await create_profile(custom)
    result = await delete_profile("custom_test")
    assert result is True
    assert await get_profile("custom_test") is None


async def test_delete_builtin_prevented():
    await seed_builtins()
    result = await delete_profile("blue_oyster")
    assert result is False
    assert await get_profile("blue_oyster") is not None


# ── srv-rest#16: built-ins are read-only templates; custom rows survive seeding ──


async def test_update_builtin_is_refused_instead_of_silently_reverting():
    """PUT on a built-in used to 200 and then be reverted by seed_builtins() on
    the next restart. CLAUDE.md §4c: customize by cloning."""
    await seed_builtins()
    stock = await get_profile("blue_oyster")
    edited = stock.model_copy(update={"common_name": "My Blue"})
    with pytest.raises(BuiltinProfileReadOnly):
        await update_profile("blue_oyster", edited)
    assert (await get_profile("blue_oyster")).common_name == "Blue Oyster"


async def test_seed_does_not_overwrite_custom_profile_sharing_builtin_id():
    custom = _make_custom_profile(id="blue_oyster", common_name="My Own Blue")
    await create_profile(custom)
    await seed_builtins()
    assert (await get_profile("blue_oyster")).common_name == "My Own Blue"
    # ... and it is still the user's (deletable) row.
    assert await delete_profile("blue_oyster") is True


async def test_seed_still_refreshes_builtin_rows():
    await seed_builtins()
    async with get_db() as db:
        await db.execute(
            "UPDATE species_profiles SET data = ? WHERE id = 'blue_oyster'",
            (_make_custom_profile(id="blue_oyster", common_name="Stale").model_dump_json(),),
        )
        await db.commit()
    await seed_builtins()
    assert (await get_profile("blue_oyster")).common_name == "Blue Oyster"


async def test_update_and_delete_resolve_hyphen_underscore_ids():
    await create_profile(_make_custom_profile(id="my_strain"))
    updated = await update_profile("my-strain", _make_custom_profile(id="my_strain", common_name="Renamed"))
    assert updated is not None
    assert (await get_profile("my_strain")).common_name == "Renamed"
    assert await delete_profile("my-strain") is True
    assert await get_profile("my_strain") is None


def test_put_builtin_endpoint_returns_409(client):
    body = client.get("/api/species/lions_mane").json()
    body["common_name"] = "Edited"
    r = client.put("/api/species/lions-mane", json=body)
    assert r.status_code == 409
    assert "clone" in r.json()["detail"].lower()
    assert client.get("/api/species/lions_mane").json()["common_name"] != "Edited"


# ── A card agrees with itself (2026-10 browser audit) ────────────────
# The Shiitake card said "Cold shock (38-50°F overnight) … 3-5 flushes" in
# its summary while its pinning trigger said cold-water soak and its yield
# said 3-6 flushes; king trumpet, yellow oyster, chestnut, pioppino and
# nameko had the same summary-vs-yield flush split.

_FLUSH_RANGE = re.compile(r"(\d+)-(\d+) flushes")


@pytest.mark.parametrize("profile", BUILTIN_PROFILES, ids=lambda p: p.id)
def test_summary_and_yield_give_one_flush_range(profile):
    ranges = {tuple(map(int, m)) for text in (profile.tldr or "", profile.yield_notes or "")
              for m in _FLUSH_RANGE.findall(text)}
    assert len(ranges) <= 1, f"{profile.id}: tldr and yield_notes disagree: {sorted(ranges)}"
    for lo, hi in ranges:
        assert lo <= profile.flush_count_typical <= hi, (profile.id, lo, hi)


def test_shiitake_summary_names_the_soak_it_reminds_about():
    shiitake = next(p for p in BUILTIN_PROFILES if p.id == "shiitake")
    assert "Cold-water soak (35-50°F, 12-24h)" in shiitake.pinning_trigger_description
    assert "cold-water soak (35-50°F, 12-24h)" in shiitake.tldr
    assert "Cold shock" not in shiitake.tldr
