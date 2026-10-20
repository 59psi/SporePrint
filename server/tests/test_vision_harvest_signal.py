"""Vision alerts the operator when fruiting slows — the harvest signal.

The spec: "cameras would monitor for contamination, fruiting, and alert when
fruiting SLOWS so you know about when to harvest." Contamination detection
already existed. This adds the harvest signal: the per-frame Claude read
(harvest_readiness / growth_rate) corroborated across recent frames, so a slowed
or ready fruit body pages the operator — without firing on a single noisy frame.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.db import get_db
from app.vision import service
from app.vision.service import (
    analyze_frame_claude,
    harvest_signal,
    insert_frame,
    update_analysis_claude,
)


def _frame(readiness="not_ready", rate="expanding"):
    return {"harvest_readiness": readiness, "growth_rate": rate}


# ── only during fruiting ───────────────────────────────────────────────────


def test_no_signal_outside_fruiting():
    ripe = [_frame("overdue", "stalled")]
    for phase in ("substrate_colonization", "cold_storage", "agar", "complete"):
        assert harvest_signal(phase, ripe) == (False, None)


def test_no_signal_while_still_growing():
    frames = [_frame("not_ready", "expanding"), _frame("approaching", "expanding")]
    assert harvest_signal("fruiting", frames) == (False, None)


# ── the signal fires ───────────────────────────────────────────────────────


def test_overdue_fires_even_on_a_single_frame():
    """Overdue is unambiguous — don't wait for corroboration to lose the flush."""
    ok, reason = harvest_signal("fruiting", [_frame("overdue", "stalled")])
    assert ok and "overdue" in reason


def test_ready_fires_only_when_corroborated():
    # one 'ready' frame after an expanding one: could be a noisy read — hold.
    assert harvest_signal("fruiting", [_frame("approaching", "expanding"),
                                       _frame("ready", "slowing")]) == (False, None)
    # two mature frames in a row: real.
    ok, reason = harvest_signal("fruiting", [_frame("ready", "slowing"),
                                             _frame("ready", "slowing")])
    assert ok and reason


def test_slowed_growth_is_the_harvest_cue():
    ok, reason = harvest_signal("fruiting", [_frame("approaching", "slowing"),
                                             _frame("approaching", "stalled")])
    assert ok and "slowed" in reason


def test_primordia_counts_as_fruiting_for_this():
    ok, _ = harvest_signal("primordia_induction", [_frame("ready", "slowing"),
                                                   _frame("overdue", "stalled")])
    assert ok


def test_empty_history_is_safe():
    assert harvest_signal("fruiting", []) == (False, None)


# ── the history a read is corroborated against ─────────────────────────────


class _Reply:
    def __init__(self, text):
        self.content = [type("Block", (), {"text": text, "type": "text"})()]
        self.stop_reason = "end_turn"


@pytest.fixture()
def claude(monkeypatch):
    """A Claude stand-in whose next answer the test sets; harvest pages captured."""
    state = {"reply": {}, "harvest": AsyncMock()}

    class _Messages:
        async def create(self, **kwargs):
            return _Reply(json.dumps(state["reply"]))

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic", _Client)
    monkeypatch.setattr(service, "harvest_ready", state["harvest"])
    monkeypatch.setattr("app.cloud.service.forward_event", AsyncMock())
    return state


async def _fruiting_session() -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, status, current_phase) "
            "VALUES ('Flush', 'blue-oyster', 'active', 'fruiting')")
        await db.commit()
        return cur.lastrowid


async def _camera_frame(tmp_path, sid: int, ts: float, node_id: str = "cam-01",
                        stored: dict | None = None) -> dict:
    path = tmp_path / f"{node_id}_{ts}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    fid = await insert_frame(session_id=sid, node_id=node_id, timestamp=ts,
                             file_path=str(path), resolution="", flash_used=0)
    if stored is not None:
        await update_analysis_claude(fid, stored)
    return {"id": fid, "session_id": sid, "node_id": node_id, "file_path": str(path)}


async def _analyse(frame: dict, claude: dict, reply: dict) -> None:
    """What POST /frames/{id}/analyze does: analyse, then store the read."""
    claude["reply"] = reply
    result = await analyze_frame_claude(frame)
    assert "error" not in result
    await update_analysis_claude(frame["id"], result)


async def test_reanalysing_one_ready_frame_does_not_corroborate_itself(tmp_path, claude):
    """The history query found the frame's own stored read as "the frame
    before it", so one image made the two-frame plateau."""
    sid = await _fruiting_session()
    await _camera_frame(tmp_path, sid, 1_000.0, stored=_frame("not_ready"))
    latest = await _camera_frame(tmp_path, sid, 2_000.0)
    await _analyse(latest, claude, _frame("ready", "slowing"))
    await _analyse(latest, claude, _frame("ready", "slowing"))  # the "Claude check" button
    claude["harvest"].assert_not_awaited()


async def test_reanalysing_an_older_frame_is_not_the_latest_read(tmp_path, claude):
    sid = await _fruiting_session()
    old = await _camera_frame(tmp_path, sid, 1_000.0, stored=_frame("ready", "slowing"))
    await _camera_frame(tmp_path, sid, 2_000.0, stored=_frame("ready", "slowing"))
    await _analyse(old, claude, _frame("ready", "slowing"))
    claude["harvest"].assert_not_awaited()


async def test_two_consecutive_ready_reads_of_one_camera_fire_once(tmp_path, claude, monkeypatch):
    forward = AsyncMock()
    monkeypatch.setattr("app.cloud.service.forward_event", forward)
    sid = await _fruiting_session()
    await _camera_frame(tmp_path, sid, 1_000.0, stored=_frame("ready", "slowing"))
    # A second camera that cannot see the fruit reads in between.
    await _camera_frame(tmp_path, sid, 1_500.0, node_id="cam-02", stored=_frame("n/a", "n/a"))
    latest = await _camera_frame(tmp_path, sid, 2_000.0)
    await _analyse(latest, claude, _frame("ready", "slowing"))
    claude["harvest"].assert_awaited_once()
    assert claude["harvest"].await_args.kwargs["dedup_key"] == f"harvest:{sid}"

    # The event and the cloud payload keep their shape.
    async with get_db() as db:
        [event] = await (await db.execute(
            "SELECT * FROM session_events WHERE session_id = ? AND type = 'harvest_ready'", (sid,),
        )).fetchall()
    assert event["source"] == "vision"
    assert event["description"].startswith("Harvest window: ")
    assert json.loads(event["data"]) == {"reason": json.loads(event["data"])["reason"],
                                         "frame_id": latest["id"]}
    fwd_event, payload = forward.await_args.args
    assert fwd_event == "harvest_ready"
    assert set(payload) == {"node_id", "session_id", "species", "reason", "frame_id"}

    # A later ready read in the same 12 h does not page again.
    newest = await _camera_frame(tmp_path, sid, 3_000.0)
    await _analyse(newest, claude, _frame("ready", "slowing"))
    claude["harvest"].assert_awaited_once()
