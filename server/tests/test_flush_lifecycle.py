"""The flush loop: a grow bag gives 2-3 flushes, then it's spent.

The harvest data model already existed (harvests table, flush_number, per-flush
yield). What was missing is the LIFECYCLE: fruit → harvest → rest → re-fruit,
repeated until the bag has given its expected flushes, then complete. Without
it, REST advanced linearly to COMPLETE and there was no way to loop back for a
second flush, nor any signal that a bag was spent.

The suggestion table itself (rest → fruiting / complete) is
test_lifecycle_cold_storage.py::test_suggested_next_phase.
"""

from app.sessions import service
from app.sessions.models import HarvestCreate
from app.species.service import seed_builtins
from tests._builders import start_grow


async def test_flush_status_counts_distinct_flushes():
    await seed_builtins()  # the expected count comes from the species profile
    s = await start_grow("pearl_oyster", "fruiting", name="Flush test", container_type="grow_bag")
    await service.add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200))
    await service.add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=50))  # same flush, 2nd pick
    await service.add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=150))

    st = await service.flush_status(s["id"])
    assert st["flushes_harvested"] == 2   # distinct flush numbers, not harvest rows
    assert st["latest_flush"] == 2


def test_a_bag_loops_back_to_fruiting_until_its_expected_flushes_are_in(client):
    """End to end through /flushes and /next-phase: rest offers another flush
    while the species expects more, and COMPLETE once the bag is spent."""
    sid = client.post("/api/sessions", json={
        "name": "Pearls", "species_profile_id": "pearl_oyster",
        "container_type": "grow_bag", "current_phase": "fruiting",
    }).json()["id"]

    def harvest(flush):
        assert client.post(f"/api/sessions/{sid}/harvest",
                           json={"flush_number": flush, "wet_weight_g": 100}).status_code == 200

    def rest_then_suggestion():
        assert client.post(f"/api/sessions/{sid}/phase", json={"phase": "rest"}).status_code == 200
        return client.get(f"/api/sessions/{sid}/next-phase").json()["suggested_next_phase"]

    harvest(1)
    flushes = client.get(f"/api/sessions/{sid}/flushes").json()
    expected = flushes["expected_flushes"]
    assert expected >= 2 and flushes["more_expected"] is True
    assert rest_then_suggestion() == "fruiting"

    assert client.post(f"/api/sessions/{sid}/phase", json={"phase": "fruiting"}).status_code == 200
    for flush in range(2, expected + 1):
        harvest(flush)
    flushes = client.get(f"/api/sessions/{sid}/flushes").json()
    assert (flushes["flushes_harvested"], flushes["more_expected"]) == (expected, False)
    assert rest_then_suggestion() == "complete"

    for route in ("flushes", "next-phase"):
        assert client.get(f"/api/sessions/9999/{route}").status_code == 404
