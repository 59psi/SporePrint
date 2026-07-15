"""Gap 3: flush tracking (2-3 flushes per bag) and the rest-between-flushes cycle.

Much of this already existed: harvests carry flush_number, add_harvest logs the
event, and get_session_stats computes per-flush yields + flush-over-flush
decline. What was missing: knowing the species' EXPECTED flush count (so the UI
can say "1 of 3 flushes left") and wiring the fruiting ⇄ rest cycle that IS the
rest period between flushes. These pin the additions.
"""

import pytest

from app.sessions.models import HarvestCreate, PhaseAdvance, SessionCreate
from app.sessions.service import (
    add_harvest, advance_phase, create_session, get_session_stats,
)
from app.sessions.lifecycle import next_phase
from app.species.service import seed_builtins


async def _bag_in_fruiting():
    await seed_builtins()
    s = await create_session(SessionCreate(
        name="flush", species_profile_id="blue_oyster",
        substrate="Masters Mix", substrate_volume="5 lb",
        current_phase="fruiting", container_type="grow_bag"))
    return s


async def test_stats_expose_expected_and_remaining_flushes():
    s = await _bag_in_fruiting()
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=300))
    stats = await get_session_stats(s["id"])
    # blue_oyster typically gives 3 flushes.
    assert stats["expected_flush_count"] == 3
    assert stats["harvested_flushes"] == 1
    assert stats["flushes_remaining"] == 2


async def test_flush_decline_still_computed():
    s = await _bag_in_fruiting()
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=400))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=300))
    stats = await get_session_stats(s["id"])
    assert stats["flush_count"] == 2
    assert stats["flushes_remaining"] == 1
    assert stats["flush_decline_pct"] == [25.0]   # 400 → 300 = 25% decline


async def test_rest_period_is_the_between_flush_cycle():
    """After a flush, the bag rests, then fruits again — that IS the rest period."""
    s = await _bag_in_fruiting()
    # fruiting → rest (auto fork)
    s = await advance_phase(s["id"], PhaseAdvance(phase="auto"))
    assert s["current_phase"] == "rest"
    # rest → fruiting (next flush)
    s = await advance_phase(s["id"], PhaseAdvance(phase="auto"))
    assert s["current_phase"] == "fruiting"
    # The phase_history records the rest period between the two fruiting spans.
    phases = [p["phase"] for p in s["phase_history"]]
    assert phases.count("fruiting") == 2 and "rest" in phases


def test_flush_cycle_pure_fork():
    assert next_phase("fruiting", "grow_bag") == "rest"
    assert next_phase("rest", "grow_bag") == "fruiting"
