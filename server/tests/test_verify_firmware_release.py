"""scripts/verify_firmware_release.py — the check every signed firmware
release zip passes before .github/workflows/firmware-release.yml publishes
it, and that anyone can run on a download.

Its manifest reader is independent of the Pi's (server/app/cloud/
ota_manifest.py), so both are held to the committed v1 vectors here. The
zips are built the way the workflow builds them: sign-ota-bundle.py signs a
firmware.bin with the vectors' TEST-ONLY key, and the image carries the
strings fw_version.py compiles in (verify key, env, version).
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.cloud import ota_manifest
from app.config import settings
from app.hardware.node_manifest import MAX_NODE_MANIFEST_BYTES, check_node_manifest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_firmware_release.py"
SIGNER = ROOT / "scripts" / "sign-ota-bundle.py"
PI_VERIFIER = ROOT / "server" / "app" / "cloud" / "ota_manifest.py"
VECTORS = json.loads((Path(__file__).parent / "fixtures" / "ota_manifest_vectors.json").read_text())
SEED = bytes.fromhex(VECTORS["private_seed_hex"])
PUBKEY_B64 = VECTORS["public_key_b64"]
OTHER_KEY = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"not the release key").digest())


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vfr = _load(SCRIPT, "verify_firmware_release")
signer = _load(SIGNER, "sign_ota_bundle_for_release_test")
PUBKEY = vfr.load_public_key(PUBKEY_B64)


# ─── The v1 vectors: the same verdicts as the Pi ──────────────────────────


def _case(case):
    return bytes.fromhex(case["manifest_hex"]), bytes.fromhex(case["signature_hex"])


@pytest.mark.parametrize("case", VECTORS["valid"], ids=lambda c: c["id"])
def test_valid_vectors_verify_with_the_same_fields_as_the_pi(case):
    data, sig = _case(case)
    fields = vfr.verify_manifest(data, sig, PUBKEY)
    assert fields == case["fields"]
    assert fields == ota_manifest.verify(data, sig, PUBKEY)


@pytest.mark.parametrize("case", VECTORS["tampered"], ids=lambda c: c["id"])
def test_tampered_vectors_fail_the_signature(case):
    data, sig = _case(case)
    with pytest.raises(vfr.SignatureError):
        vfr.verify_manifest(data, sig, PUBKEY)
    with pytest.raises(ota_manifest.ManifestError):
        ota_manifest.verify(data, sig, PUBKEY)


@pytest.mark.parametrize("case", VECTORS["signed_but_invalid"], ids=lambda c: c["id"])
def test_signed_but_invalid_vectors_fail_the_form(case):
    data, sig = _case(case)
    with pytest.raises(vfr.FormError):
        vfr.verify_manifest(data, sig, PUBKEY)
    with pytest.raises(ota_manifest.ManifestError):
        ota_manifest.verify(data, sig, PUBKEY)


def test_the_independent_reader_matches_the_pi_on_its_constants():
    assert vfr.SCHEMA == ota_manifest.SCHEMA
    assert vfr.CHANNELS == ota_manifest.CHANNELS
    assert set(vfr.FIELDS) == ota_manifest.FIELDS and list(vfr.FIELDS) == sorted(vfr.FIELDS)
    assert vfr.MAX_MANIFEST_BYTES == ota_manifest.MAX_MANIFEST_BYTES
    assert vfr.MAX_SIZE == ota_manifest.MAX_SIZE
    assert vfr.VERSION_RE.pattern == ota_manifest.VERSION_RE.pattern
    assert vfr.MAX_NODE_MANIFEST_BYTES == MAX_NODE_MANIFEST_BYTES


def test_public_key_is_derived_from_the_private_key():
    assert vfr.derive_public_key_b64(base64.b64encode(SEED).decode()) == PUBKEY_B64
    assert vfr.derive_public_key_b64(base64.b64encode(SEED).decode() + "\n") == PUBKEY_B64
    with pytest.raises(vfr.ReleaseError, match="32 bytes"):
        vfr.derive_public_key_b64(base64.b64encode(SEED[:31]).decode())
    with pytest.raises(vfr.ReleaseError, match="base64"):
        vfr.derive_public_key_b64("not base64!")


def test_the_verify_key_grammar_is_fw_version_pys():
    fw_version = (ROOT / "firmware" / "scripts" / "fw_version.py").read_text()
    assert f're.compile(r"{vfr.PUBKEY_B64_RE.pattern}")' in fw_version
    with pytest.raises(vfr.ReleaseError):
        vfr.load_public_key(PUBKEY_B64[:-2])


# ─── Release zips, built as the workflow builds them ──────────────────────

VERSION = "5.1.0"


def _esp_image(chip: int, body: bytes = b"") -> bytes:
    """An ESP image header (magic 0xE9, chip id at 12..13) and a body."""
    header = bytearray(24)
    header[0] = 0xE9
    header[1] = 4
    header[12:14] = chip.to_bytes(2, "little")
    return bytes(header) + body


def _firmware(env: str, *, version: str = VERSION, pubkey_b64: str | None = PUBKEY_B64,
              chip: int | None = None, env_string: str | None = None,
              extra: tuple[str, ...] = ()) -> bytes:
    """firmware.bin with fw_version.py's C strings in its rodata."""
    chip = vfr.ENV_CHIPS[env] if chip is None else chip
    strings = [b"SporePrint", version.encode(), (env if env_string is None else env_string).encode()]
    if pubkey_b64 is not None:
        strings.append(pubkey_b64.encode())
    strings.extend(s.encode() for s in extra)
    return _esp_image(chip, b"\x00" * 64 + b"\x00".join(strings) + b"\x00" + b"\xff" * 64)


def _sign(tmp_path: Path, image: bytes, *, artifact: str, version: str = VERSION,
          channel: str = "stable") -> tuple[bytes, bytes]:
    """sign-ota-bundle.py, as the release job runs it."""
    work = tmp_path / "sign"
    work.mkdir(exist_ok=True)
    key = work / "key"
    key.write_text(base64.b64encode(SEED).decode())
    bundle = work / "firmware.bin"
    bundle.write_bytes(image)
    manifest = work / f"{artifact}.manifest.json"
    assert signer.main([
        "--bundle", str(bundle), "--private-key", str(key), "--out", str(work / "unused.sig"),
        "--manifest-out", str(manifest), "--artifact", artifact,
        "--version", version, "--channel", channel,
    ]) == 0
    return manifest.read_bytes(), Path(str(manifest) + ".sig").read_bytes()


def _members(tmp_path: Path, env: str, **firmware_kw) -> dict[str, bytes]:
    image = _firmware(env, **firmware_kw)
    data, sig = _sign(tmp_path, image, artifact=env)
    chip = vfr.ENV_CHIPS[env]
    return {
        "firmware.bin": image,
        "bootloader.bin": _esp_image(chip, b"bootloader"),
        "partitions.bin": b"\xaa\x50\x01\x02" + b"\x00" * 28 + b"\xeb\xeb" + b"\xff" * 30,
        f"{env}.manifest.json": data,
        f"{env}.manifest.json.sig": sig,
    }


def _zip(tmp_path: Path, env: str, members: dict[str, bytes]) -> Path:
    path = tmp_path / "dist" / f"{env}.zip"
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    return path


def _good_zip(tmp_path: Path, env: str = "node_esp32") -> Path:
    return _zip(tmp_path, env, _members(tmp_path, env))


def _check(path: Path, **kw):
    kw.setdefault("version", VERSION)
    return vfr.check_zip(path, PUBKEY, pi_verifier=vfr.load_pi_verifier(PI_VERIFIER), **kw)


@pytest.mark.parametrize("env", sorted(vfr.ENV_CHIPS))
def test_a_signed_release_zip_passes(tmp_path, env):
    manifest = _check(_good_zip(tmp_path, env))
    assert manifest["artifact"] == env
    assert manifest["version"] == VERSION and manifest["channel"] == "stable"


def test_the_pi_accepts_what_the_check_passes(tmp_path, monkeypatch):
    """The Pi's own push-time check (hardware/node_manifest.py) with this
    key pinned takes the same manifest and image."""
    members = _members(tmp_path, "cam")
    monkeypatch.setattr(settings, "ota_pubkey_b64", PUBKEY_B64)
    checked = check_node_manifest(members["cam.manifest.json"], members["cam.manifest.json.sig"],
                                  members["firmware.bin"], "5.0.0")
    assert checked.manifest == vfr.check_image(members, "cam", PUBKEY, version=VERSION,
                                               channel="stable")


def test_tampered_firmware_fails_the_sha256(tmp_path):
    members = _members(tmp_path, "node_esp32")
    image = bytearray(members["firmware.bin"])
    image[-1] ^= 0x01
    members["firmware.bin"] = bytes(image)
    with pytest.raises(vfr.ReleaseError, match="sha256"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_a_manifest_with_the_wrong_size_fails(tmp_path):
    """Signed by the release key with the image's sha256 but not its size."""
    image = _firmware("node_esp32")
    manifest = ota_manifest.build(
        artifact="node_esp32", version=VERSION, channel="stable",
        sha256=hashlib.sha256(image).hexdigest(), size=len(image) + 1,
        published_at="2026-10-06T12:00:00Z")
    data, sig = ota_manifest.sign(manifest, Ed25519PrivateKey.from_private_bytes(SEED))
    members = _members(tmp_path, "node_esp32")
    members.update({"firmware.bin": image, "node_esp32.manifest.json": data,
                    "node_esp32.manifest.json.sig": sig})
    with pytest.raises(vfr.ReleaseError, match="size"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_the_manifest_version_must_be_the_release_version(tmp_path):
    path = _good_zip(tmp_path)
    with pytest.raises(vfr.ReleaseError, match="version"):
        _check(path, version="5.1.1")


def test_a_manifest_signed_for_another_version_fails(tmp_path):
    image = _firmware("node_esp32")
    data, sig = _sign(tmp_path, image, artifact="node_esp32", version="5.0.0")
    members = _members(tmp_path, "node_esp32")
    members.update({"firmware.bin": image, "node_esp32.manifest.json": data,
                    "node_esp32.manifest.json.sig": sig})
    with pytest.raises(vfr.ReleaseError, match="version"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_an_image_built_as_another_version_fails(tmp_path):
    members = _members(tmp_path, "node_esp32", version="5.0.9")
    image = members["firmware.bin"]
    data, sig = _sign(tmp_path, image, artifact="node_esp32", version=VERSION)
    members.update({"node_esp32.manifest.json": data, "node_esp32.manifest.json.sig": sig})
    with pytest.raises(vfr.ReleaseError, match="SPOREPRINT_FW_VERSION"):
        _check(_zip(tmp_path, "node_esp32", members))


@pytest.mark.parametrize("built_as", ["15.1.0", "v5.1.0", "5.1.0-rc1", "25.1.0"])
def test_an_image_whose_version_only_ends_in_the_release_version_fails(tmp_path, built_as):
    """5.1.0 must be the whole version string, not the tail of a longer one."""
    members = _members(tmp_path, "node_esp32", version=built_as)
    image = members["firmware.bin"]
    data, sig = _sign(tmp_path, image, artifact="node_esp32", version=VERSION)
    members.update({"node_esp32.manifest.json": data, "node_esp32.manifest.json.sig": sig})
    with pytest.raises(vfr.ReleaseError, match="SPOREPRINT_FW_VERSION"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_embeds_c_string_needs_a_whole_terminated_string():
    alphabet = vfr.VERSION_CHARS
    assert vfr.embeds_c_string(b"5.1.0\0", "5.1.0", alphabet)
    assert vfr.embeds_c_string(b"x\x005.1.0\0", "5.1.0", alphabet)
    assert vfr.embeds_c_string(b"SporePrint 5.1.0\0", "5.1.0", alphabet)
    # A later whole occurrence counts even after a tail match.
    assert vfr.embeds_c_string(b"v5.1.0\0\x005.1.0\0", "5.1.0", alphabet)
    assert not vfr.embeds_c_string(b"v5.1.0\0", "5.1.0", alphabet)
    assert not vfr.embeds_c_string(b"\x005.1.0", "5.1.0", alphabet)
    assert not vfr.embeds_c_string(b"\x005.1.0.1\0", "5.1.0", alphabet)


def test_an_image_with_the_key_only_as_the_tail_of_a_longer_string_fails(tmp_path):
    members = _members(tmp_path, "node_esp32", pubkey_b64="QQ" + PUBKEY_B64)
    with pytest.raises(vfr.ReleaseError, match="verify key"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_the_env_may_be_the_tail_of_a_longer_string(tmp_path):
    """The real cam image: the linker stores "cam" as the tail of the camera
    driver's "esp32 ll_cam", so the env is never a whole string there."""
    members = _members(tmp_path, "cam", env_string="esp32 ll_cam")
    assert b"\0cam\0" not in members["firmware.bin"]
    assert _check(_zip(tmp_path, "cam", members))["artifact"] == "cam"


def test_an_image_that_names_another_env_fails(tmp_path):
    """Ends in "cam" (so the cam check alone would pass) but is a node image."""
    members = _members(tmp_path, "cam", env_string="esp32 ll_cam", extra=("node_esp32",))
    with pytest.raises(vfr.ReleaseError, match="names the env 'node_esp32'"):
        _check(_zip(tmp_path, "cam", members))


def test_an_image_that_does_not_name_its_env_fails(tmp_path):
    members = _members(tmp_path, "node_esp32s3", env_string="node_esp32s3_n32r16v")
    with pytest.raises(vfr.ReleaseError, match="does not name its env"):
        _check(_zip(tmp_path, "node_esp32s3", members))


def test_a_manifest_edited_after_signing_fails_the_signature(tmp_path):
    members = _members(tmp_path, "node_esp32")
    members["node_esp32.manifest.json"] = members["node_esp32.manifest.json"].replace(
        b'"version":"5.1.0"', b'"version":"5.1.9"')
    with pytest.raises(vfr.SignatureError):
        _check(_zip(tmp_path, "node_esp32", members))


def test_a_flipped_signature_bit_fails(tmp_path):
    members = _members(tmp_path, "node_esp32")
    sig = bytearray(members["node_esp32.manifest.json.sig"])
    sig[0] ^= 0x01
    members["node_esp32.manifest.json.sig"] = bytes(sig)
    with pytest.raises(vfr.SignatureError):
        _check(_zip(tmp_path, "node_esp32", members))


def test_a_truncated_signature_fails(tmp_path):
    members = _members(tmp_path, "node_esp32")
    members["node_esp32.manifest.json.sig"] = members["node_esp32.manifest.json.sig"][:63]
    with pytest.raises(vfr.SignatureError):
        _check(_zip(tmp_path, "node_esp32", members))


def test_a_signature_by_another_key_fails(tmp_path):
    members = _members(tmp_path, "node_esp32")
    members["node_esp32.manifest.json.sig"] = OTHER_KEY.sign(members["node_esp32.manifest.json"])
    with pytest.raises(vfr.SignatureError):
        _check(_zip(tmp_path, "node_esp32", members))


def test_checking_with_another_verify_key_fails(tmp_path):
    path = _good_zip(tmp_path)
    with pytest.raises(vfr.SignatureError):
        vfr.check_zip(path, OTHER_KEY.public_key(), version=VERSION)


def test_an_image_without_the_verify_key_fails(tmp_path):
    """Built without SPOREPRINT_OTA_PUBKEY_B64: the node could not check."""
    members = _members(tmp_path, "node_esp32", pubkey_b64=None)
    with pytest.raises(vfr.ReleaseError, match="verify key"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_an_image_with_another_verify_key_fails(tmp_path):
    other = vfr.public_key_b64(OTHER_KEY.public_key())
    members = _members(tmp_path, "node_esp32", pubkey_b64=other)
    with pytest.raises(vfr.ReleaseError, match="verify key"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_another_envs_signed_image_under_this_name_fails(tmp_path):
    """cam's signed zip renamed node_esp32.zip: the artifact is cam."""
    members = _members(tmp_path, "cam")
    renamed = {name.replace("cam.manifest", "node_esp32.manifest"): blob
               for name, blob in members.items()}
    with pytest.raises(vfr.ReleaseError, match="artifact"):
        _check(_zip(tmp_path, "node_esp32", renamed))


def test_a_pi_server_manifest_is_not_a_node_image(tmp_path):
    image = _firmware("node_esp32")
    data, sig = _sign(tmp_path, image, artifact="sporeprint-server")
    members = _members(tmp_path, "node_esp32")
    members.update({"firmware.bin": image, "node_esp32.manifest.json": data,
                    "node_esp32.manifest.json.sig": sig})
    with pytest.raises(vfr.ReleaseError, match="artifact"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_an_image_for_the_wrong_chip_fails(tmp_path):
    """An ESP32-S3 build shipped as the ESP32 node image."""
    members = _members(tmp_path, "node_esp32", chip=vfr.CHIP_ESP32S3)
    with pytest.raises(vfr.ReleaseError, match="chip"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_bootloader_and_partitions_must_be_what_they_say(tmp_path):
    members = _members(tmp_path, "node_esp32s3")
    swapped = {**members, "bootloader.bin": members["partitions.bin"],
               "partitions.bin": members["bootloader.bin"]}
    with pytest.raises(vfr.ReleaseError, match="bootloader.bin"):
        _check(_zip(tmp_path, "node_esp32s3", swapped))
    esp32_bootloader = {**members, "bootloader.bin": _esp_image(vfr.CHIP_ESP32)}
    with pytest.raises(vfr.ReleaseError, match="chip"):
        _check(_zip(tmp_path, "node_esp32s3", esp32_bootloader))


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_a_zip_holds_exactly_the_five_files(tmp_path, change):
    members = _members(tmp_path, "node_esp32")
    if change == "missing":
        del members["bootloader.bin"]
    else:
        members["README.txt"] = b"unexpected"
    with pytest.raises(vfr.ReleaseError, match="expected exactly"):
        _check(_zip(tmp_path, "node_esp32", members))


def test_an_unknown_env_is_refused(tmp_path):
    with pytest.raises(vfr.ReleaseError, match="not a firmware image env"):
        _check(_zip(tmp_path, "node_esp8266", {}))


def test_a_renamed_zip_is_checked_with_an_explicit_env(tmp_path):
    good = _good_zip(tmp_path, "node_esp32")
    renamed = good.with_name("node_esp32 (1).zip")
    good.rename(renamed)
    with pytest.raises(vfr.ReleaseError, match="not a firmware image env"):
        _check(renamed)
    assert _check(renamed, env="node_esp32")["artifact"] == "node_esp32"
    # The explicit env is still the signed artifact.
    with pytest.raises(vfr.ReleaseError):
        _check(renamed, env="node_esp32s3")


def test_verifiers_must_agree(tmp_path):
    class Disagrees:
        @staticmethod
        def verify(data, sig, pubkey):
            return {**ota_manifest.verify(data, sig, pubkey), "version": "9.9.9"}

    with pytest.raises(vfr.ReleaseError, match="disagree"):
        vfr.check_zip(_good_zip(tmp_path), PUBKEY, version=VERSION, pi_verifier=Disagrees)


# ─── Command line ─────────────────────────────────────────────────────────


def test_cli_checks_every_zip_and_the_env_set(tmp_path, capsys):
    zips = [_good_zip(tmp_path, env) for env in ("node_esp32", "cam")]
    argv = ["--pubkey-b64", PUBKEY_B64, "--version", VERSION, "--pi-verifier", str(PI_VERIFIER)]
    assert vfr.main([*argv, "--expect-envs", "node_esp32 cam", *map(str, zips)]) == 0
    out = capsys.readouterr().out
    assert "ok node_esp32.zip" in out and "ok cam.zip" in out and "Pi's verifier agrees" in out

    assert vfr.main([*argv, "--expect-envs", "node_esp32,cam,cam_esp32s3", *map(str, zips)]) == 1
    assert "expected one per env" in capsys.readouterr().err

    assert vfr.main([*argv[:2], "--version", "5.2.0", str(zips[0])]) == 1
    assert "version" in capsys.readouterr().err


def test_cli_env_names_a_single_renamed_zip(tmp_path, capsys):
    good = _good_zip(tmp_path, "cam")
    renamed = good.with_name("cam(1).zip")
    good.rename(renamed)
    argv = ["--pubkey-b64", PUBKEY_B64, "--version", VERSION]
    assert vfr.main([*argv, str(renamed)]) == 1
    assert "not a firmware image env" in capsys.readouterr().err
    assert vfr.main([*argv, "--env", "cam", "--expect-envs", "cam", str(renamed)]) == 0
    assert "ok cam(1).zip: cam 5.1.0" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        vfr.main([*argv, "--env", "cam", str(renamed), str(_good_zip(tmp_path, "node_esp32"))])
    with pytest.raises(SystemExit):
        vfr.main([*argv, "--env", "node_esp8266", str(renamed)])


def test_cli_print_pubkey_prints_only_the_public_key(monkeypatch, capsys):
    private_b64 = base64.b64encode(SEED).decode()
    monkeypatch.setenv("OTA_SIGNING_KEY", private_b64)
    assert vfr.main(["--print-pubkey"]) == 0
    captured = capsys.readouterr()
    assert captured.out == PUBKEY_B64 + "\n"
    assert private_b64 not in captured.out + captured.err


@pytest.mark.parametrize("value", ["", "   ", "AAAA"])
def test_cli_print_pubkey_fails_closed(monkeypatch, capsys, value):
    monkeypatch.setenv("OTA_SIGNING_KEY", value)
    assert vfr.main(["--print-pubkey"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "OTA_SIGNING_KEY" in captured.err


def test_cli_print_pubkey_fails_closed_without_the_variable(monkeypatch):
    monkeypatch.delenv("OTA_SIGNING_KEY", raising=False)
    assert vfr.main(["--print-pubkey"]) == 1
