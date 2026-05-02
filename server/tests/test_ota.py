"""OTA pipeline tests — input validation, Ed25519 verify, tar safety."""

from __future__ import annotations

import base64
import io
import os
import tarfile
from pathlib import Path

import pytest

from app.cloud import ota
from app.cloud.ota import (
    OTAError,
    _bundle_url,
    _safe_extract_tar,
    _signature_url,
    _validate_inputs,
    _verify_signature,
)


# ─── Input validation ─────────────────────────────────────────────────


def test_validate_inputs_rejects_bad_channel():
    with pytest.raises(OTAError, match="channel must be"):
        _validate_inputs("v1.2.3", "garbage")


def test_validate_inputs_rejects_path_traversal_in_version():
    with pytest.raises(OTAError, match="version must match"):
        _validate_inputs("../../etc/passwd", "stable")


def test_validate_inputs_rejects_url_smuggling():
    with pytest.raises(OTAError, match="version must match"):
        _validate_inputs("v1.2.3/../evil", "stable")


def test_validate_inputs_accepts_canonical_versions():
    _validate_inputs("3.4.10", "stable")
    _validate_inputs("v3.4.10", "stable")
    _validate_inputs("3.4.10-rc1", "beta")
    _validate_inputs("3.4.10.dev42", "dev")


def test_url_builders_pin_to_allowlisted_hostname():
    assert _bundle_url("stable", "3.4.10").startswith(
        "https://updates.sporeprint.ai/firmware/"
    )
    assert _signature_url("stable", "3.4.10").endswith(".tar.gz.sig")


# ─── Tar extraction safety ────────────────────────────────────────────


def _build_tar(members: list[tuple[str, bytes]], dest: Path) -> Path:
    bundle = dest / "test.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        for name, content in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return bundle


def _build_tar_with_member(info: tarfile.TarInfo, dest: Path) -> Path:
    bundle = dest / "test.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        tf.addfile(info, io.BytesIO(b""))
    return bundle


def test_safe_extract_rejects_absolute_path(tmp_path):
    bundle = _build_tar([("/etc/passwd", b"oops")], tmp_path)
    staging = tmp_path / "staging"
    with pytest.raises(OTAError, match="path-traversal"):
        _safe_extract_tar(bundle, staging)


def test_safe_extract_rejects_parent_traversal(tmp_path):
    bundle = _build_tar([("../../escape.txt", b"oops")], tmp_path)
    staging = tmp_path / "staging"
    with pytest.raises(OTAError, match="path-traversal"):
        _safe_extract_tar(bundle, staging)


def test_safe_extract_rejects_symlink(tmp_path):
    info = tarfile.TarInfo(name="link.txt")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    bundle = _build_tar_with_member(info, tmp_path)
    staging = tmp_path / "staging"
    with pytest.raises(OTAError, match="symlink"):
        _safe_extract_tar(bundle, staging)


def test_safe_extract_rejects_hardlink(tmp_path):
    info = tarfile.TarInfo(name="link.txt")
    info.type = tarfile.LNKTYPE
    info.linkname = "/etc/passwd"
    bundle = _build_tar_with_member(info, tmp_path)
    staging = tmp_path / "staging"
    with pytest.raises(OTAError, match="hardlink"):
        _safe_extract_tar(bundle, staging)


def test_safe_extract_strips_setuid_bits(tmp_path):
    bundle = tmp_path / "test.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        info = tarfile.TarInfo(name="run.sh")
        info.size = 4
        info.mode = 0o4755  # setuid set
        tf.addfile(info, io.BytesIO(b"echo"))
    staging = tmp_path / "staging"
    _safe_extract_tar(bundle, staging)
    extracted = staging / "run.sh"
    assert extracted.exists()
    # 0o4755 → 0o755 (setuid bit dropped, exec bits preserved)
    assert (extracted.stat().st_mode & 0o7777) == 0o755


def test_safe_extract_accepts_normal_files(tmp_path):
    bundle = _build_tar(
        [
            ("server/app.py", b"print('hello')"),
            ("server/main.py", b"main"),
            ("README.md", b"docs"),
        ],
        tmp_path,
    )
    staging = tmp_path / "staging"
    _safe_extract_tar(bundle, staging)
    assert (staging / "server" / "app.py").read_bytes() == b"print('hello')"
    assert (staging / "server" / "main.py").exists()
    assert (staging / "README.md").exists()


# ─── Ed25519 signature verification ──────────────────────────────────


def _generate_keypair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    sk = Ed25519PrivateKey.generate()
    pk_raw = sk.public_key().public_bytes_raw()
    return sk, base64.b64encode(pk_raw).decode("ascii")


def test_verify_signature_accepts_valid_signature(tmp_path, monkeypatch):
    sk, pk_b64 = _generate_keypair()
    monkeypatch.setenv("SPOREPRINT_OTA_PUBKEY", pk_b64)
    monkeypatch.setattr(ota, "_load_pinned_pubkey", ota._load_pinned_pubkey)

    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"any payload - what matters is the sig")
    sig = sk.sign(bundle.read_bytes())
    sig_path = tmp_path / "bundle.tar.gz.sig"
    sig_path.write_bytes(sig)

    # Settings cache lookup uses module attr; clear it for the test.
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", pk_b64)

    _verify_signature(bundle, sig_path)  # should not raise


def test_verify_signature_rejects_tampered_bundle(tmp_path, monkeypatch):
    sk, pk_b64 = _generate_keypair()
    monkeypatch.setenv("SPOREPRINT_OTA_PUBKEY", pk_b64)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", pk_b64)

    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"original payload")
    sig = sk.sign(bundle.read_bytes())
    sig_path = tmp_path / "bundle.tar.gz.sig"
    sig_path.write_bytes(sig)

    # Tamper AFTER signing.
    bundle.write_bytes(b"tampered payload")

    with pytest.raises(OTAError, match="signature verification FAILED"):
        _verify_signature(bundle, sig_path)


def test_verify_signature_rejects_wrong_size_signature(tmp_path, monkeypatch):
    _, pk_b64 = _generate_keypair()
    monkeypatch.setenv("SPOREPRINT_OTA_PUBKEY", pk_b64)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", pk_b64)

    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"any payload")
    sig_path = tmp_path / "bundle.tar.gz.sig"
    sig_path.write_bytes(b"not 64 bytes")

    with pytest.raises(OTAError, match="signature wrong length"):
        _verify_signature(bundle, sig_path)


def test_load_pubkey_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv("SPOREPRINT_OTA_PUBKEY", raising=False)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", "")
    with pytest.raises(OTAError, match="not configured"):
        ota._load_pinned_pubkey()


def test_load_pubkey_rejects_wrong_length(monkeypatch):
    bad = base64.b64encode(b"too short").decode("ascii")
    monkeypatch.setenv("SPOREPRINT_OTA_PUBKEY", bad)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", bad)
    with pytest.raises(OTAError, match="wrong length"):
        ota._load_pinned_pubkey()


# ─── End-to-end ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_ota_update_rejects_unknown_channel(monkeypatch, tmp_path):
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", tmp_path / "state")
    result = await ota.run_ota_update("3.4.10", "wat")
    assert result["ok"] is False
    assert "channel must be" in result["error"]
    assert result["step"] == "validate"


@pytest.mark.asyncio
async def test_run_ota_update_rejects_bad_version(monkeypatch, tmp_path):
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", tmp_path / "state")
    result = await ota.run_ota_update("../../passwd", "stable")
    assert result["ok"] is False
    assert "version must match" in result["error"]


@pytest.mark.asyncio
async def test_run_ota_update_fails_closed_without_pubkey(monkeypatch, tmp_path):
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", tmp_path / "state")
    monkeypatch.delenv("SPOREPRINT_OTA_PUBKEY", raising=False)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", "")
    result = await ota.run_ota_update("3.4.10", "stable")
    assert result["ok"] is False
    assert "not configured" in result["error"]
    # Critical: never made it to the download step.
    assert result["step"] in ("validate", "download")


# ─── Progress events forwarded to the cloud ─────────────────────────


def _seed_pubkey(monkeypatch):
    sk, pk_b64 = _generate_keypair()
    monkeypatch.setenv("SPOREPRINT_OTA_PUBKEY", pk_b64)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", pk_b64)
    return sk


@pytest.mark.asyncio
async def test_run_ota_update_emits_failed_step_when_pubkey_missing(
    monkeypatch, tmp_path
):
    """Pubkey unset => OTA fails closed and a `failed` event ships with
    `failed_at` set so the cloud admin can see WHERE it broke."""
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", tmp_path / "state")
    monkeypatch.delenv("SPOREPRINT_OTA_PUBKEY", raising=False)
    from app import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ota_pubkey_b64", "")

    seen: list[tuple[str, dict]] = []

    async def _capture(event_type, data):
        seen.append((event_type, dict(data)))

    # Patch the late-imported forward_event so _emit_step's import sees it.
    from app.cloud import service as _svc
    monkeypatch.setattr(_svc, "forward_event", _capture)

    result = await ota.run_ota_update("3.4.10", "stable")
    assert result["ok"] is False
    assert seen, "expected at least one ota_step event"
    last_type, last_data = seen[-1]
    assert last_type == "ota_step"
    assert last_data["step"] == "failed"
    assert last_data["failed_at"] in ("validate", "download")
    assert "not configured" in last_data["error"]
    assert last_data["version"] == "3.4.10"
    assert last_data["channel"] == "stable"


@pytest.mark.asyncio
async def test_run_ota_update_emits_every_step_on_success(
    monkeypatch, tmp_path
):
    """Mocked-network happy path — assert every progress event fires in
    order with the contract-defined payload keys."""
    sk = _seed_pubkey(monkeypatch)

    install_root = tmp_path / "opt"
    state_dir = tmp_path / "state"
    install_root.mkdir()
    state_dir.mkdir()
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", install_root)
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", state_dir)

    bundle_bytes_holder: dict[str, bytes] = {}
    members_dir = tmp_path / "members"
    members_dir.mkdir()
    bundle_src = _build_tar(
        [
            ("server/app.py", b"print('hi')"),
            ("server/__init__.py", b""),
            ("README.md", b"docs"),
        ],
        members_dir,
    )
    bundle_bytes_holder["bundle"] = bundle_src.read_bytes()
    bundle_bytes_holder["sig"] = sk.sign(bundle_bytes_holder["bundle"])

    async def _fake_download(url, dest, *, max_bytes=ota._MAX_BUNDLE_BYTES):
        body = (
            bundle_bytes_holder["sig"] if url.endswith(".sig")
            else bundle_bytes_holder["bundle"]
        )
        dest.write_bytes(body)

    monkeypatch.setattr(ota, "_download_to", _fake_download)
    monkeypatch.setattr(ota, "_restart_unit", lambda: None)

    seen: list[tuple[str, dict]] = []

    async def _capture(event_type, data):
        seen.append((event_type, dict(data)))

    from app.cloud import service as _svc
    monkeypatch.setattr(_svc, "forward_event", _capture)

    result = await ota.run_ota_update("3.4.10", "stable")
    assert result["ok"] is True, result

    assert all(t == "ota_step" for t, _ in seen)
    steps = [data["step"] for _, data in seen]
    assert steps == [
        "download_started",
        "download_complete",
        "verify_complete",
        "extract_complete",
        "promote_complete",
        "restart_initiated",
    ]

    by_step = {data["step"]: data for _, data in seen}
    assert by_step["download_started"]["url"].startswith(
        "https://updates.sporeprint.ai/firmware/"
    )
    assert by_step["download_started"]["version"] == "3.4.10"
    assert by_step["download_started"]["channel"] == "stable"
    assert by_step["download_complete"]["size_bytes"] == len(
        bundle_bytes_holder["bundle"]
    )
    assert by_step["extract_complete"]["files_extracted"] == 3


@pytest.mark.asyncio
async def test_emit_step_swallows_cloud_failures(monkeypatch):
    """If the cloud connector raises, _emit_step must log + return —
    the OTA pipeline is not allowed to fail because the relay is down."""
    async def _boom(*args, **kwargs):
        raise RuntimeError("cloud is having a bad day")

    from app.cloud import service as _svc
    monkeypatch.setattr(_svc, "forward_event", _boom)

    await ota._emit_step("download_started", version="3.4.10", channel="stable")
