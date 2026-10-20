"""Pi OTA pipeline against signed release manifests.

The manifest binds version + channel + sha256 + size under the pinned key.
These tests run run_ota_update() against a fake release host and check
that a manifest that is tampered with, replayed for another version, moved
to another channel, or older than the install is refused before anything is
promoted. They also cover the transitional bundle-only-signature path, the
progress events the cloud sees, and the trees a promote leaves on the SD
card.
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
_FILES = (("app/__init__.py", b""), ("pyproject.toml", b"[project]\n"))


def _bundle_bytes(tag: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in (*_FILES, ("app/main.py", f"VERSION = {tag!r}\n".encode())):
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


def _live(pi):
    return (pi.root / "current").resolve()


def _promoted(pi) -> bool:
    return _live(pi).name != "5.0.0"


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
    assert (_live(pi) / "app" / "main.py").read_text() == "VERSION = '5.1.0'\n"
    assert _floor(pi) == "5.1.0"
    # Manifest first, then only the bundle: the legacy .sig is not needed.
    assert pi.fetched == [
        f"{BASE}/stable/5.1.0.manifest.json",
        f"{BASE}/stable/5.1.0.manifest.json.sig",
        f"{BASE}/stable/5.1.0.tar.gz",
    ]
    # Same step names and fields the cloud already accepts; verified_by is
    # additive.
    assert [e["step"] for e in pi.events] == [
        "download_started", "download_complete", "verify_complete",
        "extract_complete", "promote_complete", "restart_initiated",
    ]
    assert all((e["version"], e["channel"]) == ("5.1.0", "stable") for e in pi.events)
    by_step = {e["step"]: e for e in pi.events}
    assert by_step["download_started"]["url"] == f"{BASE}/stable/5.1.0.tar.gz"
    assert by_step["download_complete"]["size_bytes"] == fields["size"]
    assert by_step["verify_complete"]["verified_by"] == "manifest"
    assert by_step["extract_complete"]["files_extracted"] == 3


async def test_same_version_reinstall_is_allowed(pi):
    pi.publish("5.0.0", "stable")
    assert ota.validate_request("5.0.0", "stable") is None
    result = await ota.run_ota_update("5.0.0", "stable")
    assert result["ok"] is True, result


async def test_a_relay_that_is_down_does_not_stop_the_update(pi, monkeypatch):
    """Progress events are fire-and-forget: a Pi that cannot reach the cloud
    must still complete its OTA."""
    async def _down(*args, **kwargs):
        raise RuntimeError("cloud is having a bad day")

    monkeypatch.setattr(service, "forward_event", _down)
    pi.publish("5.1.0", "stable")
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is True, result
    assert _promoted(pi)


async def test_promote_keeps_two_trees_and_no_downloads(pi):
    """Each OTA left a full extracted tree and its bundle on the SD card. A
    promote keeps the live tree and the one before it (for a manual
    rollback) and removes older trees and the spent downloads."""
    leftover = pi.root / "staging" / "4.9.0"
    leftover.mkdir(parents=True)
    installed_by_hand = _live(pi)               # releases/5.0.0, outside staging/
    for version in ("5.1.0", "5.2.0"):
        pi.publish(version, "stable")
        previous = _live(pi)
        result = await ota.run_ota_update(version, "stable")
        assert result["ok"] is True, result
        assert (_live(pi) / "app" / "main.py").read_text() == f"VERSION = {version!r}\n"
        staging = {p.resolve() for p in (pi.root / "staging").iterdir()}
        assert staging == {_live(pi), previous} - {installed_by_hand}
        assert not leftover.exists()
        assert [p for p in (pi.state_dir / "incoming").iterdir() if p.is_file()] == []
    assert len(staging) == 2


# ─── Failing closed ──────────────────────────────────────────────────


async def test_a_pi_with_no_pinned_key_refuses_before_downloading(pi, monkeypatch):
    """The failed event names WHERE it broke, so the cloud admin can see it."""
    monkeypatch.setattr(settings, "ota_pubkey_b64", "")
    monkeypatch.delenv("SPOREPRINT_OTA_PUBKEY", raising=False)
    pi.publish("5.1.0", "stable")
    result = await ota.run_ota_update("5.1.0", "stable")
    assert (result["ok"], result["step"]) == (False, "validate")
    assert "not configured" in result["error"]
    assert pi.fetched == []
    failed = pi.events[-1]
    assert (failed["step"], failed["failed_at"], failed["version"], failed["channel"]) == (
        "failed", "validate", "5.1.0", "stable")
    assert "not configured" in failed["error"]


async def test_an_unexpected_failure_is_reported_and_promotes_nothing(pi, monkeypatch):
    """Not every failure is an OTAError (a full SD card mid-extract): it is
    still a failed step the cloud sees, and the running install stays."""
    def _disk_full(bundle_path, version):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ota, "_stage_install", _disk_full)
    pi.publish("5.1.0", "stable")
    result = await ota.run_ota_update("5.1.0", "stable")
    assert (result["ok"], result["step"]) == (False, "stage")
    assert result["error"].startswith("unexpected: OSError")
    assert (pi.events[-1]["step"], pi.events[-1]["failed_at"]) == ("failed", "stage")
    assert not _promoted(pi)


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

    assert (result["ok"], result["step"]) == (False, "manifest")
    assert "signature verification FAILED" in result["error"]
    assert f"{BASE}/stable/5.1.0.tar.gz" not in pi.fetched
    assert not _promoted(pi)
    assert (pi.events[-1]["step"], pi.events[-1]["failed_at"]) == ("failed", "manifest")


async def test_manifest_signed_by_another_key_is_refused(pi):
    pi.publish("5.1.0", "stable", manifest_key=Ed25519PrivateKey.generate())
    result = await ota.run_ota_update("5.1.0", "stable")
    assert result["ok"] is False
    assert "signature verification FAILED" in result["error"]
    assert not _promoted(pi)


def _same_length_other_bundle(real: bytes) -> bytes:
    """Same length, so only the digest can catch it."""
    return _bundle_bytes("evil")[: len(real)].ljust(len(real), b"\0")


@pytest.mark.parametrize("swap, step, message", [
    (_same_length_other_bundle, "verify", "sha256 does not match the signed manifest"),
    (lambda real: real + b"trailing payload", "download", "exceeded max size"),
    (lambda real: real[:-1], "verify", "bytes, the signed manifest says"),
], ids=["same-length-swap", "longer", "shorter"])
async def test_a_bundle_that_is_not_the_signed_one_is_refused(pi, swap, step, message):
    """A genuine manifest, and a different body at the bundle URL: the signed
    size caps the download, the signed sha256 and size check what came."""
    pi.publish("5.1.0", "stable")
    url = f"{BASE}/stable/5.1.0.tar.gz"
    pi.files[url] = swap(pi.files[url])

    result = await ota.run_ota_update("5.1.0", "stable")

    assert (result["ok"], result["step"]) == (False, step)
    assert message in result["error"]
    assert not _promoted(pi)


# ─── Genuine manifests that do not fit the request ────────────────────


def _serve_at(pi, src: str, dst: str) -> None:
    for suffix in (".manifest.json", ".manifest.json.sig", ".tar.gz"):
        pi.files[f"{dst}{suffix}"] = pi.files[f"{src}{suffix}"]


@pytest.mark.parametrize("publish, request_, message", [
    # A validly signed 5.1.0 manifest served at the 5.2.0 path.
    (lambda pi: (pi.publish("5.1.0", "stable"),
                 _serve_at(pi, f"{BASE}/stable/5.1.0", f"{BASE}/stable/5.2.0")),
     ("5.2.0", "stable"), "manifest version '5.1.0' != requested '5.2.0'"),
    (lambda pi: (pi.publish("5.1.0", "beta"),
                 _serve_at(pi, f"{BASE}/beta/5.1.0", f"{BASE}/stable/5.1.0")),
     ("5.1.0", "stable"), "manifest channel 'beta' != requested 'stable'"),
    (lambda pi: pi.publish("5.1.0", "stable", artifact="node-esp32"),
     ("5.1.0", "stable"), "not 'sporeprint-server'"),
    (lambda pi: pi.publish("5.1.0", "stable", size=0),
     ("5.1.0", "stable"), "declares a 0-byte bundle"),
], ids=["other-version", "other-channel", "other-artifact", "empty-bundle"])
async def test_a_genuine_manifest_for_something_else_is_refused(pi, publish, request_, message):
    publish(pi)
    result = await ota.run_ota_update(*request_)
    assert (result["ok"], result["step"]) == (False, "manifest")
    assert message in result["error"]
    assert not _promoted(pi)


# ─── Channel binding ──────────────────────────────────────────────────


async def test_pipeline_refuses_a_channel_the_pi_does_not_follow(pi):
    pi.publish("5.1.0", "beta")
    result = await ota.run_ota_update("5.1.0", "beta")
    assert (result["ok"], result["step"]) == (False, "validate")
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


# ─── Transitional: releases without a manifest ────────────────────────


async def test_legacy_only_release_refused_by_default(pi):
    pi.publish("5.1.0", "stable", manifest=False)
    result = await ota.run_ota_update("5.1.0", "stable")
    assert (result["ok"], result["step"]) == (False, "manifest")
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


@pytest.fixture
def instant_ack_flush(monkeypatch):
    """The OTA task waits 2 s for the command ack to flush; not here."""
    real_sleep = asyncio.sleep

    async def _instant(seconds, *args):
        await real_sleep(0)

    monkeypatch.setattr(service.asyncio, "sleep", _instant)


async def test_a_genuine_release_sent_from_the_cloud_is_installed(pi, instant_ack_flush):
    pi.publish("5.1.0", "stable")
    ok, err = await service._dispatch_system_command(
        "ota", {"firmware_version": "5.1.0", "channel": "stable"})
    assert (ok, err) == (True, None)
    await asyncio.wait_for(service._ota_task, timeout=10)
    assert _promoted(pi)
    assert pi.events[-1]["step"] == "restart_initiated"


async def test_cloud_supplied_pubkey_is_ignored(pi, monkeypatch, instant_ack_flush):
    """The cloud adds the account's registered `ota_pubkey` to the command.
    The Pi must never verify with it: a key from the command channel would
    let whoever controls that channel sign their own bundle. Only the
    version and channel reach the pipeline, never a key or a downgrade
    switch."""
    attacker = Ed25519PrivateKey.generate()
    attacker_b64 = base64.b64encode(attacker.public_key().public_bytes_raw()).decode()
    pi.publish("5.1.0", "stable", manifest_key=attacker)
    pi.files[f"{BASE}/stable/5.1.0.tar.gz.sig"] = attacker.sign(
        pi.files[f"{BASE}/stable/5.1.0.tar.gz"])

    calls: list = []
    real_update = ota.run_ota_update

    async def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return await real_update(*args, **kwargs)

    monkeypatch.setattr(ota, "run_ota_update", _spy)
    ok, err = await service._dispatch_system_command("ota", {
        "firmware_version": "5.1.0", "channel": "stable", "ota_pubkey": attacker_b64,
        "allow_downgrade": True,
    })
    assert ok is True, err
    await asyncio.wait_for(service._ota_task, timeout=10)

    assert calls == [(("5.1.0", "stable"), {})]
    assert not _promoted(pi)
    failed = pi.events[-1]
    assert failed["step"] == "failed"
    assert "signature verification FAILED" in failed["error"]
