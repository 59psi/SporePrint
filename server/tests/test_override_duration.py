"""A manual hold's window is timed on the Pi's own clock.

POST /api/automation/overrides takes `duration_sec` and stamps expires_at =
now + duration_sec with the Pi's time.time(); the cloud relay's override frame
does the same with the duration_sec it carries. An absolute expires_at comes
from the sender's clock, which can be hours off a Pi with no battery-backed
clock that booted without NTP: a 5 s pin then held the rules off the channel
for hours, or arrived already expired."""

import time

import pytest

from app.automation.engine import get_overrides, is_overridden
from app.automation.models import MAX_OVERRIDE_TTL_SECONDS
from app.cloud.service import _dispatch_automation_command
from tests._builders import register_node

SKEW = 2 * 3600  # the sender's clock two hours ahead of the Pi's


@pytest.mark.parametrize("duration,held_for", [
    (5, 5),
    (10 * 86400, MAX_OVERRIDE_TTL_SECONDS),   # no longer than the hold ceiling
])
def test_a_rest_hold_runs_its_duration_on_the_pis_clock(client, duration, held_for):
    before = time.time()
    r = client.post("/api/automation/overrides", json={
        "target": "relay-01", "channel": "aux", "locked": True, "reason": "pin",
        "duration_sec": duration,
        # what a browser two hours ahead of the Pi used to send
        "expires_at": before + SKEW + duration,
    })
    assert r.status_code == 200
    # The response is the stored hold, its expiry on the Pi's clock.
    assert r.json()["expires_at"] == pytest.approx(before + held_for, abs=2)
    (row,) = client.get("/api/automation/overrides").json()
    assert row["expires_at"] == pytest.approx(before + held_for, abs=2)
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


@pytest.mark.parametrize("sent_expiry", [
    SKEW + 600,   # the cloud two hours ahead: a Pi behind it held two hours more
    -30,          # the cloud behind by more than the window: it arrives already past
])
async def test_a_cloud_hold_runs_its_duration_on_the_pis_clock(sent_expiry):
    await register_node("relay-01", "relay")
    before = time.time()
    ok, err = await _dispatch_automation_command(
        "override",
        {"channel": "fae", "state": "off", "duration_sec": 600,
         "expires_at": before + sent_expiry},
    )
    assert (ok, err) == (True, None)
    assert is_overridden("relay-01", "fae") is True
    (hold,) = await get_overrides()
    assert hold.expires_at == pytest.approx(before + 600, abs=2)
