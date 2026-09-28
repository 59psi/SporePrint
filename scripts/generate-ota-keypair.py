#!/usr/bin/env python3
"""Generate an Ed25519 keypair for OTA bundle signing.

Run ONCE, on a release-signing host that you trust. Outputs:

  - The base64-encoded **public** key — paste into every Pi's
    Settings → OTA verify key (or set SPOREPRINT_OTA_PUBKEY=<value>
    in the SporePrint checkout's .env, then `docker compose up -d server`).

  - The base64-encoded **private** key — keep this on hardware you
    control (a YubiKey with PIV slot, an offline laptop, a sealed
    USB drive). The private key signs every release bundle. If it
    leaks, an attacker can push arbitrary firmware to every Pi that
    trusts this public key.

  - A signing helper command — to sign a bundle once you have the
    private key file:

        python3 scripts/sign-ota-bundle.py \\
            --bundle dist/sporeprint-server-3.4.11.tar.gz \\
            --private-key ~/.config/sporeprint/ota-signing.key

Usage:
    python3 sporeprint/scripts/generate-ota-keypair.py [--out DIR]

By default the keys are printed to stdout and NOT written to disk.
Pass `--out DIR` to write `ota-signing.key` (private) and
`ota-verify.pub` (public) into DIR — DIR must not exist or must be
empty, and the private key file is written 0600.

This script never touches the project repo. Do NOT run it inside the
sporeprint working tree with `--out .` — the private key must never be
committed to source control.
"""

from __future__ import annotations

import argparse
import base64
import os
import stat
import sys
from pathlib import Path


def _gen_keypair() -> tuple[bytes, bytes]:
    """Generate a fresh Ed25519 keypair. Returns (priv_raw32, pub_raw32)."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError as e:
        sys.stderr.write(
            "ERROR: 'cryptography' package not installed.\n"
            "Install it on this signing host:  pip install cryptography\n"
        )
        raise SystemExit(2) from e

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()

    # Raw private key bytes (seed) — 32 bytes, exactly what
    # Ed25519PrivateKey.from_private_bytes() expects on import.
    from cryptography.hazmat.primitives import serialization

    priv_raw = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pk.public_bytes_raw()
    if len(priv_raw) != 32 or len(pub_raw) != 32:
        raise SystemExit("Internal error: Ed25519 key not 32 bytes")
    return priv_raw, pub_raw


def _write_keys(out_dir: Path, priv_b64: str, pub_b64: str) -> None:
    """Write the keypair to `out_dir`. Refuses to clobber existing files
    so a typo can't overwrite a production key."""
    if out_dir.exists():
        if any(out_dir.iterdir()):
            sys.stderr.write(
                f"ERROR: output dir {out_dir} is not empty — refusing to overwrite\n"
            )
            raise SystemExit(2)
    else:
        out_dir.mkdir(parents=True, mode=0o700)
    # Lock the directory down even when it already existed (e.g. a 0755 dir
    # on a shared signing host) — mkdir's mode is also subject to the umask.
    os.chmod(out_dir, stat.S_IRWXU)

    priv_path = out_dir / "ota-signing.key"
    pub_path = out_dir / "ota-verify.pub"

    # Create the private key 0600 from the first byte (O_EXCL: never follow
    # or clobber an existing file) instead of write-then-chmod, which left it
    # umask-readable (typically 0644) until — or, if chmod failed, after —
    # the chmod.
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                 stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(priv_b64 + "\n")
    pub_path.write_text(pub_b64 + "\n")
    print(f"\nWrote {priv_path}  (mode 0600 — keep offline)", file=sys.stderr)
    print(f"Wrote {pub_path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an Ed25519 keypair for OTA signing.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write keypair to DIR (must not exist or be empty). Without --out, "
        "keys print to stdout and are NOT persisted.",
    )
    args = parser.parse_args()

    priv_raw, pub_raw = _gen_keypair()
    priv_b64 = base64.b64encode(priv_raw).decode("ascii")
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")

    print()
    print("=" * 72)
    print("OTA SIGNING KEYPAIR — Ed25519")
    print("=" * 72)
    print()
    print("Public verify key (paste into every Pi's Settings → OTA verify key,")
    print("or set SPOREPRINT_OTA_PUBKEY=<value> in the Pi's SporePrint/.env and run")
    print("`docker compose up -d server`):")
    print()
    print(f"  {pub_b64}")
    print()
    print("-" * 72)
    print("Private signing key — KEEP THIS OFFLINE. Never commit. Never email.")
    print("Anyone with this key can push arbitrary firmware to every Pi that")
    print("trusts the public key above.")
    print("-" * 72)
    print()
    print(f"  {priv_b64}")
    print()
    print("=" * 72)
    print()

    if args.out:
        _write_keys(args.out, priv_b64, pub_b64)
    else:
        print(
            "No --out specified; keys are not on disk. Save the private key now,\n"
            "or rerun with --out ~/.config/sporeprint/ota/ to persist.\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
