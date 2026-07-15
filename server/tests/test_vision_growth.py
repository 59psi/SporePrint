"""Gap 4: fruiting growth-rate tracking → "fruiting has slowed, harvest" alert.

Contamination detection already existed. Ripeness is a RATE — a fruit body grows
fast then plateaus, and the plateau is the harvest signal. The local CNN is a
stub and cannot measure change across time, so this is explicitly a Claude-vision
feature: compare the earliest and latest frames in a window and report the delta.

These pin the decision helper (pure) and the alerting orchestration, without
needing an API key — the Claude call itself is isolated and mocked.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.sessions.models import SessionCreate
from app.sessions.service import advance_phase, create_session
from app.sessions.models import PhaseAdvance
from app.species.service import seed_builtins
from app.vision.service import (
    _growth_indicates_harvest,
    evaluate_growth_trend,
    insert_frame,
)


def test_growth_helper_flags_plateau_as_harvest():
    assert _growth_indicates_harvest({"growth_rate": "stalled"}) is True
    assert _growth_indicates_harvest({"growth_rate": "slow"}) is True
    assert _growth_indicates_harvest({"recommend_harvest": True}) is True


def test_growth_helper_ignores_active_growth():
    assert _growth_indicates_harvest({"growth_rate": "rapid"}) is False
    assert _growth_indicates_harvest({"growth_rate": "moderate", "recommend_harvest": False}) is False
    assert _growth_indicates_harvest(None) is False
    assert _growth_indicates_harvest({"error": "x"}) is False


async def _fruiting_session_with_frames(n=3):
    await seed_builtins()
    session = await create_session(SessionCreate(
        name="v", species_profile_id="blue_oyster",
        current_phase="primordia_induction", container_type="grow_bag"))
    # Move to fruiting (grow bag path).
    await advance_phase(session["id"], PhaseAdvance(phase="fruiting"))
    for i in range(n):
        await insert_frame(session_id=session["id"], node_id="cam-01",
                           timestamp=1000.0 + i * 3600, file_path=f"/tmp/f{i}.jpg",
                           resolution="640x480", flash_used=1)
    return session


async def test_growth_slowed_fires_harvest_alert():
    session = await _fruiting_session_with_frames()
    stalled = {"growth_rate": "stalled", "recommend_harvest": True, "summary": "veils opening"}
    with patch("app.vision.service._claude_growth_delta", new=AsyncMock(return_value=stalled)), \
         patch("app.vision.service.harvest_ready", new=AsyncMock()) as hr, \
         patch("app.cloud.service.forward_event", new=AsyncMock()) as fe:
        result = await evaluate_growth_trend(session_id=session["id"])
    assert result["status"] == "evaluated"
    assert result["harvest_recommended"] is True
    hr.assert_awaited_once()
    fe.assert_awaited()  # cloud harvest_ready event too


async def test_active_growth_does_not_alert():
    session = await _fruiting_session_with_frames()
    rapid = {"growth_rate": "rapid", "recommend_harvest": False}
    with patch("app.vision.service._claude_growth_delta", new=AsyncMock(return_value=rapid)), \
         patch("app.vision.service.harvest_ready", new=AsyncMock()) as hr:
        result = await evaluate_growth_trend(session_id=session["id"])
    assert result["harvest_recommended"] is False
    hr.assert_not_called()


async def test_growth_trend_skips_non_fruiting_phase():
    await seed_builtins()
    session = await create_session(SessionCreate(
        name="c", species_profile_id="blue_oyster",
        current_phase="substrate_colonization", container_type="grow_bag"))
    await insert_frame(session_id=session["id"], node_id="cam-01", timestamp=1.0,
                       file_path="/tmp/x.jpg", resolution="", flash_used=1)
    with patch("app.vision.service._claude_growth_delta", new=AsyncMock()) as cg:
        result = await evaluate_growth_trend(session_id=session["id"])
    assert result["status"] == "not_fruiting"
    cg.assert_not_called()   # no Claude spend when fruit bodies can't exist yet


async def test_growth_trend_needs_two_frames():
    session = await _fruiting_session_with_frames(n=1)
    with patch("app.vision.service._claude_growth_delta", new=AsyncMock()) as cg:
        result = await evaluate_growth_trend(session_id=session["id"])
    assert result["status"] == "insufficient_frames"
    cg.assert_not_called()
