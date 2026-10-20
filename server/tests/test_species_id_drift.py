"""Regression: species_profile_id hyphen/underscore drift (gap V1-1).

scripts/port_species.py (parent repo) rewrites every profile id `_`→`-` for the
cloud/mobile view-model, so the UI stores a hyphenated `species_profile_id`
(e.g. "lions-mane") on the sessions it creates, while the Pi seeds
`species_profiles` with the underscored builtin id ("lions_mane"). Before the
fix, get_profile(stored_id) missed 63 of 74 species and returned None — silently
disabling species-driven setpoint control, safety alerts, planner warnings and
the phase-timeline projection. These tests pin the centralized canonicalization.
"""

import pytest

from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session, flush_status
from app.species.profiles import canonical_species_id, species_id_candidates
from app.species.service import (
    ProfileExistsError,
    create_profile,
    get_profile,
    seed_builtins,
    stored_species_id,
)
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


async def _store_raw(profile: SpeciesProfile) -> None:
    """A row as an older release could store it (no twin check)."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO species_profiles (id, data, is_builtin) VALUES (?, ?, 0)",
            (profile.id, profile.model_dump_json()),
        )
        await db.commit()


async def test_get_profile_prefers_exact_match_over_swap():
    """When both spellings exist (stored before twins were refused), the exact
    stored id wins (as-given first)."""
    await seed_builtins()
    # Custom profile stored with a hyphen that collides with no builtin.
    await create_profile(_custom_profile(id="my-strain", common_name="Exact Hit"))
    await _store_raw(_custom_profile(id="my_strain", common_name="Swapped"))
    await seed_builtins()  # a write through the service: the cache re-reads
    assert (await get_profile("my-strain")).common_name == "Exact Hit"
    assert (await get_profile("my_strain")).common_name == "Swapped"


async def test_a_separator_twin_of_a_stored_profile_is_refused():
    """A custom 'lions-mane' beside the built-in 'lions_mane' used to take over
    every lion's mane grow: sessions store 'lions-mane', and the exact spelling
    is found first."""
    await seed_builtins()
    session = await create_session(SessionCreate(name="LM", species_profile_id="lions_mane"))
    with pytest.raises(ProfileExistsError, match="lions_mane"):
        await create_profile(_custom_profile(id="lions-mane", common_name="Impostor"))
    assert (await get_profile(session["species_profile_id"])).id == "lions_mane"
    # An exact duplicate is the same 409, not a UNIQUE-constraint 500.
    await create_profile(_custom_profile(id="my_strain"))
    with pytest.raises(ProfileExistsError):
        await create_profile(_custom_profile(id="my_strain"))


def test_create_endpoint_answers_409_for_a_twin(client):
    body = _custom_profile(id="lions-mane").model_dump(mode="json")
    r = client.post("/api/species", json=body)
    assert r.status_code == 409, r.text
    assert client.get("/api/species/lions-mane").json()["common_name"] == "Lion's Mane"


async def test_a_custom_id_mixing_separators_resolves_from_its_session():
    """'lions_mane-custom' was stored on its session as 'lions-mane-custom',
    which neither the exact nor the swapped spelling finds: the grow ran with
    no setpoints and no stage alerts."""
    await seed_builtins()
    await create_profile(_custom_profile(id="lions_mane-custom", common_name="My LM"))
    s = await create_session(SessionCreate(
        name="LM", species_profile_id="lions_mane-custom", current_phase="fruiting"))
    profile = await get_profile(s["species_profile_id"])
    assert profile is not None and profile.id == "lions_mane-custom"
    # A session stored that way by an older release resolves too.
    assert (await get_profile("lions-mane-custom")).id == "lions_mane-custom"


async def test_a_session_keeps_its_own_profile_when_a_respelled_twin_exists():
    """With both 'my_strain' and (an older) 'my-strain' stored, a session on
    'my_strain' must not be stored hyphenated, which finds the twin."""
    await seed_builtins()
    await create_profile(_custom_profile(id="my_strain", common_name="Mine"))
    await _store_raw(_custom_profile(id="my-strain", common_name="Twin"))
    await seed_builtins()
    s = await create_session(SessionCreate(name="S", species_profile_id="my_strain"))
    assert s["species_profile_id"] == "my_strain"
    assert (await get_profile(s["species_profile_id"])).common_name == "Mine"
    assert await stored_species_id("lions_mane") == "lions-mane"
    assert await stored_species_id("no_such_species") == "no-such-species"


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
