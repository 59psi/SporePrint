"""Automation engine — which physical actuator a rule drives, and when.

A chamber's rules reach the chamber's own nodes and plugs; a plug is one
actuator whichever name a rule gives it; cooldowns, holds and in-force
commands are kept per physical actuator; a frame that carries no reading for
a rule's sensor does not take the actuator away from it.
"""

import logging
import time

import pytest

import app.automation.engine as engine
from app.automation.engine import clear_override, evaluate_rules, set_override
from app.automation.models import (
    AutomationRule,
    CompoundCondition,
    CompoundOp,
    ConditionType,
    ManualOverride,
    RuleAction,
    RuleCondition,
)
from app.automation.service import create_rule, seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.db import get_db
from app.species.service import seed_builtins
from tests._builders import (
    LIGHT_CHANNELS as _LIGHT_CHANNELS,
    RELAY_CHANNELS as _RELAY_CHANNELS,
    chamber as _chamber,
    register_node,
    start_grow as _session,
    threshold as _threshold,
)
from tests._timing import clock as _clock, local as _local


@pytest.fixture(autouse=True)
def _quiet(quiet_alerts):
    """No ntfy, no cloud forward."""


async def _node(node_id, node_type, channels=None, last_seen=None):
    await register_node(node_id, node_type, channels, last_seen=last_seen)


async def _plug(plug_id, role):
    await register_plug(plug_id=plug_id, name=role, plug_type="tasmota",
                        mqtt_topic_prefix=f"tasmota/{plug_id}", device_role=role)


def _rule(name, action, condition=None, *, priority=5, safety_max=None, rule_id=None):
    return AutomationRule(
        id=rule_id, name=name, priority=priority,
        condition=condition or _threshold("temp_f", "lt", 1000),
        action=action, cooldown_seconds=60, safety_max_on_seconds=safety_max,
        log_to_session=False,
    )


def _powers(raw, plug_id):
    return [p for t, p in raw if t == f"tasmota/{plug_id}/cmnd/POWER"]


def _cmds(mqtt, suffix):
    return [p for t, p in mqtt if t.endswith(suffix)]


# ── a plug is one actuator, whichever name a rule uses ─────────────────────


async def test_a_plug_named_by_role_and_by_id_has_one_owner(frozen_sleep, mock_mqtt, mock_mqtt_raw):
    """The higher-priority rule owns the plug: its role-named ON is not
    followed by a lower-priority OFF that names the plug by its id."""
    await seed_builtins()
    await _plug("plug-a1b2c3", "heater")
    await _session("blue_oyster", "fruiting")
    await create_rule(_rule("Heat by role", RuleAction(target="plug-heater", state="on"),
                            _threshold("temp_f", "lt", 60), priority=9, safety_max=3600))
    await create_rule(_rule("Heater off by id", RuleAction(target="plug-a1b2c3", state="off"),
                            priority=5))
    await evaluate_rules("climate-1", {"temp_f": 50})
    assert _powers(mock_mqtt_raw, "plug-a1b2c3") == ["ON"]
    assert "plug-a1b2c3:*" in engine._safety_tasks


# ── a sealed vessel gates a plug by its role ───────────────────────────────


@pytest.mark.parametrize("container,expected", [("grain_jar", []), ("monotub", ["ON"])])
async def test_sealed_gate_knows_a_humidifier_named_by_its_plug_id(
        mock_mqtt, mock_mqtt_raw, container, expected):
    await seed_builtins()
    await _plug("plug-hum42", "humidifier")
    await _session("blue_oyster", "fruiting", container_type=container)
    await create_rule(_rule("Humidify by id", RuleAction(target="plug-hum42", state="on"),
                            _threshold("humidity", "lt", 60)))
    await evaluate_rules("climate-1", {"humidity": 40})
    assert _powers(mock_mqtt_raw, "plug-hum42") == expected


# ── chambers: per-actuator cooldowns, the chamber's own plug and node ──────


async def test_each_chamber_gets_its_own_fan_on_the_same_pass(mock_mqtt):
    """One chamber's firing used to put the rule in cooldown for every other
    chamber, whose own fan then never ran."""
    await seed_builtins()
    await seed_builtin_rules()
    now = time.time()
    await _node("relay-a", "relay", _RELAY_CHANNELS, now - 10)
    await _node("relay-b", "relay", _RELAY_CHANNELS, now)
    a = await _chamber("A", ["climate-a", "relay-a"])
    b = await _chamber("B", ["climate-b", "relay-b"])
    await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting", chamber_id=b)
    with _clock(_local(12)):
        await evaluate_rules("climate-a", {"co2_ppm": 1300})
        await evaluate_rules("climate-b", {"co2_ppm": 1300})
    fae_on = [t for t, p in mock_mqtt if t.endswith("/cmd/fae") and p.get("state") == "on"]
    assert "sporeprint/relay-a/cmd/fae" in fae_on
    assert "sporeprint/relay-b/cmd/fae" in fae_on


async def test_a_chamber_drives_its_own_plug_of_a_role(mock_mqtt, mock_mqtt_raw):
    await seed_builtins()
    await _plug("plug-ha", "heater")
    await _plug("plug-hb", "heater")
    a = await _chamber("A", ["climate-a", "plug-ha"])
    b = await _chamber("B", ["climate-b", "plug-hb"])
    await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting", chamber_id=b)
    await create_rule(_rule("heat", RuleAction(target="plug-heater", state="on"),
                            _threshold("temp_f", "lt", 55)))
    await evaluate_rules("climate-a", {"temp_f": 50})
    assert (_powers(mock_mqtt_raw, "plug-ha"), _powers(mock_mqtt_raw, "plug-hb")) == (["ON"], [])
    await evaluate_rules("climate-b", {"temp_f": 50})
    assert _powers(mock_mqtt_raw, "plug-hb") == ["ON"]


def _heat():
    return _rule("heat", RuleAction(target="plug-heater", state="on"), _threshold("temp_f", "lt", 55))


async def test_nodes_in_no_chamber_drive_a_plug_no_chamber_lists(mock_mqtt, mock_mqtt_raw):
    """A grow on nodes in no chamber drove the plug of the role paired first
    even when a chamber listed it: chamber A's heater, while the closet's
    own heater stayed off."""
    await seed_builtins()
    await _plug("plug-ha", "heater")
    await _plug("plug-closet", "heater")
    a = await _chamber("A", ["climate-a", "plug-ha"])
    await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting")  # the closet's grow: no chamber
    await create_rule(_heat())
    await evaluate_rules("climate-1", {"temp_f": 50})
    assert (_powers(mock_mqtt_raw, "plug-closet"), _powers(mock_mqtt_raw, "plug-ha")) == (["ON"], [])
    await evaluate_rules("climate-a", {"temp_f": 50})
    assert _powers(mock_mqtt_raw, "plug-ha") == ["ON"]


async def test_a_plug_named_after_its_role_is_one_of_the_roles_plugs(mock_mqtt, mock_mqtt_raw):
    """A plug whose Topic is its role has the role's target name for its id
    (plug-heater): every rule naming plug-heater drove that one plug,
    whichever chamber listed it, and chamber B's own heater never ran."""
    await seed_builtins()
    await register_plug(plug_id="plug-heater", name="heater", plug_type="tasmota",
                        mqtt_topic_prefix="tasmota/plug-heater")  # no role of its own
    await _plug("plug-heater2", "heater")
    await _plug("plug-heater3", "heater")
    a = await _chamber("A", ["climate-a", "plug-heater"])
    b = await _chamber("B", ["climate-b", "plug-heater2"])
    await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting", chamber_id=b)
    await _session("blue_oyster", "fruiting")
    await create_rule(_heat())
    for node in ("climate-a", "climate-b", "climate-1"):
        await evaluate_rules(node, {"temp_f": 50})
    assert [_powers(mock_mqtt_raw, p) for p in ("plug-heater", "plug-heater2", "plug-heater3")] == [
        ["ON"], ["ON"], ["ON"]]


@pytest.mark.parametrize("chamber_grow, expected", [(False, ["ON"]), (True, [])])
async def test_nodes_in_no_chamber_borrow_only_a_plug_of_their_own_grow(
        mock_mqtt, mock_mqtt_raw, chamber_grow, expected):
    """With no plug of the role that no chamber lists, nodes in no chamber
    drive the plug of a chamber that runs their grow (one with no grow of its
    own does), never one of a chamber that runs a grow of its own."""
    await seed_builtins()
    await _plug("plug-ha", "heater")
    a = await _chamber("A", ["climate-a", "plug-ha"])
    if chamber_grow:
        await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting")
    await create_rule(_heat())
    await evaluate_rules("climate-1", {"temp_f": 50})
    assert _powers(mock_mqtt_raw, "plug-ha") == expected


async def test_another_grows_plug_does_not_silence_a_fallback(mock_mqtt, mock_mqtt_raw):
    """A fallback that runs only while the role is missing went quiet for
    nodes in no chamber because another chamber's grow had a dehumidifier."""
    await seed_builtins()
    await _plug("plug-dh", "dehumidifier")
    await _plug("plug-fan", "fan")
    a = await _chamber("A", ["climate-a", "plug-dh"])
    await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting")
    vent = _rule("vent", RuleAction(target="plug-fan", state="on"), _threshold("humidity", "gt", 90))
    vent.requires_absent_target = "plug-dehumidifier"
    await create_rule(vent)
    await evaluate_rules("climate-1", {"humidity": 95})
    assert _powers(mock_mqtt_raw, "plug-fan") == ["ON"]


def _vent():
    return _rule("vent", RuleAction(target="relay-01", channel="fae", state="on", pwm=200),
                 _threshold("co2_ppm", "gt", 1000))


def _node_cmds(mqtt):
    return [t for t, _ in mqtt if "/cmd/" in t]


async def test_nodes_in_no_chamber_drive_the_relay_and_light_no_chamber_lists(mock_mqtt):
    """For nodes in no chamber, relay-01 and light-01 resolved to the node of
    the role seen last anywhere: chamber A's fan and light ran the closet's
    grow while the closet's own stayed off."""
    await seed_builtins()
    now = time.time()
    for name, node_type, channels in (("relay", "relay", _RELAY_CHANNELS),
                                      ("light", "lighting", _LIGHT_CHANNELS)):
        await _node(f"{name}-closet", node_type, channels, now - 10)
        await _node(f"{name}-a", node_type, channels, now)
    a = await _chamber("A", ["climate-a", "relay-a", "light-a"])
    await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting")  # the closet's grow: no chamber
    await create_rule(_vent())
    await create_rule(_rule("lights", RuleAction(target="light-01", scene="fruiting_standard",
                                                 state="on")))
    await evaluate_rules("climate-1", {"co2_ppm": 1500, "temp_f": 70})
    assert sorted(_node_cmds(mock_mqtt)) == [
        "sporeprint/light-closet/cmd/scene", "sporeprint/relay-closet/cmd/fae"]
    await evaluate_rules("climate-a", {"co2_ppm": 1500, "temp_f": 70})
    assert sorted(_node_cmds(mock_mqtt)) == [
        "sporeprint/light-a/cmd/scene", "sporeprint/light-closet/cmd/scene",
        "sporeprint/relay-a/cmd/fae", "sporeprint/relay-closet/cmd/fae"]


@pytest.mark.parametrize("chamber_grow, expected", [
    (False, ["sporeprint/relay-a/cmd/fae"]), (True, [])])
async def test_nodes_in_no_chamber_borrow_only_a_relay_of_their_own_grow(
        mock_mqtt, chamber_grow, expected):
    """With no relay that no chamber lists, nodes in no chamber drive the
    relay of a chamber that runs their grow (one with no grow of its own
    does), never one of a chamber that runs a grow of its own; with none,
    nothing goes out, not even to the placeholder, which no node answers."""
    await seed_builtins()
    await _node("relay-a", "relay", _RELAY_CHANNELS)
    a = await _chamber("A", ["climate-a", "relay-a"])
    if chamber_grow:
        await _session("blue_oyster", "fruiting", chamber_id=a)
    await _session("blue_oyster", "fruiting")
    await create_rule(_vent())
    await evaluate_rules("climate-1", {"co2_ppm": 1500})
    assert _node_cmds(mock_mqtt) == expected
    async with get_db() as db:
        cursor = await db.execute("SELECT status FROM automation_firings WHERE rule_name = 'vent'")
        assert [r["status"] for r in await cursor.fetchall()] == ["sent"] * len(expected)


async def test_a_chamber_without_a_relay_publishes_nothing_to_the_placeholder(mock_mqtt):
    """Another chamber's relay used to satisfy the channel check while the
    command went to sporeprint/relay-01, reaching nothing and reading 'sent'."""
    await seed_builtins()
    await _node("relay-a", "relay", _RELAY_CHANNELS)
    await _chamber("A", ["climate-a", "relay-a"])
    b = await _chamber("B", ["climate-b"])
    await _session("blue_oyster", "fruiting", chamber_id=b)
    await create_rule(_rule("vent", RuleAction(target="relay-01", channel="fae", state="on", pwm=200),
                            _threshold("co2_ppm", "gt", 1000)))
    await evaluate_rules("climate-b", {"co2_ppm": 1500})
    assert [t for t, _ in mock_mqtt if "/cmd/" in t] == []
    async with get_db() as db:
        cursor = await db.execute("SELECT status FROM automation_firings WHERE rule_name = 'vent'")
        assert await cursor.fetchall() == []


# ── a scene rule is held by a hold on any channel of its light ─────────────


async def test_a_light_channel_hold_holds_the_photoperiod_scene(mock_mqtt):
    await seed_builtins()
    await seed_builtin_rules()
    await _node("node-light", "lighting", _LIGHT_CHANNELS)
    await _session("blue_oyster", "fruiting")
    await set_override(ManualOverride(target="node-light", channel="white", reason="operator",
                                      expires_at=time.time() + 1800))
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert _cmds(mock_mqtt, "/cmd/scene") == []

    await clear_override("node-light", "white")
    with _clock(_local(12, 1)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")] == ["fruiting_standard"]


# ── one lookup per target per frame ────────────────────────────────────────


async def test_each_target_is_resolved_once_per_frame(mock_mqtt, monkeypatch):
    await seed_builtins()
    await seed_builtin_rules()
    await _node("node-relay", "relay", _RELAY_CHANNELS)
    await _node("node-light", "lighting", _LIGHT_CHANNELS)
    await _session("blue_oyster", "fruiting")
    calls: list[str] = []
    real = engine.resolve_node_target

    async def _counting(target, chamber_nodes=None, **kwargs):
        calls.append(target)
        return await real(target, chamber_nodes, **kwargs)

    monkeypatch.setattr(engine, "resolve_node_target", _counting)
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60, "humidity": 88, "co2_ppm": 1500})
    assert calls.count("relay-01") == 1
    assert calls.count("light-01") == 1


# ── a frame that cannot judge the condition keeps the claim ────────────────


async def test_a_relay_heartbeat_does_not_hand_the_fan_to_the_schedule(mock_mqtt):
    """CO2 FAE Trigger is in force; the relay node's own frame carries no CO2
    reading, which is not the condition going false."""
    await seed_builtins()
    await seed_builtin_rules()
    await _node("node-relay", "relay", _RELAY_CHANNELS)
    await _session("blue_oyster", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 5000})
    with _clock(_local(12) + 20):
        await evaluate_rules("node-relay", {})
    assert [p.get("pwm") for p in _cmds(mock_mqtt, "/cmd/fae")] == [200]


async def test_an_or_rule_fires_on_its_good_branch_beside_a_null_reading(mock_mqtt, caplog):
    """The firmware writes a non-finite dew point as null: comparing it raised,
    skipped the rule and logged an error on every frame."""
    await seed_builtins()
    await _node("node-relay", "relay", _RELAY_CHANNELS)
    await _session("blue_oyster", "fruiting")
    either = RuleCondition(type=ConditionType.COMPOUND, compound=CompoundCondition(
        op=CompoundOp.OR,
        conditions=[_threshold("dew_point_f", "gt", 70), _threshold("temp_f", "gt", 80)],
    ))
    await create_rule(_rule("vent", RuleAction(target="relay-01", channel="exhaust", state="on"),
                            either))
    with caplog.at_level(logging.ERROR, logger="app.automation.engine"):
        await evaluate_rules("climate-1", {"temp_f": 90, "humidity": 0.0, "dew_point_f": None})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")] == ["on"]
    assert "Error evaluating rule" not in caplog.text
