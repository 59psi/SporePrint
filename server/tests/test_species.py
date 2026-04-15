from app.species.models import GrowPhase, PhaseParams, SpeciesProfile
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import (
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
