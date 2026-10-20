"""Pi→ESP32 command-signing enforcement (mqtt.py).

An unset mqtt_hmac_key used to make the
Pi ship cmd/* frames UNSIGNED, silently, with no way to enforce or observe it.
Now signing is:
  * signed when the key is set (unchanged),
  * refused (fail-closed) when unset + enforced,
  * shipped-unsigned-but-loud when unset + not enforced,
with "auto" enforcement keyed off whether the Pi is cloud-configured.
"""

import hashlib
import hmac
import json
import logging
import re

import pytest

from app import mqtt
from app.config import settings
from app.health.router import mqtt_health


class _FakeClient:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def publish(self, topic, payload):
        self.published.append((topic, json.loads(payload)))


@pytest.fixture()
def fake_client(monkeypatch):
    c = _FakeClient()
    monkeypatch.setattr(mqtt, "_client", c)
    # Reset the warn-once guards so each test observes its own logging state.
    monkeypatch.setattr(mqtt, "_signing_block_logged", False)
    monkeypatch.setattr(mqtt, "_unsigned_ship_logged", False)
    return c


def _set(monkeypatch, *, key="", policy="auto", cloud_url=""):
    monkeypatch.setattr(settings, "mqtt_hmac_key", key)
    monkeypatch.setattr(settings, "mqtt_require_signing", policy)
    monkeypatch.setattr(settings, "cloud_url", cloud_url)


CMD_TOPIC = "sporeprint/climate-01/cmd/aux"


# ── command_signing_status() ────────────────────────────────────────────

@pytest.mark.parametrize("key,policy,cloud_url,mode", [
    ("deadbeef", "auto", "", "active"),
    ("", "auto", "https://sporeprint.ai", "enforced_blocking"),
    ("", "auto", "", "permissive_unsigned"),
    ("", "always", "", "enforced_blocking"),
    ("", "never", "https://sporeprint.ai", "permissive_unsigned"),
], ids=["key-set", "auto-cloud-paired", "auto-lan-only", "always", "never"])
def test_signing_posture(monkeypatch, key, policy, cloud_url, mode):
    # "auto" enforces on a cloud-configured Pi, from config, not the live
    # connection: a cloud outage must not downgrade signing.
    _set(monkeypatch, key=key, policy=policy, cloud_url=cloud_url)
    status = mqtt.command_signing_status()
    assert status["mode"] == mode
    assert status["cloud_configured"] is bool(cloud_url)


# ── mqtt_publish enforcement ────────────────────────────────────────────

@pytest.mark.parametrize("policy,cloud_url", [("always", ""), ("auto", "https://sporeprint.ai")])
async def test_an_unsigned_command_is_refused_when_signing_is_enforced(
        monkeypatch, fake_client, caplog, policy, cloud_url):
    _set(monkeypatch, key="", policy=policy, cloud_url=cloud_url)
    with caplog.at_level(logging.WARNING, logger="app.mqtt"):
        for _ in range(2):
            assert await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"}) is False
    assert fake_client.published == []          # nothing shipped
    # Loud, once: a command every few seconds must not flood the log.
    assert [r.levelno for r in caplog.records] == [logging.CRITICAL]


async def test_trusted_lan_mode_ships_stamped_unsigned_unbound_frames(
        monkeypatch, fake_client, caplog):
    # Trusted-LAN (no key, not enforced) frames keep their pre-binding shape.
    _set(monkeypatch, key="", policy="never")
    with caplog.at_level(logging.WARNING, logger="app.mqtt"):
        for _ in range(2):
            assert await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"}) is True
    _, body = fake_client.published[0]
    assert set(body) == {"state", "ts"}            # stamped; no signature, topic or nonce
    assert [r.levelno for r in caplog.records] == [logging.WARNING]  # warned once


async def test_non_cmd_topic_never_blocked(monkeypatch, fake_client):
    # state/* + telemetry/* flow node→Pi; they are never signed nor blocked,
    # even under the strictest policy with no key.
    _set(monkeypatch, key="", policy="always", cloud_url="https://sporeprint.ai")
    ok = await mqtt.mqtt_publish("sporeprint/climate-01/state", {"temp_f": 72})
    assert ok is True
    topic, body = fake_client.published[0]
    assert "signature" not in body


# ── destination binding + per-frame nonce ───────────────────────────────
#
# Firmware verifies HMAC over canonical(frame minus "signature"), covering every
# member, so extra members are backward compatible with deployed nodes. Current
# firmware additionally rejects a frame whose signed "topic" differs from the
# arrival topic, and remembers accepted (topic, MAC) pairs to reject replays.

def _expected_sig(key: str, body: dict) -> str:
    canonical = json.dumps(
        {k: v for k, v in body.items() if k != "signature"},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    return hmac.new(key.encode(), canonical, hashlib.sha256).hexdigest()


async def test_signed_cmd_binds_the_topic_and_a_nonce(monkeypatch, fake_client):
    _set(monkeypatch, key="deadbeef")
    assert await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on", "pwm": 200}) is True
    topic, body = fake_client.published[0]
    assert topic == CMD_TOPIC
    assert body["topic"] == CMD_TOPIC
    assert re.fullmatch(r"[0-9a-f]{16}", body["nonce"])
    assert body["state"] == "on" and body["pwm"] == 200
    assert isinstance(body["ts"], int)  # the firmware's replay window reads it
    # Both members are inside the MAC, exactly as the firmware recomputes it.
    assert body["signature"] == _expected_sig("deadbeef", body)


async def test_identical_same_second_commands_are_distinct_frames(monkeypatch, fake_client):
    # on/off/on inside one second: without a nonce the third frame is
    # byte-identical to the first and the node's replay guard drops it.
    _set(monkeypatch, key="deadbeef")
    monkeypatch.setattr(mqtt.time, "time", lambda: 1_790_000_000.25)
    await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    (_, first), (_, second) = fake_client.published
    assert first["ts"] == second["ts"]
    assert first["nonce"] != second["nonce"]
    assert first["signature"] != second["signature"]


async def test_payload_cannot_choose_the_bound_topic(monkeypatch, fake_client):
    # A relayed payload smuggling its own "topic"/"nonce" never wins: the
    # signed destination is always the topic the frame is published on.
    _set(monkeypatch, key="deadbeef")
    await mqtt.mqtt_publish(
        CMD_TOPIC,
        {"state": "on", "topic": "sporeprint/relay-02/cmd/heater", "nonce": "x"},
    )
    _, body = fake_client.published[0]
    assert body["topic"] == CMD_TOPIC
    assert body["nonce"] != "x"
    assert body["signature"] == _expected_sig("deadbeef", body)


async def test_binding_is_dropped_rather_than_overflow_the_node_buffer(monkeypatch, fake_client):
    # The node's MqttLink drops any frame >= 1024 bytes. A payload that only
    # fits without the two extra members still goes out, signed but unbound.
    _set(monkeypatch, key="deadbeef")
    topic = "sporeprint/relay-01/cmd/config"
    # Fits unbound (~1000 B on the wire), not with topic + nonce (~1070 B).
    await mqtt.mqtt_publish(topic, {"server_url": "x" * 880})
    _, body = fake_client.published[0]
    assert len(json.dumps(body).encode()) < 1024
    assert "topic" not in body and "nonce" not in body
    assert body["signature"] == _expected_sig("deadbeef", body)
    bound = {**body, "topic": topic, "nonce": "0" * 16}
    assert len(json.dumps(bound).encode()) >= 1024

    # A normal-sized config frame is still bound.
    await mqtt.mqtt_publish(topic, {"server_url": "x" * 100})
    _, small = fake_client.published[1]
    assert small["topic"] == topic


@pytest.mark.parametrize("key,policy", [("deadbeef", "auto"), ("", "never")])
async def test_frame_the_node_would_drop_is_reported_unsent(monkeypatch, fake_client,
                                                            key, policy):
    # Too large even unbound: the node would drop it unread (>= 1024 bytes,
    # firmware mqtt_link.h kInboundCap). It used to go out anyway and report
    # "sent" while the command never ran; now it is refused here, which
    # send_command answers with a 503.
    _set(monkeypatch, key=key, policy=policy)
    ok = await mqtt.mqtt_publish("sporeprint/relay-01/cmd/config",
                                 {"server_url": "x" * 1100})
    assert ok is False
    assert fake_client.published == []
    # Just under the cap still goes out.
    assert await mqtt.mqtt_publish("sporeprint/relay-01/cmd/config",
                                   {"server_url": "x" * 800}) is True
    assert len(json.dumps(fake_client.published[0][1]).encode()) < \
        mqtt._NODE_INBOUND_FRAME_CAP


# ── health surfacing ────────────────────────────────────────────────────

async def test_health_detail_mqtt_surfaces_signing(monkeypatch):
    _set(monkeypatch, key="", policy="auto", cloud_url="https://sporeprint.ai")
    body = await mqtt_health()
    assert body["command_signing"]["mode"] == "enforced_blocking"
    assert body["command_signing"]["policy"] == "auto"
