"""HMAC-SHA256 verification for cloud-relayed command frames.

The cloud relay signs every command frame with HMAC-SHA256 over a
canonical JSON form of the payload. The Pi verifies that signature here
using its stored `cloud_token` — the same value the socket used to
authenticate in the first place.

Both sides agree on:
  - HMAC-SHA256 over `json.dumps(frame - {signature}, sort_keys=True, separators=(",", ":")).encode("utf-8")`
  - A `ts` (epoch seconds) field that must be within `REPLAY_WINDOW_SECONDS` of wall-clock.

The cloud side lives at `cloud/app/relay/signing.py` in the commercial
repo and mirrors this helper byte-for-byte. This duplication is deliberate
— see the parent repo's docs/signing-architecture.md for the rationale.
Drift between the two `signing.py` files (or their test fixtures) is
blocked at release time by `bump.sh` which runs `diff -q` on the
golden-file fixtures before permitting the version bump.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
    if not isinstance(ts, (int, float)):
        return False, "missing or non-numeric ts"
    if abs(now - ts) > REPLAY_WINDOW_SECONDS:
        return False, f"ts outside replay window ({abs(now - ts):.1f}s > {REPLAY_WINDOW_SECONDS}s)"

    expected = hmac.new(signing_key.encode("utf-8"), _canonical(frame), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "signature mismatch"

    return True, None
