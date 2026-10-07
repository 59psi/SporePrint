"""Pi→ESP32 command-signing enforcement (mqtt.py).

Closes the archaeology's top finding: an unset mqtt_hmac_key used to make the
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
import re

import pytest

from app import mqtt
from app.config import settings


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

def test_status_active_when_key_set(monkeypatch):
    _set(monkeypatch, key="deadbeef")
    assert mqtt.command_signing_status()["mode"] == "active"


def test_status_auto_enforces_when_cloud_configured(monkeypatch):
    _set(monkeypatch, key="", policy="auto", cloud_url="https://sporeprint.ai")
    s = mqtt.command_signing_status()
    assert s["mode"] == "enforced_blocking"
    assert s["cloud_configured"] is True


def test_status_auto_permissive_on_pure_lan(monkeypatch):
    _set(monkeypatch, key="", policy="auto", cloud_url="")
    assert mqtt.command_signing_status()["mode"] == "permissive_unsigned"


def test_status_always_enforces_regardless_of_cloud(monkeypatch):
    _set(monkeypatch, key="", policy="always", cloud_url="")
    assert mqtt.command_signing_status()["mode"] == "enforced_blocking"


def test_status_never_permissive_even_when_cloud_configured(monkeypatch):
    _set(monkeypatch, key="", policy="never", cloud_url="https://sporeprint.ai")
    assert mqtt.command_signing_status()["mode"] == "permissive_unsigned"


# ── mqtt_publish enforcement ────────────────────────────────────────────

async def test_signed_when_key_set(monkeypatch, fake_client):
    _set(monkeypatch, key="deadbeef")
    ok = await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    assert ok is True
    topic, body = fake_client.published[0]
    assert "signature" in body and "ts" in body


async def test_refused_when_unset_and_enforced(monkeypatch, fake_client):
    _set(monkeypatch, key="", policy="always")
    ok = await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    assert ok is False
    assert fake_client.published == []          # nothing shipped
    assert mqtt._signing_block_logged is True    # CRITICAL logged once


async def test_auto_refused_when_cloud_configured(monkeypatch, fake_client):
    _set(monkeypatch, key="", policy="auto", cloud_url="https://sporeprint.ai")
    ok = await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    assert ok is False and fake_client.published == []


async def test_ships_unsigned_when_unset_and_permissive(monkeypatch, fake_client):
    _set(monkeypatch, key="", policy="never")
    ok = await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    assert ok is True
    topic, body = fake_client.published[0]
    assert "signature" not in body and "ts" in body   # unsigned, but stamped
    assert mqtt._unsigned_ship_logged is True          # WARNING logged once


async def test_non_cmd_topic_never_blocked(monkeypatch, fake_client):
    # state/* + telemetry/* flow node→Pi; they are never signed nor blocked,
    # even under the strictest policy with no key.
    _set(monkeypatch, key="", policy="always", cloud_url="https://sporeprint.ai")
    ok = await mqtt.mqtt_publish("sporeprint/climate-01/state", {"temp_f": 72})
    assert ok is True
    topic, body = fake_client.published[0]
    assert "signature" not in body


# ── destination binding + per-frame nonce (fw-node#11) ──────────────────
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


async def test_unsigned_frames_carry_no_binding_members(monkeypatch, fake_client):
    # Trusted-LAN (no key) frames keep their pre-binding shape.
    _set(monkeypatch, key="", policy="never")
    await mqtt.mqtt_publish(CMD_TOPIC, {"state": "on"})
    _, body = fake_client.published[0]
    assert "topic" not in body and "nonce" not in body


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


# ── health surfacing ────────────────────────────────────────────────────

async def test_health_detail_mqtt_surfaces_signing(monkeypatch):
    from app.health.router import mqtt_health
    _set(monkeypatch, key="", policy="auto", cloud_url="https://sporeprint.ai")
    body = await mqtt_health()
    assert body["command_signing"]["mode"] == "enforced_blocking"
    assert body["command_signing"]["policy"] == "auto"
