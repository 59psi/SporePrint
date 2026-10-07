"""Pi server OTA self-update pipeline.

Pipeline: fetch + verify the signed release manifest → download the bundle
→ check its sha256/size against the manifest → extract to staging →
atomic-swap /opt/sporeprint/current → systemctl restart. Failures never
touch the running install; they bail before promote.

What is trusted (see ``ota_manifest.py`` for the format):
  - The manifest ``{version}.manifest.json`` + ``.sig`` is verified against
    the locally pinned Ed25519 key (``SPOREPRINT_OTA_PUBKEY_B64`` / Settings).
    A key the cloud sends in the OTA command (``ota_pubkey``) is ignored, so
    a compromised cloud or relay can only ask for a genuine signed release.
  - The manifest binds artifact, version, channel, sha256 and size. The Pi
    requires version == the requested version, channel == its configured
    ``SPOREPRINT_OTA_CHANNEL`` (default stable), and version >= the installed
    version / recorded floor (anti-rollback) unless the operator sets
    ``SPOREPRINT_OTA_ALLOW_DOWNGRADE=true`` on the Pi.
  - Legacy releases (bundle ``.sig`` only, no manifest) are refused unless
    ``SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE=true``. A manifest that exists
    but fails verification is never a reason to fall back.

Security posture:
  - SSRF: hostname allowlist before any HTTPS request fires.
  - Signature + digest verified BEFORE extraction (zip-slip / symlink defense).
  - Tar safety: per-member walk rejects absolute paths, .. traversal,
    symlinks/hardlinks/specials, and strips suid/sgid/sticky bits.
  - Atomic promote: sibling-symlink rename is atomic on POSIX.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..config import settings
from . import ota_manifest
from .ota_manifest import ManifestError
from .version import server_version, version_triple

log = logging.getLogger(__name__)

# SSRF guard — the only host we'll talk to for firmware bundles.
_OTA_HOSTNAME = "updates.sporeprint.ai"
_OTA_BASE_URL = f"https://{_OTA_HOSTNAME}/firmware"

_VALID_CHANNELS = set(ota_manifest.CHANNELS)

# vX.Y.Z[-suffix]; forbids slashes / leading dashes that could escape the
# URL path or the staging directory. Shared with the manifest format.
_VERSION_RE = ota_manifest.VERSION_RE

_DEFAULT_INSTALL_ROOT = Path(os.environ.get("SPOREPRINT_INSTALL_ROOT", "/opt/sporeprint"))
_DEFAULT_STATE_DIR = Path(os.environ.get("SPOREPRINT_OTA_STATE_DIR", "/var/lib/sporeprint/ota"))

# Real Pi bundles are 5-15 MB; 50 MB gives headroom, bigger bails before
# download to avoid filling the SD card.
_MAX_BUNDLE_BYTES = 50 * 1024 * 1024
# Ed25519 sigs are exactly 64 bytes; cap tightly.
_MAX_SIG_BYTES = 512

# HTTP statuses that mean "this release has no manifest" (object stores
# answer 404, or 403 when the bucket hides listing). Only these let a Pi with
# SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE fall back to the bundle-only .sig.
_ABSENT_STATUSES = frozenset({403, 404, 410})

# Highest version this Pi has installed through OTA — the anti-rollback
# floor, kept in the OTA state dir so it does not depend on how the running
# tree reports its own version.
_FLOOR_FILE = "version_floor.json"

_DOWNLOAD_TIMEOUT_S = 120
_DOWNLOAD_CONNECT_TIMEOUT_S = 15

_SYSTEMD_UNIT = os.environ.get("SPOREPRINT_SYSTEMD_UNIT", "sporeprint-server")

# Present in every Docker container. The shipped install (install.sh →
# docker compose) runs the server as a non-root user in an immutable image
# with no systemd, no sudo and no /opt/sporeprint layout, so the swap +
# `systemctl restart` pipeline below can never apply there.
_DOCKERENV = Path("/.dockerenv")


class OTAError(Exception):
    """OTA pipeline failure. The running install is never touched on
    failure — a failure state is persisted to state.json and the staged
    tree is left in place for inspection."""


class OTANotFound(OTAError):
    """The release host answered 403/404/410: the file is not published."""


def _load_pinned_pubkey() -> Ed25519PublicKey:
    raw = getattr(settings, "ota_pubkey_b64", "") or os.environ.get(
        "SPOREPRINT_OTA_PUBKEY", ""
    )
    if not raw:
        raise OTAError(
            "OTA public key not configured "
            "(set SPOREPRINT_OTA_PUBKEY or settings.ota_pubkey_b64 to the "
            "base64-encoded 32-byte Ed25519 public key)"
        )
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as e:
        raise OTAError(f"OTA pubkey is not valid base64: {e}") from e
    if len(decoded) != 32:
        raise OTAError(
            f"OTA pubkey wrong length: expected 32 bytes (Ed25519), got {len(decoded)}"
        )
    try:
        return Ed25519PublicKey.from_public_bytes(decoded)
    except Exception as e:
        raise OTAError(f"OTA pubkey rejected by cryptography: {e}") from e


def _state_dir() -> Path:
    d = _DEFAULT_STATE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_state(state: dict) -> None:
    """Persist pipeline progress to state.json (atomic rename).

    Diagnostic only — never fatal. An unwritable state dir used to raise
    from OUTSIDE the pipeline's try (no `failed` event, cloud stuck on an
    accepted OTA) and again from inside the except handlers.
    """
    try:
        path = _state_dir() / "state.json"
        tmp = path.with_suffix(".json.tmp")
        payload = {**state, "ts": time.time()}
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)
    except OSError as e:
        log.warning("OTA: could not persist state.json: %s", e)


def _validate_inputs(version: str, channel: str) -> None:
    """Format checks only (the channel/version can be used in a URL)."""
    if channel not in _VALID_CHANNELS:
        raise OTAError(
            f"channel must be one of {sorted(_VALID_CHANNELS)}, got {channel!r}"
        )
    if not ota_manifest.is_valid_version(version):
        raise OTAError(
            f"version must match {_VERSION_RE.pattern!r}, got {version!r}"
        )


def _configured_channel() -> str:
    return getattr(settings, "ota_channel", "stable") or "stable"


def _downgrade_allowed() -> bool:
    return bool(getattr(settings, "ota_allow_downgrade", False))


def _legacy_signature_allowed() -> bool:
    return bool(getattr(settings, "ota_allow_legacy_signature", False))


def _check_channel(channel: str) -> None:
    configured = _configured_channel()
    if channel != configured:
        raise OTAError(
            f"this Pi follows the {configured!r} OTA channel; refusing a "
            f"{channel!r} release (set SPOREPRINT_OTA_CHANNEL={channel} on the "
            "Pi to switch channels)"
        )


def _read_version_floor() -> str | None:
    """The version recorded by the last successful OTA, or None."""
    try:
        data = json.loads((_DEFAULT_STATE_DIR / _FLOOR_FILE).read_text())
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if ota_manifest.is_valid_version(version) else None


def _write_version_floor(version: str) -> None:
    """Record the version just promoted. Diagnostic-grade like state.json:
    a write failure leaves the installed-version check in charge."""
    try:
        path = _state_dir() / _FLOOR_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": version, "ts": time.time()}))
        tmp.replace(path)
    except OSError as e:
        log.warning("OTA: could not record the anti-rollback floor: %s", e)


def _installed_floor() -> tuple[tuple[int, int, int] | None, str]:
    """``(triple, label)`` of the lowest version an OTA may install: the
    higher of the running server's version and the recorded OTA floor."""
    candidates = []
    running = server_version()
    if version_triple(running) is not None:
        candidates.append((version_triple(running), running))
    recorded = _read_version_floor()
    if recorded is not None and version_triple(recorded) is not None:
        candidates.append((version_triple(recorded), recorded))
    if not candidates:
        return None, running
    return max(candidates, key=lambda c: c[0])


def _check_rollback(version: str) -> None:
    """Anti-rollback. A genuinely signed release is still refused when it
    is older than what this Pi runs: an older release can carry
    vulnerabilities fixed since. Pre-release suffixes are not ordered
    (X.Y.Z only), because the shipped tree reports its bare pyproject
    version, so 5.1.0-beta.2 → 5.1.0 → 5.1.0-beta.1 all count as equal."""
    if _downgrade_allowed():
        return
    floor, label = _installed_floor()
    requested = version_triple(version)
    if floor is None:
        raise OTAError(
            f"installed version {label!r} is unknown, so OTA cannot rule out "
            "a downgrade — set SPOREPRINT_OTA_ALLOW_DOWNGRADE=true on the Pi "
            "to update anyway"
        )
    if requested is None or requested < floor:
        raise OTAError(
            f"refusing OTA downgrade from {label} to {version} — set "
            "SPOREPRINT_OTA_ALLOW_DOWNGRADE=true on the Pi if this is intended"
        )


def self_update_unsupported_reason() -> str | None:
    """Why this install cannot self-update, or None when it can.

    Checked before the OTA command is acknowledged so the cloud gets a clear
    failure instead of an accepted update that never happens.
    """
    if _DOCKERENV.exists():
        return (
            "Pi self-update is not supported in the Docker deployment — update "
            "on the Pi with `git pull && ./install.sh`"
        )
    current = _DEFAULT_INSTALL_ROOT / "current"
    if not current.is_symlink():
        return (
            f"Pi self-update needs the {_DEFAULT_INSTALL_ROOT}/current install "
            "layout (systemd unit), which this Pi does not use"
        )
    return None


def validate_request(version: str, channel: str) -> str | None:
    """Pre-ack validation of an OTA command. Returns an error or None.

    Format checks, then the policy the signed manifest is held to later, so
    a command that can never succeed is refused before it is acknowledged:
    the channel must be the one this Pi follows, and the version must not be
    older than the installed one (anti-rollback, unless the operator set
    SPOREPRINT_OTA_ALLOW_DOWNGRADE on the Pi).
    """
    try:
        _validate_inputs(version, channel)
        _check_channel(channel)
        _check_rollback(version)
    except OTAError as e:
        return str(e)
    return None


def _check_manifest_policy(manifest: dict, version: str, channel: str) -> None:
    """Hold a verified manifest to this request and this Pi."""
    if manifest["artifact"] != ota_manifest.ARTIFACT_PI_SERVER:
        raise OTAError(
            f"manifest is for {manifest['artifact']!r}, not "
            f"{ota_manifest.ARTIFACT_PI_SERVER!r} — refusing"
        )
    if manifest["version"] != version:
        raise OTAError(
            f"manifest version {manifest['version']!r} != requested {version!r} "
            "— refusing"
        )
    if manifest["channel"] != channel:
        raise OTAError(
            f"manifest channel {manifest['channel']!r} != requested {channel!r} "
            "— refusing"
        )
    _check_channel(manifest["channel"])
    if not 0 < manifest["size"] <= _MAX_BUNDLE_BYTES:
        raise OTAError(
            f"manifest declares a {manifest['size']}-byte bundle, allowed is "
            f"1..{_MAX_BUNDLE_BYTES}"
        )
    _check_rollback(manifest["version"])


def _bundle_url(channel: str, version: str) -> str:
    return f"{_OTA_BASE_URL}/{channel}/{version}.tar.gz"


def _signature_url(channel: str, version: str) -> str:
    return f"{_OTA_BASE_URL}/{channel}/{version}.tar.gz.sig"


def _manifest_url(channel: str, version: str) -> str:
    return f"{_OTA_BASE_URL}/{channel}/{version}.manifest.json"


def _manifest_signature_url(channel: str, version: str) -> str:
    return f"{_OTA_BASE_URL}/{channel}/{version}.manifest.json.sig"


async def _download_to(
    url: str, dest: Path, *, max_bytes: int = _MAX_BUNDLE_BYTES
) -> None:
    # Defense in depth — redirects are disabled so this allowlist is the
    # sole gate, but we re-check the resolved host anyway.
    parsed_host = httpx.URL(url).host
    if parsed_host != _OTA_HOSTNAME:
        raise OTAError(
            f"refused: download host {parsed_host!r} is not on the OTA allowlist"
        )

    timeout = httpx.Timeout(
        timeout=_DOWNLOAD_TIMEOUT_S, connect=_DOWNLOAD_CONNECT_TIMEOUT_S
    )
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        verify=True,
    ) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code in _ABSENT_STATUSES:
                raise OTANotFound(
                    f"download {url} returned HTTP {resp.status_code}"
                )
            if resp.status_code != 200:
                raise OTAError(
                    f"download {url} returned HTTP {resp.status_code}"
                )
            content_length = resp.headers.get("content-length")
            if content_length:
                try:
                    declared = int(content_length)
                except ValueError:
                    raise OTAError(
                        f"download {url} sent a bad Content-Length {content_length!r}"
                    ) from None
                if declared > max_bytes:
                    raise OTAError(
                        f"bundle declares {content_length} bytes, max is {max_bytes}"
                    )
            written = 0
            with dest.open("wb") as out:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise OTAError(
                            f"bundle exceeded max size {max_bytes} mid-stream"
                        )
                    out.write(chunk)


def _verify_signature(bundle_path: Path, sig_path: Path) -> None:
    """Legacy check: the raw Ed25519 signature over the bundle bytes. Proves
    the bytes are a release, not which version or channel."""
    pubkey = _load_pinned_pubkey()

    sig_bytes = sig_path.read_bytes()
    if len(sig_bytes) != 64:
        raise OTAError(
            f"signature wrong length: expected 64 bytes (Ed25519), got {len(sig_bytes)}"
        )

    bundle_bytes = bundle_path.read_bytes()
    try:
        pubkey.verify(sig_bytes, bundle_bytes)
    except InvalidSignature:
        raise OTAError(
            "signature verification FAILED — bundle did not match pinned key"
        ) from None
    except Exception as e:
        raise OTAError(f"signature verification raised: {type(e).__name__}: {e}") from e


def _verify_manifest(manifest_path: Path, sig_path: Path,
                     pubkey: Ed25519PublicKey) -> dict:
    try:
        return ota_manifest.verify(
            manifest_path.read_bytes(), sig_path.read_bytes(), pubkey
        )
    except ManifestError as e:
        raise OTAError(str(e)) from None


def _verify_bundle_digest(bundle_path: Path, manifest: dict) -> None:
    """The downloaded bundle must be exactly the one the manifest signs."""
    sha256, size = ota_manifest.file_digest(bundle_path)
    if size != manifest["size"]:
        raise OTAError(
            f"bundle is {size} bytes, the signed manifest says {manifest['size']} "
            "— refusing"
        )
    if not hmac.compare_digest(sha256, manifest["sha256"]):
        raise OTAError(
            "bundle sha256 does not match the signed manifest — refusing"
        )


def _safe_extract_tar(bundle_path: Path, dest: Path) -> None:
    # Manual member walk so static analysis can see the path-traversal /
    # link rejection explicitly, with the stdlib 'data' filter applied on top
    # of it (it also refuses absolute/escaping paths and links, and drops
    # group/other write bits). Unfiltered extract() is deprecated from 3.12
    # and changes behaviour in 3.14; 'data' exists from 3.11.4 / 3.12, and
    # the manual walk alone still guards an older 3.11.
    extract_kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
    dest.mkdir(parents=True, exist_ok=True)
    dest_real = dest.resolve()

    with tarfile.open(bundle_path, "r:gz") as tf:
        for member in tf.getmembers():
            name = member.name

            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise OTAError(
                    f"tar member {name!r} attempted path-traversal — refusing"
                )

            if not (member.isreg() or member.isdir()):
                if member.issym():
                    kind = "symlink"
                elif member.islnk():
                    kind = "hardlink"
                else:
                    kind = "special-file"
                raise OTAError(
                    f"tar member {name!r} is a {kind} — refusing"
                )

            target = (dest_real / name).resolve()
            if dest_real not in target.parents and target != dest_real:
                raise OTAError(
                    f"tar member {name!r} resolves outside the staging dir — refusing"
                )

            # Strip suid/sgid/sticky and group/other write.
            member.mode = member.mode & 0o755

            tf.extract(member, path=dest, **extract_kwargs)


def _stage_install(bundle_path: Path, version: str) -> Path:
    staging = _DEFAULT_INSTALL_ROOT / "staging" / version
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    _safe_extract_tar(bundle_path, staging)
    return staging


def _promote(staging: Path, version: str) -> None:
    """Atomically swap /opt/sporeprint/current -> staging.

    Split out from the restart so a `promote_complete` event can ship before
    systemctl pulls the rug from under our async tasks.
    """
    current = _DEFAULT_INSTALL_ROOT / "current"
    new_link = _DEFAULT_INSTALL_ROOT / f"current.new.{version}"

    if new_link.exists() or new_link.is_symlink():
        new_link.unlink()
    new_link.symlink_to(staging, target_is_directory=True)
    new_link.replace(current)


def _restart_unit() -> None:
    # --no-block returns before the restart completes so the ack can flush.
    # Static argv (no shell) — _SYSTEMD_UNIT is a configured constant, never user input.
    # -n: never prompt — without NOPASSWD sudo this fails fast instead of
    # hanging, and the non-zero exit is reported instead of "complete, ok".
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "--no-block", _SYSTEMD_UNIT],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as e:
        raise OTAError(f"restart failed: {e}") from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        raise OTAError(
            f"restart failed: systemctl exited {result.returncode}"
            + (f" ({detail})" if detail else "")
        )


def _count_extracted_files(staging: Path) -> int:
    try:
        return sum(1 for p in staging.rglob("*") if p.is_file())
    except OSError:
        return -1


async def _emit_step(step: str, **fields) -> None:
    """Fire-and-forget cloud progress emit. Never raises — a cloud-unreachable
    Pi must still complete its OTA. Late-imports forward_event to avoid an
    import cycle and so test envs without socketio pay no import cost.
    """
    try:
        from .service import forward_event
        await forward_event("ota_step", {"step": step, **fields})
    except Exception as e:
        log.warning("OTA progress emit failed (step=%s): %s", step, e)


async def _fetch_manifest(version: str, channel: str, incoming: Path,
                          pubkey: Ed25519PublicKey) -> dict | None:
    """Download + verify the signed manifest and hold it to this request.

    Returns None only for a release with no manifest at all, and only when
    the operator allowed the legacy bundle-only signature. A manifest that
    exists but has no signature, a bad signature or the wrong contents
    always fails — never a fallback.
    """
    manifest_path = incoming / f"{version}.manifest.json"
    manifest_sig_path = incoming / f"{version}.manifest.json.sig"
    try:
        await _download_to(
            _manifest_url(channel, version), manifest_path,
            max_bytes=ota_manifest.MAX_MANIFEST_BYTES,
        )
    except OTANotFound:
        if not _legacy_signature_allowed():
            raise OTAError(
                f"release {version} on the {channel!r} channel has no signed "
                "manifest — refusing. Releases published before signed "
                "manifests carry only the bundle signature; set "
                "SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE=true on the Pi to accept "
                "one (version and channel are then not signed)"
            ) from None
        log.warning(
            "OTA: %s/%s has no signed manifest; accepting the legacy bundle "
            "signature because SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE is set",
            channel, version,
        )
        return None
    await _download_to(
        _manifest_signature_url(channel, version), manifest_sig_path,
        max_bytes=_MAX_SIG_BYTES,
    )
    manifest = await asyncio.to_thread(
        _verify_manifest, manifest_path, manifest_sig_path, pubkey
    )
    _check_manifest_policy(manifest, version, channel)
    return manifest


async def run_ota_update(version: str, channel: str) -> dict:
    """End-to-end OTA pipeline. Returns a state dict and persists it to
    /var/lib/sporeprint/ota/state.json. On failure `ok=False` and `step`
    names the stage that failed (validate | manifest | download | verify |
    stage | promote | restart); the running install is never touched before
    promote. Emits `ota_step` events to the cloud at every stage
    (fire-and-forget).
    """

    state: dict = {
        "version": version,
        "channel": channel,
        "step": "validate",
        "ok": False,
    }

    try:
        _write_state(state)
        _validate_inputs(version, channel)
        _check_channel(channel)

        # Pre-flight pubkey check — fail fast before downloading 15 MB.
        pubkey = _load_pinned_pubkey()
        _check_rollback(version)

        incoming = _state_dir() / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        bundle_path = incoming / f"{version}.tar.gz"
        sig_path = incoming / f"{version}.tar.gz.sig"
        for p in (
            bundle_path,
            sig_path,
            incoming / f"{version}.manifest.json",
            incoming / f"{version}.manifest.json.sig",
        ):
            if p.exists():
                p.unlink()

        state["step"] = "manifest"
        _write_state(state)
        manifest = await _fetch_manifest(version, channel, incoming, pubkey)
        if manifest is not None:
            state["verified_by"] = "manifest"
            state["sha256"] = manifest["sha256"]
            state["published_at"] = manifest["published_at"]
        else:
            state["verified_by"] = "legacy_signature"

        state["step"] = "download"
        _write_state(state)
        await _emit_step(
            "download_started",
            version=version,
            channel=channel,
            url=_bundle_url(channel, version),
        )
        if manifest is not None:
            # The signed size is the cap: a longer body is not this release.
            await _download_to(
                _bundle_url(channel, version), bundle_path,
                max_bytes=manifest["size"],
            )
        else:
            await _download_to(_bundle_url(channel, version), bundle_path)
            await _download_to(
                _signature_url(channel, version), sig_path,
                max_bytes=_MAX_SIG_BYTES,
            )
        bundle_size = bundle_path.stat().st_size
        await _emit_step(
            "download_complete",
            version=version,
            channel=channel,
            size_bytes=bundle_size,
        )

        state["step"] = "verify"
        state["bundle_size"] = bundle_size
        _write_state(state)

        # CPU-heavy verify runs off-loop so heartbeat / health endpoints
        # stay responsive on a Pi Zero.
        if manifest is not None:
            await asyncio.to_thread(_verify_bundle_digest, bundle_path, manifest)
        else:
            await asyncio.to_thread(_verify_signature, bundle_path, sig_path)
        await _emit_step(
            "verify_complete",
            version=version,
            channel=channel,
            verified_by=state["verified_by"],
        )

        state["step"] = "stage"
        _write_state(state)
        staging = await asyncio.to_thread(_stage_install, bundle_path, version)
        state["staging"] = str(staging)
        files_extracted = await asyncio.to_thread(_count_extracted_files, staging)
        await _emit_step(
            "extract_complete",
            version=version,
            channel=channel,
            files_extracted=files_extracted,
        )

        state["step"] = "promote"
        _write_state(state)
        await asyncio.to_thread(_promote, staging, version)
        # The new tree is live: it is the floor for the next OTA (also after
        # an operator-allowed downgrade, which lowers it on purpose).
        _write_version_floor(version)
        await _emit_step("promote_complete", version=version, channel=channel)

        state["step"] = "restart"
        _write_state(state)
        # Emit BEFORE systemctl — once it fires the event loop is gone.
        await _emit_step("restart_initiated", version=version, channel=channel)
        await asyncio.to_thread(_restart_unit)

        state["step"] = "complete"
        state["ok"] = True
        _write_state(state)
        log.info(
            "OTA update succeeded: version=%s channel=%s verified_by=%s staging=%s",
            version, channel, state["verified_by"], staging,
        )
        return state

    except OTAError as e:
        state["error"] = str(e)
        _write_state(state)
        log.error("OTA update FAILED at step=%s: %s", state.get("step"), e)
        await _emit_step(
            "failed",
            version=version,
            channel=channel,
            failed_at=state.get("step") or "unknown",
            error=str(e),
        )
        return state
    except Exception as e:
        state["error"] = f"unexpected: {type(e).__name__}: {e}"
        _write_state(state)
        log.exception("OTA update raised at step=%s", state.get("step"))
        await _emit_step(
            "failed",
            version=version,
            channel=channel,
            failed_at=state.get("step") or "unknown",
            error=f"unexpected: {type(e).__name__}: {e}",
        )
        return state
