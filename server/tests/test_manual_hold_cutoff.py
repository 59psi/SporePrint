"""A manual ON pin ends when the node's own safety cutoff switches the channel
off (its max-on backstop, safe mode, an OTA start): the hardware has ended
the ON, so the hold must not go on showing it held, or keep automation off it.
Holds that pin no ON (rule suspensions, safety lockouts, OFF pins) stay.
"""

import time
from unittest.mock import AsyncMock

import app.automation.engine as engine
from app.automation.engine import _safety_lockout, get_overrides, is_overridden, set_override
from app.automation.models import ManualOverride, OverrideRequest
from app.cloud.service import _dispatch_automation_command
from app.db import get_db
from app.mqtt import _handle_message


async def _cutoff(node_id: str, channel: str, trigger: str = "safety_cutoff"):
    await _handle_message(AsyncMock(), f"sporeprint/{node_id}/telemetry/{channel}",
                          {"channel": channel, "state": "off", "pwm": 0, "trigger": trigger})


async def _pin(target: str, channel: str, state: str | None, reason: str = "pin"):
    await set_override(OverrideRequest(
        target=target, channel=channel, reason=reason, duration_sec=600, state=state,
    ).to_override())


async def _stored(target: str, channel: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT held_state FROM manual_overrides WHERE target = ? AND channel = ?",
            (target, channel))
        return [r["held_state"] for r in await cursor.fetchall()]


async def test_a_safety_cutoff_ends_a_manual_on_pin():
    await _pin("relay-a1", "aux", "on")
    assert is_overridden("relay-a1", "aux")
    await _cutoff("relay-a1", "aux")
    assert not is_overridden("relay-a1", "aux")
    assert await _stored("relay-a1", "aux") == []
    assert await get_overrides() == []


async def test_holds_that_pin_no_on_are_left_alone():
    await _pin("relay-a1", "fae", "off")                              # an OFF pin
    await _pin("relay-a1", "exhaust", None, "rule 'X' suspended 30m")  # a suspension
    await _safety_lockout("relay-a1", "circulation", "Heater Max-On")  # a lockout
    for channel in ("fae", "exhaust", "circulation"):
        await _cutoff("relay-a1", channel)
        assert is_overridden("relay-a1", channel), channel


async def test_only_the_safety_cutoff_trigger_ends_the_pin():
    await _pin("relay-a1", "aux", "on")
    await _cutoff("relay-a1", "aux", trigger="report")
    await _cutoff("relay-a1", "aux", trigger="command")
    assert is_overridden("relay-a1", "aux")
    await _cutoff("relay-a2", "aux")  # another node's cutoff
    assert is_overridden("relay-a1", "aux")


async def test_the_pinned_state_survives_a_restart():
    await _pin("relay-a1", "aux", " ON ")
    assert await _stored("relay-a1", "aux") == ["on"]
    engine._overrides.clear()
    engine._overrides_loaded = False
    (held,) = await get_overrides()
    assert held.held_state == "on"
    await _cutoff("relay-a1", "aux")
    assert await get_overrides() == []


def test_a_pin_state_is_read_the_way_the_firmware_reads_a_command():
    assert ManualOverride(target="t", held_state="On").held_state == "on"
    assert ManualOverride(target="t", held_state="false").held_state == "off"
    assert ManualOverride(target="t", held_state=1).held_state is None
    assert ManualOverride(target="t").held_state is None


async def test_a_cloud_on_pin_ends_at_the_cutoff_too():
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) "
            "VALUES ('relay-c1', 'relay', '[\"aux\", \"fae\"]', ?)", (time.time(),))
        await db.commit()
    ok, error = await _dispatch_automation_command(
        "override", {"channel": "aux", "state": "on", "duration_sec": 600})
    assert (ok, error) == (True, None)
    assert await _stored("relay-c1", "aux") == ["on"]
    await _cutoff("relay-c1", "aux")
    assert not is_overridden("relay-c1", "aux")


def test_the_rest_route_records_and_returns_the_pinned_state(client):
    r = client.post("/api/automation/overrides", json={
        "target": "relay-r1", "channel": "aux", "locked": True, "reason": "pin",
        "duration_sec": 60, "state": "on"})
    assert r.status_code == 200 and r.json()["held_state"] == "on"
    (row,) = [o for o in client.get("/api/automation/overrides").json()
              if o["target"] == "relay-r1"]
    assert row["held_state"] == "on"
    # A client that sends no state pins none, as before.
    r = client.post("/api/automation/overrides", json={
        "target": "relay-r1", "channel": "fae", "locked": True, "reason": "hold"})
    assert r.json()["held_state"] is None
