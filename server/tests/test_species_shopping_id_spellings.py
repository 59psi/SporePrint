"""A custom profile whose id mixes '-' and '_' answers every spelling of it.

The dashboard's Shopping List writes a species id with '_' throughout
(pink_oyster-v2 → pink_oyster_v2) and sessions store it with '-' throughout
(pink-oyster-v2). Neither is the stored id or its one-pass '-'/'_' swap, so
the list answered 404 "Species profile not found" and the session's grow ran
without its profile.
"""

from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import create_profile, get_profile

SPELLINGS = ("pink_oyster-v2", "pink_oyster_v2", "pink-oyster-v2", "pink-oyster_v2")


def _pink_v2():
    base = next(p for p in BUILTIN_PROFILES if p.id == "pink_oyster")
    return base.model_copy(update={"id": "pink_oyster-v2", "common_name": "Pink Oyster v2"})


def test_the_shopping_list_finds_a_mixed_separator_id_by_any_spelling(client):
    r = client.post("/api/species", json=_pink_v2().model_dump(mode="json"))
    assert r.status_code == 200, r.text
    for spelling in SPELLINGS:
        r = client.get(f"/api/species/{spelling}/shopping-list?grows=2")
        assert r.status_code == 200, (spelling, r.text)
        assert r.json()["common_name"] == "Pink Oyster v2"
        assert r.json()["grows"] == 2
        assert client.get(f"/api/species/{spelling}").json()["id"] == "pink_oyster-v2"


async def test_a_grow_on_a_mixed_separator_id_runs_with_its_profile():
    await create_profile(_pink_v2())
    session = await create_session(
        SessionCreate(name="pink v2", species_profile_id="pink_oyster-v2", current_phase="fruiting")
    )
    profile = await get_profile(session["species_profile_id"])
    assert profile is not None and profile.id == "pink_oyster-v2"
    # the phase it started in carries the profile's setpoints
    assert session["phase_history"][0]["params_snapshot"] is not None
