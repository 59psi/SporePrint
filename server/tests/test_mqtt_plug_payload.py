"""Shelly / Tasmota plug state reports are plain text, not JSON.

Stock Shelly Gen1 firmware publishes `shellies/<id>/relay/0` as a bare
`on`/`off`, and Tasmota publishes `tasmota/<id>/stat/POWER` as a bare
`ON`/`OFF`. The MQTT loop used to `json.loads` every frame and drop anything
that failed to parse, so these reports never reached handle_plug_message. No
smart_plugs row was ever created, and every plug rule failed with
"no plug paired". These tests drive the real start_mqtt loop with raw bytes.
"""

import asyncio

import pytest

import app.mqtt
from app.automation.smart_plugs import send_plug_command
from app.mqtt import _decode_payload, start_mqtt
from tests._pi_a_engine import FakeSio, MqttMessage, fake_mqtt_client, plug_row, rows


async def _run_loop(monkeypatch, messages) -> FakeSio:
    monkeypatch.setattr(app.mqtt.aiomqtt, "Client", fake_mqtt_client(messages, []))
    sio = FakeSio()
    await asyncio.wait_for(start_mqtt(sio), timeout=5)
    return sio


@pytest.mark.parametrize("topic,raw,expected", [
    # Vendor topics fall back to text.
    ("tasmota/hum/stat/POWER", b"ON", "ON"),
    ("tasmota/hum/stat/POWER", b"OFF\n", "OFF"),
    ("shellies/hum/relay/0", b"on", "on"),
    ("shellies/hum/relay/0", b"off", "off"),
    ("shellies/hum/relay/0/power", b"12.5", 12.5),
    ("tasmota/hum/tele/SENSOR", b'{"ENERGY":{"Power":7}}', {"ENERGY": {"Power": 7}}),
    ("tasmota/hum/tele/LWT", b"Online", "Online"),
    # Shelly Gen2+: JSON true/false and JSON-RPC objects.
    ("shellies/humidifier/online", b"true", True),
    ("shellies/humidifier/online", b"false", False),
    ("shellies/humidifier/events/rpc", b'{"method":"NotifyStatus","params":{}}',
     {"method": "NotifyStatus", "params": {}}),
    ("shellies/humidifier/status/switch:0", b'{"id":0,"output":true}', {"id": 0, "output": True}),
    # Bytes that are not text, and an empty payload (a retained message being
    # cleared), are no plug state.
    ("tasmota/hum/stat/POWER", b"\xff\xfe", None),
    ("tasmota/hum/stat/POWER", b"", None),
    ("tasmota/hum/stat/POWER", b"   ", None),
    ("shellies/hum/relay/0", b" \r\n", None),
    # sporeprint/* frames stay JSON-object-only: bare text is dropped.
    ("sporeprint/climate-01/telemetry", b"ON", None),
    ("sporeprint/climate-01/telemetry", b"\xff\xfe", None),
    ("sporeprint/climate-01/telemetry", b"42", None),
    ("sporeprint/climate-01/status", b'{"status":"online"}', {"status": "online"}),
])
def test_a_payload_is_decoded_the_way_its_topic_speaks(topic, raw, expected):
    assert _decode_payload(topic, raw) == expected


# ── end to end through the real message loop ─────────────────────


async def test_tasmota_plain_text_power_report_registers_plug(monkeypatch, mock_mqtt_raw):
    await _run_loop(monkeypatch, [MqttMessage("tasmota/hum/stat/POWER", b"ON")])

    row = await plug_row("plug-hum")
    assert row is not None, "plain-text Tasmota state report was dropped"
    assert (row["plug_type"], row["mqtt_topic_prefix"], row["last_state"]) == (
        "tasmota", "tasmota/hum", "on")

    # The now-registered plug is commandable. (start_mqtt clears _client on
    # exit, so re-install the raw-capturing fake.)
    class _Raw:
        async def publish(self, topic, payload):
            mock_mqtt_raw.append((topic, payload))

    monkeypatch.setattr(app.mqtt, "_client", _Raw())
    assert await send_plug_command("plug-hum", "off") is True
    assert mock_mqtt_raw == [("tasmota/hum/cmnd/POWER", "OFF")]


async def test_shelly_plain_text_relay_report_registers_plug(monkeypatch):
    sio = await _run_loop(monkeypatch, [MqttMessage("shellies/dehum/relay/0", b"off")])

    row = await plug_row("plug-dehum")
    assert row is not None, "plain-text Shelly state report was dropped"
    assert (row["plug_type"], row["last_state"]) == ("shelly", "off")
    assert ("plug_state", {"plug_id": "plug-dehum", "state": "off"}) in sio.events


async def test_cleared_retained_message_registers_nothing(monkeypatch):
    await _run_loop(monkeypatch, [
        MqttMessage("tasmota/hum/stat/POWER", b""),
        MqttMessage("shellies/dehum/relay/0", b""),
    ])
    assert await rows("SELECT plug_id FROM smart_plugs") == []


async def test_vendor_topics_never_enter_sporeprint_branches(monkeypatch):
    """A Shelly Gen2 status topic under shellies/ is not a SporePrint node's
    status report, while a sporeprint/* JSON status still is."""
    await _run_loop(monkeypatch, [
        MqttMessage("shellies/plus1/status/switch:0", b'{"output":true}'),
        MqttMessage("sporeprint/node-z/status", b'{"status":"online"}'),
    ])
    assert await rows("SELECT node_id, status FROM hardware_nodes") == [
        {"node_id": "node-z", "status": "online"}]
