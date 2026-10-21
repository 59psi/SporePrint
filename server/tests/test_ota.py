"""Pi self-update (app/cloud/ota.py), unit by unit: input validation, the
release download (SSRF allowlist, size caps, no redirects), the legacy
Ed25519 bundle signature, tar safety and staging.

The pipeline end to end, against signed release manifests, is
test_ota_signed_manifest.py; the cloud command's pre-ack guards are
test_ota_dispatch_guards.py.
"""

from __future__ import annotations

import base64
import io
import tarfile
import warnings
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.cloud import ota
from app.cloud.ota import OTAError, _safe_extract_tar, _validate_inputs, _verify_signature
from app.config import settings


# ─── Input validation ─────────────────────────────────────────────────


def test_canonical_versions_and_channels_are_accepted():
    for version, channel in (("3.4.10", "stable"), ("v3.4.10", "stable"),
                             ("3.4.10-rc1", "beta"), ("3.4.10.dev42", "dev")):
        _validate_inputs(version, channel)


@pytest.mark.parametrize("version, channel, message", [
    ("v1.2.3", "garbage", "channel must be"),
    ("../../etc/passwd", "stable", "version must match"),       # path traversal
    ("v1.2.3/../evil", "stable", "version must match"),         # URL smuggling
])
def test_a_version_or_channel_that_could_leave_its_path_is_refused(version, channel, message):
    with pytest.raises(OTAError, match=message):
        _validate_inputs(version, channel)


@pytest.mark.parametrize("version, channel, message", [
    ("3.4.10", "wat", "channel must be"),
    ("../../passwd", "stable", "version must match"),
])
async def test_the_pipeline_validates_before_anything_else(monkeypatch, tmp_path, version, channel,
                                                           message):
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", tmp_path / "state")
    result = await ota.run_ota_update(version, channel)
    assert (result["ok"], result["step"]) == (False, "validate")
    assert message in result["error"]


# ─── The release download ─────────────────────────────────────────────


@pytest.fixture
def release_host(monkeypatch):
    """updates.sporeprint.ai behind httpx.MockTransport: `routes` maps a URL
    path to the response; `seen` lists every URL requested."""
    host = SimpleNamespace(routes={}, seen=[])

    def handler(request: httpx.Request) -> httpx.Response:
        host.seen.append(str(request.url))
        return host.routes.get(request.url.path, httpx.Response(404))

    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(ota, "httpx", SimpleNamespace(
        URL=httpx.URL, Timeout=httpx.Timeout, AsyncClient=client))
    return host


_BUNDLE_URL = "https://updates.sporeprint.ai/firmware/stable/5.1.0.tar.gz"
_BUNDLE_PATH = "/firmware/stable/5.1.0.tar.gz"


async def test_a_release_file_is_downloaded_byte_for_byte(release_host, tmp_path):
    release_host.routes[_BUNDLE_PATH] = httpx.Response(200, content=b"bundle bytes")
    dest = tmp_path / "5.1.0.tar.gz"
    await ota._download_to(_BUNDLE_URL, dest, max_bytes=12)
    assert dest.read_bytes() == b"bundle bytes"


async def test_a_host_off_the_allowlist_is_never_contacted(release_host, tmp_path):
    with pytest.raises(OTAError, match="not on the OTA allowlist"):
        await ota._download_to("https://evil.example/firmware/stable/5.1.0.tar.gz",
                               tmp_path / "x")
    assert release_host.seen == []


async def test_a_file_the_host_does_not_publish_is_not_found(release_host, tmp_path):
    """Only these mean "no such file" (the legacy-signature fallback hinges
    on it); every other failure is an error."""
    for status in (403, 404, 410):
        release_host.routes[_BUNDLE_PATH] = httpx.Response(status)
        with pytest.raises(ota.OTANotFound):
            await ota._download_to(_BUNDLE_URL, tmp_path / "x")


async def test_a_redirect_is_not_followed(release_host, tmp_path):
    """The allowlist is the only gate: a redirect would take the download to
    a host nobody checked."""
    release_host.routes[_BUNDLE_PATH] = httpx.Response(
        302, headers={"location": "https://evil.example/bundle.tar.gz"})
    with pytest.raises(OTAError, match="returned HTTP 302") as exc:
        await ota._download_to(_BUNDLE_URL, tmp_path / "x")
    assert not isinstance(exc.value, ota.OTANotFound)
    assert release_host.seen == [_BUNDLE_URL]


def _streamed(body: bytes):
    """A body sent without a Content-Length (chunked)."""
    async def chunks():
        for i in range(0, len(body), 4):
            yield body[i:i + 4]
    return chunks()


@pytest.mark.parametrize("response, message", [
    (lambda: httpx.Response(500), "returned HTTP 500"),
    (lambda: httpx.Response(200, headers={"content-length": "1000"}, content=b"x" * 1000),
     "declares 1000 bytes, max is 16"),
    (lambda: httpx.Response(200, headers={"content-length": "lots"}, content=b"x"),
     "bad Content-Length"),
    (lambda: httpx.Response(200, content=_streamed(b"x" * 40)), "exceeded max size 16 mid-stream"),
], ids=["server-error", "declared-too-big", "bad-length", "streamed-too-big"])
async def test_a_download_that_is_not_a_bounded_200_is_refused(release_host, tmp_path, response,
                                                               message):
    """A release is a few MB on an SD card: the size cap is enforced from
    the declared length before anything is written, and while streaming."""
    release_host.routes[_BUNDLE_PATH] = response()
    dest = tmp_path / "x"
    with pytest.raises(OTAError, match=message):
        await ota._download_to(_BUNDLE_URL, dest, max_bytes=16)
    if message.startswith("declares"):
        assert not dest.exists()


# ─── Tar extraction safety ────────────────────────────────────────────


def _build_tar(members: list[tuple[str, bytes]], dest: Path) -> Path:
    bundle = dest / "test.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        for name, content in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return bundle


def _special(name: str, kind: bytes, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = kind
    info.linkname = linkname
    return info


@pytest.mark.parametrize("member, message", [
    ("/etc/passwd", "path-traversal"),
    ("../../escape.txt", "path-traversal"),
    (_special("link.txt", tarfile.SYMTYPE, "/etc/passwd"), "is a symlink"),
    (_special("link.txt", tarfile.LNKTYPE, "/etc/passwd"), "is a hardlink"),
    (_special("pipe", tarfile.FIFOTYPE), "is a special-file"),
], ids=["absolute", "parent-traversal", "symlink", "hardlink", "fifo"])
def test_a_bundle_member_that_could_escape_staging_is_refused(tmp_path, member, message):
    bundle = tmp_path / "test.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        if isinstance(member, str):
            info = tarfile.TarInfo(name=member)
            info.size = 4
            tf.addfile(info, io.BytesIO(b"oops"))
        else:
            tf.addfile(member)
    with pytest.raises(OTAError, match=message):
        _safe_extract_tar(bundle, tmp_path / "staging")


def test_safe_extract_strips_setuid_bits(tmp_path):
    bundle = tmp_path / "test.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        info = tarfile.TarInfo(name="run.sh")
        info.size = 4
        info.mode = 0o4755  # setuid set
        tf.addfile(info, io.BytesIO(b"echo"))
    staging = tmp_path / "staging"
    _safe_extract_tar(bundle, staging)
    # 0o4755 → 0o755 (setuid bit dropped, exec bits preserved)
    assert ((staging / "run.sh").stat().st_mode & 0o7777) == 0o755


def test_normal_files_extract_through_an_explicit_tar_filter(tmp_path):
    """Unfiltered extract() is deprecated (Python 3.12+ warns; 3.14 changes
    the default). The manual member walk stays, and the stdlib 'data' filter
    is applied on top of it wherever the running Python has one."""
    bundle = _build_tar(
        [("server/app.py", b"print('hello')"), ("server/main.py", b"main"), ("README.md", b"docs")],
        tmp_path,
    )
    staging = tmp_path / "staging"
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        _safe_extract_tar(bundle, staging)
    assert (staging / "server" / "app.py").read_bytes() == b"print('hello')"
    assert (staging / "server" / "main.py").read_bytes() == b"main"
    assert (staging / "README.md").read_bytes() == b"docs"


# ─── The pinned key and the legacy bundle signature ──────────────────


@pytest.fixture
def pinned_key(monkeypatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "ota_pubkey_b64",
                        base64.b64encode(key.public_key().public_bytes_raw()).decode())
    return key


def test_verify_signature_accepts_the_pinned_keys_signature(tmp_path, pinned_key):
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"any payload - what matters is the sig")
    sig_path = tmp_path / "bundle.tar.gz.sig"
    sig_path.write_bytes(pinned_key.sign(bundle.read_bytes()))
    _verify_signature(bundle, sig_path)  # should not raise


@pytest.mark.parametrize("damage, message", [
    ("tamper", "signature verification FAILED"),
    ("short-sig", "signature wrong length"),
])
def test_verify_signature_refuses_a_bundle_the_key_did_not_sign(tmp_path, pinned_key, damage,
                                                                message):
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"original payload")
    sig_path = tmp_path / "bundle.tar.gz.sig"
    sig_path.write_bytes(pinned_key.sign(bundle.read_bytes()))
    if damage == "tamper":
        bundle.write_bytes(b"tampered payload")       # AFTER signing
    else:
        sig_path.write_bytes(b"not 64 bytes")
    with pytest.raises(OTAError, match=message):
        _verify_signature(bundle, sig_path)


@pytest.mark.parametrize("raw, message", [
    ("", "not configured"),
    (base64.b64encode(b"too short").decode("ascii"), "wrong length"),
    ("not base64!", "not valid base64"),
], ids=["unset", "wrong-length", "not-base64"])
def test_the_pinned_key_fails_closed(monkeypatch, raw, message):
    monkeypatch.setattr(settings, "ota_pubkey_b64", raw)
    monkeypatch.delenv("SPOREPRINT_OTA_PUBKEY", raising=False)
    with pytest.raises(OTAError, match=message):
        ota._load_pinned_pubkey()


# ─── Staging never touches the live tree ─────────────────────────────


def _installed_tree(install_root: Path, name: str) -> Path:
    tree = install_root / "staging" / name
    (tree / "server").mkdir(parents=True)
    (tree / "server" / "main.py").write_text(f"# {name}")
    return tree


def test_a_failed_same_version_stage_leaves_the_running_tree(monkeypatch, tmp_path):
    """After one OTA `current` points into staging/. Re-sending the same
    version (a retry after a lost ack or a failed restart) deleted that tree
    before extracting; a failure mid-extract then left `current` on a
    partial tree and the next boot failed."""
    install_root = tmp_path / "opt"
    live = _installed_tree(install_root, "5.2.3")
    (install_root / "current").symlink_to(live, target_is_directory=True)
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", install_root)

    def _disk_full(bundle_path, dest):
        (dest / "server").mkdir(parents=True)
        (dest / "server" / "first.py").write_text("partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ota, "_safe_extract_tar", _disk_full)
    with pytest.raises(OSError):
        ota._stage_install(tmp_path / "bundle.tar.gz", "5.2.3")

    assert (install_root / "current" / "server" / "main.py").read_text() == "# 5.2.3"
    assert sorted(p.name for p in (install_root / "staging").iterdir()) == ["5.2.3"], \
        "the failed extraction's own directory is removed"


def test_the_first_promote_keeps_only_the_live_tree(monkeypatch, tmp_path):
    """No tree was live before (a hand-installed Pi): every other staging
    tree and the spent downloads go."""
    install_root, state_dir = tmp_path / "opt", tmp_path / "state"
    old = _installed_tree(install_root, "5.2.2")
    live = _installed_tree(install_root, "5.2.3")
    (state_dir / "incoming").mkdir(parents=True)
    (state_dir / "incoming" / "5.2.3.tar.gz").write_bytes(b"spent")
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", install_root)
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", state_dir)

    ota._prune_after_promote(live, None)

    assert not old.exists() and live.is_dir()
    assert list((state_dir / "incoming").iterdir()) == []


def test_each_stage_extracts_into_a_new_directory(monkeypatch, tmp_path):
    install_root = tmp_path / "opt"
    live = _installed_tree(install_root, "5.2.3")
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", install_root)
    bundle = _build_tar([("server/main.py", b"# new")], tmp_path)

    staged = ota._stage_install(bundle, "5.2.3")

    assert staged.resolve() != live.resolve()
    assert staged.parent.resolve() == (install_root / "staging").resolve()
    assert staged.name.startswith("5.2.3.")
    assert (staged / "server" / "main.py").read_bytes() == b"# new"
    assert (live / "server" / "main.py").read_text() == "# 5.2.3"
