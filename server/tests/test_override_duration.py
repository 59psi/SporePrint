"""A manual hold's window is timed on the Pi's own clock.

POST /api/automation/overrides takes `duration_sec` and stamps expires_at =
now + duration_sec with the Pi's time.time(); the cloud relay's override frame
does the same with the duration_sec it carries. An absolute expires_at comes
from the sender's clock, which can be hours off a Pi with no battery-backed
clock that booted without NTP: a 5 s pin then held the rules off the channel
for hours, or arrived already expired."""

import json
import time

import pytest

from app.automation.engine import get_overrides, is_overridden
from app.cloud.service import _dispatch_automation_command
from app.db import get_db

SKEW = 2 * 3600  # the sender's clock two hours ahead of the Pi's


def test_a_rest_hold_runs_its_duration_on_the_pis_clock(client):
    before = time.time()
    r = client.post("/api/automation/overrides", json={
        "target": "relay-01", "channel": "aux", "locked": True, "reason": "pin",
        "duration_sec": 5,
        # what a browser two hours ahead of the Pi used to send
        "expires_at": before + SKEW + 5,
    })
    assert r.status_code == 200
    body = r.json()
    # The response is the stored hold, its expiry on the Pi's clock.
    assert body["expires_at"] == pytest.approx(before + 5, abs=2)
    (row,) = client.get("/api/automation/overrides").json()
    assert row["expires_at"] == pytest.approx(before + 5, abs=2)
    assert is_overridden("relay-01", "aux")


def test_a_rest_hold_with_only_an_absolute_expiry_is_served_as_before(client):
    until = time.time() + 600
    r = client.post("/api/automation/overrides", json={
        "target": "relay-01", "channel": "fae", "expires_at": until,
    })
    assert r.status_code == 200
    assert r.json()["expires_at"] == pytest.approx(until)


@pytest.mark.parametrize("bad", [0, -5, "nan"])
def test_a_rest_hold_refuses_a_duration_that_is_no_window(client, bad):
    r = client.post("/api/automation/overrides", json={
        "target": "relay-01", "channel": "fae", "duration_sec": bad,
    })
    assert r.status_code == 422
    assert client.get("/api/automation/overrides").json() == []


def test_a_long_duration_is_held_to_the_ceiling(client):
    before = time.time()
    r = client.post("/api/automation/overrides", json={
        "target": "relay-01", "channel": "fae", "duration_sec": 10 * 86400,
    })
    assert r.status_code == 200
    assert r.json()["expires_at"] <= before + 24 * 3600 + 5


async def _register_relay(node_id: str = "relay-01") -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen) VALUES (?, ?, ?, ?)",
            (node_id, "relay", json.dumps(["relay"]), time.time()),
        )
        await db.commit()


async def test_a_cloud_hold_runs_its_duration_on_the_pis_clock():
    """The cloud sends duration_sec and an expires_at off its own clock; a
    Pi two hours behind used to hold the channel for two hours more."""
    await _register_relay()
    before = time.time()
    ok, err = await _dispatch_automation_command(
        "override",
        {"channel": "fae", "state": "off", "duration_sec": 600, "expires_at": before + SKEW + 600},
    )
    assert ok is True and err is None
    ov = next(o for o in await get_overrides() if o.channel == "fae")
    assert ov.expires_at == pytest.approx(before + 600, abs=2)


async def test_a_cloud_hold_from_a_clock_behind_the_pis_still_holds():
    """The Pi ahead of the cloud by more than the window: the absolute
    expiry arrives already past, the duration still holds the channel."""
    await _register_relay()
    before = time.time()
    ok, _ = await _dispatch_automation_command(
        "override",
        {"channel": "aux", "state": "on", "duration_sec": 30, "expires_at": before - 60 + 30},
    )
    assert ok is True
    assert is_overridden("relay-01", "aux") is True
