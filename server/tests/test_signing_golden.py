"""Pi-side golden-file check for HMAC canonical form + signature.

Fails if the Pi drifts from the shared contract encoded in
`tests/fixtures/signing_vectors.json`: the verifier for the cloud relay's
frames (`app.cloud.signing._canonical` / `verify_frame`) and the signer of the
Pi's own cmd/* frames (`mqtt._sign_cmd_payload`), which the node checks
against its byte-identical copy of the same file. The cloud side carries the
same fixture and the same assertions — if they diverge, every signed command
breaks in production.
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app import mqtt
from app.cloud.signing import _canonical, verify_frame
from app.config import settings

_FIXTURE = Path(__file__).parent / "fixtures" / "signing_vectors.json"
_FIRMWARE_COPY = (Path(__file__).resolve().parents[2]
                  / "firmware" / "test" / "fixtures" / "signing_vectors.json")
_DOC = json.loads(_FIXTURE.read_text())
_VECTORS = {v["id"]: v for v in _DOC["vectors"]}
_VECTOR_IDS = [
    "a-simple-command",
    "reordered-keys-must-produce-same-signature",
    "nested-payload",
    "unicode-in-payload",
    "null-channel",
    "integer-ts-accepted",
]


def test_firmware_copy_is_byte_identical():
    """The node's native suites (test_core_canonical, test_core_hmac) assert
    the firmware's copy. A copy that drifted would let both suites pass while
    the node and the Pi disagree on what a signature covers."""
    assert _FIRMWARE_COPY.read_bytes() == _FIXTURE.read_bytes()
    # Every vector in the file is checked below (a new one must be listed).
    assert sorted(_VECTORS) == sorted(_VECTOR_IDS)


@pytest.mark.parametrize("vector_id", _VECTOR_IDS)
def test_vector_canonical_form_and_signature(monkeypatch, vector_id: str):
    key, vector = _DOC["key"], _VECTORS[vector_id]
    frame = vector["frame"]

    canonical = _canonical(frame)
    assert canonical == vector["expected_canonical"].encode("utf-8"), (
        f"Canonical form drift for {vector_id}. Re-run "
        "cloud/tests/fixtures/_gen_signing_vectors.py and verify the "
        "intentional change is mirrored in BOTH signing.py files."
    )
    sig = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    assert sig == vector["expected_signature"], f"HMAC drift for {vector_id}"

    # The relay's verifier accepts the signed frame (`now` inside the window).
    ok, reason = verify_frame(key, {**frame, "signature": sig}, now=frame["ts"] + 0.1)
    assert ok, f"{vector_id} failed verify: {reason}"

    # The Pi's cmd/* signer produces the same signature the node expects.
    monkeypatch.setattr(settings, "mqtt_hmac_key", key)
    assert mqtt._sign_cmd_payload(frame)["signature"] == vector["expected_signature"]
