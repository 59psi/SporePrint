"""Operator scripts (scripts/*.sh, install.sh, setup.sh) — run for real
against a throwaway copy of the repo layout, with `docker` / `sudo` /
`mosquitto_passwd` replaced by recording fakes on PATH.

These scripts are the only way broker credentials and the command-signing
key reach a deployed Pi, and every failure mode they had was silent: a key
written to a file compose never reads, a broker never reloaded, a password
file the broker could not open.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
BROKER_IMAGE = yaml.safe_load(COMPOSE.read_text())["services"]["mqtt"]["image"]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("openssl") is None,
    reason="needs bash + openssl",
)


# ── fixtures ─────────────────────────────────────────────────────────────


def _make_repo(tmp_path: Path) -> Path:
    """Minimal repo layout the scripts resolve via $(dirname $0)/.."""
    root = tmp_path / "SporePrint"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "config" / "mosquitto").mkdir(parents=True)
    (root / "server").mkdir()
    for rel in ("scripts/add-node-mqtt-user.sh", "scripts/rotate-mqtt-creds.sh",
                "scripts/provision-node.sh", "scripts/lib/broker.sh"):
        src = REPO_ROOT / rel
        if src.exists():
            shutil.copy2(src, root / rel)
    shutil.copy2(COMPOSE, root / "docker-compose.yml")
    return root


def _fake_bin(tmp_path: Path, *, docker_daemon: bool, broker_running: bool = True) -> Path:
    """docker/sudo/mosquitto_passwd fakes that log every call to $FAKE_LOG."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    (bindir / "docker").write_text(f"""#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  info) {'exit 0' if docker_daemon else 'exit 1'} ;;
  run)  echo "--- stdin" >> "$FAKE_LOG"; cat >> "$FAKE_LOG"; exit 0 ;;
  compose)
    if [[ " $* " == *" ps "* ]]; then {'echo cid123' if broker_running else ':'}; fi
    exit 0 ;;
esac
exit 0
""")
    (bindir / "sudo").write_text('#!/usr/bin/env bash\necho "sudo $*" >> "$FAKE_LOG"\nexit 1\n')
    (bindir / "mosquitto_passwd").write_text(
        '#!/usr/bin/env bash\necho "mosquitto_passwd $*" >> "$FAKE_LOG"\n'
        '# -b FILE USER PASS\nprintf "%s:$7$fakehash\\n" "$3" >> "$2"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    return bindir


def _run(script: Path, *args: str, bindir: Path, log: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["FAKE_LOG"] = str(log)
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True,
                          text=True, timeout=60)


def _env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    vals = re.findall(rf"^{key}=(.*)$", path.read_text(), re.M)
    return vals[-1] if vals else None


# ── add-node-mqtt-user.sh ────────────────────────────────────────────────


def test_add_node_reloads_the_compose_mqtt_service(tmp_path):
    """The compose service is `mqtt` (container <project>-mqtt-1); the old
    `grep mosquitto` on container names never matched, and the fallback hint
    named a service that does not exist — the new credential never went live."""
    root = _make_repo(tmp_path)
    bindir = _fake_bin(tmp_path, docker_daemon=True)
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", "climate-01", bindir=bindir, log=log)
    assert res.returncode == 0, res.stderr + res.stdout
    calls = log.read_text()
    assert f"compose -f {root}/docker-compose.yml kill -s HUP mqtt" in calls, calls
    assert "mqtt" in yaml.safe_load(COMPOSE.read_text())["services"]
    # passwd edited inside the broker image (hash format == broker), with the
    # credential on stdin rather than in argv.
    run_line = next(line for line in calls.splitlines() if line.startswith("docker run"))
    assert BROKER_IMAGE in run_line
    assert "climate-01" not in run_line
    assert "climate-01" in calls.split("--- stdin", 1)[1]
    assert "MQTT password:" in res.stdout


def test_add_node_prints_the_real_reload_command_when_broker_is_down(tmp_path):
    root = _make_repo(tmp_path)
    bindir = _fake_bin(tmp_path, docker_daemon=True, broker_running=False)
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", "relay-01", bindir=bindir, log=log)
    assert res.returncode == 0, res.stderr + res.stdout
    assert "docker compose kill -s HUP mqtt" in res.stdout
    assert "HUP mosquitto" not in res.stdout


def test_add_node_refuses_a_docker_created_passwd_directory(tmp_path):
    root = _make_repo(tmp_path)
    (root / "config" / "mosquitto" / "passwd").mkdir()
    bindir = _fake_bin(tmp_path, docker_daemon=True)
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", "cam-01",
               bindir=bindir, log=tmp_path / "calls.log")
    assert res.returncode != 0
    assert "install.sh" in res.stdout


# ── rotate-mqtt-creds.sh ─────────────────────────────────────────────────


def test_rotate_writes_the_env_compose_reads_and_mirrors_server_env(tmp_path):
    """The server container gets SPOREPRINT_MQTT_PASSWORD from the ROOT .env
    (compose interpolation); server/.env is never read under Docker. Writing
    only server/.env locked the Pi out of its own broker after the next
    broker reload."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n")
    (root / "server" / ".env").write_text("SPOREPRINT_MQTT_PASSWORD=old\n")
    bindir = _fake_bin(tmp_path, docker_daemon=False)  # host mosquitto_passwd path
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh", "server", bindir=bindir, log=log)
    assert res.returncode == 0, res.stderr + res.stdout
    new = _env_value(root / ".env", "SPOREPRINT_MQTT_PASSWORD")
    assert new and new != "old"
    assert _env_value(root / "server" / ".env", "SPOREPRINT_MQTT_PASSWORD") == new
    assert _env_value(root / ".env", "SPOREPRINT_MQTT_USERNAME") == "server"
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600
    assert "mosquitto_passwd -b" in log.read_text()
    # `restart` does not re-read .env — the hint must recreate.
    assert "docker compose up -d" in res.stdout
    assert "compose restart" not in res.stdout


def test_rotate_recreates_server_and_broker_when_stack_is_running(tmp_path):
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_PASSWORD=old\n")
    bindir = _fake_bin(tmp_path, docker_daemon=True, broker_running=True)
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh", "server", "sp-3p",
               bindir=bindir, log=log)
    assert res.returncode == 0, res.stderr + res.stdout
    calls = log.read_text()
    assert BROKER_IMAGE in calls  # passwd edited in the broker image
    assert "kill -s HUP mqtt" in calls
    assert f"compose -f {root}/docker-compose.yml up -d server mqtt" in calls
    stdin = calls.split("--- stdin", 1)[1]
    assert "server" in stdin and "sp-3p" in stdin
    assert _env_value(root / ".env", "SPOREPRINT_MQTT_3P_PASSWORD")


# ── provision-node.sh (command-signing key) ──────────────────────────────


def _key(path: Path) -> str | None:
    return _env_value(path, "SPOREPRINT_MQTT_HMAC_KEY")


def test_provision_node_writes_the_key_where_compose_reads_it(tmp_path):
    """server/.dockerignore excludes .env and compose passes only what its
    environment list names, interpolated from the ROOT .env. A key written
    to server/.env never reached the container: keyed nodes then rejected
    every unsigned command."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_ALLOW_UNAUTHENTICATED=true\n")
    res = _run(root / "scripts" / "provision-node.sh", bindir=_fake_bin(tmp_path, docker_daemon=False),
               log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    key = _key(root / ".env")
    assert key and re.fullmatch(r"[0-9a-f]{64}", key)
    assert _env_value(root / ".env", "SPOREPRINT_ALLOW_UNAUTHENTICATED") == "true"
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600
    assert "docker compose up -d server" in res.stdout
    assert "compose restart" not in res.stdout
    assert f"Key: {key}" in res.stdout


def test_provision_node_reuses_a_key_already_in_server_env(tmp_path):
    """An operator who ran the old script already pasted the server/.env key
    into every node. Generating a NEW key because the root .env lacks one
    would make every provisioned node reject every frame."""
    root = _make_repo(tmp_path)
    legacy = "ab" * 32
    (root / ".env").write_text("SPOREPRINT_MQTT_PASSWORD=x\n")
    (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={legacy}\n")
    res = _run(root / "scripts" / "provision-node.sh", bindir=_fake_bin(tmp_path, docker_daemon=False),
               log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    assert _key(root / ".env") == legacy
    assert _key(root / "server" / ".env") == legacy


def test_provision_node_rotate_updates_every_env_file(tmp_path):
    root = _make_repo(tmp_path)
    old = "cd" * 32
    (root / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={old}\n")
    (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={old}\n")
    res = _run(root / "scripts" / "provision-node.sh", "--rotate",
               bindir=_fake_bin(tmp_path, docker_daemon=False), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    new = _key(root / ".env")
    assert new and new != old
    assert _key(root / "server" / ".env") == new
    assert (root / ".env").read_text().count("SPOREPRINT_MQTT_HMAC_KEY=") == 1


# ── installers (static contract checks — they need a real Docker host) ────


def test_setup_pi_delegates_to_install_sh():
    """setup-pi.sh used to `docker compose up` with no broker credentials,
    certs or LAN-trust flag: Docker created passwd/ and certs/ as root-owned
    directories, the broker and server crash-looped, and the next install.sh
    could not write the passwd file. It is now a thin wrapper."""
    body = (REPO_ROOT / "scripts" / "setup-pi.sh").read_text()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "install.sh" in code
    assert "compose up" not in code


def test_install_sh_hands_broker_files_to_the_broker_uid():
    """mosquitto drops to uid 1883 before opening password_file/keyfile."""
    body = (REPO_ROOT / "install.sh").read_text()
    assert "1883" in body
    assert re.search(r"chown\b.*1883", body)


def test_install_sh_never_recreates_an_existing_passwd_file():
    """`mosquitto_passwd -c` on re-run wiped every per-node user, and the
    already-running broker kept the old hashes in memory."""
    body = (REPO_ROOT / "install.sh").read_text()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "mosquitto_passwd -c" not in code
    assert "compose restart mqtt" in code or "kill -s HUP mqtt" in code


def test_install_sh_certificate_covers_the_pi_ip():
    """Nodes provisioned with the Pi's IP as broker host fail the TLS name
    check without an IP entry (and mbedTLS 2.x in arduino-esp32 2.x only
    string-matches SAN entries, so the IP is also listed as a DNS name)."""
    body = (REPO_ROOT / "install.sh").read_text()
    assert "IP:" in body and "DNS:" in body


def test_setup_sh_is_not_the_pi_installer():
    body = (REPO_ROOT / "setup.sh").read_text()
    assert "install.sh" in body
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    # The LAN dashboard sends no bearer: an auto-generated API key made every
    # /api call 401 after `docker compose up`.
    assert "NEW_API_KEY" not in code
    assert "SPOREPRINT_ALLOW_UNAUTHENTICATED" in code
