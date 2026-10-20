import re

import pytest

from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import abort_session, create_session
from app.species.models import GrowPhase, SpeciesProfile, profile_problems
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import (
    BuiltinProfileReadOnly,
    InvalidProfileError,
    ProfileInUseError,
    seed_builtins,
    get_all_profiles,
    get_profile,
    create_profile,
    update_profile,
    delete_profile,
)
from tests._pi_c2_helpers import custom_profile


async def test_seeding_twice_stores_each_builtin_once():
    await seed_builtins()
    await seed_builtins()
    assert sorted(p.id for p in await get_all_profiles()) == sorted(p.id for p in BUILTIN_PROFILES)


# ── built-ins are read-only templates; custom rows survive seeding ──


async def test_a_builtin_is_read_only():
    """PUT on a built-in used to 200 and then be reverted by seed_builtins() on
    the next restart. CLAUDE.md §4c: customize by cloning. Deleting one is
    refused the same way."""
    await seed_builtins()
    stock = await get_profile("blue_oyster")
    edited = stock.model_copy(update={"common_name": "My Blue"})
    with pytest.raises(BuiltinProfileReadOnly):
        await update_profile("blue_oyster", edited)
    assert await delete_profile("blue_oyster") is False
    assert (await get_profile("blue_oyster")).common_name == "Blue Oyster"


async def test_seed_does_not_overwrite_custom_profile_sharing_builtin_id():
    custom = custom_profile(id="blue_oyster", common_name="My Own Blue")
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
            (custom_profile(id="blue_oyster", common_name="Stale").model_dump_json(),),
        )
        await db.commit()
    await seed_builtins()
    assert (await get_profile("blue_oyster")).common_name == "Blue Oyster"


async def test_update_and_delete_resolve_hyphen_underscore_ids():
    await create_profile(custom_profile(id="my_strain"))
    updated = await update_profile("my-strain", custom_profile(id="my_strain", common_name="Renamed"))
    assert updated.common_name == "Renamed"
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


def test_routes_on_an_unknown_profile_or_one_without_recipes(client):
    body = custom_profile(id="no_such_species").model_dump(mode="json")
    assert client.get("/api/species/no_such_species").status_code == 404
    assert client.put("/api/species/no_such_species", json=body).status_code == 404
    assert client.get("/api/species/no_such_species/shopping-list").status_code == 404
    assert client.get("/api/species/no_such_species/substrate?volume_liters=5").status_code == 404
    # DELETE answers 400 for both an unknown id and a built-in.
    assert client.delete("/api/species/no_such_species").status_code == 400
    assert client.delete("/api/species/blue_oyster").status_code == 400
    # A custom profile with no substrate recipe has no shopping list or calculator.
    assert client.post("/api/species", json=custom_profile().model_dump(mode="json")).status_code == 200
    for route in ("shopping-list", "substrate?volume_liters=5"):
        r = client.get(f"/api/species/custom_test/{route}")
        assert r.status_code == 404 and "No substrate recipes" in r.json()["detail"], route


# ── A card agrees with itself ────────────────────────────────────────
# The Shiitake card said "Cold shock (38-50°F overnight) … 3-5 flushes" in
# its summary while its pinning trigger said cold-water soak and its yield
# said 3-6 flushes; king trumpet, yellow oyster, chestnut, pioppino and
# nameko had the same summary-vs-yield flush split.

_FLUSH_RANGE = re.compile(r"(\d+)-(\d+) flushes")


def test_every_card_gives_one_flush_range_around_its_typical_count():
    problems = {}
    for profile in BUILTIN_PROFILES:
        ranges = {tuple(map(int, m)) for text in (profile.tldr or "", profile.yield_notes or "")
                  for m in _FLUSH_RANGE.findall(text)}
        if len(ranges) > 1:
            problems[profile.id] = f"tldr and yield_notes disagree: {sorted(ranges)}"
        for lo, hi in ranges:
            if not lo <= profile.flush_count_typical <= hi:
                problems[profile.id] = f"flush_count_typical {profile.flush_count_typical} outside {lo}-{hi}"
    assert problems == {}


def test_shiitake_summary_names_the_soak_it_reminds_about():
    shiitake = next(p for p in BUILTIN_PROFILES if p.id == "shiitake")
    assert "Cold-water soak (35-50°F, 12-24h)" in shiitake.pinning_trigger_description
    assert "cold-water soak (35-50°F, 12-24h)" in shiitake.tldr
    assert "Cold shock" not in shiitake.tldr


# ── setpoints automation can run (checked when a profile is written) ───────


def _with_fruiting(**changes) -> SpeciesProfile:
    profile = custom_profile()
    fruiting = profile.phases[GrowPhase.FRUITING].model_copy(update=changes)
    return profile.model_copy(update={"phases": {**profile.phases, GrowPhase.FRUITING: fruiting}})


@pytest.mark.parametrize("changes", [
    {"temp_min_f": 80, "temp_max_f": 70},            # heater and cooler both "on" at 75 °F
    {"humidity_min": 95, "humidity_max": 80},        # humidifier vs dehumidifier
    {"humidity_max": 120},
    {"light_hours_on": 30, "light_hours_off": -6},
    {"light_hours_on": 12, "light_hours_off": 10},
    {"expected_duration_days": (20, 5)},
    {"co2_min_ppm": 900, "co2_max_ppm": 700},
    {"temp_min_f": float("nan")},
])
async def test_a_profile_automation_cannot_run_is_refused(changes):
    bad = _with_fruiting(**changes)
    assert profile_problems(bad)
    with pytest.raises(InvalidProfileError, match="fruiting"):
        await create_profile(bad)
    assert await get_profile(bad.id) is None
    await create_profile(custom_profile())
    with pytest.raises(InvalidProfileError):
        await update_profile("custom_test", bad)
    assert (await get_profile("custom_test")).phases[GrowPhase.FRUITING].temp_min_f == 55


def test_every_builtin_profile_passes_the_setpoint_checks():
    assert {p.id: profile_problems(p) for p in BUILTIN_PROFILES if profile_problems(p)} == {}


def test_species_endpoints_answer_422_for_unusable_setpoints(client):
    body = _with_fruiting(temp_min_f=80, temp_max_f=70).model_dump(mode="json")
    r = client.post("/api/species", json=body)
    assert r.status_code == 422, r.text
    assert "temp_min_f" in r.json()["detail"]
    assert client.post("/api/species", json=custom_profile().model_dump(mode="json")).status_code == 200
    assert client.put("/api/species/custom_test", json=body).status_code == 422


# ── PUT keeps the profile's own id ──────────────────────────────────────────


async def test_put_with_another_profiles_id_in_the_body_is_refused():
    """The body was stored under the path's row: the listing then showed two
    'blue_oyster' entries and no 'custom_a' that GET/PUT could reach."""
    await seed_builtins()
    await create_profile(custom_profile(id="custom_a"))
    with pytest.raises(InvalidProfileError, match="custom_a"):
        await update_profile("custom_a", custom_profile(id="blue_oyster", common_name="X"))
    ids = [p.id for p in await get_all_profiles()]
    assert ids.count("blue_oyster") == 1 and "custom_a" in ids
    # The other spelling of its own id is the same profile, stored under its row.
    updated = await update_profile("custom-a", custom_profile(id="custom-a", common_name="Renamed"))
    assert updated.id == "custom_a"
    assert (await get_profile("custom_a")).common_name == "Renamed"


# ── a profile active grows run on cannot be deleted ─────────────────────────


async def test_deleting_a_profile_an_active_grow_runs_on_is_refused():
    """The grow then resolved no profile: no setpoints and no stage alerts for
    the rest of its run."""
    await create_profile(custom_profile(id="my_strain"))
    session = await create_session(SessionCreate(name="Mine", species_profile_id="my_strain"))
    assert session["species_profile_id"] == "my-strain"
    with pytest.raises(ProfileInUseError, match="Mine"):
        await delete_profile("my_strain")
    assert await get_profile(session["species_profile_id"]) is not None
    # Once the grow has ended the profile can go.
    await abort_session(session["id"])
    assert await delete_profile("my-strain") is True


def test_delete_endpoint_answers_409_while_in_use(client):
    assert client.post("/api/species", json=custom_profile().model_dump(mode="json")).status_code == 200
    client.post("/api/sessions", json={"name": "S", "species_profile_id": "custom_test"})
    r = client.delete("/api/species/custom_test")
    assert r.status_code == 409, r.text
    assert client.get("/api/species/custom_test").status_code == 200


# ── one parsed copy per change ──────────────────────────────────────────────


def test_the_listing_follows_every_profile_write(client):
    """GET /api/species is rendered once per change and must still show each
    write at once."""
    listed = lambda: {p["id"]: p for p in client.get("/api/species").json()}  # noqa: E731
    before = listed()
    assert "custom_test" not in before and "blue_oyster" in before
    body = custom_profile().model_dump(mode="json")
    assert client.post("/api/species", json=body).status_code == 200
    assert listed()["custom_test"]["common_name"] == "Test Species"
    body["common_name"] = "Renamed"
    assert client.put("/api/species/custom_test", json=body).status_code == 200
    assert listed()["custom_test"]["common_name"] == "Renamed"
    assert client.delete("/api/species/custom_test").status_code == 200
    assert "custom_test" not in listed()
    # The same JSON the profiles render to.
    assert listed()["blue_oyster"] == next(
        p for p in BUILTIN_PROFILES if p.id == "blue_oyster").model_dump(mode="json")


async def test_an_unreadable_stored_row_does_not_hide_the_others():
    await seed_builtins()
    async with get_db() as db:
        await db.execute("INSERT INTO species_profiles (id, data, is_builtin) VALUES ('broken', '{}', 0)")
        await db.commit()
    await create_profile(custom_profile())  # a write: the cache re-reads
    assert await get_profile("broken") is None
    assert (await get_profile("blue_oyster")).common_name == "Blue Oyster"
    assert len(await get_all_profiles()) == len(BUILTIN_PROFILES) + 1

