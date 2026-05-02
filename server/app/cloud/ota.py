"""Pi server OTA self-update pipeline.

Pipeline: download bundle + signature → verify Ed25519 → extract to
staging → atomic-swap /opt/sporeprint/current → systemctl restart.
Failures never touch the running install; they bail in staging.

Security posture:
  - SSRF: hostname allowlist before any HTTPS request fires.
  - Signature verified BEFORE extraction (zip-slip / symlink defense).
  - Tar safety: per-member walk rejects absolute paths, .. traversal,
    symlinks/hardlinks/specials, and strips suid/sgid/sticky bits.
  - Atomic promote: sibling-symlink rename is atomic on POSIX.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# SSRF guard — the only host we'll talk to for firmware bundles.
_OTA_HOSTNAME = "updates.sporeprint.ai"
_OTA_BASE_URL = f"https://{_OTA_HOSTNAME}/firmware"

_VALID_CHANNELS = {"stable", "beta", "dev"}

# vX.Y.Z[-suffix]; forbids slashes / leading dashes that could escape the
# URL path or the staging directory.
_VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.-]+)?$")

_DEFAULT_INSTALL_ROOT = Path(os.environ.get("SPOREPRINT_INSTALL_ROOT", "/opt/sporeprint"))
_DEFAULT_STATE_DIR = Path(os.environ.get("SPOREPRINT_OTA_STATE_DIR", "/var/lib/sporeprint/ota"))

# Real Pi bundles are 5-15 MB; 50 MB gives headroom, bigger bails before
# download to avoid filling the SD card.
_MAX_BUNDLE_BYTES = 50 * 1024 * 1024

_DOWNLOAD_TIMEOUT_S = 120
_DOWNLOAD_CONNECT_TIMEOUT_S = 15

_SYSTEMD_UNIT = os.environ.get("SPOREPRINT_SYSTEMD_UNIT", "sporeprint-server")


class OTAError(Exception):
    """OTA pipeline failure. The running install is never touched on
    failure — a failure state is persisted to state.json and the staged
    tree is left in place for inspection."""


def _load_pinned_pubkey():
    # Late imports — keep this module loadable even if cryptography fails.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    from ..config import settings as _settings  # type: ignore

    raw = getattr(_settings, "ota_pubkey_b64", "") or os.environ.get(
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
    # Atomic rename over state.json so concurrent readers never see a half-written file.
    path = _state_dir() / "state.json"
    tmp = path.with_suffix(".json.tmp")
    payload = {**state, "ts": time.time()}
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


def _validate_inputs(version: str, channel: str) -> None:
    if channel not in _VALID_CHANNELS:
        raise OTAError(
            f"channel must be one of {sorted(_VALID_CHANNELS)}, got {channel!r}"
        )
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise OTAError(
            f"version must match {_VERSION_RE.pattern!r}, got {version!r}"
        )


def _bundle_url(channel: str, version: str) -> str:
    return f"{_OTA_BASE_URL}/{channel}/{version}.tar.gz"


def _signature_url(channel: str, version: str) -> str:
    return f"{_OTA_BASE_URL}/{channel}/{version}.tar.gz.sig"


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
            if resp.status_code != 200:
                raise OTAError(
                    f"download {url} returned HTTP {resp.status_code}"
                )
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
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
    from cryptography.exceptions import InvalidSignature

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


def _safe_extract_tar(bundle_path: Path, dest: Path) -> None:
    # Manual member walk instead of tarfile.extractall(filter='data') so
    # static-analysis can see the path-traversal / symlink rejection
    # explicitly. (filter='data' is good but doesn't show up in audit tools.)
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

            # Strip suid/sgid/sticky — tarfile honors mode bits by default.
            member.mode = member.mode & 0o755

            tf.extract(member, path=dest)


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
    subprocess.run(
        ["sudo", "systemctl", "restart", "--no-block", _SYSTEMD_UNIT],
        check=False,
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


async def run_ota_update(version: str, channel: str) -> dict:
    """End-to-end OTA pipeline. Returns a state dict and persists it to
    /var/lib/sporeprint/ota/state.json. On failure `ok=False` and `step`
    names the stage that failed; the running install is never touched.
    Emits `ota_step` events to the cloud at every stage (fire-and-forget).
    """

    state: dict = {
        "version": version,
        "channel": channel,
        "step": "validate",
        "ok": False,
    }
    _write_state(state)

    try:
        _validate_inputs(version, channel)

        # Pre-flight pubkey check — fail fast before downloading 15 MB.
        _load_pinned_pubkey()

        state["step"] = "download"
        _write_state(state)

        incoming = _state_dir() / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        bundle_path = incoming / f"{version}.tar.gz"
        sig_path = incoming / f"{version}.tar.gz.sig"

        for p in (bundle_path, sig_path):
            if p.exists():
                p.unlink()

        await _emit_step(
            "download_started",
            version=version,
            channel=channel,
            url=_bundle_url(channel, version),
        )
        await _download_to(_bundle_url(channel, version), bundle_path)
        # Ed25519 sig is exactly 64 bytes; cap tightly.
        await _download_to(_signature_url(channel, version), sig_path, max_bytes=512)
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
        await asyncio.to_thread(_verify_signature, bundle_path, sig_path)
        await _emit_step("verify_complete", version=version, channel=channel)

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
            "OTA update succeeded: version=%s channel=%s staging=%s",
            version, channel, staging,
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
