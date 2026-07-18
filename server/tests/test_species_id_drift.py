"""Regression: species_profile_id hyphen/underscore drift (gap V1-1).

scripts/port_species.py (parent repo) rewrites every profile id `_`→`-` for the
cloud/mobile view-model, so the UI stores a hyphenated `species_profile_id`
(e.g. "lions-mane") on the sessions it creates, while the Pi seeds
`species_profiles` with the underscored builtin id ("lions_mane"). Before the
fix, get_profile(stored_id) missed 63 of 74 species and returned None — silently
disabling species-driven setpoint control, safety alerts, planner warnings and
the phase-timeline projection. These tests pin the centralized canonicalization.
"""

from app.sessions.models import SessionCreate
from app.sessions.service import create_session, flush_status
from app.species.profiles import canonical_species_id, species_id_candidates
from app.species.service import create_profile, get_profile, seed_builtins
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile


# ── get_profile tolerance ────────────────────────────────────────────────────


async def test_get_profile_resolves_hyphenated_multiword_id():
    """The UI's hyphenated id resolves to the underscored builtin profile."""
    await seed_builtins()
    profile = await get_profile("lions-mane")  # table is seeded "lions_mane"
    assert profile is not None
    assert profile.id == "lions_mane"
    assert profile.common_name == "Lion's Mane"


async def test_get_profile_still_resolves_underscored_id():
    """Exact underscored ids — used by direct DB inserts — keep working."""
    await seed_builtins()
    profile = await get_profile("lions_mane")
    assert profile is not None
    assert profile.common_name == "Lion's Mane"


async def test_get_profile_unknown_id_returns_none():
    """A genuinely unknown id (neither spelling exists) still returns None."""
    await seed_builtins()
    assert await get_profile("not-a-real-species") is None


async def test_get_profile_prefers_exact_match_over_swap():
    """When both spellings exist, the exact stored id wins (as-given first)."""
    await seed_builtins()
    # Custom profile stored with a hyphen that collides with no builtin.
    await create_profile(_custom_profile(id="my-strain", common_name="Exact Hit"))
    await create_profile(_custom_profile(id="my_strain", common_name="Swapped"))
    assert (await get_profile("my-strain")).common_name == "Exact Hit"
    assert (await get_profile("my_strain")).common_name == "Swapped"


# ── create_session: the write path that carries the UI's hyphenated id ───────


async def test_create_session_multiword_species_is_resolvable():
    """Core gap V1-1 case: a session created the way the UI does (hyphenated,
    multi-word id) resolves back to its profile — every species-driven feature
    (setpoints, safety, planner, timeline) depends on this."""
    await seed_builtins()
    s = await create_session(
        SessionCreate(name="LM grow", species_profile_id="lions-mane")
    )
    stored_id = s["species_profile_id"]
    profile = await get_profile(stored_id)
    assert profile is not None
    assert profile.id == "lions_mane"
    assert profile.common_name == "Lion's Mane"
    # The flush lifecycle resolves the species' expected count via get_profile.
    status = await flush_status(s["id"])
    assert status["expected_flushes"] == 2  # lions_mane flush_count_typical


async def test_create_session_normalizes_underscored_id_to_ui_form():
    """A caller that submits the underscored id is normalized to the hyphenated
    UI spelling, so the stored row matches what the cloud/mobile surfaces send
    and locally match against — while still resolving to the profile."""
    await seed_builtins()
    s = await create_session(
        SessionCreate(name="LM grow", species_profile_id="lions_mane")
    )
    assert s["species_profile_id"] == "lions-mane"
    assert (await get_profile(s["species_profile_id"])) is not None


# ── centralized helpers ──────────────────────────────────────────────────────


def test_species_id_candidates_try_as_given_first_then_swapped():
    assert species_id_candidates("lions-mane") == ["lions-mane", "lions_mane"]
    assert species_id_candidates("lions_mane") == ["lions_mane", "lions-mane"]


def test_species_id_candidates_single_token_has_one_candidate():
    assert species_id_candidates("shiitake") == ["shiitake"]


def test_canonical_species_id_is_hyphenated_and_idempotent():
    assert canonical_species_id("lions_mane") == "lions-mane"
    assert canonical_species_id("lions-mane") == "lions-mane"  # already canonical
    assert canonical_species_id("shiitake") == "shiitake"


# ── local fixtures ───────────────────────────────────────────────────────────


def _custom_profile(**overrides) -> SpeciesProfile:
    defaults = dict(
        id="custom",
        common_name="Custom",
        scientific_name="Testus testii",
        category="gourmet",
        substrate_types=["straw"],
        colonization_visual_description="White mycelium",
        contamination_risk_notes="Watch for trich",
        pinning_trigger_description="Cold shock",
        phases={
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
                light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 7),
            ),
        },
        flush_count_typical=3,
        yield_notes="Test yield",
    )
    defaults.update(overrides)
    return SpeciesProfile(**defaults)
