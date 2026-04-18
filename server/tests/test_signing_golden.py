"""Pi-side golden-file check for HMAC canonical form + signature.

Fails if the Pi's `verify_frame` or `_canonical` computation drifts away from
the shared contract encoded in `tests/fixtures/signing_vectors.json`. The cloud
side carries the same fixture and the same assertions — if they diverge, every
signed command breaks in production.
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app.cloud.signing import _canonical, verify_frame


_FIXTURE = Path(__file__).parent / "fixtures" / "signing_vectors.json"


def _load_fixture():
    with _FIXTURE.open() as f:
        doc = json.load(f)
    return doc["key"], doc["vectors"]


@pytest.mark.parametrize("vector_id", [
    "a-simple-command",
    "reordered-keys-must-produce-same-signature",
    "nested-payload",
    "unicode-in-payload",
    "null-channel",
    "integer-ts-accepted",
])
def test_canonical_form_matches_fixture(vector_id: str):
    key, vectors = _load_fixture()
    vector = next(v for v in vectors if v["id"] == vector_id)
    expected = vector["expected_canonical"].encode("utf-8")
    assert _canonical(vector["frame"]) == expected, (
        f"Canonical form drift for {vector_id}. Re-run "
        "cloud/tests/fixtures/_gen_signing_vectors.py and verify the "
        "intentional change is mirrored in BOTH signing.py files."
    )


def test_all_vectors_produce_expected_signature():
    key, vectors = _load_fixture()
    for vector in vectors:
        body = _canonical(vector["frame"])
        sig = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
        assert sig == vector["expected_signature"], (
            f"HMAC drift for {vector['id']}"
        )


def test_verify_frame_accepts_all_signed_fixtures():
    """Each frame, after being signed with the golden key, verifies successfully."""
    key, vectors = _load_fixture()
    for vector in vectors:
        body = _canonical(vector["frame"])
        sig = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
        signed = {**vector["frame"], "signature": sig}
        # Inject a `now` close to the vector's ts to skip the replay window.
        ts = vector["frame"]["ts"]
        ok, reason = verify_frame(key, signed, now=ts + 0.1)
        assert ok, f"{vector['id']} failed verify: {reason}"
