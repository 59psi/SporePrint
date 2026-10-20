"""Session end → actuator safing + chamber detach.

When the last active session is completed or aborted the automation engine stops
evaluating entirely (engine.evaluate_rules returns early with no active
session), so whatever automation last switched ON stays ON forever — a cooler
plug from "Pre-cool for Hot Forecast" (no safety_max_on) or the fruiting light
scene. Ending the session must command the automation-driven actuators OFF, and
the chamber must stop advertising the finished session as its live grow.
"""

import json
import time

import pytest

import app.automation.engine as engine
from app.automation.models import (
    AutomationRule,
    ConditionType,
    ManualOverride,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule, hold_applies, seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber, get_chamber
from app.db import get_db
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import (
    SessionConflictError,
    abort_session,
    advance_phase,
    complete_session,
    create_session,
    get_events,
    get_session,
)
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    engine_state,
    json_publishes,
    kasa_driver,
    kasa_wire,
)


async def _session(name="Grow", **kw):
    return await create_session(SessionCreate(name=name, species_profile_id="blue_oyster", **kw))


@pytest.mark.parametrize("end", [complete_session, abort_session])
async def test_ending_the_last_grow_commands_automation_actuators_off(
        end, json_publishes, mock_mqtt_raw):
    await seed_builtin_rules()
    # A paired cooler plug (the seeded rules target the role "plug-cooler").
    await register_plug("plug-abc123", "Cooler", "shelly", "shellies/abc123", device_role="cooler")
    s = await _session()

    await end(s["id"])

    topics = {t: p for t, p in json_publishes}
    # Every relay channel automation can switch ON gets an explicit OFF.
    for ch in ("fae", "exhaust", "circulation", "aux"):
        assert topics[f"sporeprint/relay-01/cmd/{ch}"]["state"] == "off"
    # Lights go to the dark scene, the all-off command every automation OFF uses.
    assert topics["sporeprint/light-01/cmd/scene"] == {
        "state": "off", "scene": "colonization_dark", "reason": "session_ended"}
    # The paired plug is switched off on the vendor topic (bare payload).
    assert ("shellies/abc123/relay/0/command", "off") in mock_mqtt_raw
    # Nothing was switched ON.
    assert all(p.get("state") == "off" for _, p in json_publishes)

    safed = [e for e in await get_events(s["id"]) if e["type"] == "actuators_safed"]
    assert len(safed) == 1
    data = json.loads(safed[0]["data"])
    assert any(r["target"] == "relay-01" and r["channel"] == "fae" for r in data["actuators"])


async def test_no_safing_while_another_grow_is_still_active(json_publishes, mock_mqtt_raw,
                                                            kasa_wire):
    """The engine keeps driving the closet for the remaining grow; a blanket
    OFF would fight it."""
    await seed_builtin_rules()
    await _kasa_heater_rule()
    older = await _session("Older")
    await _session("Newer")
    await complete_session(older["id"])
    assert json_publishes == [] and mock_mqtt_raw == [] and kasa_wire == []
    assert not any(e["type"] == "actuators_safed" for e in await get_events(older["id"]))


async def test_a_manually_held_actuator_is_left_alone(json_publishes, mock_mqtt_raw, kasa_wire):
    await seed_builtin_rules()
    await _kasa_heater_rule()
    async with get_db() as db:
        for target, channel in (("relay-01", "fae"), ("vendor:kasa", None)):
            await db.execute(
                "INSERT INTO manual_overrides (target, channel, locked, reason) VALUES (?, ?, 1, ?)",
                (target, channel, "operator hold"),
            )
        await db.commit()
    s = await _session()
    await complete_session(s["id"])
    published = {t for t, _ in json_publishes}
    assert "sporeprint/relay-01/cmd/fae" not in published
    assert "sporeprint/relay-01/cmd/exhaust" in published
    assert kasa_wire == []


# ── a hold is read as the engine reads it ──────────────────────


async def _node(node_id: str, node_type: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen) VALUES (?, ?, ?, ?)",
            (node_id, node_type, json.dumps([node_type]), time.time() - 5),
        )
        await db.commit()


async def _hold(target: str, channel: str | None) -> None:
    await engine.set_override(ManualOverride(target=target, channel=channel, reason="operator hold",
                                             expires_at=time.time() + 600))


async def _engine_holds(action: RuleAction, chamber_nodes: list[str] | None = None) -> bool:
    return engine._target_held(action, await engine._resolve_target(action, chamber_nodes))


async def _plug_rule(target: str) -> RuleAction:
    action = RuleAction(target=target, state="on")
    await create_rule(AutomationRule(
        name=f"Cool ({target})",
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=80)),
        action=action,
    ))
    return action


@pytest.mark.parametrize("held, scenes_off", [
    # The chamber page pins the light's real node: that light keeps its scene.
    ("node-l2", ["sporeprint/node-l1/cmd/scene"]),
    # The rule's own placeholder name holds every light it stands for.
    ("light-01", []),
])
async def test_a_light_with_one_channel_pinned_keeps_its_scene(
        held, scenes_off, json_publishes, mock_mqtt_raw):
    """A scene sets every dim channel of its light, so the engine holds the
    scene rules while one channel is pinned; the grow's end sent the pinned
    light the all-off scene all the same."""
    await seed_builtin_rules()
    await _node("node-l1", "lighting")
    await _node("node-l2", "lighting")
    await _hold(held, "white")
    s = await _session()
    await complete_session(s["id"])
    assert [t for t, _ in json_publishes if t.endswith("/cmd/scene")] == scenes_off
    # The relay is not held: its channels still go off.
    assert "sporeprint/relay-01/cmd/fae" in {t for t, _ in json_publishes}
    # Exactly the lights the engine keeps its scene rules off.
    lights_on = RuleAction(target="light-01", scene="fruiting_standard", state="on")
    assert await _engine_holds(lights_on, ["node-l2"])
    assert await _engine_holds(lights_on, ["node-l1"]) is (held == "light-01")


@pytest.mark.parametrize("rule_target, held, switched_off", [
    ("plug-cooler", None, True),
    # Held by its id (as a safety lockout is), the rule naming its role.
    ("plug-cooler", "plug-abc123", False),
    # Held by its role, the rule naming its id.
    ("plug-abc123", "plug-cooler", False),
    # Another plug's hold holds nothing here.
    ("plug-cooler", "plug-heater", True),
])
async def test_a_plug_is_held_under_its_id_and_its_role(
        rule_target, held, switched_off, json_publishes, mock_mqtt_raw):
    """A plug held under one of its names was switched off at the grow's end
    through a rule naming it by the other, though the engine held that rule."""
    await register_plug("plug-abc123", "Cooler", "shelly", "shellies/abc123", device_role="cooler")
    await register_plug("plug-def456", "Heater", "shelly", "shellies/def456", device_role="heater")
    action = await _plug_rule(rule_target)
    if held:
        await _hold(held, None)
    s = await _session()
    await complete_session(s["id"])
    assert (("shellies/abc123/relay/0/command", "off") in mock_mqtt_raw) is switched_off
    assert await _engine_holds(action) is not switched_off


# ── each chamber's own plug ────────────────────────────────────


def _off(prefix: str) -> tuple[str, str]:
    return (f"shellies/{prefix}/relay/0/command", "off")


async def _three_coolers() -> tuple[dict, dict]:
    """Chamber A's and chamber B's own cooler (each lists its plug), and a
    cooler no chamber lists."""
    for plug in ("aaa", "bbb", "ccc"):
        await register_plug(f"plug-{plug}", f"Cooler {plug}", "shelly", f"shellies/{plug}",
                            device_role="cooler")
    a = await create_chamber(ChamberCreate(name="A", node_ids=["plug-aaa"]))
    b = await create_chamber(ChamberCreate(name="B", node_ids=["plug-bbb"]))
    return a, b


async def test_each_chambers_own_plugs_go_off_with_its_grow(json_publishes, mock_mqtt_raw):
    """Each chamber switches its own plug of a role on, but the grow's end
    reached one plug of the role (the first found), and while another grow
    ran it switched no plug off at all."""
    a, b = await _three_coolers()
    await _plug_rule("plug-cooler")
    grow_a = await _session("A", chamber_id=a["id"])
    grow_b = await _session("B", chamber_id=b["id"])

    await complete_session(grow_a["id"])
    # A's own cooler: no grow drives it now. B's is B's grow's; the one no
    # chamber lists may serve B's grow too.
    assert mock_mqtt_raw == [_off("aaa")]

    del mock_mqtt_raw[:]
    await complete_session(grow_b["id"])
    # The last grow: every cooler.
    assert sorted(mock_mqtt_raw) == [_off("aaa"), _off("bbb"), _off("ccc")]
    safed = [e for e in await get_events(grow_b["id"]) if e["type"] == "actuators_safed"]
    assert {r["target"] for r in json.loads(safed[0]["data"])["actuators"]} == {
        "plug-aaa", "plug-bbb", "plug-ccc"}


async def test_one_held_plug_of_a_role_stays_on(json_publishes, mock_mqtt_raw):
    await _three_coolers()
    cool = await _plug_rule("plug-cooler")
    await _hold("plug-bbb", None)
    s = await _session()
    await complete_session(s["id"])
    assert sorted(mock_mqtt_raw) == [_off("aaa"), _off("ccc")]
    # The engine holds the rule for chamber B (its own cooler), not for A.
    assert await _engine_holds(cool, ["plug-bbb"])
    assert not await _engine_holds(cool, ["plug-aaa"])


async def _coolers(*plugs: str) -> None:
    for plug in plugs:
        await register_plug(f"plug-{plug}", f"Cooler {plug}", "shelly", f"shellies/{plug}",
                            device_role="cooler")


async def test_the_closets_own_plug_goes_off_with_the_closets_grow(json_publishes, mock_mqtt_raw):
    """A grow on nodes in no chamber drives a plug no chamber lists. It stayed
    on when that grow ended while a chamber's grow ran, though that chamber
    drives its own and nothing drove this one any more."""
    await _coolers("aaa", "ccc")
    await _node("climate-1", "climate")
    a = await create_chamber(ChamberCreate(name="A", node_ids=["climate-a", "plug-aaa"]))
    await _plug_rule("plug-cooler")
    await _session("A", chamber_id=a["id"])
    closet = await _session("Closet")
    await complete_session(closet["id"])
    assert mock_mqtt_raw == [_off("ccc")]


async def test_a_plug_no_chamber_lists_stays_on_for_a_chamber_without_its_own(
        json_publishes, mock_mqtt_raw):
    await _coolers("ccc")
    await _node("climate-1", "climate")
    b = await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"]))
    await _plug_rule("plug-cooler")
    await _session("B", chamber_id=b["id"])
    closet = await _session("Closet")
    await complete_session(closet["id"])
    # Chamber B has no cooler of its own: its grow still drives this one.
    assert mock_mqtt_raw == []


async def test_a_plug_lent_to_the_closets_grow_goes_off_with_it(json_publishes, mock_mqtt_raw):
    """With no plug of the role of their own, nodes in no chamber drive the
    plug of a chamber that runs the same grow."""
    await _coolers("aaa", "bbb")
    await _node("climate-1", "climate")
    await create_chamber(ChamberCreate(name="A", node_ids=["plug-aaa"]))  # no grow of its own
    b = await create_chamber(ChamberCreate(name="B", node_ids=["plug-bbb"]))
    await _plug_rule("plug-cooler")
    await _session("B", chamber_id=b["id"])
    closet = await _session("Closet")
    await complete_session(closet["id"])
    assert mock_mqtt_raw == [_off("aaa")]


async def test_a_plug_named_after_its_role_and_the_roles_other_plugs_go_off(
        json_publishes, mock_mqtt_raw):
    """A plug whose Topic is its role has the role's target name for its id:
    the last grow's end switched off that plug alone, and left the role's
    other plugs, each its chamber's own, on."""
    await register_plug("plug-cooler", "Cooler", "shelly", "shellies/cooler")
    await _coolers("cooler2")
    a = await create_chamber(ChamberCreate(name="A", node_ids=["plug-cooler"]))
    b = await create_chamber(ChamberCreate(name="B", node_ids=["plug-cooler2"]))
    await _plug_rule("plug-cooler")
    grow_a = await _session("A", chamber_id=a["id"])
    grow_b = await _session("B", chamber_id=b["id"])
    await complete_session(grow_a["id"])
    assert mock_mqtt_raw == [_off("cooler")]
    del mock_mqtt_raw[:]
    await complete_session(grow_b["id"])
    assert sorted(mock_mqtt_raw) == [_off("cooler"), _off("cooler2")]


def test_which_holds_keep_an_action_out_of_automation():
    """The one rule the engine and session-end safing read holds by."""
    names = {"light-01", "node-l1"}
    # The action's channel or the whole target, under any of its names; an
    # empty channel is the whole target, as the override key reads it.
    for hold in (("light-01", "white"), ("node-l1", "white"), ("node-l1", None), ("node-l1", "")):
        assert hold_applies(*hold, names, channel="white"), hold
    assert not hold_applies("node-l1", "red", names, channel="white")
    assert not hold_applies("node-l2", None, names, channel="white")
    # A scene (no channel) is held by a hold on any channel of its node ...
    assert hold_applies("node-l1", "red", names, scene="fruiting_standard")
    assert not hold_applies("node-l2", "red", names, scene="fruiting_standard")
    # ... a channel action, or a vendor action, only by its own channel.
    assert not hold_applies("node-l1", "red", names, channel="white", scene="fruiting_standard")
    assert not hold_applies("vendor:kasa", "x", {"vendor:kasa"}, scene="on", vendor_slug="kasa")


async def test_unknown_session_returns_none_and_publishes_nothing(json_publishes, mock_mqtt_raw):
    await seed_builtin_rules()
    assert await complete_session(9999) is None
    assert await abort_session(9999) is None
    assert json_publishes == []


# ── chamber.active_session_id lifecycle ──────────────────────────


@pytest.mark.parametrize("end", [complete_session, abort_session])
async def test_ending_session_clears_chamber_active_session(end, json_publishes, mock_mqtt_raw):
    chamber = await create_chamber(ChamberCreate(name="Closet"))
    s = await _session(chamber_id=chamber["id"])
    assert (await get_chamber(chamber["id"]))["active_session_id"] == s["id"]

    await end(s["id"])

    assert (await get_chamber(chamber["id"]))["active_session_id"] is None


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


# ── vendor devices are switched off too ─────────────────────────


async def _kasa_heater_rule(on=True):
    await create_rule(AutomationRule(
        name="Heater (kasa)", priority=1,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=60)),
        action=RuleAction(target="vendor:kasa", vendor_slug="kasa", vendor_action="set_power",
                          vendor_params={"ip": "10.0.0.20", "on": on}),
    ))


async def test_last_grow_ending_switches_a_vendor_device_off(json_publishes, mock_mqtt_raw, kasa_wire):
    """A vendor plug a rule switched on was left on: session-end safing
    skipped every vendor rule as having 'no generic OFF'."""
    await _kasa_heater_rule()
    await _kasa_heater_rule(on=False)  # an OFF rule switches nothing on
    s = await _session()
    await complete_session(s["id"])
    assert kasa_wire == [("10.0.0.20", {"system": {"set_relay_state": {"state": 0}}})]
    safed = [e for e in await get_events(s["id"]) if e["type"] == "actuators_safed"]
    actuators = json.loads(safed[0]["data"])["actuators"]
    assert {"target": "vendor:kasa:10.0.0.20", "channel": None, "kind": "vendor",
            "published": True} in actuators



async def test_a_vendor_device_that_cannot_be_switched_off_never_strands_the_rest(
        json_publishes, mock_mqtt_raw, monkeypatch):
    """An unreachable plug is recorded as not switched off; a rule naming no
    device has nothing to switch; every other actuator still goes off."""
    sent: list[str] = []

    async def query(ip, payload, timeout):
        if ip == "10.0.0.21":
            raise kasa_driver.KasaError("connect refused")
        sent.append(ip)
        return {}

    monkeypatch.setattr(kasa_driver, "_kasa_query", query)
    await seed_builtin_rules()
    for name, ip in (("unreachable", "10.0.0.21"), ("no device", ""), ("heater", "10.0.0.20")):
        await create_rule(AutomationRule(
            name=name, condition=RuleCondition(
                type=ConditionType.THRESHOLD,
                threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=60)),
            action=RuleAction(target="vendor:kasa", vendor_slug="kasa", vendor_action="set_power",
                              vendor_params={"ip": ip, "on": True}),
        ))
    s = await _session()
    await complete_session(s["id"])

    assert sent == ["10.0.0.20"]
    assert "sporeprint/relay-01/cmd/fae" in {t for t, _ in json_publishes}
    (safed,) = [e for e in await get_events(s["id"]) if e["type"] == "actuators_safed"]
    vendors = [a for a in json.loads(safed["data"])["actuators"] if a["kind"] == "vendor"]
    assert sorted((a["target"], a["published"]) for a in vendors) == [
        ("vendor:kasa:10.0.0.20", True), ("vendor:kasa:10.0.0.21", False)]


async def test_a_config_command_rule_gets_no_off_at_session_end(json_publishes, mock_mqtt_raw):
    """cmd/config reads no on/off state: there is nothing to switch off."""
    await create_rule(AutomationRule(
        name="cadence", condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=0)),
        action=RuleAction(target="climate-01", state="on"),
    ))
    s = await _session()
    await complete_session(s["id"])
    assert json_publishes == [] and mock_mqtt_raw == []

# ── a grow is ended once ───────────────────────────────────────


async def test_an_ended_grow_is_not_ended_again(json_publishes, mock_mqtt_raw):
    """Aborting a completed grow rewrote its outcome and end time, logged a
    second end and switched its actuators off again."""
    await seed_builtin_rules()
    s = await _session()
    done = await complete_session(s["id"])
    sent = len(json_publishes)
    # The same end again is a no-op ...
    again = await complete_session(s["id"])
    assert again["status"] == "completed" and again["completed_at"] == done["completed_at"]
    # ... another one is refused.
    with pytest.raises(SessionConflictError, match="completed"):
        await abort_session(s["id"])
    after = await get_session(s["id"])
    assert after["status"] == "completed" and after["completed_at"] == done["completed_at"]
    events = [e["type"] for e in await get_events(s["id"])]
    assert events.count("session_completed") == 1 and "session_aborted" not in events
    assert events.count("actuators_safed") == 1
    assert len(json_publishes) == sent


def test_end_endpoints_answer_409_for_an_ended_grow(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    assert client.post(f"/api/sessions/{s['id']}/complete").status_code == 200
    assert client.post(f"/api/sessions/{s['id']}/complete").json()["status"] == "completed"
    r = client.post(f"/api/sessions/{s['id']}/abort")
    assert r.status_code == 409, r.text
    assert client.post(f"/api/sessions/{s['id']}/contaminated").status_code == 409
    assert client.post(f"/api/sessions/{s['id']}/phase", json={"phase": "fruiting"}).status_code == 409


async def test_advancing_to_complete_ends_the_grow(json_publishes, mock_mqtt_raw):
    """POST /phase {"phase": "complete"} set only the phase: the grow stayed
    active, managed with no setpoints, and nothing was switched off."""
    await seed_builtin_rules()
    s = await _session()
    ended = await advance_phase(s["id"], PhaseAdvance(phase="complete"))
    assert ended["status"] == "completed" and ended["current_phase"] == "complete"
    assert ended["completed_at"] is not None
    assert any(t == "sporeprint/relay-01/cmd/fae" for t, _ in json_publishes)
    assert all(ph["exited_at"] is not None for ph in ended["phase_history"])
    # An ended grow changes phase no more (it reopened a phase_history row).
    with pytest.raises(SessionConflictError):
        await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    assert (await get_session(s["id"]))["current_phase"] == "complete"
