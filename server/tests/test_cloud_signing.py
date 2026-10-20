"""Pi-side HMAC verification for cloud-relayed command frames.

The cloud relay signs every command with HMAC-SHA256(device_token, canonical_json).
The Pi refuses unsigned, tampered, wrongly keyed or replayed (stale or future
ts) frames before they reach any other layer of the command handler. The
canonical form itself is pinned against the shared golden vectors in
test_signing_golden.py.
"""

import json

import pytest

from app.cloud.signing import REPLAY_WINDOW_SECONDS, verify_frame
from tests._signing import sign

_KEY = "unit-test-device-token"
_NOW = 1_800_000_000.0


def _frame(**fields) -> dict:
    return {"id": "abc", "tier": "premium", "target": "relay-01", "ts": _NOW, **fields}


def _without(field: str) -> dict:
    frame = _frame()
    del frame[field]
    return frame


def _tampered() -> dict:
    frame = sign(_frame(), _KEY)
    frame["target"] = "relay-02"  # changed AFTER signing
    return frame


@pytest.mark.parametrize("skew", [-REPLAY_WINDOW_SECONDS, REPLAY_WINDOW_SECONDS])
def test_a_signed_frame_verifies_up_to_the_edge_of_the_replay_window(skew):
    assert verify_frame(_KEY, sign(_frame(ts=_NOW + skew), _KEY), now=_NOW) == (True, None)


@pytest.mark.parametrize("key, frame, reason", [
    (_KEY, _frame(), "missing signature"),
    # Signed without a ts, so only the ts check can refuse it.
    (_KEY, sign(_without("ts"), _KEY), "missing or non-numeric ts"),
    (_KEY, sign(_frame(ts=_NOW - REPLAY_WINDOW_SECONDS - 0.5), _KEY), "ts outside replay window"),
    (_KEY, sign(_frame(ts=_NOW + REPLAY_WINDOW_SECONDS + 0.5), _KEY), "ts outside replay window"),
    (_KEY, sign(_frame(), "some-other-token"), "signature mismatch"),
    (_KEY, _tampered(), "signature mismatch"),
    ("", sign(_frame(), _KEY), "no signing key configured"),
], ids=["unsigned", "no-ts", "stale", "future",
        "wrong-key", "tampered", "no-key"])
def test_a_frame_that_fails_any_check_is_refused_with_its_reason(key, frame, reason):
    ok, why = verify_frame(key, frame, now=_NOW)
    assert ok is False
    assert why.startswith(reason), why


@pytest.mark.parametrize("ts", [float("nan"), float("inf"), float("-inf"), True, False])
def test_a_ts_that_is_not_a_finite_time_is_rejected(ts):
    """NaN passes any `>` window test, so a NaN-ts frame never expired and
    became replayable once the replay cache forgot its id. Python's json
    reads NaN and Infinity, so such a frame can arrive validly signed."""
    ok, reason = verify_frame(_KEY, sign(_frame(ts=ts), _KEY), now=_NOW)
    assert (ok, reason) == (False, "missing or non-numeric ts")


def test_a_nan_ts_off_the_wire_is_rejected():
    wire = json.dumps(sign(_frame(ts=float("nan")), _KEY))
    assert '"ts": NaN' in wire
    assert verify_frame(_KEY, json.loads(wire), now=_NOW) == (False, "missing or non-numeric ts")
