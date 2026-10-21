"""How a smart plug's transport is resolved, checked and kept, for every
transport (Tasmota, Shelly Gen1, Shelly Gen2+).

- A command only goes to a prefix the broker lets the server publish to: one
  level under shellies/ or tasmota/. Elsewhere Mosquitto drops it silently
  and the firing would read 'sent'.
- A command reaches the paired plug on its own topic tree, resolved the way
  target_is_present resolves it: by plug id or device role, the exact id
  winning. A plug that was never paired is an honest no-op, never a
  speculative publish that logs 'sent' for hardware that is not there.
- One resolution of a plug target (paired_plug): commands, presence checks,
  aliases and the engine's plug-state read agree on which row a target means.
- A plug's own report that it is ON again re-arms a cutoff's suppressed OFF.
- A report on another transport re-points a plug only once its stored
  transport has gone quiet; while it is live the report is ignored.
- A report that changes nothing is not written on every message.

Gen2's JSON-RPC protocol and status shapes: tests/test_shelly_gen2_plugs.py.
"""

import json
import logging
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
import app.automation.smart_plugs as smart_plugs
from app.automation.engine import _fire_rule
from app.automation.models import RuleAction
from app.automation.smart_plugs import (
    handle_plug_message,
    paired_plug,
    plug_aliases,
    plug_prefix_error,
    register_plug,
    send_plug_command,
    target_is_present,
)
from tests._builders import insert_plug, make_rule, plug_row
from tests._fakes import RecordingSio


def _at(ts: float):
    return patch.object(time, "time", lambda: ts)


def _wire(raw: list[tuple[str, str]]) -> list[tuple[str, object]]:
    """Raw plug publishes, a Gen2 JSON-RPC frame read as (method, params)."""
    out = []
    for topic, payload in raw:
        if topic.endswith("/rpc"):
            frame = json.loads(payload)
            payload = (frame["method"], frame.get("params"))
        out.append((topic, payload))
    return out


# ── Commands reach only prefixes the broker grants ─────────────────────────


@pytest.mark.parametrize("plug_type,prefix", [
    ("tasmota", "home/heater"),
    ("tasmota", "tasmota/closet/heater"),
    ("tasmota", "shellies/heater"),
    ("shelly", "shellies/closet/heater"),
    ("shelly", "tasmota/heater"),
    ("shelly", ""),
    ("shelly_gen2", "shellyplusplugs-a8032ab12345"),   # the factory prefix: a top-level tree
    ("shelly_gen2", "shellies/closet/humidifier"),
    ("shelly_gen2", "shellies/+"),
    ("shelly_gen2", ""),
])
async def test_a_command_to_a_prefix_the_broker_drops_is_not_sent(
        mock_mqtt_raw, plug_type, prefix, caplog):
    """Refused, and the log says how to fix the device."""
    await insert_plug("plug-heater", plug_type, prefix)
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        assert await send_plug_command("plug-heater", "on") is False
    assert mock_mqtt_raw == []
    assert plug_prefix_error(plug_type, prefix) in caplog.text


async def test_a_plug_of_an_unknown_type_is_not_commanded(mock_mqtt_raw):
    await insert_plug("plug-heater", "wemo", "tasmota/heater")
    assert await send_plug_command("plug-heater", "on") is False
    assert mock_mqtt_raw == []


def test_prefix_error_names_the_fix():
    assert plug_prefix_error("tasmota", "tasmota/heater") is None
    assert plug_prefix_error("shelly_gen2", "shellies/heater") is None
    assert "tasmota/<role>" in plug_prefix_error("tasmota", "home/heater")
    assert "shellies/<role>" in plug_prefix_error("shelly", "shellies/a/b")
    assert "Unknown plug_type" in plug_prefix_error("kasa", "kasa/heater")


@pytest.mark.parametrize("body", [
    {"plug_type": "tasmota", "mqtt_topic_prefix": "home/closet/heater"},
    {"plug_type": "shelly", "mqtt_topic_prefix": "shellies/closet/heater"},
    {"plug_type": "tasmota", "mqtt_topic_prefix": "tasmota/heater/"},
    {"plug_type": "wemo", "mqtt_topic_prefix": "tasmota/heater"},
])
def test_registering_a_plug_no_command_could_reach_is_422(client, body):
    r = client.post("/api/automation/plugs",
                    json={"plug_id": "plug-heater", "name": "heater", **body})
    assert r.status_code == 422, r.text
    assert client.get("/api/automation/plugs").json() == []


def test_registering_a_one_level_prefix_is_accepted(client):
    r = client.post("/api/automation/plugs", json={
        "plug_id": "plug-heater", "name": "heater", "plug_type": "tasmota",
        "mqtt_topic_prefix": "tasmota/heater", "device_role": "heater"})
    assert r.status_code == 200, r.text


async def test_register_plug_refuses_a_prefix_no_command_reaches():
    with pytest.raises(ValueError):
        await register_plug("plug-heater", "heater", "tasmota", "home/heater")
    assert await plug_row("plug-heater") is None


# ── A command reaches the paired plug on its own transport ────────────────


# (the paired rows, the target a rule names, the state) -> what goes out.
# Per the build guide a plug pairs as plug-<hwid> with a device_role, while
# the seeded rules name the role (plug-heater): resolving by id alone found
# nothing though target_is_present said the plug was there.
_COMMANDS = {
    "tasmota, by role": (
        [("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", "heater", None)], "plug-heater", "on",
        [("tasmota/a1b2c3/cmnd/POWER", "ON")]),
    # Bare text, not JSON: a Shelly rejects "on" with quotes.
    "shelly, by role": (
        [("plug-9f7e", "shelly", "shellies/9f7e", "humidifier", None)], "plug-humidifier", "on",
        [("shellies/9f7e/relay/0/command", "on")]),
    "shelly gen2, by role": (
        [("plug-shellyplugsg3-b1", "shelly_gen2", "shellies/shellyplugsg3-b1", "heater", None)],
        "plug-heater", "off",
        [("shellies/shellyplugsg3-b1/rpc", ("Switch.Set", {"id": 0, "on": False}))]),
    # A multi-channel Gen2 device: the switch id comes from the row.
    "shelly gen2, switch 2": (
        [("plug-closet-2", "shelly_gen2", "shellies/closet", "cooler", {"switch_id": 2})],
        "plug-cooler", "on",
        [("shellies/closet/rpc", ("Switch.Set", {"id": 2, "on": True}))]),
    # A plug whose id IS the friendly name, with no role.
    "by id, no role": (
        [("plug-heater", "tasmota", "tasmota/heater", None, None)], "plug-heater", "off",
        [("tasmota/heater/cmnd/POWER", "OFF")]),
    # One row's exact id and another row's role: the exact id wins.
    "exact id over a role": (
        [("plug-other", "shelly", "shellies/other", "heater", None),
         ("plug-heater", "tasmota", "tasmota/heater", None, None)], "plug-heater", "off",
        [("tasmota/heater/cmnd/POWER", "OFF")]),
}


@pytest.mark.parametrize("case", list(_COMMANDS))
async def test_a_command_reaches_the_paired_plug_on_its_own_transport(mock_mqtt_raw, case):
    paired, target, state, sent = _COMMANDS[case]
    for plug_id, plug_type, prefix, role, config in paired:
        await insert_plug(plug_id, plug_type, prefix, role=role, config=config)
    assert await target_is_present(target) is True
    assert await send_plug_command(target, state) is True
    assert _wire(mock_mqtt_raw) == sent


async def test_a_plug_that_was_never_paired_is_an_honest_no_op(mock_mqtt_raw):
    assert await target_is_present("plug-dehumidifier") is False
    assert await send_plug_command("plug-dehumidifier", "on") is False
    assert mock_mqtt_raw == []


# ── One resolution of a plug target ────────────────────────────────────────


async def test_every_reader_resolves_a_target_to_the_same_plug():
    # "plug-heater" is one row's exact id AND another row's role: the exact id wins.
    await insert_plug("plug-heater", "tasmota", "tasmota/heater", last_state="off")
    await insert_plug("plug-a1b2", "tasmota", "tasmota/a1b2", role="heater", last_state="on")
    row = await paired_plug("plug-heater")
    assert row["plug_id"] == "plug-heater"
    assert await plug_aliases("plug-heater") == {"plug-heater"}
    assert await engine._plug_reports_on("plug-heater") is False  # the exact row's state
    assert await target_is_present("plug-heater") is True
    # A role nobody holds resolves to nothing.
    assert await plug_aliases("plug-cooler") == {"plug-cooler"}
    assert await target_is_present("plug-cooler") is False


async def test_a_role_target_reads_the_role_holder():
    await insert_plug("plug-a1b2", "tasmota", "tasmota/a1b2", role="heater", last_state="on")
    assert await plug_aliases("plug-heater") == {"plug-heater", "plug-a1b2"}
    assert await engine._plug_reports_on("plug-heater") is True
    assert await target_is_present("plug-heater") is True


# ── A plug reporting itself ON re-arms a suppressed cutoff OFF ─────────────


# (row, the report that says the relay is ON again)
_REPORTS_ON = {
    "tasmota": (("plug-heater", "tasmota", "tasmota/heater"),
                ("tasmota/heater/stat/POWER", "ON")),
    "shelly": (("plug-heater", "shelly", "shellies/heater"), ("shellies/heater/relay/0", "on")),
    "shelly gen2": (("plug-heater", "shelly_gen2", "shellies/heater"),
                    ("shellies/heater/events/rpc", {
                        "src": "shellyplusplugs-a8032ab12345", "dst": "shellies/heater/events",
                        "method": "NotifyStatus",
                        "params": {"switch:0": {"id": 0, "output": True, "source": "button"}}})),
}


@pytest.mark.parametrize("transport", list(_REPORTS_ON))
async def test_a_plug_reporting_itself_on_re_arms_a_suppressed_cutoff_off(
        mock_mqtt, mock_mqtt_raw, transport):
    """A cutoff's repeat OFF is suppressed for 15 min, unless the plug says it
    was switched back on at the device: then the OFF goes out at once."""
    row, (topic, report) = _REPORTS_ON[transport]
    await insert_plug(*row)
    cutoff = make_rule(RuleAction(target="plug-heater", state="off"), name="Heating Cutoff")

    await _fire_rule(cutoff, {"temp_f": 80}, None)
    await _fire_rule(cutoff, {"temp_f": 80}, None)
    assert len(mock_mqtt_raw) == 1, "the repeat OFF is suppressed"

    await handle_plug_message(RecordingSio(), topic, report)
    await _fire_rule(cutoff, {"temp_f": 80}, None)
    assert len(mock_mqtt_raw) == 2
    assert _wire(mock_mqtt_raw)[0] == _wire(mock_mqtt_raw)[1], "the same OFF, again"


# ── Reports: Tasmota's JSON and plain-text shapes ──────────────────────────


@pytest.mark.parametrize("topic,payload,state", [
    ("tasmota/heat1/stat/POWER", "ON", "on"),
    # A command reply and the periodic status carry the relay as JSON
    # (POWER1 on multi-relay firmware): a plug whose SetOption kept
    # stat/POWER quiet reported its state nowhere else.
    ("tasmota/heat1/stat/RESULT", {"POWER": "ON"}, "on"),
    ("tasmota/heat1/stat/RESULT", {"POWER1": "OFF"}, "off"),
    ("tasmota/heat1/tele/STATE",
     {"Time": "2026-09-27T10:00:00", "Uptime": "0T01:00:00", "POWER": "ON"}, "on"),
])
async def test_a_tasmota_report_records_the_plugs_state(topic, payload, state):
    sio = RecordingSio()
    await handle_plug_message(sio, topic, payload)
    row = await plug_row("plug-heat1")
    assert (row["plug_type"], row["mqtt_topic_prefix"]) == ("tasmota", "tasmota/heat1")
    assert row["last_state"] == state
    assert sio.events == [("plug_state", {"plug_id": "plug-heat1", "state": state})]


@pytest.mark.parametrize("payload", [{"Dimmer": 40}, "not json"])
async def test_a_tasmota_reply_saying_nothing_about_the_relay_registers_nothing(payload):
    sio = RecordingSio()
    await handle_plug_message(sio, "tasmota/heat1/stat/RESULT", payload)
    assert await plug_row("plug-heat1") is None
    assert sio.events == []


async def test_a_tasmota_energy_report_records_a_registered_plugs_power():
    sensor = "tasmota/heat1/tele/SENSOR"
    await handle_plug_message(RecordingSio(), sensor, {"ENERGY": {"Power": 7}})
    assert await plug_row("plug-heat1") is None, "a power reading alone is not a plug"
    await handle_plug_message(RecordingSio(), "tasmota/heat1/stat/POWER", "ON")
    await handle_plug_message(RecordingSio(), sensor, {"ENERGY": {"Power": 7}})
    assert (await plug_row("plug-heat1"))["last_power_w"] == 7.0
    for unreadable in ({"ENERGY": {"Power": "lots"}}, {"ENERGY": 7}, "not json"):
        await handle_plug_message(RecordingSio(), sensor, unreadable)
    assert (await plug_row("plug-heat1"))["last_power_w"] == 7.0


# ── A second device, or a forged report, never re-points a live plug ───────


async def test_a_report_on_another_transport_leaves_a_live_plug_alone(mock_mqtt_raw, caplog):
    now = time.time()
    await insert_plug("plug-heater", "tasmota", "tasmota/heater",
                      status="online", last_state="on", last_seen=now - 30)
    sio = RecordingSio()
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        await handle_plug_message(sio, "shellies/heater/relay/0", "off")
    row = await plug_row("plug-heater")
    assert (row["plug_type"], row["mqtt_topic_prefix"], row["last_state"]) == (
        "tasmota", "tasmota/heater", "on")
    assert sio.events == []
    assert "was ignored" in caplog.text
    # The Pi's OFF still reaches the plug that is really there.
    assert await send_plug_command("plug-heater", "off") is True
    assert mock_mqtt_raw == [("tasmota/heater/cmnd/POWER", "OFF")]


async def test_the_conflict_is_logged_once_per_window(caplog):
    await insert_plug("plug-heater", "tasmota", "tasmota/heater",
                      status="online", last_seen=time.time())
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        for _ in range(5):
            await handle_plug_message(RecordingSio(), "shellies/heater/relay/0", "off")
    assert caplog.text.count("was ignored") == 1


@pytest.mark.parametrize("status,age", [("offline", 30), ("online", 700), ("unknown", None)])
async def test_a_quiet_plug_follows_its_new_transport(status, age, caplog):
    """A Gen1 swapped for a Gen2 (or a Tasmota for a Shelly) under the same
    name heals as soon as the old device is gone: offline, silent for over
    ten minutes, or registered by hand and never seen."""
    last_seen = None if age is None else time.time() - age
    await insert_plug("plug-heater", "tasmota", "tasmota/heater", status=status,
                      last_seen=last_seen)
    sio = RecordingSio()
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        await handle_plug_message(sio, "shellies/heater/relay/0", "on")
    row = await plug_row("plug-heater")
    assert (row["plug_type"], row["mqtt_topic_prefix"], row["status"], row["last_state"]) == (
        "shelly", "shellies/heater", "online", "on")
    assert sio.events == [("plug_state", {"plug_id": "plug-heater", "state": "on"})]
    assert "now reports as shelly" in caplog.text


async def test_a_power_report_for_another_transport_is_not_recorded():
    await insert_plug("plug-heater", "tasmota", "tasmota/heater", status="online",
                      last_seen=time.time())
    await handle_plug_message(RecordingSio(), "shellies/heater/relay/0/power", "1500")
    assert (await plug_row("plug-heater"))["last_power_w"] is None


# ── A report that changes nothing is not written each time ─────────────────


async def test_unchanged_reports_do_not_write_until_last_seen_is_due():
    t0 = 1_800_000_000.0
    with _at(t0):
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0", "off")
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0/power", "0.00")
    assert (await plug_row("plug-h1"))["last_seen"] == t0
    with _at(t0 + 30):  # Gen1 republishes both every 30 s
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0", "off")
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0/power", "0.00")
    assert (await plug_row("plug-h1"))["last_seen"] == t0  # nothing written
    with _at(t0 + 60):  # a change is written at once
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0", "on")
    row = await plug_row("plug-h1")
    assert (row["last_state"], row["last_seen"]) == ("on", t0 + 60)
    with _at(t0 + 90):
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0/power", "41.5")
    row = await plug_row("plug-h1")
    assert (row["last_power_w"], row["last_seen"]) == (41.5, t0 + 90)
    with _at(t0 + 90 + smart_plugs._LAST_SEEN_REFRESH_SECONDS):  # refresh is due
        await handle_plug_message(RecordingSio(), "shellies/h1/relay/0", "on")
    assert (await plug_row("plug-h1"))["last_seen"] == t0 + 90 + smart_plugs._LAST_SEEN_REFRESH_SECONDS


async def test_an_unchanged_report_from_an_offline_plug_brings_it_online():
    await insert_plug("plug-h1", "shelly", "shellies/h1", status="offline", last_state="off",
                      last_seen=time.time())
    await handle_plug_message(RecordingSio(), "shellies/h1/relay/0", "off")
    assert (await plug_row("plug-h1"))["status"] == "online"
