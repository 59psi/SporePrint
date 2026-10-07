#!/usr/bin/env python3
"""Verify signed SporePrint firmware release zips.

A firmware release (``.github/workflows/firmware-release.yml``, tag
``firmware-vX.Y.Z``) publishes one ``<env>.zip`` per PlatformIO image env,
holding exactly:

    firmware.bin              the app image: what the Pi pushes over OTA
    bootloader.bin            second-stage bootloader (first flash over USB)
    partitions.bin            partition table (first flash over USB)
    <env>.manifest.json       signed release manifest v1 for firmware.bin
    <env>.manifest.json.sig   raw 64-byte Ed25519 signature over those bytes

For each zip this checks what a Pi (``server/app/hardware/node_manifest.py``)
and a node (``firmware/lib/sp_core/ota_manifest.h``) will check, and more:

* the manifest: its signature under the release verify key, its exact
  canonical v1 bytes and every field's grammar. This file reads the format
  on its own, mirroring ``server/app/cloud/ota_manifest.py`` without sharing
  code with it; with ``--pi-verifier`` that file verifies it too and both
  readings must agree. It must also fit the node's command frame
  (``MAX_NODE_MANIFEST_BYTES``);
* the binding: artifact = the zip's env, the release version and channel,
  and the SHA-256 and size of the ``firmware.bin`` beside it;
* the image: an ESP app image for the env's chip, built with this verify
  key, this env and this version compiled in (``firmware/scripts/
  fw_version.py``), and naming no other image env. A node checks manifests
  only when its image carries the key, so a signed image without it would
  promise a check the node cannot make;
* ``bootloader.bin`` and ``partitions.bin`` are what their names say.

The release workflow runs it on every zip before it creates the release.
Anyone can run it on a downloaded zip, from a checkout of the release tag,
with the key their Pi pins (Settings → OTA verify key):

    python3 scripts/verify_firmware_release.py \\
        --pubkey-b64 <the key your Pi pins> --version 5.1.0 node_esp32.zip

The env is the zip's file name; ``--env node_esp32`` names it for a single
download the browser renamed (``node_esp32 (1).zip``).

``--print-pubkey`` prints the base64 public key of the base64 private key in
``$OTA_SIGNING_KEY`` and nothing else (the workflow's key job uses it to hand
the build jobs only the public half). The private key is never printed.

Needs Python 3.11+ and ``cryptography``.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import importlib.util
import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# ─── Manifest v1, read independently of server/app/cloud/ota_manifest.py ──

SCHEMA = "sporeprint.ota.manifest.v1"
PI_SERVER_ARTIFACT = "sporeprint-server"
CHANNELS = ("stable", "beta", "dev")
# Sorted: the canonical key order.
FIELDS = ("artifact", "channel", "published_at", "schema", "sha256", "size", "version")
MAX_MANIFEST_BYTES = 4096
# A node takes its manifest inside one signed command frame
# (server/app/hardware/node_manifest.py MAX_NODE_MANIFEST_BYTES).
MAX_NODE_MANIFEST_BYTES = 480
SIGNATURE_BYTES = 64
MAX_SIZE = 2**53 - 1
VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.-]+)?")
MAX_VERSION_LEN = 64
# fw_version.py compiles at most 32 characters of the version into an image.
MAX_IMAGE_VERSION_LEN = 32
ARTIFACT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PUBLISHED_AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
PUBLISHED_AT_FMT = "%Y-%m-%dT%H:%M:%SZ"
# Base64 of 32 bytes with its one '=' of padding (fw_version.py's grammar).
PUBKEY_B64_RE = re.compile(r"[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=")

# ─── The images ───────────────────────────────────────────────────────────

# Every image env in firmware/platformio.ini → the chip id its ESP image
# header must carry (ESP-IDF esp_app_format.h: ESP32 0x0000, ESP32-S3 0x0009).
CHIP_ESP32 = 0x0000
CHIP_ESP32S3 = 0x0009
ENV_CHIPS = {
    "node_esp32": CHIP_ESP32,
    "node_esp32s3": CHIP_ESP32S3,
    "node_esp32s3_n32r16v": CHIP_ESP32S3,
    "cam": CHIP_ESP32,
    "cam_esp32s3": CHIP_ESP32S3,
    "cam_xiao_esp32s3": CHIP_ESP32S3,
    "cam_waveshare_s3": CHIP_ESP32S3,
}
# The byte alphabets of the C strings fw_version.py compiles in. A byte from
# the same alphabet just before a string means it is only the tail of a
# longer one ("15.1.0" or "v5.1.0" for 5.1.0).
VERSION_CHARS = frozenset(b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._+-")
BASE64_CHARS = frozenset(b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/=")
ESP_IMAGE_MAGIC = 0xE9
ESP_IMAGE_HEADER_BYTES = 24
PARTITION_TABLE_MAGIC = b"\xaa\x50"
# The largest app slot is 4 MB; nothing in a release zip comes close to this.
MAX_MEMBER_BYTES = 32 * 1024 * 1024


class ReleaseError(Exception):
    """A Pi or a node would refuse this, or it is not what was meant to ship."""


class SignatureError(ReleaseError):
    """Not signed by the release verify key."""


class FormError(ReleaseError):
    """Signed, but not a canonical, well-formed manifest v1."""


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise FormError(f"manifest repeats key {key!r}")
        out[key] = value
    return out


def _no_floats(text: str):
    raise FormError(f"manifest holds a non-integer number {text!r}")


def _check_fields(m: dict) -> None:
    if sorted(m) != list(FIELDS):
        raise FormError(f"manifest keys are {sorted(m)}, expected {list(FIELDS)}")
    for key in FIELDS:
        if key != "size" and not isinstance(m[key], str):
            raise FormError(f"manifest {key} must be a string")
    if m["schema"] != SCHEMA:
        raise FormError(f"manifest schema {m['schema']!r} is not {SCHEMA!r}")
    if not ARTIFACT_RE.fullmatch(m["artifact"]):
        raise FormError(f"manifest artifact {m['artifact']!r} is not a valid name")
    if len(m["version"]) > MAX_VERSION_LEN or not VERSION_RE.fullmatch(m["version"]):
        raise FormError(f"manifest version {m['version']!r} is not a valid version")
    if m["channel"] not in CHANNELS:
        raise FormError(f"manifest channel {m['channel']!r} is not one of {list(CHANNELS)}")
    if not SHA256_RE.fullmatch(m["sha256"]):
        raise FormError("manifest sha256 must be 64 lowercase hex digits")
    size = m["size"]
    # type() rather than isinstance(): True must not pass as a size of 1.
    if type(size) is not int or not 0 <= size <= MAX_SIZE:
        raise FormError(f"manifest size {size!r} is not an integer in [0, {MAX_SIZE}]")
    if not PUBLISHED_AT_RE.fullmatch(m["published_at"]):
        raise FormError(f"manifest published_at {m['published_at']!r} is not UTC {PUBLISHED_AT_FMT}")
    try:
        datetime.strptime(m["published_at"], PUBLISHED_AT_FMT)
    except ValueError:
        raise FormError(f"manifest published_at {m['published_at']!r} is not a real time") from None


def verify_manifest(data: bytes, sig: bytes, pubkey: Ed25519PublicKey) -> dict:
    """The signature over the exact bytes, then the strict v1 form.

    Returns the fields. Raises SignatureError or FormError.
    """
    if len(data) > MAX_MANIFEST_BYTES:
        raise FormError(f"manifest is {len(data)} bytes, at most {MAX_MANIFEST_BYTES}")
    if len(sig) != SIGNATURE_BYTES:
        raise SignatureError(f"manifest signature is {len(sig)} bytes, not {SIGNATURE_BYTES}")
    try:
        pubkey.verify(sig, data)
    except InvalidSignature:
        raise SignatureError("manifest signature does not verify under the release key") from None
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise FormError("manifest is not ASCII") from None
    try:
        parsed = json.loads(text, object_pairs_hook=_no_duplicates,
                            parse_float=_no_floats, parse_constant=_no_floats)
    except json.JSONDecodeError as e:
        raise FormError(f"manifest is not JSON: {e}") from None
    if not isinstance(parsed, dict):
        raise FormError("manifest is not a JSON object")
    _check_fields(parsed)
    # The canonical form, written out longhand rather than with json.dumps so
    # this check shares no encoder with the signer it is checking. The field
    # grammars admit no character that JSON would escape.
    canonical = "{" + ",".join(
        f'"{key}":{parsed[key]}' if key == "size" else f'"{key}":"{parsed[key]}"'
        for key in FIELDS
    ) + "}"
    if canonical.encode("ascii") != data:
        raise FormError("manifest is signed but not in canonical form")
    return {key: parsed[key] for key in FIELDS}


# ─── Keys ─────────────────────────────────────────────────────────────────


def load_public_key(b64: str) -> Ed25519PublicKey:
    b64 = b64.strip()
    if not PUBKEY_B64_RE.fullmatch(b64):
        raise ReleaseError("the verify key must be the base64 of 32 bytes (44 characters)")
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64, validate=True))


def public_key_b64(pubkey: Ed25519PublicKey) -> str:
    raw = pubkey.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def derive_public_key_b64(private_b64: str) -> str:
    """The base64 public half of a base64 32-byte Ed25519 private key (the
    format scripts/generate-ota-keypair.py writes). Errors never quote it."""
    try:
        raw = base64.b64decode(private_b64.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise ReleaseError("the private key is not valid base64") from None
    if len(raw) != 32:
        raise ReleaseError(f"the private key must decode to 32 bytes, not {len(raw)}")
    return public_key_b64(Ed25519PrivateKey.from_private_bytes(raw).public_key())


# ─── One release zip ──────────────────────────────────────────────────────


def zip_members(env: str) -> tuple[str, ...]:
    return ("firmware.bin", "bootloader.bin", "partitions.bin",
            f"{env}.manifest.json", f"{env}.manifest.json.sig")


def _read_zip(path: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            found = sorted(info.filename for info in infos)
            if found != sorted(names):
                raise ReleaseError(f"holds {found}, expected exactly {sorted(names)}")
            out = {}
            for info in infos:
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ReleaseError(f"{info.filename} is {info.file_size} bytes")
                out[info.filename] = zf.read(info)  # checks the CRC-32
            return out
    except (zipfile.BadZipFile, OSError) as e:
        raise ReleaseError(f"cannot read the zip: {e}") from None


def _check_esp_image(blob: bytes, chip: int, name: str) -> None:
    if len(blob) < ESP_IMAGE_HEADER_BYTES or blob[0] != ESP_IMAGE_MAGIC:
        raise ReleaseError(f"{name} is not an ESP image (no 0xE9 header)")
    found = int.from_bytes(blob[12:14], "little")
    if found != chip:
        raise ReleaseError(f"{name} is built for chip id {found:#06x}, this env needs {chip:#06x}")


def embeds_c_string(image: bytes, text: str, alphabet: frozenset[int]) -> bool:
    """``text`` is in ``image`` as a whole C string: NUL-terminated, and not
    the tail of a longer string over the same alphabet."""
    needle = text.encode("ascii") + b"\0"
    at = image.find(needle)
    while at != -1:
        if at == 0 or image[at - 1] not in alphabet:
            return True
        at = image.find(needle, at + 1)
    return False


def load_pi_verifier(path: Path):
    """server/app/cloud/ota_manifest.py, loaded by path (it has no
    package-relative imports)."""
    if not path.is_file():
        raise ReleaseError(f"Pi verifier {path} not found")
    spec = importlib.util.spec_from_file_location("sporeprint_pi_ota_manifest", path)
    if spec is None or spec.loader is None:
        raise ReleaseError(f"cannot load the Pi verifier {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "SCHEMA", None) != SCHEMA:
        raise ReleaseError(f"the Pi verifier speaks {getattr(module, 'SCHEMA', None)!r}, not {SCHEMA!r}")
    return module


def check_image(members: dict[str, bytes], env: str, pubkey: Ed25519PublicKey, *,
                version: str | None, channel: str, pi_verifier=None) -> dict:
    """One env's files (zip member name → bytes). Returns the manifest."""
    if env not in ENV_CHIPS:
        raise ReleaseError(f"{env!r} is not a firmware image env ({', '.join(ENV_CHIPS)})")
    image = members["firmware.bin"]
    data = members[f"{env}.manifest.json"]
    sig = members[f"{env}.manifest.json.sig"]

    if len(data) > MAX_NODE_MANIFEST_BYTES:
        raise FormError(f"manifest is {len(data)} bytes; a node takes at most {MAX_NODE_MANIFEST_BYTES}")
    manifest = verify_manifest(data, sig, pubkey)

    expected: dict[str, object] = {
        "artifact": env,
        "channel": channel,
        "sha256": hashlib.sha256(image).hexdigest(),
        "size": len(image),
    }
    if version is not None:
        expected["version"] = version
    for key, value in expected.items():
        if manifest[key] != value:
            raise ReleaseError(f"manifest {key} is {manifest[key]!r}, the release has {value!r}")
    if len(manifest["version"]) > MAX_IMAGE_VERSION_LEN:
        raise ReleaseError(f"version {manifest['version']!r} is longer than an image can carry "
                           f"({MAX_IMAGE_VERSION_LEN} characters)")

    chip = ENV_CHIPS[env]
    _check_esp_image(image, chip, "firmware.bin")
    _check_esp_image(members["bootloader.bin"], chip, "bootloader.bin")
    if not members["partitions.bin"].startswith(PARTITION_TABLE_MAGIC):
        raise ReleaseError("partitions.bin is not a partition table (no 0xAA50 entry)")

    # fw_version.py compiles these in as C strings (NUL-terminated).
    if not embeds_c_string(image, public_key_b64(pubkey), BASE64_CHARS):
        raise ReleaseError("firmware.bin does not embed the release verify key: it was built "
                           "without SPOREPRINT_OTA_PUBKEY_B64, so the node cannot check manifests")
    if not embeds_c_string(image, manifest["version"], VERSION_CHARS):
        raise ReleaseError(f"firmware.bin was not built as version {manifest['version']!r} "
                           "(SPOREPRINT_FW_VERSION)")
    # The env (SP_FW_ARTIFACT) cannot be held to a whole string: the linker
    # stores a string that ends another as that string's tail, and "cam" is
    # the tail of the camera driver's "esp32 ll_cam". So: its own name
    # NUL-terminated, and no other image env's name as a whole string
    # (NUL on both sides, as every other env name sits in the real images).
    if env.encode("ascii") + b"\0" not in image:
        raise ReleaseError(f"firmware.bin does not name its env {env!r} (SP_FW_ARTIFACT)")
    others = [other for other in ENV_CHIPS
              if other != env and b"\0" + other.encode("ascii") + b"\0" in image]
    if others:
        raise ReleaseError(f"firmware.bin names the env {others[0]!r}, not {env!r} (SP_FW_ARTIFACT)")

    if pi_verifier is not None:
        try:
            pi_manifest = pi_verifier.verify(data, sig, pubkey)
        except Exception as e:  # noqa: BLE001 — any refusal is a failed release
            raise ReleaseError(f"the Pi's own verifier refuses the manifest: {e}") from None
        if dict(pi_manifest) != manifest:
            raise ReleaseError(f"verifiers disagree: the Pi read {pi_manifest!r}, this check {manifest!r}")
    return manifest


def zip_env(path: Path) -> str:
    """The env a release asset is named for: ``<env>.zip``."""
    if path.suffix != ".zip":
        raise ReleaseError("a release asset is named <env>.zip (give --env for a renamed file)")
    return path.name[: -len(".zip")]


def check_zip(path: Path, pubkey: Ed25519PublicKey, *, version: str | None,
              channel: str = "stable", pi_verifier=None, env: str | None = None) -> dict:
    """``<env>.zip`` as published (or any file name, given ``env``). Returns
    the manifest."""
    if env is None:
        env = zip_env(path)
    if env not in ENV_CHIPS:
        raise ReleaseError(f"{env!r} is not a firmware image env ({', '.join(ENV_CHIPS)})")
    members = _read_zip(path, zip_members(env))
    return check_image(members, env, pubkey, version=version, channel=channel,
                       pi_verifier=pi_verifier)


# ─── Command line ─────────────────────────────────────────────────────────


def _error(text: str) -> None:
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "error: "
    print(prefix + text, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("zips", nargs="*", type=Path, metavar="ENV.zip",
                        help="release zips to check")
    parser.add_argument("--pubkey-b64", help="the release verify key (base64, 32 bytes)")
    parser.add_argument("--version", help="the release version (tag firmware-v<version>)")
    parser.add_argument("--channel", default="stable", choices=CHANNELS)
    parser.add_argument("--pi-verifier", type=Path, default=None,
                        help="also verify with the Pi's server/app/cloud/ota_manifest.py")
    parser.add_argument("--expect-envs", default=None,
                        help="space- or comma-separated envs: exactly one zip each, no others")
    parser.add_argument("--env", choices=sorted(ENV_CHIPS), default=None,
                        help="the env of a single zip whose file name is not <env>.zip")
    parser.add_argument("--print-pubkey", action="store_true",
                        help="print the public key of the private key in $OTA_SIGNING_KEY")
    args = parser.parse_args(argv)

    if args.print_pubkey:
        if args.zips:
            parser.error("--print-pubkey takes no zips")
        secret = os.environ.get("OTA_SIGNING_KEY", "")
        if not secret.strip():
            _error("OTA_SIGNING_KEY is empty: refusing to release unsigned firmware")
            return 1
        try:
            print(derive_public_key_b64(secret))
        except ReleaseError as e:
            _error(f"OTA_SIGNING_KEY: {e}")
            return 1
        return 0

    if not args.zips:
        parser.error("give at least one <env>.zip")
    if args.env is not None and len(args.zips) != 1:
        parser.error("--env names the env of exactly one zip")
    if not args.pubkey_b64:
        parser.error("--pubkey-b64 is required")
    try:
        pubkey = load_public_key(args.pubkey_b64)
        pi = load_pi_verifier(args.pi_verifier) if args.pi_verifier else None
    except ReleaseError as e:
        _error(str(e))
        return 1

    failed = False
    if args.expect_envs is not None:
        wanted = sorted(args.expect_envs.replace(",", " ").split())
        got = sorted(args.env or p.name.removesuffix(".zip") for p in args.zips)
        if got != wanted:
            _error(f"release zips are {got}, expected one per env {wanted}")
            failed = True

    for path in args.zips:
        try:
            m = check_zip(path, pubkey, version=args.version, channel=args.channel,
                          pi_verifier=pi, env=args.env)
        except ReleaseError as e:
            _error(f"{path.name}: {e}")
            failed = True
            continue
        print(f"ok {path.name}: {m['artifact']} {m['version']} on {m['channel']}, "
              f"sha256 {m['sha256']}, {m['size']} bytes, signed {m['published_at']}; "
              "the image embeds the verify key"
              + ("; the Pi's verifier agrees" if pi is not None else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
