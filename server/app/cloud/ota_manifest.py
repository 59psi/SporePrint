"""Signed OTA release manifest: format, signing and verification.

A Pi-server release publishes four files under
``https://updates.sporeprint.ai/firmware/{channel}/``::

    {version}.tar.gz              the bundle
    {version}.tar.gz.sig          legacy: raw Ed25519 signature over the bundle
                                  bytes (only covers the bytes, not the
                                  version or channel; kept for older Pis)
    {version}.manifest.json       the manifest, in canonical form (below)
    {version}.manifest.json.sig   raw 64-byte Ed25519 signature over exactly
                                  the manifest file's bytes

Both signatures come from the same Ed25519 key, the one pinned on every Pi
(``SPOREPRINT_OTA_PUBKEY_B64``).

Manifest v1. Every key is required and no other key is allowed:

    schema        "sporeprint.ota.manifest.v1"
    artifact      what the bundle is: "sporeprint-server" for the Pi server
    version       release version, same grammar as the OTA command
    channel       "stable" | "beta" | "dev"
    sha256        lowercase hex SHA-256 of the bundle
    size          bundle length in bytes (a JSON integer)
    published_at  UTC signing time, "YYYY-MM-DDTHH:MM:SSZ"

Canonical bytes: ``json.dumps(m, sort_keys=True, separators=(",", ":"),
ensure_ascii=True)`` encoded as ASCII, with no trailing newline. Every value
is an ASCII string from a fixed grammar or a non-negative integer, so this is
a strict subset of RFC 8785 (JCS). The verifier re-encodes what it parsed and
requires the result to equal the signed bytes. That rejects duplicate keys,
whitespace or key-order variants, floats (``1.0``), escapes and BOMs, so each
manifest has exactly one valid byte string. The ``schema`` value also
separates manifest signatures from bundle signatures: a gzip tarball can
never parse as a manifest.

This module needs only the standard library and ``cryptography`` and has no
package-relative imports. ``scripts/sign-ota-bundle.py`` and the private
repo's release workflow load it by file path, so releases are signed and
checked by the same code the Pi runs. ``server/tests/fixtures/
ota_manifest_vectors.json`` pins the v1 bytes and signatures. A copy of that
file lives in the release repo, so both sides check the same bytes. Any
format change needs a new ``schema`` value; v1 bytes never change.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SCHEMA = "sporeprint.ota.manifest.v1"
ARTIFACT_PI_SERVER = "sporeprint-server"
CHANNELS: tuple[str, ...] = ("stable", "beta", "dev")
FIELDS = frozenset(
    {"schema", "artifact", "version", "channel", "sha256", "size", "published_at"}
)

# vX.Y.Z[-suffix]: no slashes or leading dashes, so a version can never
# leave its URL path segment or the staging directory. Always matched with
# fullmatch(): a `$` anchor would accept a trailing newline.
VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.-]+)?")
MAX_VERSION_LEN = 64

MAX_MANIFEST_BYTES = 4096
SIGNATURE_BYTES = 64
# Largest integer every JSON parser holds exactly.
MAX_SIZE = 2**53 - 1

_ARTIFACT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PUBLISHED_AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_PUBLISHED_AT_FMT = "%Y-%m-%dT%H:%M:%SZ"


class ManifestError(ValueError):
    """The manifest is malformed, not canonical, or not validly signed."""


def is_valid_version(version: object) -> bool:
    return (
        isinstance(version, str)
        and len(version) <= MAX_VERSION_LEN
        and VERSION_RE.fullmatch(version) is not None
    )


def _require_str(manifest: Mapping, key: str) -> str:
    value = manifest[key]
    if not isinstance(value, str):
        raise ManifestError(f"manifest {key} must be a string, got {type(value).__name__}")
    return value


def validate(manifest: Mapping) -> dict:
    """Check the key set and every value. Returns a plain-dict copy."""
    if not isinstance(manifest, Mapping):
        raise ManifestError("manifest must be a JSON object")
    keys = set(manifest)
    if keys != FIELDS:
        missing = sorted(FIELDS - keys)
        extra = sorted(str(k) for k in keys - FIELDS)
        raise ManifestError(f"manifest keys wrong (missing {missing}, unexpected {extra})")

    if _require_str(manifest, "schema") != SCHEMA:
        raise ManifestError(f"manifest schema must be {SCHEMA!r}, got {manifest['schema']!r}")
    if not _ARTIFACT_RE.fullmatch(_require_str(manifest, "artifact")):
        raise ManifestError(f"manifest artifact {manifest['artifact']!r} is not a valid name")
    if not is_valid_version(_require_str(manifest, "version")):
        raise ManifestError(f"manifest version {manifest['version']!r} is not a valid version")
    if _require_str(manifest, "channel") not in CHANNELS:
        raise ManifestError(f"manifest channel must be one of {list(CHANNELS)}, got {manifest['channel']!r}")
    if not _SHA256_RE.fullmatch(_require_str(manifest, "sha256")):
        raise ManifestError("manifest sha256 must be 64 lowercase hex digits")

    size = manifest["size"]
    # bool is an int subclass; True must not pass as a size of 1.
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_SIZE:
        raise ManifestError(f"manifest size must be an integer in [0, {MAX_SIZE}], got {size!r}")

    published_at = _require_str(manifest, "published_at")
    if not _PUBLISHED_AT_RE.fullmatch(published_at):
        raise ManifestError(f"manifest published_at must be UTC {_PUBLISHED_AT_FMT!r}, got {published_at!r}")
    try:
        datetime.strptime(published_at, _PUBLISHED_AT_FMT)
    except ValueError as e:
        raise ManifestError(f"manifest published_at is not a real time: {e}") from None

    return {key: manifest[key] for key in sorted(FIELDS)}


def canonical_bytes(manifest: Mapping) -> bytes:
    """The exact bytes that get signed (see the module docstring)."""
    checked = validate(manifest)
    return json.dumps(
        checked, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def format_published_at(when: datetime) -> str:
    if when.tzinfo is None:
        raise ManifestError("published_at needs a timezone-aware datetime")
    return when.astimezone(timezone.utc).strftime(_PUBLISHED_AT_FMT)


def build(
    *,
    artifact: str,
    version: str,
    channel: str,
    sha256: str,
    size: int,
    published_at: str,
) -> dict:
    return validate(
        {
            "schema": SCHEMA,
            "artifact": artifact,
            "version": version,
            "channel": channel,
            "sha256": sha256,
            "size": size,
            "published_at": published_at,
        }
    )


def file_digest(path: Path) -> tuple[str, int]:
    """``(sha256 hex, size)`` of a file, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sign(manifest: Mapping, private_key: Ed25519PrivateKey) -> tuple[bytes, bytes]:
    """``(canonical manifest bytes, 64-byte signature)``."""
    data = canonical_bytes(manifest)
    return data, private_key.sign(data)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    seen: dict = {}
    for key, value in pairs:
        if key in seen:
            raise ManifestError(f"manifest repeats key {key!r}")
        seen[key] = value
    return seen


def _reject_float(text: str):
    raise ManifestError(f"manifest holds a non-integer number {text!r}")


def _parse(data: bytes) -> dict:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ManifestError("manifest is not ASCII") from None
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest is not valid JSON: {e}") from None
    if not isinstance(parsed, dict):
        raise ManifestError("manifest must be a JSON object")
    return parsed


def verify(
    manifest_bytes: bytes, signature: bytes, public_key: Ed25519PublicKey
) -> dict:
    """Verify the signature over the exact bytes, then parse and require the
    canonical form. Returns the manifest; raises ManifestError otherwise.

    Checks only the format. Whether the manifest fits the request (artifact,
    version, channel, anti-rollback) is the caller's policy
    (``app/cloud/ota.py``).
    """
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ManifestError(
            f"manifest is {len(manifest_bytes)} bytes, max is {MAX_MANIFEST_BYTES}"
        )
    if len(signature) != SIGNATURE_BYTES:
        raise ManifestError(
            f"manifest signature wrong length: expected {SIGNATURE_BYTES} bytes "
            f"(Ed25519), got {len(signature)}"
        )
    try:
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature:
        raise ManifestError(
            "manifest signature verification FAILED — not signed by the pinned key"
        ) from None
    manifest = _parse(manifest_bytes)
    if canonical_bytes(manifest) != manifest_bytes:
        raise ManifestError("manifest is signed but not in canonical form — refusing")
    return validate(manifest)
