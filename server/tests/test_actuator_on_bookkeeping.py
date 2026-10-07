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
from app.automation.engine import evaluate_rules, note_actuator_on
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


# ── the hook itself ──────────────────────────────────────────────────────


async def test_note_actuator_on_drops_the_redundant_off_entry():
    key = engine._safety_key("relay-01", "heater")
    engine._last_off_sent[key] = time.time()
    engine._last_off_sent[engine._safety_key("relay-01", "fae")] = time.time()
    await note_actuator_on("relay-01", "heater")
    assert key not in engine._last_off_sent
    assert engine._safety_key("relay-01", "fae") in engine._last_off_sent


async def test_note_actuator_on_covers_both_names_of_a_plug():
    await register_plug(plug_id="plug-h1", name="heater", plug_type="shelly",
                        mqtt_topic_prefix="shellies/h1", device_role="heater")
    for name in ("plug-heater", "plug-h1"):
        engine._last_off_sent[engine._safety_key(name, None)] = time.time()
    await note_actuator_on("plug-h1", None)
    assert engine._last_off_sent == {}


# ── native channel: every out-of-engine ON path ──────────────────────────


async def test_manual_node_on_lets_the_cutoff_resend_its_off(mock_mqtt):
    await _cutoff_rule("relay-01", "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 1          # suppressed repeat
    with _clock(t0 + 90):
        topic, published = await send_command("relay-01", {"channel": "heater", "state": "on"})
    assert published
    with _clock(t0 + 122):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 2


async def test_manual_pwm_command_counts_as_on(mock_mqtt):
    await _cutoff_rule("relay-01", "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    await send_command("relay-01", {"channel": "heater", "pwm": 200})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 2


async def test_manual_off_keeps_the_suppression(mock_mqtt):
    await _cutoff_rule("relay-01", "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    await send_command("relay-01", {"channel": "heater", "state": "off"})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 2          # rule's first + the manual one


async def test_unpublished_manual_on_changes_nothing(mock_mqtt):
    await _cutoff_rule("relay-01", "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    mock_mqtt.mock.return_value = False
    await send_command("relay-01", {"channel": "heater", "state": "on"})
    mock_mqtt.mock.return_value = True
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 1


async def test_cloud_on_lets_the_cutoff_resend_its_off(mock_mqtt, cloud_env):
    await _register_relay_node()
    await _cutoff_rule(RELAY_NODE, "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    sio = _Sio()
    await handle_cloud_command(sio, _cloud_cmd("cmd-on", "heater", {"state": "on"}))
    assert sio.last_result()["success"] is True
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 2


async def test_node_reporting_the_channel_on_lets_the_cutoff_resend(mock_mqtt, monkeypatch):
    """A node button (or any path the Pi never saw) switches the channel ON;
    the node's own switch-state report is enough."""
    async def _no_forward(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_telemetry", _no_forward)
    await _cutoff_rule("relay-01", "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    await _handle_message(_Sio(), "sporeprint/relay-01/telemetry/heater",
                          {"channel": "heater", "state": "on", "trigger": "button"})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 2


async def test_node_reporting_the_channel_off_keeps_the_suppression(mock_mqtt, monkeypatch):
    async def _no_forward(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_telemetry", _no_forward)
    await _cutoff_rule("relay-01", "heater")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    await _handle_message(_Sio(), "sporeprint/relay-01/telemetry/heater",
                          {"channel": "heater", "state": "off", "trigger": "cmd"})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert len(_offs(mock_mqtt, "/cmd/heater")) == 1


# ── plug endpoint ────────────────────────────────────────────────────────


async def test_plug_endpoint_on_lets_the_cutoff_resend_its_off(mock_mqtt, mock_mqtt_raw):
    await register_plug(plug_id="plug-h1", name="heater", plug_type="shelly",
                        mqtt_topic_prefix="shellies/h1", device_role="heater")
    await _cutoff_rule("plug-heater", None)
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 90})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"temp_f": 90})
    cmds = [p for t, p in mock_mqtt_raw if t == "shellies/h1/relay/0/command"]
    assert cmds == ["off"]
    # By its id, while the rule names it by role: both names are one plug.
    await command_plug("plug-h1", {"state": "on"})
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


def test_cloud_service_reuses_the_automation_off_helpers():
    """No private copies of the OFF detection / duty stripping."""
    assert not hasattr(cloud_service, "_is_plain_off")
    assert not hasattr(cloud_service, "_strip_duty")
