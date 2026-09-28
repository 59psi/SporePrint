"""Session end → actuator safing + chamber detach (audit srv-auto#17, #26).

When the last active session is completed or aborted the automation engine stops
evaluating entirely (engine.evaluate_rules returns early with no active
session), so whatever automation last switched ON stays ON forever — a cooler
plug from "Pre-cool for Hot Forecast" (no safety_max_on) or the fruiting light
scene. Ending the session must command the automation-driven actuators OFF, and
the chamber must stop advertising the finished session as its live grow.
"""

import json

import pytest

import app.sessions.service as sessions_service
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.chambers.models import ChamberCreate, ChamberUpdate
from app.chambers.service import create_chamber, get_chamber, update_chamber
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import (
    abort_session,
    complete_session,
    create_session,
    get_events,
)


@pytest.fixture()
def json_publishes(monkeypatch):
    """Record the JSON (native-node) publishes the session service makes."""
    calls: list[tuple[str, dict]] = []

    async def _fake_publish(topic, payload):
        calls.append((topic, payload))
        return True

    monkeypatch.setattr(sessions_service, "mqtt_publish", _fake_publish)
    return calls


async def _session(name="Grow", **kw):
    return await create_session(SessionCreate(name=name, species_profile_id="blue_oyster", **kw))


async def test_complete_last_session_commands_automation_actuators_off(json_publishes, mock_mqtt_raw):
    await seed_builtin_rules()
    # A paired cooler plug (the seeded rules target the role "plug-cooler").
    await register_plug("plug-abc123", "Cooler", "shelly", "shellies/abc123", device_role="cooler")
    s = await _session()

    await complete_session(s["id"])

    topics = {t: p for t, p in json_publishes}
    # Every relay channel automation can switch ON gets an explicit OFF.
    for ch in ("fae", "exhaust", "circulation", "aux"):
        assert topics[f"sporeprint/relay-01/cmd/{ch}"]["state"] == "off"
    # Lights go to the dark scene, same wire shape as the Lights-Off rule.
    assert topics["sporeprint/light-01/cmd/scene"] == {"state": "off", "scene": "colonization_dark"}
    # The paired plug is switched off on the vendor topic (bare payload).
    assert ("shellies/abc123/relay/0/command", "off") in mock_mqtt_raw
    # Nothing was switched ON.
    assert all(p.get("state") == "off" for _, p in json_publishes)

    events = await get_events(s["id"])
    safed = [e for e in events if e["type"] == "actuators_safed"]
    assert len(safed) == 1
    data = json.loads(safed[0]["data"])
    assert any(r["target"] == "relay-01" and r["channel"] == "fae" for r in data["actuators"])


async def test_abort_last_session_also_safes_actuators(json_publishes, mock_mqtt_raw):
    await seed_builtin_rules()
    s = await _session()
    await abort_session(s["id"])
    assert any(t == "sporeprint/relay-01/cmd/fae" for t, _ in json_publishes)


async def test_no_safing_while_another_session_is_still_active(json_publishes, mock_mqtt_raw):
    """The engine keeps driving the closet for the remaining active session;
    blanket-OFF would fight it."""
    await seed_builtin_rules()
    older = await _session("Older")
    await _session("Newer")
    await complete_session(older["id"])
    assert json_publishes == []
    assert mock_mqtt_raw == []
    events = await get_events(older["id"])
    assert not any(e["type"] == "actuators_safed" for e in events)


async def test_manually_held_actuator_is_left_alone(json_publishes, mock_mqtt_raw):
    await seed_builtin_rules()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO manual_overrides (target, channel, locked, reason) VALUES (?, ?, 1, ?)",
            ("relay-01", "fae", "operator hold"),
        )
        await db.commit()
    s = await _session()
    await complete_session(s["id"])
    published = {t for t, _ in json_publishes}
    assert "sporeprint/relay-01/cmd/fae" not in published
    assert "sporeprint/relay-01/cmd/exhaust" in published


async def test_unknown_session_returns_none_and_publishes_nothing(json_publishes, mock_mqtt_raw):
    await seed_builtin_rules()
    assert await complete_session(9999) is None
    assert await abort_session(9999) is None
    assert json_publishes == []


# ── srv-auto#26: chamber.active_session_id lifecycle ─────────────


@pytest.mark.parametrize("end", [complete_session, abort_session])
async def test_ending_session_clears_chamber_active_session(end, json_publishes, mock_mqtt_raw):
    chamber = await create_chamber(ChamberCreate(name="Closet"))
    s = await _session(chamber_id=chamber["id"])
    assert (await get_chamber(chamber["id"]))["active_session_id"] == s["id"]

    await end(s["id"])

    assert (await get_chamber(chamber["id"]))["active_session_id"] is None


async def test_chamber_patch_explicit_null_clears_active_session():
    chamber = await create_chamber(ChamberCreate(name="Closet"))
    s = await _session(chamber_id=chamber["id"])

    # Omitting the field leaves it untouched ...
    kept = await update_chamber(chamber["id"], ChamberUpdate(name="Renamed"))
    assert kept["active_session_id"] == s["id"]

    # ... an explicit null clears it.
    cleared = await update_chamber(chamber["id"], ChamberUpdate(active_session_id=None))
    assert cleared["active_session_id"] is None
    assert cleared["name"] == "Renamed"


def test_chamber_patch_endpoint_explicit_null_clears(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    s = client.post("/api/sessions", json={
        "name": "G", "species_profile_id": "blue_oyster", "chamber_id": chamber["id"],
    }).json()
    assert client.get(f"/api/chambers/{chamber['id']}").json()["active_session_id"] == s["id"]

    r = client.patch(f"/api/chambers/{chamber['id']}", json={"description": "x"})
    assert r.json()["active_session_id"] == s["id"]

    r = client.patch(f"/api/chambers/{chamber['id']}", json={"active_session_id": None})
    assert r.status_code == 200
    assert r.json()["active_session_id"] is None
