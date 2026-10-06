"""Pi OTA pipeline against signed release manifests.

The manifest binds version + channel + sha256 + size under the pinned key.
These tests run run_ota_update() against a fake release host and check
that a manifest that is tampered with, replayed for another version, moved
to another channel, or older than the install is refused before anything is
promoted. They also cover the transitional bundle-only-signature path.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import tarfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.cloud.service as service
from app.cloud import ota, ota_manifest
from app.config import settings

BASE = "https://updates.sporeprint.ai/firmware"


def _bundle_bytes(tag: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in (("app/__init__.py", b""),
                              ("app/main.py", f"VERSION = {tag!r}\n".encode()),
                              ("pyproject.toml", b"[project]\n")):
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class ReleaseHost:
    """In-memory updates.sporeprint.ai. Missing paths answer 404."""

    def __init__(self, key: Ed25519PrivateKey):
        self.key = key
        self.files: dict[str, bytes] = {}
        self.fetched: list[str] = []

    def publish(self, version: str, channel: str, *, legacy: bool = True,
                manifest: bool = True, bundle: bytes | None = None,
                manifest_key: Ed25519PrivateKey | None = None,
                **manifest_overrides) -> dict:
        body = bundle if bundle is not None else _bundle_bytes(version)
        prefix = f"{BASE}/{channel}/{version}"
        self.files[f"{prefix}.tar.gz"] = body
        if legacy:
            self.files[f"{prefix}.tar.gz.sig"] = self.key.sign(body)
        fields = {
            "artifact": ota_manifest.ARTIFACT_PI_SERVER,
            "version": version,
            "channel": channel,
            "sha256": hashlib.sha256(body).hexdigest(),
            "size": len(body),
            "published_at": "2026-10-05T12:00:00Z",
            **manifest_overrides,
        }
        if manifest:
            data, sig = ota_manifest.sign(ota_manifest.build(**fields),
                                          manifest_key or self.key)
            self.files[f"{prefix}.manifest.json"] = data
            self.files[f"{prefix}.manifest.json.sig"] = sig
        return fields

    async def download(self, url, dest, *, max_bytes=ota._MAX_BUNDLE_BYTES):
        self.fetched.append(url)
        if url not in self.files:
            raise ota.OTANotFound(f"download {url} returned HTTP 404")
        body = self.files[url]
        if len(body) > max_bytes:
            raise ota.OTAError(f"bundle exceeded max size {max_bytes} mid-stream")
        dest.write_bytes(body)


@pytest.fixture
def pi(tmp_path, monkeypatch):
    """A bare-metal Pi on 5.0.0 following stable, key pinned, fake host."""
    key = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    monkeypatch.setattr(settings, "ota_pubkey_b64", pub_b64)
    monkeypatch.setattr(settings, "ota_channel", "stable")
    monkeypatch.setattr(settings, "ota_allow_downgrade", False)
    monkeypatch.setattr(settings, "ota_allow_legacy_signature", False)

    root = tmp_path / "opt"
    (root / "releases" / "5.0.0").mkdir(parents=True)
    (root / "current").symlink_to(root / "releases" / "5.0.0")
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", root)
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(ota, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(ota, "server_version", lambda: "5.0.0")
    monkeypatch.setattr(ota, "_restart_unit", lambda: None)
    monkeypatch.setattr(service, "_ota_task", None)

    host = ReleaseHost(key)
    monkeypatch.setattr(ota, "_download_to", host.download)

    events: list[dict] = []

    async def _capture(event_type, data):
        assert event_type == "ota_step"
        events.append(dict(data))

    monkeypatch.setattr(service, "forward_event", _capture)
    host.events = events
    host.root = root
    host.state_dir = tmp_path / "state"
    return host


def _promoted(pi) -> bool:
    return (pi.root / "current").resolve().name != "5.0.0"


def _floor(pi) -> str | None:
    path = pi.state_dir / ota._FLOOR_FILE
    return json.loads(path.read_text())["version"] if path.exists() else None


# ─── Happy path ───────────────────────────────────────────────────────


async def test_signed_manifest_release_installs(pi):
    fields = pi.publish("5.1.0", "stable")
    result = await ota.run_ota_update("5.1.0", "stable")

    assert result["ok"] is True, result
    assert result["verified_by"] == "manifest"
    assert result["sha256"] == fields["sha256"]
    assert _promoted(pi)
    assert _floor(pi) == "5.1.0"
    # Manifest first, then only the bundle: the legacy .sig is not needed.
    assert pi.fetched == [
        f"{BASE}/stable/5.1.0.manifest.json",
        f"{BASE}/stable/5.1.0.manifest.json.sig",
        f"{BASE}/stable/5.1.0.tar.gz",
    ]
    # Same step names the cloud already accepts; verified_by is additive.
    assert [e["step"] for e in pi.events] == [
        "download_started", "download_complete", "verify_complete",
        "extract_complete", "promote_complete", "restart_initiated",
    ]
    verify = next(e for e in pi.events if e["step"] == "verify_complete")
    assert verify["verified_by"] == "manifest"


async def test_same_version_reinstall_is_allowed(pi):
    pi.publish("5.0.0", "stable")
    result = await ota.run_ota_update("5.0.0", "stable")
    assert result["ok"] is True, result


# ─── Tampering ────────────────────────────────────────────────────────


def _rewrite_manifest(pi, url_prefix: str, **changes) -> None:
    """Edit the published manifest bytes but keep the old signature."""
    path = f"{url_prefix}.manifest.json"
    fields = json.loads(pi.files[path])
    fields.update(changes)
    pi.files[path] = ota_manifest.canonical_bytes(fields)


@pytest.mark.parametrize("changes", [
    {"version": "5.2.0"},
    {"channel": "beta"},
    {"sha256": hashlib.sha256(b"evil").hexdigest()},
    {"size": 1},
], ids=["version", "channel", "sha256", "size"])
async def test_tampered_manifest_is_refused_before_download(pi, changes):
    pi.publish("5.1.0", "stable")
    _rewrite_manifest(pi, f"{BASE}/stable/5.1.0", **changes)

    result = await ota.run_ota_update("5.1.0", "stable")

    assert result["ok"] is False
    assert result["step"] == "manifest"
    assert "signature verification FAILED" in result["error"]
    assert f"{BASE}/stable/5.1.0.tar.gz" not in pi.fetched
    assert not _promoted(pi)
    assert pi.events[-1]["step"] == "failed"
    assert pi.events[-1]["failed_at"] == "manifest"


async def test_manifest_signed_by_another_key_is_refused(pi):
    pi.publish("5.1.0", "stable", manifest_key=Ed25519PrivateKey.generate())
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert "signature verification FAILED" in result["error"]
    assert not _promoted(pi)


async def test_swapped_bundle_fails_the_signed_sha256(pi):
    """Genuine manifest, different tarball at the bundle URL."""
    pi.publish("5.1.0", "stable")
    evil = _bundle_bytes("evil")
    real = pi.files[f"{BASE}/stable/5.1.0.tar.gz"]
    # Same length so only the digest can catch it.
    pi.files[f"{BASE}/stable/5.1.0.tar.gz"] = evil[: len(real)].ljust(len(real), b"\0")

    result = await ota.run_ota_update("5.1.0", "stable")

    assert result["ok"] is False
    assert result["step"] == "verify"
    assert "sha256 does not match" in result["error"]
    assert not _promoted(pi)


async def test_longer_bundle_is_cut_off_at_the_signed_size(pi):
    pi.publish("5.1.0", "stable")
    pi.files[f"{BASE}/stable/5.1.0.tar.gz"] += b"trailing payload"
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert result["step"] == "download"
    assert not _promoted(pi)


async def test_shorter_bundle_fails_the_signed_size(pi):
    pi.publish("5.1.0", "stable")
    pi.files[f"{BASE}/stable/5.1.0.tar.gz"] = pi.files[f"{BASE}/stable/5.1.0.tar.gz"][:-1]
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert "bytes, the signed manifest says" in result["error"]


# ─── Replay / mix-and-match of genuine manifests ─────────────────────


async def test_genuine_manifest_for_another_version_is_refused(pi):
    """A validly signed 5.1.0 manifest served at the 5.2.0 path."""
    pi.publish("5.1.0", "stable")
    pi.publish("5.2.0", "stable")
    for suffix in (".manifest.json", ".manifest.json.sig", ".tar.gz"):
        pi.files[f"{BASE}/stable/5.2.0{suffix}"] = pi.files[f"{BASE}/stable/5.1.0{suffix}"]

    result = await ota.run_ota_update("5.2.0", "stable")

    assert result["ok"] is False
    assert "manifest version '5.1.0' != requested '5.2.0'" in result["error"]
    assert not _promoted(pi)


async def test_genuine_beta_manifest_on_the_stable_path_is_refused(pi):
    pi.publish("5.1.0", "beta")
    for suffix in (".manifest.json", ".manifest.json.sig", ".tar.gz"):
        pi.files[f"{BASE}/stable/5.1.0{suffix}"] = pi.files[f"{BASE}/beta/5.1.0{suffix}"]

    result = await ota.run_ota_update("5.1.0", "stable")

    assert result["ok"] is False
    assert "manifest channel 'beta' != requested 'stable'" in result["error"]
    assert not _promoted(pi)


async def test_manifest_for_another_artifact_is_refused(pi):
    pi.publish("5.1.0", "stable", artifact="node-esp32")
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert "not 'sporeprint-server'" in result["error"]


# ─── Channel binding ──────────────────────────────────────────────────


async def test_other_channel_refused_before_ack(pi, monkeypatch):
    started: list = []
    monkeypatch.setattr(ota, "run_ota_update", lambda *a: started.append(a))
    ok, err = await service._dispatch_system_command(
        "ota", {"firmware_version": "5.1.0-beta.1", "channel": "beta"})
    assert ok is False
    assert "follows the 'stable' OTA channel" in err
    assert "SPOREPRINT_OTA_CHANNEL=beta" in err
    assert started == []


async def test_pipeline_refuses_a_channel_the_pi_does_not_follow(pi):
    pi.publish("5.1.0", "beta")
    result = await ota.run_ota_update("5.1.0", "beta")
    assert result["ok"] is False
    assert result["step"] == "validate"
    assert pi.fetched == []


async def test_beta_pi_installs_beta_but_not_stable(pi, monkeypatch):
    monkeypatch.setattr(settings, "ota_channel", "beta")
    pi.publish("5.1.0-beta.1", "beta")
    assert ota.validate_request("5.1.0-beta.1", "beta") is None
    assert "follows the 'beta'" in ota.validate_request("5.1.0", "stable")
    result = await ota.run_ota_update("5.1.0-beta.1", "beta")
    assert result["ok"] is True, result


# ─── Anti-rollback ────────────────────────────────────────────────────


async def test_older_signed_release_is_refused(pi):
    pi.publish("4.9.0", "stable")
    assert "downgrade" in ota.validate_request("4.9.0", "stable")
    result = await ota.run_ota_update("4.9.0", "stable")
    assert result["ok"] is False
    assert "downgrade" in result["error"]
    assert pi.fetched == []  # refused before any download
    assert not _promoted(pi)


async def test_recorded_floor_beats_a_stale_installed_version(pi):
    """The running tree may misreport its version (stale package metadata);
    the floor recorded by the last OTA still blocks the rollback."""
    pi.state_dir.mkdir(parents=True, exist_ok=True)
    (pi.state_dir / ota._FLOOR_FILE).write_text(json.dumps({"version": "5.2.0"}))
    pi.publish("5.1.0", "stable")
    assert "downgrade from 5.2.0" in ota.validate_request("5.1.0", "stable")
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False


async def test_operator_downgrade_flag_allows_and_lowers_the_floor(pi, monkeypatch):
    monkeypatch.setattr(settings, "ota_allow_downgrade", True)
    pi.state_dir.mkdir(parents=True, exist_ok=True)
    (pi.state_dir / ota._FLOOR_FILE).write_text(json.dumps({"version": "5.0.0"}))
    pi.publish("4.9.0", "stable")
    assert ota.validate_request("4.9.0", "stable") is None
    result = await ota.run_ota_update("4.9.0", "stable")
    assert result["ok"] is True, result
    assert _floor(pi) == "4.9.0"


async def test_unknown_installed_version_fails_closed(pi, monkeypatch):
    monkeypatch.setattr(ota, "server_version", lambda: "unknown")
    pi.publish("5.1.0", "stable")
    err = ota.validate_request("5.1.0", "stable")
    assert "unknown" in err and "SPOREPRINT_OTA_ALLOW_DOWNGRADE" in err
    monkeypatch.setattr(settings, "ota_allow_downgrade", True)
    assert ota.validate_request("5.1.0", "stable") is None


async def test_downgrade_cannot_be_requested_from_the_cloud(pi, monkeypatch):
    """Only the Pi's own setting allows a downgrade; payload keys don't."""
    ok, err = await service._dispatch_system_command("ota", {
        "firmware_version": "4.9.0", "channel": "stable",
        "allow_downgrade": True, "ota_allow_downgrade": True,
    })
    assert ok is False
    assert "downgrade" in err


# ─── Transitional: releases without a manifest ────────────────────────


async def test_legacy_only_release_refused_by_default(pi):
    pi.publish("5.1.0", "stable", manifest=False)
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert result["step"] == "manifest"
    assert "no signed manifest" in result["error"]
    assert "SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE" in result["error"]
    assert f"{BASE}/stable/5.1.0.tar.gz" not in pi.fetched


async def test_legacy_only_release_allowed_by_the_transitional_flag(pi, monkeypatch):
    monkeypatch.setattr(settings, "ota_allow_legacy_signature", True)
    pi.publish("5.1.0", "stable", manifest=False)
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is True, result
    assert result["verified_by"] == "legacy_signature"
    verify = next(e for e in pi.events if e["step"] == "verify_complete")
    assert verify["verified_by"] == "legacy_signature"


async def test_legacy_path_still_checks_the_bundle_signature(pi, monkeypatch):
    monkeypatch.setattr(settings, "ota_allow_legacy_signature", True)
    pi.publish("5.1.0", "stable", manifest=False)
    pi.files[f"{BASE}/stable/5.1.0.tar.gz.sig"] = Ed25519PrivateKey.generate().sign(
        pi.files[f"{BASE}/stable/5.1.0.tar.gz"])
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert "signature verification FAILED" in result["error"]


async def test_legacy_path_still_refuses_a_downgrade(pi, monkeypatch):
    monkeypatch.setattr(settings, "ota_allow_legacy_signature", True)
    pi.publish("4.9.0", "stable", manifest=False)
    result = await ota.run_ota_update("4.9.0", "stable")
    assert result["ok"] is False
    assert "downgrade" in result["error"]


@pytest.mark.parametrize("damage", ["drop_manifest_sig", "bad_manifest_sig", "tamper"])
async def test_a_broken_manifest_never_falls_back_to_legacy(pi, monkeypatch, damage):
    """Stripping or corrupting a manifest must not downgrade the check to
    the legacy signature, even with the transitional flag on."""
    monkeypatch.setattr(settings, "ota_allow_legacy_signature", True)
    pi.publish("5.1.0", "stable")
    prefix = f"{BASE}/stable/5.1.0"
    if damage == "drop_manifest_sig":
        del pi.files[f"{prefix}.manifest.json.sig"]
    elif damage == "bad_manifest_sig":
        pi.files[f"{prefix}.manifest.json.sig"] = b"\0" * 64
    else:
        _rewrite_manifest(pi, prefix, channel="beta")

    result = await ota.run_ota_update("5.1.0", "stable")

    assert result["ok"] is False
    assert result.get("verified_by") is None
    assert f"{prefix}.tar.gz.sig" not in pi.fetched
    assert not _promoted(pi)


# ─── What the OTA command may carry ──────────────────────────────────


async def test_cloud_supplied_pubkey_is_ignored(pi, monkeypatch):
    """The cloud adds the account's registered `ota_pubkey` to the command.
    The Pi must never verify with it: a key from the command channel would
    let whoever controls that channel sign their own bundle."""
    attacker = Ed25519PrivateKey.generate()
    attacker_b64 = base64.b64encode(attacker.public_key().public_bytes_raw()).decode()
    pi.publish("5.1.0", "stable", manifest_key=attacker)
    pi.files[f"{BASE}/stable/5.1.0.tar.gz.sig"] = attacker.sign(
        pi.files[f"{BASE}/stable/5.1.0.tar.gz"])

    ok, err = await service._dispatch_system_command("ota", {
        "firmware_version": "5.1.0", "channel": "stable", "ota_pubkey": attacker_b64,
    })
    assert ok is True, err
    await asyncio.wait_for(service._ota_task, timeout=10)

    assert not _promoted(pi)
    failed = pi.events[-1]
    assert failed["step"] == "failed"
    assert "signature verification FAILED" in failed["error"]


async def test_dispatch_passes_only_version_and_channel(pi, monkeypatch):
    calls: list = []

    async def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr(ota, "run_ota_update", _fake)
    ok, _ = await service._dispatch_system_command("ota", {
        "firmware_version": "5.1.0", "channel": "stable",
        "ota_pubkey": "AAAA", "allow_downgrade": True,
    })
    assert ok is True
    await asyncio.wait_for(service._ota_task, timeout=10)
    assert calls == [(("5.1.0", "stable"), {})]
