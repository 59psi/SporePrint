"""Signed OTA release manifest v1: canonical bytes, signatures, test vectors.

The vectors in fixtures/ota_manifest_vectors.json pin the exact bytes the
release workflow signs and the Pi verifies. The private release repo keeps
a byte-identical copy and checks its own verifier against it.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.cloud import ota_manifest as om

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VECTORS_PATH = FIXTURES / "ota_manifest_vectors.json"
GENERATOR = FIXTURES / "_gen_ota_manifest_vectors.py"
MODULE_PATH = Path(om.__file__)

VECTORS = json.loads(VECTORS_PATH.read_text())
KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(VECTORS["private_seed_hex"]))
PUBKEY = Ed25519PublicKey.from_public_bytes(base64.b64decode(VECTORS["public_key_b64"]))


def _ids(cases):
    return [c["id"] for c in cases]


def _bytes(case) -> bytes:
    return bytes.fromhex(case["manifest_hex"])


def _sig(case) -> bytes:
    return bytes.fromhex(case["signature_hex"])


# ─── The vector file itself ───────────────────────────────────────────


def test_vectors_pin_schema_v1_and_their_key():
    assert VECTORS["schema"] == om.SCHEMA == "sporeprint.ota.manifest.v1"
    assert KEY.public_key().public_bytes_raw() == PUBKEY.public_bytes_raw()
    # Every case kind is present, so no category can silently go empty.
    assert len(VECTORS["valid"]) >= 3
    assert {"version-raised", "version-lowered", "channel-swapped",
            "sha256-swapped"} <= set(_ids(VECTORS["tampered"]))
    assert {"duplicate-key", "pretty-printed", "unknown-key",
            "float-size"} <= set(_ids(VECTORS["signed_but_invalid"]))


def test_vectors_are_what_the_generator_produces(capsys):
    """Ed25519 is deterministic: regenerating must reproduce the committed
    file byte for byte (so nobody hand-edits a vector)."""
    spec = importlib.util.spec_from_file_location("gen_ota_vectors", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.main()
    assert capsys.readouterr().out == VECTORS_PATH.read_text()


# ─── Valid manifests ──────────────────────────────────────────────────


@pytest.mark.parametrize("case", VECTORS["valid"], ids=_ids(VECTORS["valid"]))
def test_valid_vector_canonical_bytes_signature_and_verify(case):
    data = _bytes(case)
    assert om.canonical_bytes(case["fields"]) == data
    assert data == json.dumps(case["fields"], sort_keys=True,
                              separators=(",", ":")).encode("ascii")
    assert not data.endswith(b"\n")
    # Deterministic signature over the canonical bytes.
    assert om.sign(case["fields"], KEY) == (data, _sig(case))
    assert om.verify(data, _sig(case), PUBKEY) == case["fields"]
    # The digest fields describe the vector's bundle.
    bundle = case["bundle"].encode("ascii")
    assert case["fields"]["sha256"] == hashlib.sha256(bundle).hexdigest()
    assert case["fields"]["size"] == len(bundle)


def test_file_digest_matches_hashlib(tmp_path):
    payload = b"x" * (3 * 1024 * 1024 + 17)  # spans several read chunks
    path = tmp_path / "b.tar.gz"
    path.write_bytes(payload)
    assert om.file_digest(path) == (hashlib.sha256(payload).hexdigest(), len(payload))


# ─── Tampered manifests (signature no longer matches) ────────────────


@pytest.mark.parametrize("case", VECTORS["tampered"], ids=_ids(VECTORS["tampered"]))
def test_tampered_vector_fails_the_signature(case):
    with pytest.raises(om.ManifestError, match="signature verification FAILED"):
        om.verify(_bytes(case), _sig(case), PUBKEY)


# ─── Signed by the right key, but not a valid v1 manifest ────────────


@pytest.mark.parametrize("case", VECTORS["signed_but_invalid"],
                         ids=_ids(VECTORS["signed_but_invalid"]))
def test_signed_but_invalid_vector_is_rejected_after_the_signature(case):
    data, sig = _bytes(case), _sig(case)
    PUBKEY.verify(sig, data)  # the signature itself is genuine
    with pytest.raises(om.ManifestError) as exc:
        om.verify(data, sig, PUBKEY)
    assert "signature" not in str(exc.value)


def test_duplicate_key_is_named_not_last_one_wins():
    case = next(c for c in VECTORS["signed_but_invalid"] if c["id"] == "duplicate-key")
    with pytest.raises(om.ManifestError, match="repeats key 'version'"):
        om.verify(_bytes(case), _sig(case), PUBKEY)


# ─── Encoder / validator edges ────────────────────────────────────────


def _fields(**changes):
    base = dict(VECTORS["valid"][0]["fields"])
    base.update(changes)
    return base


@pytest.mark.parametrize("changes, message", [
    ({"version": "5.1.0\n"}, "version"),           # `$` would have allowed it
    ({"version": "v" + "1" * 70 + ".0.0"}, "version"),
    ({"version": "-5.1.0"}, "version"),
    ({"channel": "Stable"}, "channel"),
    ({"size": -1}, "size"),
    ({"size": om.MAX_SIZE + 1}, "size"),
    ({"size": "35"}, "size"),
    ({"artifact": "Sporeprint Server"}, "artifact"),
    ({"published_at": "2026-10-05T12:00:00+00:00"}, "published_at"),
    ({"published_at": "2026-02-30T12:00:00Z"}, "published_at"),
    ({"sha256": "ab" * 31}, "sha256"),
    ({"schema": 1}, "schema"),
])
def test_canonical_bytes_refuses_invalid_fields(changes, message):
    with pytest.raises(om.ManifestError, match=message):
        om.canonical_bytes(_fields(**changes))


def test_extra_or_missing_keys_refused():
    with pytest.raises(om.ManifestError, match="unexpected"):
        om.canonical_bytes(_fields(extra="x"))
    fields = _fields()
    del fields["sha256"]
    with pytest.raises(om.ManifestError, match="missing"):
        om.canonical_bytes(fields)


def test_verify_bounds_checked_before_the_signature():
    case = VECTORS["valid"][0]
    with pytest.raises(om.ManifestError, match="max is"):
        om.verify(b" " * (om.MAX_MANIFEST_BYTES + 1), _sig(case), PUBKEY)
    with pytest.raises(om.ManifestError, match="wrong length"):
        om.verify(_bytes(case), _sig(case)[:63], PUBKEY)


def test_format_published_at_is_utc_and_needs_a_timezone():
    when = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert om.format_published_at(when) == "2026-10-05T12:00:00Z"
    with pytest.raises(om.ManifestError):
        om.format_published_at(datetime(2026, 10, 5, 12, 0, 0))


def test_a_bundle_signature_is_never_a_manifest_signature():
    """Same key signs bundles (legacy .sig) and manifests: a gzip body can't
    parse as a manifest, and a manifest signature never verifies a bundle."""
    case = VECTORS["valid"][0]
    gzip_body = b"\x1f\x8b\x08\x00" + b"\x00" * 60
    with pytest.raises(om.ManifestError):
        om.verify(gzip_body, KEY.sign(gzip_body), PUBKEY)
    with pytest.raises(InvalidSignature):
        PUBKEY.verify(_sig(case), case["bundle"].encode("ascii"))


# ─── Loadable by path (the signer and the release workflow do this) ───


def test_module_loads_standalone_by_path():
    source = MODULE_PATH.read_text()
    assert "from ." not in source and "import app" not in source
    spec = importlib.util.spec_from_file_location("standalone_ota_manifest", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    case = VECTORS["valid"][0]
    assert mod.verify(_bytes(case), _sig(case), PUBKEY) == case["fields"]
