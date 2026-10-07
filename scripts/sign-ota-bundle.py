#!/usr/bin/env python3
"""Sign a Pi-server OTA bundle with the OTA private key.

Always writes the legacy detached `.sig`: a raw 64-byte Ed25519 signature over
the bundle bytes. Pis from before signed manifests verify only this, so the
release keeps publishing it.

With `--manifest-out` (plus `--version` and `--channel`) it also writes the
signed release manifest that current Pis require:

    {version}.manifest.json      canonical JSON {schema, artifact, version,
                                 channel, sha256, size, published_at}
    {version}.manifest.json.sig  raw 64-byte Ed25519 signature over exactly
                                 those bytes

The manifest format, canonical encoding and verification all live in
`server/app/cloud/ota_manifest.py`. This script loads that file by path, so the
bytes it signs are the bytes the Pi verifier (`server/app/cloud/ota.py`) checks
(`server/tests/test_ota_keypair_script.py` signs with this script and verifies
with the Pi code).

Usage:
    python3 scripts/sign-ota-bundle.py \\
        --bundle dist/5.1.0.tar.gz \\
        --private-key ~/.config/sporeprint/ota/ota-signing.key \\
        --manifest-out dist/5.1.0.manifest.json \\
        --version 5.1.0 --channel stable

Upload to the release host, the manifest last (it is what current Pis look
for first):
    s3://updates.sporeprint.ai/firmware/{channel}/{version}.tar.gz
    s3://updates.sporeprint.ai/firmware/{channel}/{version}.tar.gz.sig
    s3://updates.sporeprint.ai/firmware/{channel}/{version}.manifest.json.sig
    s3://updates.sporeprint.ai/firmware/{channel}/{version}.manifest.json

What each signature covers: the legacy `.sig` covers only the bundle bytes, so
an older Pi takes the version and channel from the OTA command and can only
refuse a downgrade by comparing version names. The manifest binds version,
channel, sha256 and size: a current Pi installs it only when the version is the
one requested and not older than the installed one (no downgrade unless the
operator sets SPOREPRINT_OTA_ALLOW_DOWNGRADE on the Pi) and the channel is the
Pi's own SPOREPRINT_OTA_CHANNEL. Only bare-metal Pis on the
<SPOREPRINT_INSTALL_ROOT>/current (systemd) layout self-update; Docker installs
(install.sh) refuse cloud OTA and update with `git pull && ./install.sh`.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_MODULE = (
    Path(__file__).resolve().parents[1] / "server" / "app" / "cloud" / "ota_manifest.py"
)
DEFAULT_ARTIFACT = "sporeprint-server"


def load_manifest_module(path: Path = MANIFEST_MODULE):
    """Import the Pi's `ota_manifest.py` by file path (it has no package-
    relative imports), without importing the server package."""
    spec = importlib.util.spec_from_file_location("sporeprint_ota_manifest", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
        help="Output legacy .sig path (defaults to {bundle}.sig)",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=None,
        help="Also write the signed manifest here ({path}.sig next to it); "
        "needs --version and --channel",
    )
    parser.add_argument("--version", default=None, help="Release version (manifest)")
    parser.add_argument(
        "--channel", default=None, help="Release channel: stable | beta | dev (manifest)"
    )
    parser.add_argument(
        "--artifact", default=DEFAULT_ARTIFACT, help=f"Manifest artifact (default {DEFAULT_ARTIFACT})"
    )
    parser.add_argument(
        "--published-at",
        default=None,
        help="Manifest published_at, UTC YYYY-MM-DDTHH:MM:SSZ (default: now)",
    )
    args = parser.parse_args(argv)
    if args.manifest_out is not None and (not args.version or not args.channel):
        parser.error("--manifest-out needs --version and --channel")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

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

    if args.manifest_out is None:
        return 0

    manifest_mod = load_manifest_module()
    try:
        published_at = args.published_at or manifest_mod.format_published_at(
            datetime.now(timezone.utc)
        )
        sha256, size = manifest_mod.file_digest(args.bundle)
        manifest = manifest_mod.build(
            artifact=args.artifact,
            version=args.version,
            channel=args.channel,
            sha256=sha256,
            size=size,
            published_at=published_at,
        )
        data, manifest_sig = manifest_mod.sign(manifest, sk)
        # Self-check with the Pi's verifier before anything is written.
        manifest_mod.verify(data, manifest_sig, sk.public_key())
    except manifest_mod.ManifestError as e:
        sys.stderr.write(f"ERROR: cannot build the manifest: {e}\n")
        return 2

    manifest_sig_out = args.manifest_out.with_name(args.manifest_out.name + ".sig")
    args.manifest_out.write_bytes(data)
    manifest_sig_out.write_bytes(manifest_sig)
    print(
        f"Manifest {args.manifest_out} ({args.version} on {args.channel}, "
        f"sha256 {sha256}, {size} bytes) → {manifest_sig_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
