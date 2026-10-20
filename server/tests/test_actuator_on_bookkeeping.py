"""An ON sent outside the engine re-enables the rule's OFF (final review).

A rule's plain OFF is not re-sent for _OFF_REASSERT_SECONDS (15 min) after it
went out (engine._skip_redundant_off). The suppression entry was cleared only
by an engine ON, so an actuator switched back ON by hand (manual node command,
cloud command, the plug endpoint, a node button) stayed ON for up to 15 min
while its cutoff rule held and did nothing. At 3140ea8 the OFF was re-sent
every cooldown.

engine.note_actuator_on(target, channel) drops the suppression. It is called
for every published non-OFF command from hardware.service.send_command, the
cloud hardware-command branch and POST /api/automation/plugs/{id}/command, and
for a node's own switch-state report of a channel ON.

Also covered: the cloud OFF path keys a scene OFF on channel None (as the
engine and hardware.service do) and uses the automation helpers for OFF
detection and duty stripping.
"""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import evaluate_rules
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.router import command_plug
from app.automation.service import create_rule
from app.automation.smart_plugs import register_plug
from app.cloud.service import handle_cloud_command
from app.db import get_db
from app.hardware.service import send_command
from app.mqtt import _handle_message
from app.sessions.models import SessionCreate
from app.sessions.service import create_session

_real_localtime = time.localtime
_KEY = "unit-test-cloud-token"
RELAY_NODE = "node-relay-7a3f1c"


def _local(hour, minute=0):
    return time.mktime((2026, 7, 13, hour, minute, 0, 0, 0, -1))


def _clock(ts):
    return patch.multiple(
        time,
        time=lambda: ts,
        localtime=lambda t=None: _real_localtime(ts if t is None else t),
    )


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def last_result(self) -> dict:
        event, data = self.events[-1]
        assert event == "command_result", event
        return data


@pytest.fixture(autouse=True)
def _reset_pause_state():
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


@pytest.fixture()
def cloud_env(monkeypatch):
    monkeypatch.setattr(cloud_service.settings, "cloud_token", _KEY)
    cloud_service._seen_command_ids.clear()
    yield
    cloud_service._seen_command_ids.clear()


def _sign(frame: dict) -> dict:
    body = json.dumps({k: v for k, v in frame.items() if k != "signature"},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**frame, "signature": hmac.new(_KEY.encode(), body, hashlib.sha256).hexdigest()}


def _cloud_cmd(cmd_id: str, channel, payload) -> dict:
    return _sign({"id": cmd_id, "tier": "premium", "target_kind": "relay",
                  "channel": channel, "payload": payload, "ts": time.time()})


async def _register_relay_node(node_id: str = RELAY_NODE) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) VALUES (?, ?, ?, ?)",
            (node_id, "relay", json.dumps(["heater", "fae"]), time.time()),
        )
        await db.commit()


async def _cutoff_rule(target: str, channel: str | None) -> None:
    await create_session(SessionCreate(
        name="grow", species_profile_id="unit-test-species", substrate="test",
        current_phase="fruiting",
    ))
    await create_rule(AutomationRule(
        name="Heat Cutoff",
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt",
                                                             value=80)),
        action=RuleAction(target=target, channel=channel, state="off"),
        cooldown_seconds=0,
    ))


def _offs(mqtt_calls, suffix):
    return [p for t, p in mqtt_calls if t.endswith(suffix) and p.get("state") == "off"]


# ── every out-of-engine switch, and what it does to a suppressed OFF ─────


def _manual(command, published=True):
    async def _do(mock_mqtt):
        mock_mqtt.mock.return_value = published
        await send_command("relay-01", command)
        mock_mqtt.mock.return_value = True
    return _do


async def _cloud_on(mock_mqtt):
    sio = _Sio()
    await handle_cloud_command(sio, _cloud_cmd("cmd-on", "heater", {"state": "on"}))
    assert sio.last_result()["success"] is True


def _node_reports(state, trigger):
    async def _do(mock_mqtt):
        await _handle_message(_Sio(), "sporeprint/relay-01/telemetry/heater",
                              {"channel": "heater", "state": state, "trigger": trigger})
    return _do


@pytest.mark.parametrize("target,switch,offs", [
    # Anything that may have switched the heater ON lets the cutoff re-send.
    ("relay-01", _manual({"channel": "heater", "state": "on"}), 2),
    ("relay-01", _manual({"channel": "heater", "pwm": 200}), 2),     # a duty is an ON
    (RELAY_NODE, _cloud_on, 2),
    # A node button, or any path the Pi never saw: the node's own report.
    ("relay-01", _node_reports("on", "button"), 2),
    # An OFF, or an ON that never went out, changes nothing (the manual OFF
    # is the second OFF on the wire; the rule's stays suppressed).
    ("relay-01", _manual({"channel": "heater", "state": "off"}), 2),
    ("relay-01", _manual({"channel": "heater", "state": "on"}, published=False), 1),
    ("relay-01", _node_reports("off", "cmd"), 1),
], ids=["manual on", "manual pwm", "cloud on", "node reports on", "manual off",
        "unpublished manual on", "node reports off"])
async def test_an_on_from_outside_the_engine_lets_the_cutoff_resend_its_off(
        mock_mqtt, cloud_env, monkeypatch, target, switch, offs):
    async def _no_forward(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_telemetry", _no_forward)
    if target == RELAY_NODE:  # the cloud command reaches the chamber's real relay
        await _register_relay_node()
    await _cutoff_rule(target, "heater")
    t0 = _local(12)
    for dt in (0, 61):
        with _clock(t0 + dt):
            await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 1, "the repeat OFF is suppressed"
    with _clock(t0 + 90):
        await switch(mock_mqtt)
    with _clock(t0 + 122):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == offs


@pytest.mark.parametrize("named", ["plug-h1", "plug-heater"])
async def test_a_plug_endpoint_on_lets_the_cutoff_resend_its_off(mock_mqtt, mock_mqtt_raw, named):
    """By either of its names while the rule names it by role: both names
    are one plug."""
    await register_plug(plug_id="plug-h1", name="heater", plug_type="shelly",
                        mqtt_topic_prefix="shellies/h1", device_role="heater")
    await _cutoff_rule("plug-heater", None)
    t0 = _local(12)
    for dt in (0, 61):
        with _clock(t0 + dt):
            await evaluate_rules("climate-1", {"temp_f": 90})
    cmds = [p for t, p in mock_mqtt_raw if t == "shellies/h1/relay/0/command"]
    assert cmds == ["off"]
    await command_plug(named, {"state": "on"})
    with _clock(t0 + 122):
        await evaluate_rules("climate-1", {"temp_f": 90})
    cmds = [p for t, p in mock_mqtt_raw if t == "shellies/h1/relay/0/command"]
    assert cmds == ["off", "on", "off"]


# ── wiring: which commands call which hook ───────────────────────────────


@pytest.fixture()
def hooks(monkeypatch):
    calls: list[tuple[str, str, str | None]] = []

    async def _on(target, channel):
        calls.append(("on", target, channel))

    async def _off(target, channel, *, sent_at=None):
        calls.append(("off", target, channel))

    monkeypatch.setattr("app.automation.engine.note_actuator_on", _on)
    monkeypatch.setattr("app.automation.engine.note_actuator_off", _off)
    monkeypatch.setattr("app.hardware.service.note_actuator_on", _on)
    monkeypatch.setattr("app.hardware.service.note_actuator_off", _off)
    monkeypatch.setattr("app.automation.router.note_actuator_on", _on)
    monkeypatch.setattr("app.automation.router.note_actuator_off", _off)
    return calls


@pytest.mark.parametrize("command,expected", [
    ({"channel": "heater", "state": "on"}, [("on", "relay-01", "heater")]),
    ({"channel": "heater", "state": "OFF", "pwm": 10}, [("off", "relay-01", "heater")]),
    ({"channel": "scene", "scene": "fruiting_standard"}, [("on", "relay-01", None)]),
    ({"channel": "scene", "state": "off"}, [("off", "relay-01", None)]),
    ({"channel": "config", "state": "on"}, []),
    ({"interval_sec": 60}, []),
])
async def test_node_command_hooks(mock_mqtt, hooks, command, expected):
    await send_command("relay-01", command)
    assert hooks == expected


@pytest.mark.parametrize("channel,payload,expected", [
    ("heater", {"state": "on"}, [("on", RELAY_NODE, "heater")]),
    ("heater", {"pwm": 0}, [("on", RELAY_NODE, "heater")]),     # no explicit OFF
    ("heater", {"state": " Off "}, [("off", RELAY_NODE, "heater")]),
    ("scene", {"state": "off"}, [("off", RELAY_NODE, None)]),
    ("scene", {"scene": "cordyceps_blue"}, [("on", RELAY_NODE, None)]),
    ("config", {"state": "off"}, []),
    (None, {"state": "off"}, []),
])
async def test_cloud_command_hooks(mock_mqtt, hooks, cloud_env, channel, payload, expected):
    await _register_relay_node()
    await handle_cloud_command(_Sio(), _cloud_cmd("cmd-hook", channel, payload))
    assert len(mock_mqtt) == 1
    assert hooks == expected


async def test_undelivered_cloud_on_calls_no_hook(mock_mqtt, hooks, cloud_env):
    await _register_relay_node()
    mock_mqtt.mock.return_value = False
    await handle_cloud_command(_Sio(), _cloud_cmd("cmd-lost", "heater", {"state": "on"}))
    assert hooks == []


async def test_cloud_scene_off_carries_no_duty(mock_mqtt, hooks, cloud_env):
    await _register_relay_node()
    await handle_cloud_command(_Sio(), _cloud_cmd(
        "cmd-scene-off", "scene", {"state": "off", "level": 900, "pwm": 3}))
    assert mock_mqtt[0] == (f"sporeprint/{RELAY_NODE}/cmd/scene", {"state": "off"})


async def test_cloud_non_object_payload_calls_no_hook(mock_mqtt, hooks, cloud_env):
    """A node drops a non-object command, so nothing was switched."""
    await _register_relay_node()
    await handle_cloud_command(_Sio(), _cloud_cmd("cmd-list", "heater", ["on"]))
    assert hooks == []


@pytest.mark.parametrize("state,expected", [
    ("on", [("on", "plug-h1", None)]),
    ("off", [("off", "plug-h1", None)]),
    ("OFF", [("off", "plug-h1", None)]),
])
async def test_plug_endpoint_hooks(mock_mqtt_raw, hooks, state, expected):
    await register_plug(plug_id="plug-h1", name="heater", plug_type="shelly",
                        mqtt_topic_prefix="shellies/h1", device_role="heater")
    await command_plug("plug-h1", {"state": state})
    assert hooks == expected
