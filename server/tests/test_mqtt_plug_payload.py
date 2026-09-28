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
from app.db import get_db
from app.mqtt import _decode_payload, start_mqtt


class _FakeMessage:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def _fake_client_factory(messages: list[_FakeMessage]):
    """An aiomqtt.Client stand-in that yields `messages`, then cancels the loop."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def subscribe(self, topic):
            return None

        async def publish(self, topic, payload):
            return None

        @property
        def messages(self):
            async def _gen():
                for m in messages:
                    yield m
                # start_mqtt returns cleanly on CancelledError.
                raise asyncio.CancelledError

            return _gen()

    return _FakeClient


async def _run_loop(monkeypatch, messages):
    monkeypatch.setattr(app.mqtt.aiomqtt, "Client", _fake_client_factory(messages))
    sio = _RecordingSio()
    await asyncio.wait_for(start_mqtt(sio), timeout=5)
    return sio


class _RecordingSio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))


def _raw_client(calls):
    class _C:
        async def publish(self, topic, payload):
            calls.append((topic, payload))

    return _C()


async def _plug_row(plug_id: str):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM smart_plugs WHERE plug_id = ?", (plug_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# ── pure decode helper ────────────────────────────────────────────


@pytest.mark.parametrize(
    "topic,raw,expected",
    [
        ("tasmota/hum/stat/POWER", b"ON", "ON"),
        ("tasmota/hum/stat/POWER", b"OFF\n", "OFF"),
        ("shellies/hum/relay/0", b"on", "on"),
        ("shellies/hum/relay/0", b"off", "off"),
        ("shellies/hum/relay/0/power", b"12.5", 12.5),
        ("tasmota/hum/tele/SENSOR", b'{"ENERGY":{"Power":7}}', {"ENERGY": {"Power": 7}}),
        ("tasmota/hum/tele/LWT", b"Online", "Online"),
    ],
)
def test_decode_vendor_payload_falls_back_to_text(topic, raw, expected):
    assert _decode_payload(topic, raw) == expected


def test_decode_sporeprint_payload_is_json_only():
    # sporeprint/* frames stay JSON-object-only: bare text is dropped.
    assert _decode_payload("sporeprint/climate-01/telemetry", b"ON") is None
    assert _decode_payload("sporeprint/climate-01/telemetry", b"\xff\xfe") is None
    assert _decode_payload("sporeprint/climate-01/telemetry", b"42") is None
    assert _decode_payload("sporeprint/climate-01/status", b'{"status":"online"}') == {
        "status": "online"
    }


def test_decode_undecodable_bytes_dropped_for_vendor_topics():
    assert _decode_payload("tasmota/hum/stat/POWER", b"\xff\xfe") is None


@pytest.mark.parametrize("raw", [b"", b"   ", b" \r\n"])
def test_decode_empty_vendor_payload_dropped(raw):
    # A retained message being cleared is an empty payload: not a plug state.
    assert _decode_payload("tasmota/hum/stat/POWER", raw) is None
    assert _decode_payload("shellies/hum/relay/0", raw) is None


# ── end to end through the real message loop ─────────────────────


async def test_tasmota_plain_text_power_report_registers_plug(monkeypatch, mock_mqtt_raw):
    await _run_loop(monkeypatch, [_FakeMessage("tasmota/hum/stat/POWER", b"ON")])

    row = await _plug_row("plug-hum")
    assert row is not None, "plain-text Tasmota state report was dropped"
    assert row["plug_type"] == "tasmota"
    assert row["mqtt_topic_prefix"] == "tasmota/hum"
    assert row["last_state"] == "on"

    # The now-registered plug is commandable. (start_mqtt clears _client on
    # exit, so re-install the raw-capturing fake.)
    monkeypatch.setattr(app.mqtt, "_client", _raw_client(mock_mqtt_raw))
    assert await send_plug_command("plug-hum", "off") is True
    assert ("tasmota/hum/cmnd/POWER", "OFF") in mock_mqtt_raw


async def test_shelly_plain_text_relay_report_registers_plug(monkeypatch):
    sio = await _run_loop(monkeypatch, [_FakeMessage("shellies/dehum/relay/0", b"off")])

    row = await _plug_row("plug-dehum")
    assert row is not None, "plain-text Shelly state report was dropped"
    assert row["plug_type"] == "shelly"
    assert row["last_state"] == "off"
    assert ("plug_state", {"plug_id": "plug-dehum", "state": "off"}) in sio.events


async def test_cleared_retained_message_registers_nothing(monkeypatch):
    await _run_loop(monkeypatch, [
        _FakeMessage("tasmota/hum/stat/POWER", b""),
        _FakeMessage("shellies/dehum/relay/0", b""),
    ])
    assert await _plug_row("plug-hum") is None
    assert await _plug_row("plug-dehum") is None


async def test_vendor_topics_never_enter_sporeprint_branches(monkeypatch):
    # A Shelly Gen2 status topic under the shellies/ prefix must not be
    # misread as a SporePrint node status report.
    await _run_loop(
        monkeypatch,
        [_FakeMessage("shellies/plus1/status/switch:0", b'{"output":true}')],
    )
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS n FROM hardware_nodes WHERE node_id = 'plus1'")
        assert (await cursor.fetchone())["n"] == 0


async def test_sporeprint_json_still_routed(monkeypatch):
    await _run_loop(
        monkeypatch,
        [_FakeMessage("sporeprint/node-z/status", b'{"status":"online"}')],
    )
    async with get_db() as db:
        cursor = await db.execute("SELECT status FROM hardware_nodes WHERE node_id = 'node-z'")
        row = await cursor.fetchone()
    assert row is not None and row["status"] == "online"
