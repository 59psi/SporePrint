"""The MQTT supervisor loop (start_mqtt) and the publish primitive.

The loop is the Pi's only ingest: everything one frame does stays inside it,
a broker drop reconnects, and an unexpected error restarts the session. A
frame that escaped it ended the session (and its subscriptions), and a
retained frame that raised again on every redelivery kept ingest down for
good. Frames are driven through the real loop by tests/_pi_b1_mqtt.FakeBroker.
"""

import time

import aiomqtt
import pytest

import app.health.service
import app.mqtt
from app.config import settings
from app.mqtt import mqtt_publish
from tests._builders import node_row, register_node
from tests._fakes import FakeBroker, Message, run_mqtt_loop


async def test_the_loop_logs_in_with_the_configured_broker_account(monkeypatch):
    # The broker refuses anonymous clients (config/mosquitto/mosquitto.conf).
    monkeypatch.setattr(settings, "mqtt_username", "server")
    monkeypatch.setattr(settings, "mqtt_password", "s3cret")
    broker = FakeBroker([])
    await run_mqtt_loop(monkeypatch, broker)
    assert broker.connects == [{"username": "server", "password": "s3cret"}]


async def test_a_frame_that_breaks_its_handler_does_not_end_the_session(monkeypatch):
    """A poison retained frame (JSON Python cannot build) and a frame whose
    handler raises are each dropped; the frame after them is handled in the
    same session, with no supervisor restart."""
    real_handler = app.mqtt._handle_message

    async def _handler(sio, topic, payload, **kwargs):
        if topic == "sporeprint/node-x/telemetry":
            raise RuntimeError("synthetic handler failure")
        await real_handler(sio, topic, payload, **kwargs)

    monkeypatch.setattr(app.mqtt, "_handle_message", _handler)
    restarts = app.mqtt._mqtt_restart_count
    broker = FakeBroker([
        Message("tasmota/x/stat/POWER", b"[" * 20_000, retain=True),
        Message("sporeprint/node-x/telemetry", b'{"temp_f": 70}'),
        Message("sporeprint/node-b2/status", b'{"status": "online"}'),
    ])
    await run_mqtt_loop(monkeypatch, broker)
    assert len(broker.connects) == 1
    assert app.mqtt._mqtt_restart_count == restarts
    assert (await node_row("node-b2"))["status"] == "online"


async def test_the_retained_flag_reaches_the_status_handler(monkeypatch):
    """A retained 'online' is the broker replaying a stored frame on
    (re)subscribe, not the node talking: last_seen keeps its value."""
    stale = time.time() - 3 * 86400
    await register_node("node-c3", "climate", status="online", last_seen=stale)
    await run_mqtt_loop(monkeypatch, FakeBroker([
        Message("sporeprint/node-c3/status", b'{"status": "online"}', retain=True),
    ]))
    assert (await node_row("node-c3"))["last_seen"] == stale


async def test_the_supervisor_keeps_ingest_alive_through_failures(monkeypatch):
    """Boot housekeeping that fails, a broker that drops the connection and
    an unexpected session error each cost a pause, never the ingest."""
    async def _purge_fails():
        raise OSError("database is locked")

    states = []
    monkeypatch.setattr(app.mqtt, "purge_reserved_nodes", _purge_fails)
    monkeypatch.setattr(app.health.service, "update_task",
                        lambda name, status, error=None: states.append((name, status)))
    restarts = app.mqtt._mqtt_restart_count
    broker = FakeBroker(
        aiomqtt.MqttError("connection refused"),
        RuntimeError("unexpected"),
        [Message("sporeprint/node-r1/status", b'{"status": "online"}')],
    )

    pauses = await run_mqtt_loop(monkeypatch, broker)

    assert pauses == [5, 5]
    assert len(broker.connects) == 3
    assert app.mqtt._mqtt_restart_count == restarts + 1  # the broker drop is not a restart
    assert [s for _, s in states] == [
        "connecting", "disconnected", "connecting", "error", "connecting", "running", "stopped"]
    assert (await node_row("node-r1"))["status"] == "online"
    assert app.mqtt._client is None


@pytest.mark.parametrize("broker_state", ["not connected", "publish raises"])
async def test_a_frame_the_broker_did_not_take_is_reported_unsent(monkeypatch, broker_state):
    # Callers act on the bool: a rule firing is recorded 'failed', a command
    # route answers 503.
    class _Failing:
        async def publish(self, topic, payload):
            raise aiomqtt.MqttError("not connected")

    client = None if broker_state == "not connected" else _Failing()
    monkeypatch.setattr(app.mqtt, "_client", client)
    assert await mqtt_publish("sporeprint/relay-01/state", {"fae": "on"}) is False
