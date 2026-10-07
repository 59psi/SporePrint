"""Regenerate tests/fixtures/ota_manifest_vectors.json.

Run from the repo root:
    python3 server/tests/fixtures/_gen_ota_manifest_vectors.py \\
        > server/tests/fixtures/ota_manifest_vectors.json

then copy the result over the cloud parent repo's copy of the same fixture,
which pins its release verifier to these vectors.

The signing key is a TEST-ONLY key derived from a public string. It signs
nothing real; no Pi pins it.

Ed25519 is deterministic (RFC 8032), so the file reproduces byte for byte.
The v1 vectors must never change: a format change gets a new schema value
and new vectors next to these.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODULE = Path(__file__).resolve().parents[2] / "app" / "cloud" / "ota_manifest.py"
_spec = importlib.util.spec_from_file_location("ota_manifest_gen", MODULE)
om = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(om)

SEED = hashlib.sha256(b"sporeprint ota manifest v1 TEST-ONLY key").digest()
OTHER_SEED = hashlib.sha256(b"sporeprint ota manifest v1 TEST-ONLY wrong key").digest()
KEY = Ed25519PrivateKey.from_private_bytes(SEED)
OTHER_KEY = Ed25519PrivateKey.from_private_bytes(OTHER_SEED)
PUBLISHED_AT = "2026-10-05T12:00:00Z"


def _bundle(version: str) -> bytes:
    return f"sporeprint-server {version} test bundle".encode()


def _manifest(version: str, channel: str) -> dict:
    bundle = _bundle(version)
    return om.build(
        artifact=om.ARTIFACT_PI_SERVER,
        version=version,
        channel=channel,
        sha256=hashlib.sha256(bundle).hexdigest(),
        size=len(bundle),
        published_at=PUBLISHED_AT,
    )


def _raw(obj: dict) -> bytes:
    """Canonical-looking encoding WITHOUT validation (for invalid cases)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("ascii")


def _case(case_id: str, data: bytes, sig: bytes, expect: str, why: str) -> dict:
    return {
        "id": case_id,
        # manifest_hex is authoritative; manifest_text is for reading.
        "manifest_hex": data.hex(),
        "manifest_text": data.decode("utf-8"),
        "signature_hex": sig.hex(),
        "expect": expect,
        "why": why,
    }


def main() -> None:
    valid = []
    for case_id, version, channel in (
        ("stable-release", "5.1.0", "stable"),
        ("beta-prerelease", "5.2.0-beta.1", "beta"),
        ("dev-build", "5.2.0.dev7", "dev"),
    ):
        manifest = _manifest(version, channel)
        data, sig = om.sign(manifest, KEY)
        valid.append({
            **_case(case_id, data, sig, "ok", "canonical bytes signed by the test key"),
            "fields": manifest,
            "bundle": _bundle(version).decode("ascii"),
        })

    base = _manifest("5.1.0", "stable")
    base_bytes, base_sig = om.sign(base, KEY)

    def _tamper(case_id: str, why: str, **changes) -> dict:
        data = om.canonical_bytes({**base, **changes})
        return _case(case_id, data, base_sig, "bad_signature", why)

    tampered = [
        _tamper("version-raised", "version edited after signing", version="5.1.1"),
        _tamper("version-lowered", "version edited after signing (rollback)", version="5.0.0"),
        _tamper("channel-swapped", "stable manifest relabelled beta", channel="beta"),
        _tamper("sha256-swapped", "sha256 of a different bundle",
                sha256=hashlib.sha256(b"evil bundle").hexdigest()),
        _tamper("size-changed", "size edited after signing", size=base["size"] + 1),
        _tamper("artifact-changed", "artifact edited after signing", artifact="node-esp32"),
        _case("signature-bitflip", base_bytes,
              bytes([base_sig[0] ^ 0x01]) + base_sig[1:], "bad_signature",
              "one bit of the signature flipped"),
        _case("wrong-key", base_bytes, OTHER_KEY.sign(base_bytes), "bad_signature",
              "valid manifest signed by a key no Pi pins"),
    ]

    def _signed(case_id: str, data: bytes, why: str) -> dict:
        return _case(case_id, data, KEY.sign(data), "bad_form", why)

    size = base["size"]
    signed_but_invalid = [
        _signed("pretty-printed",
                json.dumps(base, sort_keys=True, indent=2).encode("ascii"),
                "same fields, not canonical (whitespace)"),
        _signed("unsorted-keys",
                json.dumps(dict(reversed(list(base.items()))),
                           separators=(",", ":")).encode("ascii"),
                "same fields, not canonical (key order)"),
        _signed("trailing-newline", base_bytes + b"\n", "canonical bytes plus a newline"),
        _signed("duplicate-key",
                base_bytes[:-1] + b',"version":"9.9.9"}',
                "a repeated key: parsers disagree on which value wins"),
        _signed("unknown-key", _raw({**base, "note": "x"}), "a key outside the v1 set"),
        _signed("missing-key", _raw({k: v for k, v in base.items() if k != "channel"}),
                "channel left out"),
        _signed("float-size",
                _raw(base).replace(b'"size":%d' % size, b'"size":%d.0' % size),
                "size written as a float"),
        _signed("bool-size", _raw({**base, "size": True}), "size written as true"),
        _signed("wrong-schema", _raw({**base, "schema": "sporeprint.ota.manifest.v2"}),
                "an unknown schema version"),
        _signed("uppercase-sha256", _raw({**base, "sha256": base["sha256"].upper()}),
                "sha256 must be lowercase hex"),
        _signed("bad-channel", _raw({**base, "channel": "nightly"}), "channel outside the set"),
        _signed("bad-version", _raw({**base, "version": "5.1.0/../x"}), "version with a path"),
        _signed("bad-published-at", _raw({**base, "published_at": "2026-13-01T00:00:00Z"}),
                "month 13"),
        _signed("not-an-object", b'["sporeprint.ota.manifest.v1"]', "a JSON array"),
        _signed("non-ascii", _raw(base).replace(b"5.1.0", "5.1.0é".encode("utf-8")),
                "UTF-8 outside ASCII"),
    ]

    out = {
        "schema": om.SCHEMA,
        "note": (
            "OTA release manifest v1 test vectors. TEST-ONLY key derived from a "
            "public string; never pinned on a Pi. Regenerate with "
            "server/tests/fixtures/_gen_ota_manifest_vectors.py; v1 cases never change."
        ),
        "canonical_encoding": "json.dumps(m, sort_keys=True, separators=(',', ':'), ensure_ascii=True), ASCII, no trailing newline",
        "private_seed_hex": SEED.hex(),
        "public_key_b64": base64.b64encode(
            KEY.public_key().public_bytes_raw()).decode("ascii"),
        "valid": valid,
        "tampered": tampered,
        "signed_but_invalid": signed_but_invalid,
    }
    print(json.dumps(out, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
