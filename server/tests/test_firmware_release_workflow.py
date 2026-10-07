""".github/workflows/firmware-release.yml publishes SIGNED firmware from a
public repository. These pin its security properties:

* it runs only for a pushed firmware-v* tag or a manual dispatch, never for
  pull requests or other workflows' events;
* the token is read-only except in the release job, which never holds the
  signing key;
* the signing key (secret OTA_SIGNING_KEY) reaches only the one step that
  needs it in each of the two jobs that run no build tooling, no third-party
  action and no write token (both in the firmware-release environment); the
  PlatformIO builds get the public verify key only;
* untrusted values reach shell through env vars, and the tag guard accepts
  exactly firmware-vX.Y.Z (the guard itself runs here under bash);
* the sign job signs with sign-ota-bundle.py from a shredded 0600 key file
  and checks every zip with verify_firmware_release.py (no secret); the
  release job checks them again before it creates the release (the sign,
  package and verify scripts themselves run here under bash);
* every image env in platformio.ini is built, signed, checked and shipped.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "firmware-release.yml"
PLATFORMIO_INI = ROOT / "firmware" / "platformio.ini"
SECRET = "${{ secrets.OTA_SIGNING_KEY }}"
KEY_JOBS = {"release-key", "sign"}
# Every job that installs Python tooling, each from the same pinned lock.
TOOLING_JOBS = ("release-key", "sign", "release")
ENVIRONMENT = "firmware-release"
BASH = shutil.which("bash")
ZIP = shutil.which("zip")
VECTORS = json.loads((ROOT / "server" / "tests" / "fixtures" / "ota_manifest_vectors.json").read_text())

WF = yaml.safe_load(WORKFLOW.read_text())
JOBS = WF["jobs"]

_spec = importlib.util.spec_from_file_location(
    "verify_firmware_release_for_workflow_test", ROOT / "scripts" / "verify_firmware_release.py")
vfr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vfr)


def _triggers() -> dict:
    # YAML 1.1 reads the bare key `on` as True.
    return WF.get("on", WF.get(True))


def _steps(job: str) -> list[dict]:
    return JOBS[job]["steps"]


def _step(job: str, name_part: str) -> dict:
    matches = [s for s in _steps(job) if name_part in s.get("name", "")]
    assert len(matches) == 1, f"{job}: {len(matches)} steps named like {name_part!r}"
    return matches[0]


def _index(job: str, step: dict) -> int:
    return next(i for i, s in enumerate(_steps(job)) if s is step)


def _image_envs() -> list[str]:
    return [e for e in re.findall(r"^\[env:([a-z0-9_]+)\]", PLATFORMIO_INI.read_text(), re.M)
            if e != "native"]


def _python_on_path(tmp_path: Path) -> Path:
    """A bin dir whose `python` is this interpreter, its venv included (a
    symlink to a venv's python loses the venv)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    wrapper = bindir / "python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    return bindir


def _run_step(step: dict, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    """A run: script under bash as Actions runs it (bash -e -o pipefail)."""
    return subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                          env={"PATH": os.environ["PATH"], **env}, cwd=cwd,
                          capture_output=True, text=True, check=False)


# ─── Triggers and token ───────────────────────────────────────────────────


def test_runs_only_for_release_tags_and_manual_dispatch():
    on = _triggers()
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"tags": ["firmware-v*"]}
    assert set(on["workflow_dispatch"]["inputs"]) == {"tag"}
    text = WORKFLOW.read_text()
    for event in ("pull_request", "pull_request_target", "workflow_run", "issue_comment",
                  "repository_dispatch"):
        assert not re.search(rf"^\s*{event}\s*:", text, re.M), event


def test_the_token_is_read_only_except_in_the_release_job():
    assert WF["permissions"] == {"contents": "read"}
    assert set(JOBS) == {"release-key", "build", "sign", "release"}
    assert JOBS["release"]["permissions"] == {"contents": "write"}
    for name, job in JOBS.items():
        if name != "release":
            assert job.get("permissions") == {"contents": "read"}, name
    # The writer never holds the key, and comes after the signer.
    assert "secrets" not in yaml.safe_dump(JOBS["release"])
    assert "sign" in JOBS["release"]["needs"]


def test_no_job_is_a_reusable_workflow_call_or_inherits_secrets():
    for name, job in JOBS.items():
        assert "uses" not in job and "secrets" not in job, name
        assert "steps" in job, name


def test_the_key_jobs_run_in_the_release_environment():
    """So the secret can be an environment secret released only to the ref
    patterns the environment allows. The jobs without the key stay out."""
    for name, job in JOBS.items():
        if name in KEY_JOBS:
            assert job["environment"] == ENVIRONMENT, name
        else:
            assert "environment" not in job, name


def test_actions_are_pinned_to_commit_shas_and_checkouts_keep_no_token():
    for name, job in JOBS.items():
        for step in job["steps"]:
            uses = step.get("uses")
            if not uses:
                continue
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses), f"{name}: {uses}"
            if uses.startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False, name
            # A restored cache could hand a release build a poisoned toolchain
            # (actions/cache, or setup-python's own pip cache).
            assert not uses.startswith("actions/cache"), f"{name}: {uses}"
            assert not any(k.startswith("cache") for k in step.get("with", {})), f"{name}: {uses}"


def test_only_github_actions_run_where_the_key_is():
    """The one third-party action creates the release, in the job that never
    holds the key; the key jobs run only GitHub's own actions."""
    third_party = {(name, step["uses"].split("@")[0]) for name, job in JOBS.items()
                   for step in job["steps"]
                   if "uses" in step and not step["uses"].startswith("actions/")}
    assert third_party == {("release", "softprops/action-gh-release")}


def test_every_checkout_is_the_checked_tag():
    for name, job in JOBS.items():
        checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
        assert len(checkouts) == 1, name
        ref = checkouts[0]["with"]["ref"]
        if name == "release-key":
            assert ref == "refs/tags/${{ steps.meta.outputs.tag }}"
            assert _index(name, checkouts[0]) > _index(name, _step(name, "check the release tag"))
        else:
            assert ref == "refs/tags/${{ needs.release-key.outputs.tag }}", name
            assert "release-key" in (job["needs"] if isinstance(job["needs"], list) else [job["needs"]])


# ─── The signing key ──────────────────────────────────────────────────────


def test_only_the_signing_secret_is_used():
    """Every mention of the secrets context is secrets.OTA_SIGNING_KEY: no
    toJSON(secrets), secrets['...'], `secrets: inherit` or other secret."""
    text = WORKFLOW.read_text()
    mentions = [m.start() for m in re.finditer(r"\bsecrets\b", text)]
    assert len(mentions) == 2
    for at in mentions:
        assert text.startswith(SECRET, at - len("${{ ")), text[at - 10:at + 40]
    assert "toJSON" not in text and "fromJSON" not in text


def test_the_private_key_reaches_only_steps_of_the_jobs_without_build_tooling():
    assert "env" not in WF, "no workflow-level env"
    holders = []
    for name, job in JOBS.items():
        assert SECRET not in yaml.safe_dump(job.get("env", {})), f"{name}: job-level env"
        for step in job["steps"]:
            dumped = yaml.safe_dump({k: v for k, v in step.items() if k != "env"})
            assert "secrets." not in dumped, f"{name}: {step.get('name')} uses a secret outside env"
            secret_vars = [k for k, v in step.get("env", {}).items() if "secrets." in str(v)]
            if secret_vars:
                assert secret_vars == ["OTA_SIGNING_KEY"], f"{name}: {secret_vars}"
                assert step["env"]["OTA_SIGNING_KEY"] == SECRET
                holders.append((name, step["name"]))
    assert {job for job, _ in holders} == KEY_JOBS
    assert [s for j, s in holders if j == "release-key"] == [
        "Derive the release verify key (public half only)"]
    assert [s for j, s in holders if j == "sign"] == [
        "Sign each image's release manifest (Ed25519)"]
    for name in JOBS.keys() - KEY_JOBS:
        assert "secrets" not in yaml.safe_dump(JOBS[name]), name


def test_jobs_holding_the_key_run_no_platformio():
    for name in KEY_JOBS:
        text = yaml.safe_dump(JOBS[name]).lower()
        assert "platformio" not in text and "pio run" not in text, name


def _pin_step(job: str) -> dict:
    return _step(job, "tooling to server/uv.lock")


def test_tooling_jobs_install_only_hash_pinned_wheels_from_the_lock():
    for name in TOOLING_JOBS:
        installs = [s for s in _steps(name) if "pip install" in s.get("run", "")]
        assert len(installs) == 1, name
        cmd = installs[0]["run"]
        for flag in ("--require-hashes", "--only-binary=:all:", "--no-deps"):
            assert flag in cmd, f"{name}: {flag}"
        pin = _pin_step(name)
        assert _index(name, pin) < _index(name, installs[0])
        assert "server/uv.lock" in pin["run"]
        assert pin["run"] == _pin_step("sign")["run"], name
        assert installs[0]["run"] == next(
            s for s in _steps("sign") if "pip install" in s.get("run", ""))["run"], name


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_the_pinned_tooling_is_the_locked_cryptography_with_hashes(tmp_path):
    (tmp_path / "server").mkdir()
    shutil.copy(ROOT / "server" / "uv.lock", tmp_path / "server" / "uv.lock")
    bindir = _python_on_path(tmp_path)
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c",
         _pin_step("sign")["run"]],
        env={"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path)},
        cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    lines = (tmp_path / "release-requirements.txt").read_text().splitlines()
    pins = {line.split()[0].split("==")[0]: line for line in lines}
    lock = {p["name"]: p for p in tomllib.loads((ROOT / "server" / "uv.lock").read_text())["package"]}
    assert "cryptography" in pins
    for name, line in pins.items():
        assert line.startswith(f"{name}=={lock[name]['version']} --hash=sha256:"), line
        assert line.count("--hash=") == len(lock[name]["wheels"]), name
        for dep in lock[name].get("dependencies", []):
            assert dep["name"] in pins, f"{name} needs {dep['name']}"


def test_the_derive_step_fails_closed_and_outputs_only_the_public_key():
    run = _step("release-key", "Derive the release verify key")["run"]
    assert '[ -z "${OTA_SIGNING_KEY:-}" ]' in run and "exit 1" in run
    assert "scripts/verify_firmware_release.py --print-pubkey" in run
    assert JOBS["release-key"]["outputs"] == {
        "tag": "${{ steps.meta.outputs.tag }}",
        "version": "${{ steps.meta.outputs.version }}",
        "channel": "${{ steps.meta.outputs.channel }}",
        "sha": "${{ steps.commit.outputs.sha }}",
        "pubkey": "${{ steps.derive.outputs.pubkey }}",
    }
    outputs = set(re.findall(r"echo \"(\w+)=", run))
    assert outputs == {"pubkey"}


def test_the_sign_step_uses_a_shredded_0600_key_file():
    run = _step("sign", "Sign each image's release manifest")["run"]
    assert '[ -z "${OTA_SIGNING_KEY:-}" ]' in run
    assert "umask 077" in run and 'chmod 600 "$KEYFILE"' in run
    assert re.search(r"KEYFILE=\"\$\(mktemp \"\$RUNNER_TEMP/", run)
    trap = run.index("trap 'shred -u \"$KEYFILE\"")
    assert trap < run.index("printf '%s' \"$OTA_SIGNING_KEY\" > \"$KEYFILE\"")
    assert "python scripts/sign-ota-bundle.py" in run and '--private-key "$KEYFILE"' in run
    for flag in ('--artifact "$ENV_NAME"', '--version "$VERSION"', '--channel "$CHANNEL"',
                 '--manifest-out "$DIR/$ENV_NAME.manifest.json"'):
        assert flag in run, flag
    # The key never reaches a command line.
    assert not re.search(r"(echo|python|cat)[^\n]*\$OTA_SIGNING_KEY", run)


def _uses(job: str, action: str) -> list[dict]:
    return [s for s in _steps(job) if s.get("uses", "").startswith(action + "@")]


def test_every_zip_is_verified_without_the_secret_before_the_release():
    sign_verify = _step("sign", "Verify every zip")
    release_verify = _step("release", "Verify every zip again")
    for verify in (sign_verify, release_verify):
        run = verify["run"]
        assert "secrets" not in yaml.safe_dump(verify)
        assert "python scripts/verify_firmware_release.py" in run
        for flag in ('--pubkey-b64 "$PUBKEY"', '--version "$VERSION"', '--channel "$CHANNEL"',
                     "--pi-verifier server/app/cloud/ota_manifest.py",
                     '--expect-envs "$FIRMWARE_ENVS"', "dist/*.zip"):
            assert flag in run, flag
        assert verify["env"] == {"VERSION": "${{ needs.release-key.outputs.version }}",
                                 "CHANNEL": "${{ needs.release-key.outputs.channel }}",
                                 "PUBKEY": "${{ needs.release-key.outputs.pubkey }}"}
    assert sign_verify["run"] == release_verify["run"]

    # sign: sign → package → verify → hand the zips on.
    sign = _step("sign", "Sign each image's release manifest")
    package = _step("sign", "Package one zip per env")
    [upload] = _uses("sign", "actions/upload-artifact")
    assert _index("sign", sign) < _index("sign", package) < _index("sign", sign_verify) \
        < _index("sign", upload)
    assert upload["with"]["path"] == "dist/" and upload["with"]["if-no-files-found"] == "error"

    # release: exactly those zips → verify again → publish.
    [download] = _uses("release", "actions/download-artifact")
    assert download["with"] == {"name": upload["with"]["name"], "path": "dist"}
    [publish] = _uses("release", "softprops/action-gh-release")
    assert _index("release", download) < _index("release", release_verify) \
        < _index("release", publish)
    assert publish["with"]["files"] == "dist/*.zip"
    assert publish["with"]["fail_on_unmatched_files"] is True
    assert publish["with"]["tag_name"] == "${{ needs.release-key.outputs.tag }}"


def test_the_usb_flash_notes_reset_the_ota_boot_selection():
    """The zips carry no otadata: a USB flash that keeps the old otadata can
    go on booting the other app slot's old image."""
    body = _uses("release", "softprops/action-gh-release")[0]["with"]["body"]
    flashes = [line for line in body.splitlines() if "write-flash" in line]
    assert len(flashes) == 2 and all("write-flash --erase-all" in line for line in flashes)
    assert "esptool erase-region 0xe000 0x2000" in body
    for csv in sorted((ROOT / "firmware").glob("partitions*.csv")):
        rows = [[c.strip() for c in line.split(",")] for line in csv.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
        assert ["otadata", "data", "ota", "0xe000", "0x2000", ""] in rows, csv.name


def test_the_build_gets_the_public_key_and_the_tag_version():
    build = _step("build", "Build ${{ matrix.env }}")
    assert build["env"]["SPOREPRINT_OTA_PUBKEY_B64"] == "${{ needs.release-key.outputs.pubkey }}"
    assert build["env"]["SPOREPRINT_FW_VERSION"] == "${{ needs.release-key.outputs.version }}"
    assert "SPOREPRINT_OTA_REQUIRE_MANIFEST" not in yaml.safe_dump(JOBS)
    assert 'pio run -e "$BUILD_ENV"' in build["run"]
    preflight = _step("build", "Preflight")
    assert "firmware/VERSION.txt" in preflight["run"]
    assert _index("build", preflight) < _index("build", build)


# ─── Every image, and only images ─────────────────────────────────────────


def test_every_image_env_is_built_signed_and_checked():
    envs = _image_envs()
    assert len(envs) == 7
    assert JOBS["build"]["strategy"]["matrix"]["env"] == envs
    assert JOBS["sign"]["env"]["FIRMWARE_ENVS"].split() == envs
    assert JOBS["release"]["env"]["FIRMWARE_ENVS"].split() == envs
    assert sorted(vfr.ENV_CHIPS) == sorted(envs)


# ─── Untrusted input ──────────────────────────────────────────────────────


def test_no_expression_is_interpolated_into_a_shell_script():
    for name, job in JOBS.items():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), f"{name}: {step.get('name')}"


TAG_STEP = next(s for s in _steps("release-key") if s.get("id") == "meta")


def _resolve(tmp_path: Path, **env: str) -> tuple[int, dict[str, str]]:
    out = tmp_path / "github_output"
    out.write_text("")
    base = {"EVENT_NAME": "push", "INPUT_TAG": "", "REF_NAME": "", "REF_TYPE": "tag",
            "GITHUB_OUTPUT": str(out)}
    result = _run_step(TAG_STEP, {**base, **env}, tmp_path)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result.returncode, outputs


@pytest.mark.skipif(BASH is None, reason="needs bash")
@pytest.mark.parametrize("tag, version", [
    ("firmware-v5.1.0", "5.1.0"), ("firmware-v0.0.1", "0.0.1"), ("firmware-v10.20.300", "10.20.300"),
])
def test_tag_guard_accepts_release_tags(tmp_path, tag, version):
    assert _resolve(tmp_path, REF_NAME=tag) == (0, {"tag": tag, "version": version,
                                                    "channel": "stable"})
    rc, outputs = _resolve(tmp_path, EVENT_NAME="workflow_dispatch", INPUT_TAG=tag,
                           REF_NAME="main", REF_TYPE="branch")
    assert (rc, outputs["tag"], outputs["version"]) == (0, tag, version)


@pytest.mark.skipif(BASH is None, reason="needs bash")
@pytest.mark.parametrize("tag", [
    "", "main", "v5.1.0", "firmware-v5.1", "firmware-v5.1.0-beta.1", "firmware-v5.1.0.1",
    "firmware-v05.1.0", "firmware-v5.1.0 ", " firmware-v5.1.0", "refs/tags/firmware-v5.1.0",
    "firmware-v5.1.0\nversion=9.9.9", "firmware-v5.1.0\n", "firmware-v1234567890.0.0",
    "firmware-v5.1.0;id", "firmware-v$(id).1.0",
])
def test_tag_guard_refuses_everything_else(tmp_path, tag):
    for env in ({"REF_NAME": tag},
                {"EVENT_NAME": "workflow_dispatch", "INPUT_TAG": tag, "REF_NAME": "firmware-v5.1.0"}):
        assert _resolve(tmp_path, **env) == (1, {}), (env, tag)


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_tag_guard_refuses_a_branch_push(tmp_path):
    assert _resolve(tmp_path, REF_NAME="firmware-v5.1.0", REF_TYPE="branch") == (1, {})


# ─── The sign → package → verify scripts, run as the jobs run them ───────


def _image(chip: int, strings: list[str]) -> bytes:
    """An ESP image header (magic 0xE9, chip id at 12..13) and C strings."""
    header = bytearray(24)
    header[0], header[1] = 0xE9, 4
    header[12:14] = chip.to_bytes(2, "little")
    body = b"\x00" * 64 + b"\x00".join(s.encode() for s in strings) + b"\x00" + b"\xff" * 64
    return bytes(header) + body


def _workspace(tmp_path: Path, version: str = "5.1.0") -> tuple[Path, dict[str, str]]:
    """A checkout's scripts/ and server/, and the build jobs' artifacts as
    download-artifact lays them out (unsigned/firmware-<env>/...)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "scripts").symlink_to(ROOT / "scripts")
    (ws / "server").symlink_to(ROOT / "server")
    for env, chip in vfr.ENV_CHIPS.items():
        out = ws / "unsigned" / f"firmware-{env}"
        out.mkdir(parents=True)
        (out / "firmware.bin").write_bytes(
            _image(chip, ["SporePrint", version, env, VECTORS["public_key_b64"]]))
        (out / "bootloader.bin").write_bytes(_image(chip, ["bootloader"]))
        (out / "partitions.bin").write_bytes(b"\xaa\x50" + b"\x00" * 30 + b"\xff" * 32)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    bindir = _python_on_path(tmp_path)
    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_WORKSPACE": str(ws),
        "FIRMWARE_ENVS": JOBS["sign"]["env"]["FIRMWARE_ENVS"],
        "VERSION": version,
        "CHANNEL": "stable",
        "PUBKEY": VECTORS["public_key_b64"],
    }
    return ws, env


def _run_job_steps(job: str, names: list[str], ws: Path, env: dict[str, str]):
    for name in names:
        result = _run_step(_step(job, name), env, ws)
        if result.returncode != 0:
            return name, result
    return None, result


SIGN_STEPS = ["Sign each image's release manifest", "Package one zip per env", "Verify every zip ("]


@pytest.mark.skipif(BASH is None or ZIP is None, reason="needs bash and zip")
def test_the_sign_package_and_verify_scripts_ship_only_good_zips(tmp_path):
    ws, env = _workspace(tmp_path)
    secret = base64.b64encode(bytes.fromhex(VECTORS["private_seed_hex"])).decode()
    failed, result = _run_job_steps("sign", SIGN_STEPS, ws, {**env, "OTA_SIGNING_KEY": secret})
    assert failed is None, (failed, result.stdout, result.stderr)
    assert secret not in result.stdout + result.stderr
    # The key file is gone, and the legacy whole-file .sig with it.
    assert list(Path(env["RUNNER_TEMP"]).iterdir()) == []
    zips = sorted(p.name for p in (ws / "dist").iterdir())
    assert zips == sorted(f"{e}.zip" for e in vfr.ENV_CHIPS)
    pubkey = vfr.load_public_key(VECTORS["public_key_b64"])
    for name in zips:
        manifest = vfr.check_zip(ws / "dist" / name, pubkey, version="5.1.0")
        assert manifest["artifact"] == name.removesuffix(".zip")

    # The release job's own check, on the zips the sign job handed on.
    verify_again = _step("release", "Verify every zip again")
    assert _run_step(verify_again, env, ws).returncode == 0
    # A zip swapped after signing never ships.
    cam = ws / "dist" / "cam.zip"
    other = _image(vfr.CHIP_ESP32, ["SporePrint", "5.1.0", "cam", VECTORS["public_key_b64"], "x"])
    with zipfile.ZipFile(cam) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    members["firmware.bin"] = other
    with zipfile.ZipFile(cam, "w") as zf:
        for n, blob in members.items():
            zf.writestr(n, blob)
    result = _run_step(verify_again, env, ws)
    assert result.returncode == 1 and "cam.zip" in result.stderr and "sha256" in result.stderr


@pytest.mark.skipif(BASH is None or ZIP is None, reason="needs bash and zip")
def test_a_failed_signing_still_removes_the_key_file(tmp_path):
    ws, env = _workspace(tmp_path)
    (ws / "unsigned" / "firmware-cam_waveshare_s3" / "firmware.bin").unlink()
    secret = base64.b64encode(bytes.fromhex(VECTORS["private_seed_hex"])).decode()
    result = _run_step(_step("sign", "Sign each image's release manifest"),
                       {**env, "OTA_SIGNING_KEY": secret}, ws)
    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr
    assert not list(Path(env["RUNNER_TEMP"]).glob("ota-signing.*"))


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_the_sign_step_fails_closed_without_the_key(tmp_path):
    ws, env = _workspace(tmp_path)
    result = _run_step(_step("sign", "Sign each image's release manifest"),
                       {**env, "OTA_SIGNING_KEY": ""}, ws)
    assert result.returncode == 1 and "OTA_SIGNING_KEY" in result.stdout
    assert not list((ws / "unsigned").rglob("*.manifest.json"))


@pytest.mark.skipif(BASH is None or ZIP is None, reason="needs bash and zip")
def test_a_zip_signed_by_another_key_fails_the_check(tmp_path):
    """Signed with a key whose public half is not the one the images carry."""
    ws, env = _workspace(tmp_path)
    other = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"not the release key").digest())
    secret = base64.b64encode(other.private_bytes_raw()).decode()
    failed, result = _run_job_steps("sign", SIGN_STEPS, ws, {**env, "OTA_SIGNING_KEY": secret})
    assert failed == "Verify every zip ("
    assert result.stderr.count("signature does not verify") == len(vfr.ENV_CHIPS)


# ─── One commit for the whole run ─────────────────────────────────────────

GIT = shutil.which("git")


def test_release_key_records_the_tagged_commit_and_every_later_job_checks_it():
    record = _step("release-key", "Record the tagged commit")
    checkout = next(s for s in _steps("release-key") if s.get("uses", "").startswith("actions/checkout@"))
    assert _index("release-key", checkout) < _index("release-key", record)
    assert record["id"] == "commit" and "git rev-parse HEAD" in record["run"]
    assert JOBS["release-key"]["outputs"]["sha"] == "${{ steps.commit.outputs.sha }}"
    for name in ("build", "sign", "release"):
        check = _step(name, "Check the tag still names the commit")
        steps = _steps(name)
        checkout_at = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/checkout@"))
        # Right after the checkout, before anything from the tree runs.
        assert _index(name, check) == checkout_at + 1, name
        assert check["env"] == {"RELEASE_SHA": "${{ needs.release-key.outputs.sha }}"}, name
        assert check["run"] == _step("sign", "Check the tag still names the commit")["run"], name


@pytest.mark.skipif(BASH is None or GIT is None, reason="needs bash and git")
def test_the_commit_check_refuses_a_moved_tag(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git_env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
               "HOME": str(tmp_path)}
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run([GIT, *args], cwd=repo, env={**os.environ, **git_env}, check=True)
    head = subprocess.run([GIT, "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()
    check = _step("build", "Check the tag still names the commit")
    assert _run_step(check, {"RELEASE_SHA": head, **git_env}, repo).returncode == 0
    for other in ("0" * 40, ""):
        result = _run_step(check, {"RELEASE_SHA": other, **git_env}, repo)
        assert result.returncode != 0, other
        assert "moved during the run" in result.stdout


# ─── The build toolchain ──────────────────────────────────────────────────


def test_the_build_uses_only_hash_checked_platform_packages():
    prepare = _step("build", "Fetch the PlatformIO platform and packages")
    check = _step("build", "Check the build installed only checked packages")
    build = _step("build", "Build ${{ matrix.env }}")
    install = _step("build", "Install PlatformIO")
    assert _index("build", install) < _index("build", prepare) < _index("build", build)
    assert _index("build", build) < _index("build", check) < _index("build", _step("build", "Collect the images"))
    assert "scripts/pin_firmware_toolchain.py prepare" in prepare["run"]
    assert "scripts/pin_firmware_toolchain.py check" in check["run"]


# ─── The build's Python packages ─────────────────────────────────────────


def test_the_build_installs_platformio_from_the_hashed_lock():
    install = _step("build", "Install PlatformIO")["run"]
    for flag in ("--require-hashes", "--only-binary=:all:", "-r firmware/requirements-pio.txt"):
        assert flag in install, flag
    assert "platformio==" not in install


def test_the_build_creates_the_platform_penv_from_the_hashed_lock_before_building():
    penv = _step("build", "Create the platform's Python environment")
    run = penv["run"]
    assert 'python -m venv "$HOME/.platformio/penv"' in run
    for flag in ("--require-hashes", "--no-deps", "--only-binary=:all:", "-r firmware/requirements-penv.txt"):
        assert flag in run, flag
    prepare = _step("build", "Fetch the PlatformIO platform and packages")
    build = next(s for s in _steps("build") if "pio run" in s.get("run", ""))
    assert _index("build", prepare) < _index("build", penv) < _index("build", build)


def test_the_build_cannot_fetch_python_packages():
    build = next(s for s in _steps("build") if "pio run" in s.get("run", ""))
    assert build["env"]["UV_OFFLINE"] == "1"
    assert build["env"]["UV_NO_BUILD_ISOLATION"] == "1"
    assert build["env"]["PIP_NO_INDEX"] == "1"
    # ...and the post-build check also covers the penv.
    check = _step("build", "Check the build installed only checked packages")["run"]
    assert "pin_firmware_toolchain.py check" in check


def test_every_pip_install_in_the_release_is_hash_checked():
    for name, job in JOBS.items():
        for step in job["steps"]:
            joined = step.get("run", "").replace("\\\n", " ")  # shell line continuations
            for m in re.finditer(r"pip install([^\n]*)", joined):
                assert "--require-hashes" in m.group(1), f"{name}: {step.get('name')}"
