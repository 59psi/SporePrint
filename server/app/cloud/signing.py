"""HMAC-SHA256 verification for cloud-relayed command frames.

The cloud relay signs every command frame with HMAC-SHA256 over a
canonical JSON form of the payload. The Pi verifies that signature here
using its stored `cloud_token` — the same value the socket used to
authenticate in the first place.

Both sides agree on:
  - HMAC-SHA256 over `json.dumps(frame - {signature}, sort_keys=True, separators=(",", ":")).encode("utf-8")`
  - A `ts` (epoch seconds) field that must be within `REPLAY_WINDOW_SECONDS` of wall-clock.

The cloud side keeps its own copy of the canonical form and the verify logic
in the commercial repo. The two files are not identical: only the cloud's
signs, and this one also refuses an empty key. This duplication is
deliberate — see the parent repo's docs/signing-architecture.md for the
rationale. Each copy is checked against the shared golden-file fixture
(tests/fixtures/signing_vectors.json, byte-identical in both repos; here by
tests/test_signing_golden.py). The release script diffs the two fixture
copies; nothing compares the two modules.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time

REPLAY_WINDOW_SECONDS = 30


def _canonical(frame: dict) -> bytes:
    filtered = {k: v for k, v in frame.items() if k != "signature"}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_frame(signing_key: str, frame: dict, now: float | None = None) -> tuple[bool, str | None]:
    """Return (ok, error_reason). `now` is injectable for tests."""
    if not signing_key:
        return False, "no signing key configured"

    if now is None:
        now = time.time()

    sig = frame.get("signature")
    if not isinstance(sig, str) or not sig:
        return False, "missing signature"

    ts = frame.get("ts")
    # NaN passes any `>` window test (every comparison with it is False) and
    # Python's json reads NaN / Infinity, so a non-finite ts would never
    # expire. A bool is an int to isinstance, not a time.
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
        return False, "missing or non-numeric ts"
    if abs(now - ts) > REPLAY_WINDOW_SECONDS:
        return False, f"ts outside replay window ({abs(now - ts):.1f}s > {REPLAY_WINDOW_SECONDS}s)"

    expected = hmac.new(signing_key.encode("utf-8"), _canonical(frame), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "signature mismatch"

    return True, None
