"""The cloud relay's frame signature, written out independently of the Pi's.

Not collected (no ``test_`` prefix).
"""

import hashlib
import hmac
import json


def sign(frame: dict, key: str) -> dict:
    """Sign `frame` as the cloud relay does: HMAC-SHA256 with the device token
    over the canonical JSON of every field but `signature`. Written out here
    rather than borrowed from app.cloud.signing, so a drift in the Pi's
    canonical form fails the tests instead of following them."""
    filtered = {k: v for k, v in frame.items() if k != "signature"}
    body = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {**frame, "signature": digest}
