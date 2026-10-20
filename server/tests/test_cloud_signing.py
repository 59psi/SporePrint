"""Pi-side HMAC verification for cloud-relayed command frames.

The cloud relay signs every command with HMAC-SHA256(device_token, canonical_json).
The Pi refuses unsigned, tampered, or replayed frames before they reach
any other layer of the command handler.
"""

import hashlib
import hmac
import json
import time

import pytest

from app.cloud.signing import REPLAY_WINDOW_SECONDS, verify_frame


_KEY = "unit-test-device-token"


def _sign(key: str, frame: dict) -> dict:
    """Test helper that mirrors the cloud-side sign_frame exactly."""
    filtered = {k: v for k, v in frame.items() if k != "signature"}
    body = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {**frame, "signature": sig}


def test_signed_frame_verifies():
    frame = _sign(_KEY, {"id": "abc", "tier": "premium", "target": "relay-01",
                         "ts": time.time()})
    ok, reason = verify_frame(_KEY, frame)
    assert ok, reason


def test_missing_signature_rejected():
    ok, reason = verify_frame(_KEY, {"id": "abc", "ts": time.time()})
    assert not ok
    assert reason == "missing signature"


def test_missing_ts_rejected():
    frame = _sign(_KEY, {"id": "abc"})
    # Strip ts to simulate a client that forgot to include it.
    frame.pop("ts", None)
    # Re-sign without ts so the signature matches what's left — this
    # isolates the ts check from the signature check.
    body = json.dumps({k: v for k, v in frame.items() if k != "signature"},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    frame["signature"] = hmac.new(_KEY.encode("utf-8"), body, hashlib.sha256).hexdigest()
    ok, reason = verify_frame(_KEY, frame)
    assert not ok
    assert "ts" in reason


def test_expired_ts_rejected():
    old = time.time() - (REPLAY_WINDOW_SECONDS + 5)
    frame = _sign(_KEY, {"id": "abc", "ts": old})
    ok, reason = verify_frame(_KEY, frame)
    assert not ok
    assert "replay window" in reason


def test_future_ts_rejected():
    future = time.time() + (REPLAY_WINDOW_SECONDS + 5)
    frame = _sign(_KEY, {"id": "abc", "ts": future})
    ok, reason = verify_frame(_KEY, frame)
    assert not ok
    assert "replay window" in reason


def test_wrong_key_rejected():
    frame = _sign("some-other-token", {"id": "abc", "ts": time.time()})
    ok, reason = verify_frame(_KEY, frame)
    assert not ok
    assert reason == "signature mismatch"


def test_tampered_payload_rejected():
    """Modifying any field after signing must invalidate the signature."""
    frame = _sign(_KEY, {"id": "abc", "ts": time.time(), "target": "relay-01"})
    frame["target"] = "relay-02"  # swap target AFTER signing
    ok, reason = verify_frame(_KEY, frame)
    assert not ok
    assert reason == "signature mismatch"


def test_empty_key_rejected():
    frame = _sign(_KEY, {"id": "abc", "ts": time.time()})
    ok, reason = verify_frame("", frame)
    assert not ok
    assert "signing key" in reason


@pytest.mark.parametrize("ts", [float("nan"), float("inf"), float("-inf"), True, False])
def test_a_ts_that_is_not_a_finite_time_is_rejected(ts):
    """NaN passes any `>` window test, so a NaN-ts frame never expired and
    became replayable once the replay cache forgot its id. Python's json
    reads NaN and Infinity, so such a frame can arrive validly signed."""
    frame = _sign(_KEY, {"id": "abc", "ts": ts})
    for now in (time.time(), time.time() + 3600, time.time() + 10 * 365 * 86400):
        ok, reason = verify_frame(_KEY, frame, now=now)
        assert not ok
        assert reason == "missing or non-numeric ts"


def test_a_nan_ts_off_the_wire_is_rejected():
    wire = json.dumps(_sign(_KEY, {"id": "abc", "ts": float("nan")}))
    assert '"ts": NaN' in wire
    ok, reason = verify_frame(_KEY, json.loads(wire))
    assert not ok and reason == "missing or non-numeric ts"
