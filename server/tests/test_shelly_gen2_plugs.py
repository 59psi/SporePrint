"""Shelly Gen2+ smart plugs (Plus / Pro / Mini, Gen3, Gen4): JSON-RPC over MQTT.

A Gen2+ device speaks Shelly's JSON-RPC API instead of Gen1's bare-text relay
topics. With its MQTT prefix set to shellies/<role> (the only shape the broker
ACL lets the plug login and the server use), it:

  * takes commands as a JSON-RPC frame on <prefix>/rpc —
    {"id", "src", "method": "Switch.Set", "params": {"id": 0, "on": true}} —
    and replies on <src>/rpc (src = <prefix>/sporeprint);
  * reports switch status in NotifyStatus / NotifyFullStatus on
    <prefix>/events/rpc and, with "Generic status update over MQTT" on, the
    full status on <prefix>/status/switch:<id>;
  * publishes <prefix>/online true/false (retained; the LWT).

These tests pin the command frames, the status parsing (Gen2 Plus and the
Gen3 / Gen4 field shapes), routing through the real MQTT loop and
online/offline. Gen2 works like Gen1 and Tasmota everywhere else, tested
across all three transports: the prefixes the broker grants, resolution by
role and switch id (tests/test_smart_plug_transport.py), a rule reaching
the plug (tests/test_automation_routing.py), the safety ceiling's OFF
(tests/test_safety_max_on.py) and a manual OFF ending it
(tests/test_safety_watchdog_hardening.py).
"""

import asyncio
import json
import logging

import pytest

import app.automation.smart_plugs as smart_plugs
import app.mqtt
from app.automation.smart_plugs import (
    PLUG_TYPE_SHELLY,
    PLUG_TYPE_SHELLY_GEN2,
    PLUG_TYPE_TASMOTA,
    handle_plug_message,
    register_plug,
    send_plug_command,
)
from app.mqtt import start_mqtt
from tests._pi_a_engine import (
    FakeSio as _Sio,
    MqttMessage,
    fake_mqtt_client,
    insert_plug,
    plug_row as _row,
    rows,
)

# Real payloads, as the devices publish them (trimmed of unrelated components).
PLUS_PLUG_S_FULL_STATUS = {
    "src": "shellyplusplugs-a8032ab12345",
    "dst": "shellies/humidifier/events",
    "method": "NotifyFullStatus",
    "params": {
        "ts": 1759622400.12,
        "ble": {},
        "cloud": {"connected": False},
        "mqtt": {"connected": True},
        "switch:0": {
            "id": 0, "source": "init", "output": True, "apower": 31.4,
            "voltage": 120.6, "current": 0.27,
            "aenergy": {"total": 1234.5, "by_minute": [0.0, 0.0, 0.0], "minute_ts": 1759622400},
            "temperature": {"tC": 36.1, "tF": 97.0},
        },
        "sys": {"mac": "A8032AB12345", "uptime": 812},
        "wifi": {"sta_ip": "192.168.1.50", "status": "got ip", "rssi": -58},
    },
}

# Shelly Plug S Gen3 / Gen4: extra metering fields and an errors list.
GEN3_SWITCH_STATUS = {
    "id": 0, "source": "button", "output": True, "apower": 1418.2, "voltage": 121.0,
    "freq": 60.0, "current": 11.72, "pf": 0.99,
    "aenergy": {"total": 9001.2, "by_minute": [23.6, 23.5, 23.6], "minute_ts": 1759622460},
    "ret_aenergy": {"total": 0.0, "by_minute": [0.0, 0.0, 0.0], "minute_ts": 1759622460},
    "temperature": {"tC": 51.0, "tF": 123.8},
    "errors": [],
}
GEN4_SWITCH_STATUS = {
    "id": 0, "source": "SHC", "output": False, "apower": 0, "voltage": 230.1,
    "freq": 50.0, "current": 0, "pf": 0,
    "aenergy": {"total": 12.0, "by_minute": [0, 0, 0], "minute_ts": 1759622520},
    "ret_aenergy": {"total": 0, "by_minute": [0, 0, 0], "minute_ts": 1759622520},
    "temperature": {"tC": 30.2, "tF": 86.4},
}
# Shelly 1 Mini Gen3: a relay with no power metering — no apower at all.
MINI_GEN3_SWITCH_STATUS = {
    "id": 0, "source": "WS_in", "output": True,
    "temperature": {"tC": 41.0, "tF": 105.8},
}


def _notify_status(prefix: str, switches: dict) -> dict:
    return {"src": "shellyplusplugs-a8032ab12345", "dst": f"{prefix}/events",
            "method": "NotifyStatus", "params": {"ts": 1759622461.5, **switches}}


@pytest.fixture(autouse=True)
def _reset_gen2_state():
    smart_plugs._gen2_errors_seen.clear()
    yield
    smart_plugs._gen2_errors_seen.clear()


async def _register_gen2(plug_id: str, prefix: str, role: str | None = None,
                         switch_id: int | None = None) -> None:
    await insert_plug(plug_id, PLUG_TYPE_SHELLY_GEN2, prefix, role=role,
                      config=None if switch_id is None else {"switch_id": switch_id})


def _frames(raw_calls) -> list[tuple[str, dict]]:
    """Decode the JSON-RPC frames among captured raw publishes."""
    return [(topic, json.loads(payload)) for topic, payload in raw_calls]


# ── command frames ─────────────────────────────────────────────────────


@pytest.mark.parametrize("state,on", [("on", True), ("off", False), ("ON", True), ("Off", False)])
async def test_switch_set_frame(mock_mqtt_raw, state, on):
    await _register_gen2("plug-humidifier", "shellies/humidifier")
    assert await send_plug_command("plug-humidifier", state) is True

    [(topic, frame)] = _frames(mock_mqtt_raw)
    assert topic == "shellies/humidifier/rpc"
    assert frame["method"] == "Switch.Set"
    assert frame["params"] == {"id": 0, "on": on}
    # Replies come back inside the plug's own subtree, which sp-3p may publish.
    assert frame["src"] == "shellies/humidifier/sporeprint"
    assert isinstance(frame["id"], int) and not isinstance(frame["id"], bool)
    assert set(frame) == {"id", "src", "method", "params"}


async def test_request_ids_are_unique(mock_mqtt_raw):
    await _register_gen2("plug-heater", "shellies/heater")
    await send_plug_command("plug-heater", "on")
    await send_plug_command("plug-heater", "off")
    ids = [frame["id"] for _, frame in _frames(mock_mqtt_raw)]
    assert len(set(ids)) == 2




async def test_toggle_maps_to_switch_toggle(mock_mqtt_raw):
    await _register_gen2("plug-humidifier", "shellies/humidifier")
    assert await send_plug_command("plug-humidifier", "toggle") is True
    [(_, frame)] = _frames(mock_mqtt_raw)
    assert frame["method"] == "Switch.Toggle"
    assert frame["params"] == {"id": 0}


@pytest.mark.parametrize("state", ["50", "", " off", "dim"])
async def test_state_without_a_switch_meaning_is_not_sent(mock_mqtt_raw, state):
    """Only exactly on/off/toggle (any case) — the same test the plug endpoint
    uses before clearing a ceiling, so an OFF the device would not read as OFF
    can never be reported as one."""
    await _register_gen2("plug-humidifier", "shellies/humidifier")
    assert await send_plug_command("plug-humidifier", state) is False
    assert mock_mqtt_raw == []



async def test_broker_down_is_not_sent(monkeypatch):
    await _register_gen2("plug-humidifier", "shellies/humidifier")
    monkeypatch.setattr(app.mqtt, "_client", None)
    assert await send_plug_command("plug-humidifier", "on") is False


@pytest.mark.parametrize("config", ["[not json", '{"switch_id": -1}', '{"switch_id": true}',
                                    '{"switch_id": "2"}'])
async def test_a_switch_id_it_cannot_read_falls_back_to_zero(mock_mqtt_raw, config):
    await insert_plug("plug-x", PLUG_TYPE_SHELLY_GEN2, "shellies/x", config=config)
    assert await send_plug_command("plug-x", "on") is True
    assert _frames(mock_mqtt_raw)[0][1]["params"]["id"] == 0


# ── status parsing ─────────────────────────────────────────────────────


async def test_full_status_registers_the_plug_with_state_and_power():
    sio = _Sio()
    await handle_plug_message(sio, "shellies/humidifier/events/rpc", PLUS_PLUG_S_FULL_STATUS)

    row = await _row("plug-humidifier")
    assert row is not None, "a Gen2 status report must register the plug"
    assert row["plug_type"] == PLUG_TYPE_SHELLY_GEN2
    assert row["mqtt_topic_prefix"] == "shellies/humidifier"
    assert row["last_state"] == "on"
    assert row["last_power_w"] == pytest.approx(31.4)
    assert row["status"] == "online"
    assert json.loads(row["config"]) == {"switch_id": 0}
    assert ("plug_state", {"plug_id": "plug-humidifier", "state": "on"}) in sio.events
    # Only the switch is a plug — sys / wifi / mqtt never register anything.
    assert len(await rows("SELECT plug_id FROM smart_plugs")) == 1


async def test_notify_status_delta_keeps_what_it_does_not_mention():
    """NotifyStatus is a delta: a missing `output` is unchanged, never off."""
    sio = _Sio()
    await handle_plug_message(sio, "shellies/humidifier/events/rpc", PLUS_PLUG_S_FULL_STATUS)
    await handle_plug_message(sio, "shellies/humidifier/events/rpc", _notify_status(
        "shellies/humidifier", {"switch:0": {"id": 0, "apower": 12.0, "current": 0.1}}))
    row = await _row("plug-humidifier")
    assert row["last_state"] == "on"
    assert row["last_power_w"] == pytest.approx(12.0)

    # An energy-counter tick carries neither: nothing changes.
    await handle_plug_message(sio, "shellies/humidifier/events/rpc", _notify_status(
        "shellies/humidifier",
        {"switch:0": {"id": 0, "aenergy": {"total": 1300.0, "by_minute": [1.0],
                                           "minute_ts": 1759622520}}}))
    row = await _row("plug-humidifier")
    assert (row["last_state"], row["last_power_w"]) == ("on", pytest.approx(12.0))

    await handle_plug_message(sio, "shellies/humidifier/events/rpc", _notify_status(
        "shellies/humidifier", {"switch:0": {"id": 0, "output": False, "source": "WS_in"}}))
    assert (await _row("plug-humidifier"))["last_state"] == "off"
    assert sio.events[-1] == ("plug_state", {"plug_id": "plug-humidifier", "state": "off"})


async def test_first_delta_without_output_registers_with_unknown_state():
    sio = _Sio()
    await handle_plug_message(sio, "shellies/dehumidifier/events/rpc", _notify_status(
        "shellies/dehumidifier", {"switch:0": {"id": 0, "aenergy": {"total": 1.0}}}))
    row = await _row("plug-dehumidifier")
    assert row is not None and row["plug_type"] == PLUG_TYPE_SHELLY_GEN2
    assert row["last_state"] is None and row["last_power_w"] is None
    assert sio.events == []  # no state to announce


@pytest.mark.parametrize("status,state,power", [
    (GEN3_SWITCH_STATUS, "on", 1418.2),
    (GEN4_SWITCH_STATUS, "off", 0.0),
    (MINI_GEN3_SWITCH_STATUS, "on", None),
])
async def test_status_topic_gen3_gen4_shapes(status, state, power):
    """<prefix>/status/switch:0 (Generic status update over MQTT): Gen3/Gen4
    add freq, pf, ret_aenergy and errors; a non-metering Mini has no apower."""
    await handle_plug_message(_Sio(), "shellies/heater/status/switch:0", status)
    row = await _row("plug-heater")
    assert row["plug_type"] == PLUG_TYPE_SHELLY_GEN2
    assert row["last_state"] == state
    if power is None:
        assert row["last_power_w"] is None
    else:
        assert row["last_power_w"] == pytest.approx(power)


async def test_multi_channel_device_registers_one_plug_per_switch(mock_mqtt_raw):
    """A Pro 2PM / 4PM or Power Strip: switch:0 is plug-<role>, switch:<n> is
    plug-<role>-<n>, each commanded on its own switch id."""
    await handle_plug_message(_Sio(), "shellies/closet/events/rpc", {
        "method": "NotifyFullStatus",
        "params": {"switch:0": {"id": 0, "output": False, "apower": 0.0},
                   "switch:1": {"id": 1, "output": True, "apower": 55.5},
                   "input:0": {"id": 0, "state": False}},
    })
    first, second = await _row("plug-closet"), await _row("plug-closet-1")
    assert (first["last_state"], second["last_state"]) == ("off", "on")
    assert json.loads(second["config"]) == {"switch_id": 1}
    assert second["mqtt_topic_prefix"] == "shellies/closet"

    assert await send_plug_command("plug-closet-1", "off") is True
    [(topic, frame)] = _frames(mock_mqtt_raw)
    assert topic == "shellies/closet/rpc" and frame["params"] == {"id": 1, "on": False}


async def test_status_topic_switch_id_comes_from_the_topic():
    await handle_plug_message(_Sio(), "shellies/closet/status/switch:3",
                              {"id": 3, "output": True})
    row = await _row("plug-closet-3")
    assert row["last_state"] == "on" and json.loads(row["config"]) == {"switch_id": 3}


@pytest.mark.parametrize("topic,payload", [
    # NotifyEvent (button pushes etc.) carries no switch status.
    ("shellies/x/events/rpc", {"method": "NotifyEvent",
                               "params": {"events": [{"component": "switch:0",
                                                      "event": "toggle"}]}}),
    ("shellies/x/events/rpc", "not json"),
    ("shellies/x/events/rpc", {"method": "NotifyStatus", "params": "nope"}),
    ("shellies/x/events/rpc", {"method": "NotifyStatus",
                               "params": {"switch:abc": {"output": True},
                                          "switch:0": "on", "sys": {"uptime": 3}}}),
    ("shellies/x/status/sys", {"uptime": 3}),
    ("shellies/x/status/input:0", {"id": 0, "state": True}),
    ("shellies/x/status/switch:0", "on"),
    # The server hears its own requests echoed back on shellies/#.
    ("shellies/x/rpc", {"id": 1, "src": "shellies/x/sporeprint", "method": "Switch.Set",
                        "params": {"id": 0, "on": True}}),
    ("shellies/x/announce", {"id": "shellyplusplugs-a8032ab12345", "model": "SNPL-00116US"}),
    ("shellies/announce", {"id": "shellyplusplugs-a8032ab12345"}),
    ("shellies//events/rpc", PLUS_PLUG_S_FULL_STATUS),
])
async def test_non_switch_frames_register_nothing(topic, payload):
    sio = _Sio()
    await handle_plug_message(sio, topic, payload)
    assert await rows("SELECT plug_id FROM smart_plugs") == []
    assert sio.events == []


async def test_errors_are_logged_once_per_change(caplog):
    tripped = {**GEN3_SWITCH_STATUS, "output": False, "apower": 0.0, "errors": ["overpower"]}
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        for _ in range(3):
            await handle_plug_message(_Sio(), "shellies/heater/status/switch:0", tripped)
    assert caplog.text.count("reports overpower") == 1
    assert (await _row("plug-heater"))["last_state"] == "off"

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.automation.smart_plugs"):
        await handle_plug_message(_Sio(), "shellies/heater/status/switch:0", GEN3_SWITCH_STATUS)
        # A delta without `errors` says nothing about them.
        await handle_plug_message(_Sio(), "shellies/heater/events/rpc", _notify_status(
            "shellies/heater", {"switch:0": {"id": 0, "apower": 5.0}}))
    assert caplog.text.count("faults cleared") == 1


# ── RPC replies ────────────────────────────────────────────────────────


async def test_get_status_reply_updates_the_plug():
    sio = _Sio()
    await handle_plug_message(sio, "shellies/humidifier/sporeprint/rpc", {
        "id": 7, "src": "shellyplusplugs-a8032ab12345", "dst": "shellies/humidifier/sporeprint",
        "result": PLUS_PLUG_S_FULL_STATUS["params"],
    })
    row = await _row("plug-humidifier")
    assert row["last_state"] == "on" and row["plug_type"] == PLUG_TYPE_SHELLY_GEN2


async def test_switch_set_reply_changes_nothing():
    await _register_gen2("plug-humidifier", "shellies/humidifier")
    await handle_plug_message(_Sio(), "shellies/humidifier/sporeprint/rpc",
                              {"id": 8, "src": "shellyplusplugs-a8032ab12345",
                               "dst": "shellies/humidifier/sporeprint",
                               "result": {"was_on": False}})
    assert (await _row("plug-humidifier"))["last_state"] is None


async def test_error_reply_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        await handle_plug_message(_Sio(), "shellies/closet/sporeprint/rpc", {
            "id": 9, "src": "shellypro4pm-f008d1d8b8b8", "dst": "shellies/closet/sporeprint",
            "error": {"code": -105, "message": "Argument 'id', value 7 not found!"},
        })
    assert "value 7 not found" in caplog.text and "-105" in caplog.text
    assert await _row("plug-closet") is None


# ── online / offline ───────────────────────────────────────────────────


async def test_online_flag_marks_every_row_under_the_prefix(mock_mqtt_raw):
    await _register_gen2("plug-closet", "shellies/closet", switch_id=0)
    await _register_gen2("plug-closet-1", "shellies/closet", switch_id=1)
    sio = _Sio()

    await handle_plug_message(sio, "shellies/closet/online", False)
    assert {(await _row(p))["status"] for p in ("plug-closet", "plug-closet-1")} == {"offline"}
    assert ("plug_online", {"plug_id": "plug-closet-1", "online": False}) in sio.events
    assert mock_mqtt_raw == []

    await handle_plug_message(sio, "shellies/closet/online", True)
    assert {(await _row(p))["status"] for p in ("plug-closet", "plug-closet-1")} == {"online"}
    # Back online: ask for the whole status — the device publishes none by
    # itself on (re)connect, and its relay may have changed while it was away.
    [(topic, frame)] = _frames(mock_mqtt_raw)
    assert topic == "shellies/closet/rpc"
    assert frame["method"] == "Shelly.GetStatus"
    assert frame["src"] == "shellies/closet/sporeprint"
    assert "params" not in frame


async def test_offline_is_logged_once(caplog):
    await _register_gen2("plug-heater", "shellies/heater")
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        await handle_plug_message(_Sio(), "shellies/heater/online", False)
        await handle_plug_message(_Sio(), "shellies/heater/online", False)
    assert caplog.text.count("went offline") == 1


async def test_online_for_an_unknown_device_registers_nothing_but_asks(mock_mqtt_raw):
    """The flag alone cannot say which transport a device speaks; the status
    query it triggers is what registers a new Gen2 plug (its reply carries the
    switch), with no toggle needed."""
    sio = _Sio()
    await handle_plug_message(sio, "shellies/heater/online", True)
    assert await _row("plug-heater") is None
    assert sio.events == []
    assert [t for t, _ in mock_mqtt_raw] == ["shellies/heater/rpc"]


async def test_report_after_offline_marks_online_again():
    await _register_gen2("plug-heater", "shellies/heater")
    await handle_plug_message(_Sio(), "shellies/heater/online", False)
    await handle_plug_message(_Sio(), "shellies/heater/status/switch:0", GEN4_SWITCH_STATUS)
    assert (await _row("plug-heater"))["status"] == "online"


async def test_gen1_and_tasmota_report_online_too():
    sio = _Sio()
    await handle_plug_message(sio, "shellies/shellyplug-s-7c87ce/relay/0", "on")
    await handle_plug_message(sio, "shellies/shellyplug-s-7c87ce/online", "false")
    assert (await _row("plug-shellyplug-s-7c87ce"))["status"] == "offline"

    await handle_plug_message(sio, "tasmota/cooler/stat/POWER", "OFF")
    await handle_plug_message(sio, "tasmota/cooler/tele/LWT", "Offline")
    assert (await _row("plug-cooler"))["status"] == "offline"
    await handle_plug_message(sio, "tasmota/cooler/tele/LWT", "Online")
    assert (await _row("plug-cooler"))["status"] == "online"


@pytest.mark.parametrize("payload", ["maybe", 1, None, {"online": True}])
async def test_unreadable_online_payload_is_ignored(payload, mock_mqtt_raw):
    await _register_gen2("plug-heater", "shellies/heater")
    await handle_plug_message(_Sio(), "shellies/heater/online", payload)
    assert (await _row("plug-heater"))["status"] == "unknown"
    assert mock_mqtt_raw == []


# ── transport healing / registration ───────────────────────────────────


async def test_gen2_report_retypes_a_row_registered_as_gen1(mock_mqtt_raw):
    """A plug added by hand with the endpoint's default type ('shelly' = Gen1)
    would be commanded on relay/0/command, which a Gen2 never reads. Its own
    report says what it is."""
    await register_plug(plug_id="plug-humidifier", name="Humidifier", plug_type="shelly",
                        mqtt_topic_prefix="shellies/humidifier", device_role=None)
    await handle_plug_message(_Sio(), "shellies/humidifier/events/rpc", PLUS_PLUG_S_FULL_STATUS)
    row = await _row("plug-humidifier")
    assert row["plug_type"] == PLUG_TYPE_SHELLY_GEN2
    assert row["name"] == "Humidifier"  # the operator's name is kept
    await send_plug_command("plug-humidifier", "off")
    assert [t for t, _ in mock_mqtt_raw] == ["shellies/humidifier/rpc"]


async def test_role_assignment_with_the_default_type_keeps_gen2():
    """POST /api/automation/plugs defaults plug_type to 'shelly': assigning a
    role to an auto-registered Gen2 plug must not demote it to Gen1."""
    await handle_plug_message(_Sio(), "shellies/plugsg3-b1/status/switch:0", GEN3_SWITCH_STATUS)
    await register_plug(plug_id="plug-plugsg3-b1", name="Heater", plug_type="shelly",
                        mqtt_topic_prefix="shellies/plugsg3-b1", device_role="heater")
    row = await _row("plug-plugsg3-b1")
    assert (row["plug_type"], row["device_role"]) == (PLUG_TYPE_SHELLY_GEN2, "heater")
    assert json.loads(row["config"]) == {"switch_id": 0}

    # An explicit other type, or a different prefix, is the operator's call.
    await register_plug(plug_id="plug-plugsg3-b1", name="Heater", plug_type=PLUG_TYPE_TASMOTA,
                        mqtt_topic_prefix="tasmota/heater", device_role="heater")
    assert (await _row("plug-plugsg3-b1"))["plug_type"] == PLUG_TYPE_TASMOTA


async def test_gen1_report_retypes_a_swapped_device():
    await _register_gen2("plug-dehum", "shellies/dehum")
    await handle_plug_message(_Sio(), "shellies/dehum/relay/0", "off")
    assert (await _row("plug-dehum"))["plug_type"] == PLUG_TYPE_SHELLY


async def test_gen1_relay_1_and_bad_power_are_not_plug_reports():
    sio = _Sio()
    await handle_plug_message(sio, "shellies/shelly25-1/relay/1", "on")
    assert await _row("plug-shelly25-1") is None
    await handle_plug_message(sio, "shellies/shelly25-1/relay/0", "on")
    await handle_plug_message(sio, "shellies/shelly25-1/relay/1/power", 99.0)
    await handle_plug_message(sio, "shellies/shelly25-1/relay/0/power", "garbage")
    assert (await _row("plug-shelly25-1"))["last_power_w"] is None
    await handle_plug_message(sio, "shellies/shelly25-1/relay/0/power", 42.5)
    assert (await _row("plug-shelly25-1"))["last_power_w"] == pytest.approx(42.5)


# ── through the real MQTT loop (raw bytes in, frames out) ──────────────


async def test_real_loop_registers_a_gen2_plug_from_its_retained_online_and_reply(monkeypatch):
    """What a server (re)start sees: the retained `online` (JSON true), then the
    device's reply to the status query that triggers, then a live delta."""
    full = json.dumps({"id": 1, "src": "shellyplusplugs-a8032ab12345",
                       "dst": "shellies/humidifier/sporeprint",
                       "result": PLUS_PLUG_S_FULL_STATUS["params"]}).encode()
    delta = json.dumps(_notify_status(
        "shellies/humidifier", {"switch:0": {"id": 0, "output": False}})).encode()
    published: list[tuple[str, str]] = []
    monkeypatch.setattr(app.mqtt.aiomqtt, "Client", fake_mqtt_client([
        MqttMessage("shellies/humidifier/online", b"true"),
        MqttMessage("shellies/humidifier/sporeprint/rpc", full),
        MqttMessage("shellies/humidifier/events/rpc", delta),
    ], published))
    sio = _Sio()
    await asyncio.wait_for(start_mqtt(sio), timeout=5)

    assert [(t, json.loads(p)["method"]) for t, p in published] == [
        ("shellies/humidifier/rpc", "Shelly.GetStatus")]
    row = await _row("plug-humidifier")
    assert row["plug_type"] == PLUG_TYPE_SHELLY_GEN2
    assert row["last_state"] == "off" and row["last_power_w"] == pytest.approx(31.4)
    # Never mistaken for a SporePrint node.
    assert await rows("SELECT node_id FROM hardware_nodes") == []

