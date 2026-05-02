#!/usr/bin/env python3
"""Sign a firmware bundle with the OTA private key.

Produces a detached `.sig` file alongside the bundle. The Pi-side
verifier (`sporeprint/server/app/cloud/ota.py::_verify_signature`)
expects a 64-byte raw Ed25519 signature in this exact format.

Usage:
    python3 sign-ota-bundle.py \\
        --bundle dist/sporeprint-server-3.4.11.tar.gz \\
        --private-key ~/.config/sporeprint/ota/ota-signing.key

After signing, upload BOTH files to the release host:
    s3://updates.sporeprint.ai/firmware/{channel}/{version}.tar.gz
    s3://updates.sporeprint.ai/firmware/{channel}/{version}.tar.gz.sig
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bundle", type=Path, required=True, help="Path to .tar.gz to sign")
    parser.add_argument(
        "--private-key",
        type=Path,
        required=True,
        help="Path to base64-encoded private key (output of generate-ota-keypair.py)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output .sig path (defaults to {bundle}.sig)",
    )
    args = parser.parse_args()

    if not args.bundle.is_file():
        sys.stderr.write(f"ERROR: bundle not found: {args.bundle}\n")
        return 2
    if not args.private_key.is_file():
        sys.stderr.write(f"ERROR: private key not found: {args.private_key}\n")
        return 2

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        sys.stderr.write(
            "ERROR: 'cryptography' package not installed.\n"
            "Install on the signing host:  pip install cryptography\n"
        )
        return 2

    priv_b64 = args.private_key.read_text().strip()
    try:
        priv_raw = base64.b64decode(priv_b64, validate=True)
    except Exception as e:
        sys.stderr.write(f"ERROR: private key is not valid base64: {e}\n")
        return 2
    if len(priv_raw) != 32:
        sys.stderr.write(
            f"ERROR: private key must decode to 32 bytes, got {len(priv_raw)}\n"
        )
        return 2

    sk = Ed25519PrivateKey.from_private_bytes(priv_raw)
    bundle_bytes = args.bundle.read_bytes()
    sig = sk.sign(bundle_bytes)
    if len(sig) != 64:
        sys.stderr.write(
            f"ERROR: produced signature wrong length ({len(sig)}); "
            "this should be impossible with Ed25519\n"
        )
        return 2

    out = args.out if args.out is not None else args.bundle.with_suffix(args.bundle.suffix + ".sig")
    out.write_bytes(sig)
    print(f"Signed {args.bundle} → {out}  ({len(sig)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
