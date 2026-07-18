"""Frame-level tests for the cloud → Pi remote-command security gate.

``handle_cloud_command(sio, data)`` is the whole premium-gated remote-actuation
boundary: HMAC verify → premium tier → replay dedup → target_kind resolution →
injection guards → registered-target check → MQTT publish to the RESOLVED node.
It was a nested closure inside ``start_cloud_connector`` (untestable); extracting
it to a module-level handler lets us drive real signed frames through the whole
gate and assert on the emitted ``command_result`` and the published MQTT topic.

Canonical-ID masking is avoided: the relay node registers under a MAC-derived id
(``node-relay-7a3f1c``) DISTINCT from the ``relay-01`` placeholder and from the
``relay`` target_kind, so a publish to the wrong id would fail the topic assert.
"""

import hashlib
import hmac
import json
import time

import pytest

import app.cloud.service as service
from app.cloud.service import handle_cloud_command
from app.db import get_db


_KEY = "unit-test-cloud-token"

# Real relay node id — MAC-derived, NOT the seeded relay-01 placeholder and NOT
# the "relay" target_kind. A publish to either of those would be a routing bug.
RELAY_NODE = "node-relay-7a3f1c"


def _sign(frame: dict, key: str = _KEY) -> dict:
    """Mirror the cloud-side sign_frame exactly (matches cloud/signing verify)."""
    filtered = {k: v for k, v in frame.items() if k != "signature"}
    body = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {**frame, "signature": sig}


def _cmd(cmd_id: str, *, tier: str = "premium", target_kind: str = "relay",
         channel: str | None = "fae", payload: dict | None = None,
         ts: float | None = None) -> dict:
    frame = {
        "id": cmd_id,
        "tier": tier,
        "target_kind": target_kind,
        "channel": channel,
        "payload": payload if payload is not None else {"state": "on"},
        "ts": ts if ts is not None else time.time(),
    }
    return frame


class _FakeSio:
    def __init__(self) -> None:
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))

    def last_result(self) -> dict:
        assert self.emits, "handler emitted nothing"
        event, data = self.emits[-1]
        assert event == "command_result", event
        return data


@pytest.fixture(autouse=True)
def _cloud_env(monkeypatch):
    """Pin the signing key and start each test with an empty replay cache."""
    monkeypatch.setattr(service.settings, "cloud_token", _KEY)
    service._seen_command_ids.clear()
    yield
    service._seen_command_ids.clear()


async def _register_relay_node(node_id: str = RELAY_NODE) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, "relay", json.dumps(["fae", "exhaust"]), 1_752_700_000.0),
        )
        await db.commit()


# ── happy path: signed premium frame publishes to the RESOLVED node ────────

async def test_valid_premium_frame_publishes_to_resolved_node(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()

    await handle_cloud_command(sio, _sign(_cmd("cmd-ok", channel="fae")))

    # Published to the MAC-derived node the "relay" kind resolves to — not the
    # target_kind, not the relay-01 placeholder.
    topics = [t for t, _ in mock_mqtt]
    assert topics == [f"sporeprint/{RELAY_NODE}/cmd/fae"], topics
    assert RELAY_NODE not in ("relay", "relay-01")

    result = sio.last_result()
    assert result["success"] is True, result
    assert result["target"] == RELAY_NODE
    assert result["target_kind"] == "relay"
    assert result["channel"] == "fae"


async def test_publish_payload_is_forwarded_verbatim(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    await handle_cloud_command(
        sio, _sign(_cmd("cmd-payload", payload={"state": "on", "duration_sec": 90})))
    (_topic, published_payload) = mock_mqtt[0]
    assert published_payload == {"state": "on", "duration_sec": 90}


# ── premium gate ───────────────────────────────────────────────────────────

async def test_free_tier_is_rejected_and_never_publishes(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()

    await handle_cloud_command(sio, _sign(_cmd("cmd-free", tier="free")))

    assert mock_mqtt == [], "free-tier command must never reach MQTT"
    result = sio.last_result()
    assert result["success"] is False
    assert result["error"] == "Remote control requires premium tier"


async def test_missing_tier_defaults_to_free_and_is_rejected(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    frame = _cmd("cmd-notier")
    del frame["tier"]
    await handle_cloud_command(sio, _sign(frame))
    assert mock_mqtt == []
    assert sio.last_result()["error"] == "Remote control requires premium tier"


# ── replay dedup + FIFO eviction ───────────────────────────────────────────

async def test_replayed_command_id_is_rejected(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    frame = _sign(_cmd("cmd-dup"))

    await handle_cloud_command(sio, frame)      # first: executes
    await handle_cloud_command(sio, frame)      # second: same id → replay

    assert len(mock_mqtt) == 1, "replayed frame must not publish a second time"
    assert sio.emits[0][1]["success"] is True
    assert sio.emits[1][1]["success"] is False
    assert sio.emits[1][1]["error"] == "Replayed command id"


async def test_fifo_eviction_evicts_oldest_inserted_id(mock_mqtt, monkeypatch):
    """Past the cache cap the OLDEST-inserted id is evicted (FIFO), so it is no
    longer treated as a replay — while a still-cached recent id is."""
    await _register_relay_node()
    monkeypatch.setattr(service, "_COMMAND_ID_CACHE_CAP", 3)
    sio = _FakeSio()

    # Fill past cap: inserting cmd-3 evicts the oldest (cmd-0).
    for i in range(4):
        await handle_cloud_command(sio, _sign(_cmd(f"cmd-{i}")))
    assert "cmd-0" not in service._seen_command_ids
    assert "cmd-2" in service._seen_command_ids

    published_before = len(mock_mqtt)

    # cmd-0 was evicted → re-send is NOT a replay → it executes again.
    sio_a = _FakeSio()
    await handle_cloud_command(sio_a, _sign(_cmd("cmd-0")))
    assert sio_a.last_result()["success"] is True, sio_a.last_result()
    assert len(mock_mqtt) == published_before + 1

    # cmd-2 is still cached → re-send IS a replay.
    sio_b = _FakeSio()
    await handle_cloud_command(sio_b, _sign(_cmd("cmd-2")))
    assert sio_b.last_result()["error"] == "Replayed command id"


# ── injection guards + unregistered / unresolved target ────────────────────

async def test_bad_channel_is_rejected_before_publish(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    # ';' is outside the safe-id charset — no topic injection allowed.
    await handle_cloud_command(sio, _sign(_cmd("cmd-badchan", channel="fae;rm")))
    assert mock_mqtt == []
    assert "Invalid target_kind or channel" in sio.last_result()["error"]


async def test_unknown_target_kind_is_rejected(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    await handle_cloud_command(sio, _sign(_cmd("cmd-badkind", target_kind="furnace")))
    assert mock_mqtt == []
    assert "Invalid target_kind or channel" in sio.last_result()["error"]


async def test_unresolved_target_kind_is_rejected_when_no_node_registered(mock_mqtt):
    # No relay node registered → the "relay" kind resolves to nothing.
    sio = _FakeSio()
    await handle_cloud_command(sio, _sign(_cmd("cmd-noresolve")))
    assert mock_mqtt == []
    result = sio.last_result()
    assert result["success"] is False
    assert result["error"] == "No registered relay node"


# ── verify_frame reject-reason categorisation ──────────────────────────────

async def test_unsigned_frame_rejected_as_signature_category(mock_mqtt):
    # A frame with no signature at all fails as "missing signature" → the
    # signature_mismatch category (a compromised/broken relay, not a clock).
    await _register_relay_node()
    sio = _FakeSio()
    frame = _cmd("cmd-unsigned")          # never signed
    await handle_cloud_command(sio, frame)
    assert mock_mqtt == []
    result = sio.last_result()
    assert result["success"] is False
    assert result["reject_reason"] == "signature_mismatch"
    assert "Signature check failed" in result["error"]


async def test_missing_ts_rejected_as_bad_frame(mock_mqtt):
    # bad_frame is the residual category — reason mentions neither "signature"
    # nor "replay window". A frame signed WITHOUT ts (so the signature matches
    # the ts-less body) trips the missing-ts check → bad_frame.
    await _register_relay_node()
    sio = _FakeSio()
    frame = _cmd("cmd-nots")
    del frame["ts"]
    await handle_cloud_command(sio, _sign(frame))
    assert mock_mqtt == []
    result = sio.last_result()
    assert result["success"] is False
    assert result["reject_reason"] == "bad_frame"


async def test_wrong_key_rejected_as_signature_mismatch(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    frame = _sign(_cmd("cmd-wrongkey"), key="a-different-token")
    await handle_cloud_command(sio, frame)
    assert mock_mqtt == []
    assert sio.last_result()["reject_reason"] == "signature_mismatch"


async def test_expired_ts_rejected_as_clock_skew(mock_mqtt):
    await _register_relay_node()
    sio = _FakeSio()
    frame = _sign(_cmd("cmd-old", ts=time.time() - 3600))
    await handle_cloud_command(sio, frame)
    assert mock_mqtt == []
    assert sio.last_result()["reject_reason"] == "clock_skew"


async def test_signature_gate_precedes_tier_gate(mock_mqtt):
    """A compromised relay can't reach actuation with a forged 'premium' tier —
    the signature is checked before the tier string is even read."""
    await _register_relay_node()
    sio = _FakeSio()
    # Correctly-shaped premium frame, but signed with the wrong key.
    frame = _sign(_cmd("cmd-forged", tier="premium"), key="attacker-key")
    await handle_cloud_command(sio, frame)
    assert mock_mqtt == []
    result = sio.last_result()
    assert result["success"] is False
    assert result["reject_reason"] == "signature_mismatch"
    # Rejected at the signature layer, NOT the tier layer.
    assert result["error"] != "Remote control requires premium tier"
