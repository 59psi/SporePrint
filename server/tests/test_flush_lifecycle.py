"""The flush loop: a grow bag gives 2-3 flushes, then it's spent.

The harvest data model already existed (harvests table, flush_number, per-flush
yield). What was missing is the LIFECYCLE: fruit → harvest → rest → re-fruit,
repeated until the bag has given its expected flushes, then complete. Without
it, REST advanced linearly to COMPLETE and there was no way to loop back for a
second flush, nor any signal that a bag was spent.
"""

import pytest

from app.sessions import service
from app.sessions.models import SessionCreate, HarvestCreate


async def _bag_session(species="pearl_oyster"):
    from app.species.service import seed_builtins
    await seed_builtins()  # get_profile reads the species_profiles table
    s = await service.create_session(SessionCreate(
        name="Flush test", species_profile_id=species,
        container_type="grow_bag", current_phase="fruiting",
    ))
    return s["id"]


# ── the flush-loop fork ────────────────────────────────────────────────────


def test_rest_loops_back_to_fruiting_while_flushes_remain():
    assert service.suggested_next_phase("rest", "grow_bag", more_flushes_expected=True) == "fruiting"


def test_rest_completes_when_the_bag_is_spent():
    assert service.suggested_next_phase("rest", "grow_bag", more_flushes_expected=False) == "complete"


def test_fruiting_still_advances_to_rest():
    """You rest after every flush before deciding whether to go again."""
    assert service.suggested_next_phase("fruiting", "grow_bag") == "rest"


# ── flush counting against the species' expected count ─────────────────────


async def test_flush_status_counts_distinct_flushes():
    sid = await _bag_session()
    await service.add_harvest(sid, HarvestCreate(flush_number=1, wet_weight_g=200))
    await service.add_harvest(sid, HarvestCreate(flush_number=1, wet_weight_g=50))  # same flush, 2nd pick
    await service.add_harvest(sid, HarvestCreate(flush_number=2, wet_weight_g=150))

    st = await service.flush_status(sid)
    assert st["flushes_harvested"] == 2   # distinct flush numbers, not harvest rows
    assert st["latest_flush"] == 2


async def test_more_expected_true_until_the_species_count_is_reached():
    from app.species.service import get_profile
    sid = await _bag_session("pearl_oyster")
    expected = (await get_profile("pearl_oyster")).flush_count_typical
    assert expected and expected >= 2

    # One flush in — more expected.
    await service.add_harvest(sid, HarvestCreate(flush_number=1, wet_weight_g=200))
    assert (await service.flush_status(sid))["more_expected"] is True

    # Harvest up to the expected count — bag is now spent.
    for f in range(2, expected + 1):
        await service.add_harvest(sid, HarvestCreate(flush_number=f, wet_weight_g=100))
    st = await service.flush_status(sid)
    assert st["flushes_harvested"] == expected
    assert st["more_expected"] is False


async def test_next_phase_from_rest_reflects_flush_status():
    """End to end: a spent bag at REST is suggested COMPLETE, not another flush."""
    from app.species.service import get_profile
    sid = await _bag_session("pearl_oyster")
    expected = (await get_profile("pearl_oyster")).flush_count_typical
    for f in range(1, expected + 1):
        await service.add_harvest(sid, HarvestCreate(flush_number=f, wet_weight_g=100))
    await service.advance_phase(sid, __import__("app.sessions.models", fromlist=["PhaseAdvance"]).PhaseAdvance(phase="rest", trigger="test"))

    st = await service.flush_status(sid)
    assert service.suggested_next_phase("rest", "grow_bag", st["more_expected"]) == "complete"
