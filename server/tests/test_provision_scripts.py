"""Operator scripts (scripts/*.sh, install.sh, setup.sh) — run for real
against a throwaway copy of the repo layout, with `docker` / `sudo` /
`mosquitto_passwd` replaced by recording fakes on PATH.

These scripts are the only way broker credentials and the command-signing
key reach a deployed Pi, and every failure mode they had was silent: a key
written to a file compose never reads, a broker never reloaded, a password
file the broker could not open.

An install.sh run costs a few hundred milliseconds of subprocesses, so the
tests that check different facts of the same scenario (a new install, an
upgrade, an operator's own settings) share one run through module-scoped
fixtures; a test that changes the tree works on its own copy.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.config import Settings

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
    for rel in ("scripts/add-node-mqtt-user.sh", "scripts/add-plug-mqtt-user.sh",
                "scripts/rotate-mqtt-creds.sh", "scripts/provision-node.sh",
                "scripts/lib/broker.sh", "scripts/lib/host.sh"):
        src = REPO_ROOT / rel
        if src.exists():
            shutil.copy2(src, root / rel)
    shutil.copy2(COMPOSE, root / "docker-compose.yml")
    return root


def _fake_bin(tmp_path: Path, *, docker_daemon: bool, broker_running: bool = True) -> Path:
    """docker/sudo/mosquitto_passwd fakes that log every call to $FAKE_LOG.

    With FAKE_RUN_PASSWD=1 in the environment, a `docker run` of a broker
    image script that edits passwd runs that script here (its /work mount
    mapped to the host directory) against the fake mosquitto_passwd."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    (bindir / "docker").write_text(f"""#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  info) {'exit 0' if docker_daemon else 'exit 1'} ;;
  run)
    script=""; work=""; prev=""
    for a in "$@"; do
      if [ "$prev" = "-v" ] && [[ "$a" == *:/work ]]; then work="${{a%:/work}}"; fi
      if [ "$prev" = "-c" ]; then script="$a"; fi
      prev="$a"
    done
    if [ "${{FAKE_RUN_PASSWD:-}}" = "1" ] && [[ "$script" == *mosquitto_passwd* ]]; then
      SP_CHOWN=0 exec sh -c "${{script//\\/work/$work}}"
    fi
    echo "--- stdin" >> "$FAKE_LOG"; cat >> "$FAKE_LOG"; exit 0 ;;
  compose)
    if [[ " $* " == *" ps "* ]]; then {'echo cid123' if broker_running else ':'}; fi
    exit 0 ;;
  inspect) echo "${{FAKE_MQTT_HEALTH:-healthy}}"; exit 0 ;;
esac
exit 0
""")
    (bindir / "sudo").write_text('#!/usr/bin/env bash\necho "sudo $*" >> "$FAKE_LOG"\nexit 1\n')
    # `mosquitto_passwd FILE USER` with the password and its confirmation on
    # stdin, the only form the scripts may use: `-b FILE USER PASS` puts the
    # password in the process table, so this fake refuses it.
    (bindir / "mosquitto_passwd").write_text(r"""#!/usr/bin/env bash
echo "mosquitto_passwd $*" >> "$FAKE_LOG"
[ "$#" -eq 2 ] || { echo "fake mosquitto_passwd: want FILE USER, got $*" >&2; exit 2; }
IFS= read -r pw; IFS= read -r again
{ [ -n "$pw" ] && [ "$pw" = "$again" ]; } || { echo "fake mosquitto_passwd: no password on stdin" >&2; exit 1; }
printf '%s:fakehash-of-%s\n' "$2" "$pw" >> "$1"
""")
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


def test_add_node_passes_the_password_on_stdin_in_both_paths(tmp_path, monkeypatch):
    """Through the broker image or the host's mosquitto_passwd, the password
    reaches mosquitto_passwd on stdin: every process, a container's included,
    shows in the Pi's process table. The fake mosquitto_passwd refuses -b."""
    monkeypatch.setenv("FAKE_RUN_PASSWD", "1")
    for daemon in (True, False):
        case = tmp_path / ("docker" if daemon else "host")
        case.mkdir()
        root = _make_repo(case)
        log = case / "calls.log"
        res = _run(root / "scripts" / "add-node-mqtt-user.sh", "climate-02",
                   bindir=_fake_bin(case, docker_daemon=daemon), log=log)
        assert res.returncode == 0, res.stderr + res.stdout
        password = re.search(r"MQTT password:\s+(\S+)", res.stdout).group(1)
        assert password not in log.read_text(), daemon
        passwd = root / "config" / "mosquitto" / "passwd"
        assert passwd.read_text() == f"climate-02:fakehash-of-{password}\n", daemon
        assert stat.S_IMODE(passwd.stat().st_mode) == 0o600, daemon


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


# Each fixed service account and the configured login, and one mixed-case
# spelling of each kind (the script folds the id's case once for all).
@pytest.mark.parametrize("name", ["server", "sp-3p", "SP-3P", "sp-cmd", "sp-telemetry",
                                  "pi-core", "PI-Core"])
@pytest.mark.parametrize("daemon", [True, False])
def test_add_node_refuses_a_broker_service_account(tmp_path, name, daemon):
    """A node id equal to a service account (any case, or the server's own
    configured login) used to get a fresh password and a broker reload: the
    Pi server, or every smart plug, was cut off the broker while .env kept
    the old password, and the server drops node frames under those names."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=pi-core\nSPOREPRINT_MQTT_PASSWORD=pw\n")
    passwd = root / "config" / "mosquitto" / "passwd"
    passwd.write_text("server:hash\nsp-3p:hash\n")
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", name,
               bindir=_fake_bin(tmp_path, docker_daemon=daemon), log=log)
    assert res.returncode == 1, res.stdout
    assert "service account" in res.stdout and "rotate-mqtt-creds.sh" in res.stdout
    assert passwd.read_text() == "server:hash\nsp-3p:hash\n"
    calls = log.read_text() if log.exists() else ""
    assert "docker run" not in calls and "mosquitto_passwd" not in calls
    assert "HUP" not in calls
    assert "MQTT password:" not in res.stdout


def test_add_node_reads_the_bare_metal_server_login(tmp_path):
    root = _make_repo(tmp_path)
    (root / "server" / ".env").write_text("SPOREPRINT_MQTT_USERNAME=pi-core\n")
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", "pi-core",
               bindir=_fake_bin(tmp_path, docker_daemon=True), log=tmp_path / "calls.log")
    assert res.returncode == 1 and "service account" in res.stdout
    # A node id that merely contains a reserved name is still a node.
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", "sp-3p-plug-bridge",
               bindir=tmp_path / "fakebin", log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout


@pytest.mark.parametrize("env_file", [".env", "server/.env"])
@pytest.mark.parametrize("name", ["humidifier", "Humidifier", "heater"])
def test_add_node_refuses_a_smart_plugs_login(tmp_path, env_file, name):
    """A plug's own broker login (SPOREPRINT_MQTT_PLUG_USERS) is not a node
    either: re-keying it here would cut that plug off the broker."""
    root = _make_repo(tmp_path)
    (root / env_file).write_text("SPOREPRINT_MQTT_PLUG_USERS=heater, humidifier\n")
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", name,
               bindir=_fake_bin(tmp_path, docker_daemon=True), log=log)
    assert res.returncode == 1, res.stdout
    assert "smart plug's broker login" in res.stdout and "add-plug-mqtt-user.sh" in res.stdout
    calls = log.read_text() if log.exists() else ""
    assert "docker run" not in calls and "HUP" not in calls
    # Any other id still gets its login.
    res = _run(root / "scripts" / "add-node-mqtt-user.sh", "climate-01",
               bindir=tmp_path / "fakebin", log=log)
    assert res.returncode == 0, res.stderr + res.stdout


# ── add-plug-mqtt-user.sh ────────────────────────────────────────────────


def test_add_plug_gives_a_plug_its_own_login(tmp_path, monkeypatch):
    """One broker login per plug, which the ACL scopes to the plug's own tree.
    The name goes into SPOREPRINT_MQTT_PLUG_USERS (root .env and server/.env)
    so the server never takes node frames from it, and the server is
    recreated to read it. A re-run gives the plug a new password."""
    monkeypatch.setenv("FAKE_RUN_PASSWD", "1")
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PLUG_USERS=cooler")
    (root / "server" / ".env").write_text("SPOREPRINT_MQTT_PASSWORD=x\n")
    bindir = _fake_bin(tmp_path, docker_daemon=True, broker_running=True)
    log = tmp_path / "calls.log"
    for _ in range(2):
        res = _run(root / "scripts" / "add-plug-mqtt-user.sh", "heater", bindir=bindir, log=log)
        assert res.returncode == 0, res.stderr + res.stdout
    password = re.search(r"Password:\s+(\S+)", res.stdout).group(1)
    assert password not in log.read_text()
    assert f"heater:fakehash-of-{password}\n" in (root / "config" / "mosquitto" / "passwd").read_text()
    assert _env_value(root / ".env", "SPOREPRINT_MQTT_PLUG_USERS") == "cooler,heater"
    assert _env_value(root / ".env", "SPOREPRINT_MQTT_USERNAME") == "server"
    assert _env_value(root / "server" / ".env", "SPOREPRINT_MQTT_PLUG_USERS") == "heater"
    calls = log.read_text()
    assert "kill -s HUP mqtt" in calls
    assert f"compose -f {root}/docker-compose.yml up -d server" in calls
    assert "Topic heater" in res.stdout and "shellies/heater" in res.stdout


@pytest.mark.parametrize("name", ["server", "SP-3P", "sp-cmd", "sp-telemetry", "pi-core", "a/b", ""])
def test_add_plug_refuses_service_accounts_and_bad_names(tmp_path, name):
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=pi-core\n")
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "add-plug-mqtt-user.sh", *([name] if name else []),
               bindir=_fake_bin(tmp_path, docker_daemon=True), log=log)
    assert res.returncode == 1, res.stdout
    assert not (root / "config" / "mosquitto" / "passwd").exists()
    assert "SPOREPRINT_MQTT_PLUG_USERS" not in (root / ".env").read_text()
    assert "docker run" not in (log.read_text() if log.exists() else "")


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
    calls = log.read_text()
    assert f"mosquitto_passwd {root}/config/mosquitto/passwd server" in calls
    # The password went to mosquitto_passwd on stdin, never on its command line.
    assert new not in calls
    assert f"server:fakehash-of-{new}" in (root / "config" / "mosquitto" / "passwd").read_text()
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


COMMAND_AUTH = REPO_ROOT / "firmware" / "lib" / "sp_device" / "command_auth.cpp"
_PI_STEP = "Apply the key to the Pi server"
_NODES_STEP = "For EACH ESP32 node"


def _steps(stdout: str) -> list[str]:
    """The numbered steps the script prints, in order (1., 2., ...)."""
    found = re.findall(rf"^(\d)\. ({_PI_STEP}|{_NODES_STEP})", stdout, re.M)
    assert [n for n, _ in found] == [str(i + 1) for i in range(len(found))], found
    return [name for _, name in found]


def test_provision_node_rotate_rekeys_the_nodes_before_the_server(tmp_path):
    """A node used to hold one key: once the server signed with a new one,
    every node still on the old key rejected all commands (lights stayed as
    they were, relay channels could not be switched on) until it was
    re-keyed. A re-keyed node now keeps the key it replaced until the first
    command signed with the new one, so a rotation re-keys every node first
    and switches the server last, and nothing is rejected in between."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={'cd' * 32}\n")
    res = _run(root / "scripts" / "provision-node.sh", "--rotate",
               bindir=_fake_bin(tmp_path, docker_daemon=False), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    assert _steps(res.stdout) == [_NODES_STEP, _PI_STEP]
    out = " ".join(res.stdout.split())
    note = out.split(f"1. {_NODES_STEP}", 1)[0]
    assert "REPLACED the signing key" in note
    for needle in ("re-key every node (step 1) BEFORE", "accepts the key it replaced",
                   "first command signed with the new one", "re-key such nodes last",
                   "docker compose up -d", "without --rotate"):
        assert needle in note, needle
    # The old outage advice is gone.
    assert "lights off" not in out and "rejects EVERY command" not in out
    # Where to retire an old key at once.
    assert "docs/firmware-security.md, Rotating the key" in out
    # Step 3 tells the node states apart, quoting the firmware's own log lines.
    assert "A node with NO key accepts every command" in out
    assert "A node with a DIFFERENT key" in out
    firmware = re.sub(r'"\s*"', "", COMMAND_AUTH.read_text())  # "a " "b" -> "a b", as C reads it
    for line in ("verified with the PREVIOUS signing key",
                 "verified with the new signing key - previous key retired"):
        assert line in out, line
        assert line in firmware, f"command_auth.cpp no longer logs {line!r}"


@pytest.mark.parametrize("root_key, server_key, first", [
    ("", None, _PI_STEP),             # a first key
    ("", "ab" * 32, _PI_STEP),        # an older script's server/.env key, new to compose
    ("cd" * 32, None, _NODES_STEP),   # the key compose already reads (a re-run, maybe mid-rotation)
])
def test_provision_node_puts_the_server_first_only_with_its_first_key(tmp_path, root_key,
                                                                    server_key, first):
    """With no key in the root .env the dockerized server signs nothing yet,
    and a node without the key accepts signed frames: switching the server
    first cuts no node off, while a node re-keyed first would refuse the
    server's unsigned frames. With a key already there the nodes go first,
    as in a rotation: a re-run that only prints the key may be in the middle
    of one."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={root_key}\n")
    if server_key is not None:
        (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={server_key}\n")
    res = _run(root / "scripts" / "provision-node.sh",  # no --rotate
               bindir=_fake_bin(tmp_path, docker_daemon=False), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    steps = _steps(res.stdout)
    assert sorted(steps) == sorted([_PI_STEP, _NODES_STEP]) and steps[0] == first, steps
    # Only --rotate replaces a key, and only then is the operator warned.
    assert "REPLACED" not in res.stdout
    assert "Rotating the key" not in res.stdout


# ── installers (static contract checks — they need a real Docker host) ────


def _code(path: Path) -> str:
    """A shell script (or compose file) without its comment lines."""
    return "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))


def test_setup_pi_delegates_to_install_sh():
    """setup-pi.sh used to `docker compose up` with no broker credentials,
    certs or LAN-trust flag: Docker created passwd/ and certs/ as root-owned
    directories, the broker and server crash-looped, and the next install.sh
    could not write the passwd file. It is now a thin wrapper."""
    code = _code(REPO_ROOT / "scripts" / "setup-pi.sh")
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
    code = _code(REPO_ROOT / "install.sh")
    assert "mosquitto_passwd -c" not in code
    assert "compose restart mqtt" in code or "kill -s HUP mqtt" in code


def test_setup_sh_is_not_the_pi_installer():
    assert "install.sh" in (REPO_ROOT / "setup.sh").read_text()
    code = _code(REPO_ROOT / "setup.sh")
    # The LAN dashboard sends no bearer: an auto-generated API key made every
    # /api call 401 after `docker compose up`.
    assert "NEW_API_KEY" not in code
    assert "SPOREPRINT_ALLOW_UNAUTHENTICATED" in code


_BROKER_SCRIPTS = [REPO_ROOT / "install.sh", REPO_ROOT / "setup.sh",
                   *sorted((REPO_ROOT / "scripts").rglob("*.sh")), COMPOSE]


def test_no_script_puts_a_broker_password_on_a_command_line():
    """`mosquitto_passwd -b FILE USER PASS` and `mosquitto_sub -P PASS` put the
    password in the process table (a throwaway broker container's processes
    included), where any local user reads it. Passwords go to mosquitto_passwd
    on stdin and to the clients in an options file."""
    for path in _BROKER_SCRIPTS:
        code = _code(path)
        assert not re.search(r"mosquitto_passwd(\s+-\w+)*\s+-b\b", code), path.name
        for m in re.finditer(r"mosquitto_(?:sub|pub|rr)\s[^\n;|]*", code):
            assert not re.search(r"(^|\s)-P\s", m.group(0)), (path.name, m.group(0))


# ── rotate-mqtt-creds.sh vs the bare-metal server/.env ───────────────────


def test_rotate_keeps_the_bare_metal_server_env_bootable(tmp_path):
    """Bare metal runs uvicorn from server/, which loads server/.env as a
    dotenv. Only the password the server itself uses is mirrored there: the
    sp-cmd / sp-telemetry / sp-3p passwords stay in the root .env, and the
    server still boots on the result."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n")
    (root / "server" / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n")
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh", "server", "sp-cmd", "sp-telemetry", "sp-3p",
               bindir=_fake_bin(tmp_path, docker_daemon=False), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    server_env = root / "server" / ".env"
    new = _env_value(root / ".env", "SPOREPRINT_MQTT_PASSWORD")
    assert new and new != "old"
    assert _env_value(server_env, "SPOREPRINT_MQTT_PASSWORD") == new
    for key in ("SPOREPRINT_MQTT_3P_PASSWORD", "SPOREPRINT_MQTT_CMD_PASSWORD",
                "SPOREPRINT_MQTT_TELEMETRY_PASSWORD"):
        assert _env_value(root / ".env", key), f"{key} missing from the root .env"
        assert _env_value(server_env, key) is None, f"{key} written into server/.env"
    Settings(_env_file=str(server_env))


# ── install.sh, run for real (SPOREPRINT_SKIP_START=1) ───────────────────

FAKE_HOSTNAME = "sporepi"
FAKE_IPS = ("192.168.1.50", "10.0.0.7")


def _make_install_repo(tmp_path: Path) -> Path:
    root = _make_repo(tmp_path)
    for rel in ("install.sh", ".env.example", "scripts/lib/host.sh"):
        if (REPO_ROOT / rel).exists():
            shutil.copy2(REPO_ROOT / rel, root / rel)
    return root


def _fake_host(bindir: Path, *, ips: str = " ".join(FAKE_IPS) + " fe80::1") -> None:
    """hostname / timedatectl fakes: the host's name, IPs and time zone
    ($FAKE_TZ; unset → timedatectl fails like on a non-systemd host)."""
    ip_branch = f'echo "{ips}"' if ips else "exit 1"
    (bindir / "hostname").write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        f"  -I) {ip_branch} ;;\n"
        f"  *)  echo {FAKE_HOSTNAME} ;;\n"
        "esac\n")
    (bindir / "timedatectl").write_text(
        "#!/usr/bin/env bash\n"
        '[ -n "${FAKE_TZ:-}" ] || exit 1\n'
        'if [ "$*" = "show -p Timezone --value" ]; then echo "$FAKE_TZ"; fi\n')
    for name in ("hostname", "timedatectl"):
        (bindir / name).chmod(0o755)


def _fake_zoneinfo(tmp_path: Path) -> Path:
    """A zoneinfo tree like Debian's: canonical zones are files, legacy
    aliases are symlinks to them."""
    zi = tmp_path / "zoneinfo"
    for zone in ("America/Los_Angeles", "America/Denver", "Europe/Berlin", "UTC"):
        (zi / zone).parent.mkdir(parents=True, exist_ok=True)
        (zi / zone).write_bytes(b"TZif2")
    (zi / "US").mkdir()
    (zi / "US" / "Pacific").symlink_to("../America/Los_Angeles")
    return zi


def _run_install(root: Path, tmp_path: Path, *, fake_tz: str | None = None,
                 zoneinfo: Path | None = None, extra_env: dict | None = None,
                 umask: int | None = None) -> subprocess.CompletedProcess:
    bindir = tmp_path / "fakebin"
    if not bindir.exists():
        _fake_bin(tmp_path, docker_daemon=True, broker_running=False)
        _fake_host(bindir)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SPOREPRINT_") and k != "TZ"}
    env.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               SPOREPRINT_SKIP_START="1", HOME=str(tmp_path))
    if fake_tz is not None:
        env["FAKE_TZ"] = fake_tz
    if zoneinfo is not None:
        env["SP_ZONEINFO_DIR"] = str(zoneinfo)
    env.update(extra_env or {})
    return subprocess.run(["bash", str(root / "install.sh")], cwd=root, env=env,
                          capture_output=True, text=True, timeout=120,
                          umask=-1 if umask is None else umask)


def _ok(res: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    assert res.returncode == 0, res.stderr + res.stdout
    return res


_HOST_TZ = "America/Denver"
_LEGACY_KEY, _ROOT_KEY, _STALE_KEY = "ef" * 32, "12" * 32, "34" * 32


@pytest.fixture(scope="module")
def fresh_install(tmp_path_factory):
    """A first install.sh run on a host in America/Denver, then a re-run.

    The broker image's passwd script runs here against the fake
    mosquitto_passwd (FAKE_RUN_PASSWD) and the host has no chrony. What the
    first run left is kept apart (a copy of the tree, the .env mode, the
    calls it made), so a check of what a NEW install writes never sees what
    the re-run added."""
    base = tmp_path_factory.mktemp("fresh-install")
    root = _make_install_repo(base)
    zi = _fake_zoneinfo(base)
    env = {"FAKE_RUN_PASSWD": "1", "SP_CHRONY_CONF": str(base / "no-chrony" / "chrony.conf")}
    first = _ok(_run_install(root, base, fake_tz=_HOST_TZ, zoneinfo=zi, extra_env=env))
    after_first = base / "after-first-run" / root.name
    shutil.copytree(root, after_first, symlinks=True)
    run = SimpleNamespace(root=root, zoneinfo=zi, env=env, first=first, after_first=after_first,
                          first_env_mode=stat.S_IMODE((root / ".env").stat().st_mode),
                          first_calls=(base / "calls.log").read_text())
    run.rerun = _ok(_run_install(root, base, fake_tz=_HOST_TZ, zoneinfo=zi, extra_env=env))
    return run


def _clone_install(fresh_install: SimpleNamespace, tmp_path: Path) -> Path:
    """A copy of the fresh install as its first run left it, to change."""
    root = tmp_path / "SporePrint"
    shutil.copytree(fresh_install.after_first, root, symlinks=True)
    return root


def _rerun_clone(fresh_install: SimpleNamespace, root: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    return _run_install(root, tmp_path, fake_tz=_HOST_TZ, zoneinfo=fresh_install.zoneinfo,
                        extra_env=fresh_install.env)


@pytest.fixture(scope="module")
def upgraded_install(tmp_path_factory):
    """install.sh over an install from before TZ, the signing key and the
    ntfy topic: the operator's .env, its last line saved with no newline, and
    the key an older provision-node.sh left in server/.env."""
    base = tmp_path_factory.mktemp("upgraded-install")
    root = _make_install_repo(base)
    (root / ".env").write_text("SPOREPRINT_ALLOW_UNAUTHENTICATED=true\nSPOREPRINT_API_KEY=my-mobile-key")
    (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={_LEGACY_KEY}\n")
    res = _ok(_run_install(root, base, fake_tz=_HOST_TZ, zoneinfo=_fake_zoneinfo(base)))
    return SimpleNamespace(root=root, res=res)


@pytest.fixture(scope="module")
def operator_install(tmp_path_factory):
    """install.sh over a .env the operator set up: a time zone, an ntfy
    topic, the signing key compose reads (server/.env holds a stale one) and
    broker passwords quoted the ways compose allows."""
    base = tmp_path_factory.mktemp("operator-install")
    root = _make_install_repo(base)
    (root / ".env").write_text(
        "SPOREPRINT_ALLOW_UNAUTHENTICATED=true\nTZ=Europe/Berlin\nSPOREPRINT_NTFY_TOPIC=my-own-topic\n"
        f"SPOREPRINT_MQTT_HMAC_KEY={_ROOT_KEY}\nSPOREPRINT_MQTT_USERNAME=server\n"
        "SPOREPRINT_MQTT_PASSWORD=\"quoted pw\"\nSPOREPRINT_MQTT_3P_PASSWORD='plug pw'\n")
    (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={_STALE_KEY}\n")
    res = _ok(_run_install(root, base, fake_tz=_HOST_TZ, zoneinfo=_fake_zoneinfo(base),
                           extra_env={"FAKE_RUN_PASSWD": "1"}))
    return SimpleNamespace(root=root, res=res)


@pytest.fixture
def default_topic_install(tmp_path):
    """install.sh over an install still on the default ntfy topic."""
    root = _make_install_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_ALLOW_UNAUTHENTICATED=true\nSPOREPRINT_NTFY_TOPIC=sporeprint\n")
    res = _ok(_run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path)))
    return SimpleNamespace(root=root, res=res)


def test_install_sh_writes_the_host_timezone(fresh_install):
    assert _env_value(fresh_install.after_first / ".env", "TZ") == _HOST_TZ


def test_install_sh_resolves_a_legacy_zone_alias(tmp_path):
    """Raspberry Pi OS bookworm offers US/Pacific; the Debian trixie server
    image ships canonical zones only (the aliases moved to tzdata-legacy),
    and glibc runs an unknown TZ on UTC without a word."""
    root = _make_install_repo(tmp_path)
    _ok(_run_install(root, tmp_path, fake_tz="US/Pacific", zoneinfo=_fake_zoneinfo(tmp_path)))
    assert _env_value(root / ".env", "TZ") == "America/Los_Angeles"


def test_install_sh_warns_an_upgrade_that_schedules_leave_utc(upgraded_install, fresh_install):
    """An existing install ran every schedule on UTC; operators may have
    typed UTC times to compensate. The upgrade must say so."""
    assert _env_value(upgraded_install.root / ".env", "TZ") == _HOST_TZ
    assert "ran on UTC" in upgraded_install.res.stdout and "TZ=UTC" in upgraded_install.res.stdout
    # A fresh install has nothing to migrate.
    assert "ran on UTC" not in fresh_install.first.stdout


def test_install_sh_keeps_the_operator_timezone(operator_install):
    assert _env_value(operator_install.root / ".env", "TZ") == "Europe/Berlin"


_CHRONY_LAN = ("allow 10.0.0.0/8", "allow 172.16.0.0/12", "allow 192.168.0.0/16", "local stratum 10")


@pytest.mark.parametrize("debian_layout", [True, False])
def test_install_sh_makes_chrony_serve_ntp_to_the_lan(tmp_path, debian_layout):
    """Nodes in a room without internet are told to take their time from the
    Pi (portal hint, docs), and a keyed node refuses every command until its
    clock is set. timesyncd, or chrony as installed, answers no clients:
    install.sh adds `allow` for the private ranges and `local stratum`."""
    root = _make_install_repo(tmp_path)
    bindir = _fake_bin(tmp_path, docker_daemon=True, broker_running=False)
    _fake_host(bindir)
    fakes = {
        "sudo": 'echo "sudo $*" >> "$FAKE_LOG"\nexec "$@"\n',
        "chronyc": 'echo "chronyc $*" >> "$FAKE_LOG"\n[ "$1" = accheck ] && echo "208 Access allowed"\nexit 0\n',
        "systemctl": 'echo "systemctl $*" >> "$FAKE_LOG"\nexit 0\n',
    }
    for name, body in fakes.items():
        (bindir / name).write_text("#!/usr/bin/env bash\n" + body)
        (bindir / name).chmod(0o755)
    conf = tmp_path / "chrony" / "chrony.conf"
    conf.parent.mkdir()
    base = "pool 2.debian.pool.ntp.org iburst\n"
    if debian_layout:
        base += f"confdir {conf.parent}/conf.d\n"
    conf.write_text(base)
    zi = _fake_zoneinfo(tmp_path)
    for _ in range(2):  # idempotent
        res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=zi,
                           extra_env={"SP_CHRONY_CONF": str(conf)})
        assert res.returncode == 0, res.stderr + res.stdout
    dropin = (conf.parent / "conf.d" / "sporeprint.conf").read_text().splitlines()
    assert all(line in dropin for line in _CHRONY_LAN), dropin
    assert conf.read_text() == base + ("" if debian_layout else f"include {conf.parent}/conf.d/sporeprint.conf\n")
    assert "systemctl restart chrony" in (tmp_path / "calls.log").read_text()
    assert "answers NTP from the LAN" in res.stdout


def test_install_sh_ntp_step_never_fails_the_install(fresh_install):
    """No apt, no chrony (or no sudo): the time step warns and moves on."""
    step = fresh_install.first.stdout.split("LAN time server", 1)[1].split("▶", 1)[0]
    assert "[!]" in step and "nodes cannot" in step, step


def test_install_sh_gives_a_new_install_an_unguessable_ntfy_topic(fresh_install):
    """The bundled ntfy server has no logins: on the default `sporeprint`
    topic anyone on the network (or a web page posting blind) could read the
    alerts or push fake critical ones to the operator's phone."""
    topic = _env_value(fresh_install.after_first / ".env", "SPOREPRINT_NTFY_TOPIC")
    assert re.fullmatch(r"sporeprint-[0-9a-f]{16}", topic or ""), topic
    assert topic in fresh_install.first.stdout  # the operator subscribes the phone to it
    assert _env_value(fresh_install.root / ".env", "SPOREPRINT_NTFY_TOPIC") == topic
    assert "default ntfy topic" not in fresh_install.rerun.stdout


@pytest.mark.parametrize("install, topic, warned", [
    ("default_topic_install", "sporeprint", True),
    ("upgraded_install", None, True),
    ("operator_install", "my-own-topic", False),
], ids=["default-topic", "no-topic", "own-topic"])
def test_install_sh_keeps_an_existing_installs_ntfy_topic(request, install, topic, warned):
    """Phones subscribe to the topic: moving an existing install to a new one
    would silently stop its alerts, so it is kept, with a warning while it is
    the guessable default."""
    run = request.getfixturevalue(install)
    assert _env_value(run.root / ".env", "SPOREPRINT_NTFY_TOPIC") == topic
    assert ("default ntfy topic" in run.res.stdout) is warned


def test_install_sh_never_writes_an_unknown_zone(tmp_path):
    root = _make_install_repo(tmp_path)
    res = _ok(_run_install(root, tmp_path, fake_tz="Mars/Olympus_Mons", zoneinfo=_fake_zoneinfo(tmp_path)))
    assert not _env_value(root / ".env", "TZ")
    assert "UTC" in res.stdout  # the operator is told schedules stay on UTC


def test_install_sh_provisions_the_command_signing_key(fresh_install):
    """Once paired, cloud_url is set and mqtt_require_signing=auto REFUSES
    every unsigned cmd/* publish: a Pi without a key lost all actuation after
    pairing + restart. With a key the Pi signs everything — nodes that have
    no key accept signed frames (hmac_verify.cpp NoKey → AcceptUnsigned) and
    keyed nodes verify them — so the installer always provisions one."""
    key = _key(fresh_install.after_first / ".env")
    assert key and re.fullmatch(r"[0-9a-f]{64}", key)
    assert fresh_install.first_env_mode == 0o600
    assert key not in fresh_install.first.stdout  # never echoed into install logs
    # …and a re-run keeps it (nodes may hold it by then).
    assert _key(fresh_install.root / ".env") == key


def test_install_sh_reuses_the_key_nodes_already_hold(upgraded_install):
    assert _key(upgraded_install.root / ".env") == _LEGACY_KEY


def test_install_sh_keeps_the_root_signing_key(operator_install):
    assert _key(operator_install.root / ".env") == _ROOT_KEY


def test_install_sh_passes_broker_passwords_on_stdin(fresh_install):
    """install.sh's loop runs in the broker image (run here against the fake
    mosquitto_passwd, which refuses -b): each password reaches
    mosquitto_passwd on stdin and lands under its own user."""
    root = fresh_install.after_first
    server_pw = _env_value(root / ".env", "SPOREPRINT_MQTT_PASSWORD")
    plug_pw = _env_value(root / ".env", "SPOREPRINT_MQTT_3P_PASSWORD")
    assert server_pw and plug_pw
    passwd = (root / "config" / "mosquitto" / "passwd").read_text()
    assert f"server:fakehash-of-{server_pw}\n" in passwd
    assert f"sp-3p:fakehash-of-{plug_pw}\n" in passwd
    calls = fresh_install.first_calls
    assert server_pw not in calls and plug_pw not in calls


# ── install.sh: the broker CA is never replaced behind pinned nodes ──────


def _openssl(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["openssl", *args], capture_output=True, text=True, check=True,
                          cwd=cwd).stdout


def _fingerprint(cert: Path) -> str:
    return _openssl("x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256")


def _issued_by(certs: Path) -> bool:
    return subprocess.run(["openssl", "verify", "-CAfile", str(certs / "ca.crt"), str(certs / "server.crt")],
                          capture_output=True, text=True).returncode == 0


def _reissue(certs: Path, *, days: int, ips: tuple[str, ...] = FAKE_IPS) -> None:
    """A server certificate from the install's CA, valid for `days`."""
    san = ",".join(["DNS:sporeprint.local", *(f"IP:{ip},DNS:{ip}" for ip in ips)])
    (certs / "san.ext").write_text(f"subjectAltName={san}\n")
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "server.key", "-out", "server.csr",
             "-subj", "/CN=sporeprint.local", cwd=certs)
    _openssl("x509", "-req", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
             "-CAcreateserial", "-days", str(days), "-out", "server.crt", "-extfile", "san.ext", cwd=certs)


def _certs(root: Path) -> Path:
    return root / "config" / "mosquitto" / "certs"


def test_install_sh_reissues_a_missing_server_cert_from_the_same_ca(fresh_install, tmp_path):
    """A missing server.crt (deleted to force a fresh one, or lost to a failed
    move) made install.sh generate a NEW CA: every node that had pinned the
    old one failed TLS, never fell back, and needed a factory reset."""
    root = _clone_install(fresh_install, tmp_path)
    certs = _certs(root)
    ca = _fingerprint(certs / "ca.crt")
    for lost in ("server.crt", "server.key"):
        (certs / lost).unlink()
        res = _ok(_rerun_clone(fresh_install, root, tmp_path))
        assert "Generated CA" not in res.stdout and "existing CA" in res.stdout, lost
        assert _fingerprint(certs / "ca.crt") == ca, lost
        assert _issued_by(certs), lost
    assert not list(certs.glob(".issue.*"))


def test_install_sh_never_replaces_a_ca_whose_key_is_gone(fresh_install, tmp_path):
    root = _clone_install(fresh_install, tmp_path)
    certs = _certs(root)
    ca = _fingerprint(certs / "ca.crt")
    (certs / "server.crt").unlink()
    (certs / "ca.key").unlink()
    res = _rerun_clone(fresh_install, root, tmp_path)
    assert res.returncode != 0
    assert "ca.key" in res.stderr and "factory-reset" in res.stderr
    assert _fingerprint(certs / "ca.crt") == ca


def test_install_sh_renews_a_server_cert_about_to_expire(fresh_install, tmp_path):
    """The server certificate runs for five years and nothing renewed it;
    deleting it, the only remedy, regenerated the CA. A re-run now re-issues
    one that expires within 30 days, from the same CA."""
    root = _clone_install(fresh_install, tmp_path)
    certs = _certs(root)
    ca = _fingerprint(certs / "ca.crt")
    _reissue(certs, days=1)
    res = _ok(_rerun_clone(fresh_install, root, tmp_path))
    assert "expires within 30 days" in res.stdout
    assert subprocess.run(["openssl", "x509", "-in", str(certs / "server.crt"), "-noout",
                           "-checkend", str(365 * 86400)]).returncode == 0
    assert _fingerprint(certs / "ca.crt") == ca and _issued_by(certs)
    # A current certificate is left alone (the fresh install's re-run).
    assert "already present" in fresh_install.rerun.stdout
    assert (_certs(fresh_install.root) / "server.crt").read_bytes() == \
        (_certs(fresh_install.after_first) / "server.crt").read_bytes()


def test_install_sh_warns_when_the_ca_itself_nears_expiry(tmp_path):
    root = _make_install_repo(tmp_path)
    certs = root / "config" / "mosquitto" / "certs"
    certs.mkdir(parents=True)
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-days", "100", "-nodes", "-keyout", "ca.key",
             "-out", "ca.crt", "-subj", "/CN=SporePrint Local CA", cwd=certs)
    _reissue(certs, days=90)
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert "expires within a year" in res.stdout and "factory-reset" in res.stdout


def test_install_sh_leaves_broker_files_readable_under_a_strict_umask(tmp_path):
    """mosquitto opens acl.conf and the certificates after dropping to uid
    1883. A checkout made under umask 077 left them 0600 / 0700 and the broker
    crash-looped."""
    root = _make_install_repo(tmp_path)
    mosq = root / "config" / "mosquitto"
    for name in ("acl.conf", "mosquitto.conf"):
        shutil.copy2(REPO_ROOT / "config" / "mosquitto" / name, mosq / name)
        (mosq / name).chmod(0o600)
    (mosq / "certs").mkdir(mode=0o700)
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path), umask=0o077)
    assert res.returncode == 0, res.stderr + res.stdout
    mode = {p.name: stat.S_IMODE(p.stat().st_mode) for p in (*mosq.iterdir(), *(mosq / "certs").iterdir())}
    assert (mode["acl.conf"], mode["mosquitto.conf"], mode["certs"]) == (0o644, 0o644, 0o755)
    assert (mode["ca.crt"], mode["server.crt"], mode["server.key"], mode["ca.key"]) == (0o644, 0o644, 0o600, 0o600)
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600


def _full_install(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    """install.sh with the start: docker, curl and sleep faked. The fake
    broker reports $FAKE_MQTT_HEALTH; the API's MQTT detail carries the
    broker's stats only when FAKE_SERVER_MQTT=1."""
    root = _make_install_repo(tmp_path)
    if "api_key" in env:
        (root / ".env").write_text(f"SPOREPRINT_API_KEY={env.pop('api_key')}\n")
    bindir = _fake_bin(tmp_path, docker_daemon=True, broker_running=True)
    _fake_host(bindir)
    (bindir / "curl").write_text(r"""#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
if [[ " $* " == *" -K - "* ]]; then cat > "$FAKE_CURL_CONFIG"; fi
case "${!#}" in
  */api/health) exit 0 ;;
  */api/health/detail/mqtt)
    if [ "$FAKE_SERVER_MQTT" = "1" ]; then echo '{"version":"mosquitto version 2.1.2","command_signing":{}}'
    else echo '{"command_signing":{}}'; fi
    exit 0 ;;
esac
exit 22
""")
    (bindir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for name in ("curl", "sleep"):
        (bindir / name).chmod(0o755)
    return _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path),
                        extra_env={"SPOREPRINT_SKIP_START": "0",
                                   "FAKE_CURL_CONFIG": str(tmp_path / "curl.config"), **env})


@pytest.mark.parametrize("health, server_mqtt, ok", [
    ("healthy", "1", True), ("unhealthy", "1", False), ("healthy", "0", False), ("starting", "1", False),
])
def test_install_sh_reports_success_only_with_the_server_on_the_broker(tmp_path, health, server_mqtt, ok):
    """/api/health answers whatever the broker does: a passwd that did not
    match .env still ended with '✓ SporePrint is running.' while the server
    had no MQTT (no telemetry, no rules, no commands)."""
    res = _full_install(tmp_path, FAKE_MQTT_HEALTH=health, FAKE_SERVER_MQTT=server_mqtt)
    assert res.returncode == 0, res.stderr + res.stdout
    assert ("✓ SporePrint is running." in res.stdout) is ok, res.stdout
    assert ("NOT connected to the MQTT broker" in res.stdout + res.stderr) is not ok
    if not ok:
        assert "compose logs --tail=20 mqtt server" in (tmp_path / "calls.log").read_text()


def test_install_sh_mqtt_check_keeps_the_api_key_off_curls_command_line(tmp_path):
    res = _full_install(tmp_path, api_key="my-mobile-key", FAKE_MQTT_HEALTH="healthy", FAKE_SERVER_MQTT="1")
    assert res.returncode == 0, res.stderr + res.stdout
    assert "✓ SporePrint is running." in res.stdout
    assert "my-mobile-key" not in (tmp_path / "calls.log").read_text()
    assert (tmp_path / "curl.config").read_text() == 'header = "Authorization: Bearer my-mobile-key"\n'


# ── scripts/lib/host.sh (setup.sh's copy of install.sh's host logic) ─────


def _lib(tmp_path: Path, snippet: str, *, ips: str = " ".join(FAKE_IPS) + " fe80::1",
         extra_env: dict | None = None) -> str:
    bindir = tmp_path / "hostbin"
    bindir.mkdir(exist_ok=True)
    _fake_host(bindir, ips=ips)
    env = {k: v for k, v in os.environ.items() if k != "TZ"}
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env.update(extra_env or {})
    res = subprocess.run(["bash", "-c", f'. "{REPO_ROOT}/scripts/lib/host.sh"; {snippet}'],
                         env=env, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _cert_san(cert: Path) -> set[str]:
    text = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-text"],
                          capture_output=True, text=True, check=True).stdout
    line = text.split("Subject Alternative Name:", 1)[1].strip().splitlines()[0]
    return {e.strip().replace("IP Address:", "IP:") for e in line.split(",")}


def test_host_lib_lists_ipv4_addresses(tmp_path):
    assert _lib(tmp_path, "sp_host_ipv4s").split() == list(FAKE_IPS)


def test_host_lib_falls_back_to_ifconfig_without_hostname_I(tmp_path):
    """macOS `hostname` has no -I — setup.sh runs on developer Macs."""
    bindir = tmp_path / "hostbin"
    bindir.mkdir()
    (bindir / "ifconfig").write_text(
        "#!/usr/bin/env bash\ncat <<'OUT'\n"
        "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n"
        "\tinet 127.0.0.1 netmask 0xff000000\n"
        "\tinet6 ::1 prefixlen 128\n"
        "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
        "\tinet 192.168.1.77 netmask 0xffffff00 broadcast 192.168.1.255\n"
        "eth0      Link encap:Ethernet\n"
        "          inet addr:10.1.2.3  Bcast:10.1.2.255  Mask:255.255.255.0\n"
        "OUT\n")
    (bindir / "ifconfig").chmod(0o755)
    assert _lib(tmp_path, "sp_host_ipv4s", ips="").split() == ["192.168.1.77", "10.1.2.3"]


def test_setup_sh_certificate_covers_the_host_ips_like_install_sh(fresh_install, tmp_path):
    """Nodes provisioned with the Pi's IP as broker host fail the TLS name
    check without an IP entry, and mbedTLS 2.28 (arduino-esp32 2.x)
    string-matches DNS SANs only: install.sh lists every host IP as both.
    setup.sh issued DNS-only SANs; its helper must produce exactly the SAN
    install.sh puts in the real certificate."""
    issued = _cert_san(_certs(fresh_install.after_first) / "server.crt")
    for ip in FAKE_IPS:
        assert {f"IP:{ip}", f"DNS:{ip}"} <= issued
    lib = _lib(tmp_path, f"sp_server_san {FAKE_HOSTNAME} $(sp_host_ipv4s)")
    assert set(lib.split(",")) == issued


def test_host_lib_timezone_matches_install_sh(tmp_path):
    zi = _fake_zoneinfo(tmp_path)
    for fake, expected in (("America/Denver", "America/Denver"),
                           ("US/Pacific", "America/Los_Angeles"),
                           ("Mars/Olympus_Mons", "")):
        got = _lib(tmp_path, "sp_host_timezone",
                   extra_env={"FAKE_TZ": fake, "SP_ZONEINFO_DIR": str(zi)})
        assert got == expected, fake


def test_host_lib_signing_key_prefers_root_then_server_env(tmp_path):
    root = tmp_path / "r"
    (root / "server").mkdir(parents=True)
    (root / "server" / ".env").write_text("SPOREPRINT_MQTT_HMAC_KEY=" + "ab" * 32 + "\n")
    assert _lib(tmp_path, f'sp_ensure_signing_key "{root}"') == "ab" * 32
    assert _key(root / ".env") == "ab" * 32
    (root / ".env").write_text("SPOREPRINT_MQTT_HMAC_KEY=" + "cd" * 32 + "\n")
    assert _lib(tmp_path, f'sp_ensure_signing_key "{root}"') == "cd" * 32
    root2 = tmp_path / "fresh"
    root2.mkdir()
    fresh = _lib(tmp_path, f'sp_ensure_signing_key "{root2}"')
    assert re.fullmatch(r"[0-9a-f]{64}", fresh) and _key(root2 / ".env") == fresh


def test_host_lib_cert_helpers_match_install_sh(tmp_path):
    """setup.sh's helpers re-issue from the CA in place and give the reasons
    install.sh gives; a failed issue keeps the old pair."""
    certs = tmp_path / "certs"
    certs.mkdir()
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-days", "3650", "-nodes", "-keyout", "ca.key",
             "-out", "ca.crt", "-subj", "/CN=SporePrint Local CA", cwd=certs)
    _lib(tmp_path, f'sp_issue_server_cert "{certs}" {FAKE_HOSTNAME} {" ".join(FAKE_IPS)}')
    assert _issued_by(certs) and stat.S_IMODE((certs / "server.key").stat().st_mode) == 0o600
    assert _lib(tmp_path, f'sp_cert_reissue_reason "{certs}" {FAKE_IPS[0]}') == ""
    assert _lib(tmp_path, f'sp_cert_reissue_reason "{certs}" 192.168.9.9') == "it does not cover 192.168.9.9"
    _reissue(certs, days=1)
    assert _lib(tmp_path, f'sp_cert_reissue_reason "{certs}" {FAKE_IPS[0]}') == "it expires within 30 days"
    before = (certs / "server.crt").read_bytes(), (certs / "server.key").read_bytes()
    (certs / "ca.key").unlink()
    assert _lib(tmp_path, f'sp_issue_server_cert "{certs}" {FAKE_HOSTNAME} || echo failed') == "failed\n"
    assert ((certs / "server.crt").read_bytes(), (certs / "server.key").read_bytes()) == before
    assert not list(certs.glob(".issue.*"))


# What `docker compose config` reads from each form of .env line. The scripts
# must read the same value: a password read with its quotes is hashed into
# passwd while compose hands the server the bare value, and the server's
# broker login fails.
_ENV_FORMS = [
    ('A="dq value"', "dq value"),
    ("B='sq value'", "sq value"),
    ("C=plain # comment", "plain"),
    ('D="dq" # c', "dq"),
    ("E=  spaced  ", "spaced"),
    ("export F=exported", "exported"),
    ('G=a"b', 'a"b'),
    (r'H="esc\"q\\x"', r'esc"q\x'),
    (r"I='lit\n'", r"lit\n"),
    ("J=tail#hash", "tail#hash"),
    (r'K="a\nb"', "a\nb"),
    (r'L="a\qb"', r"a\qb"),
    (r'M="a\tb"', "a\tb"),
    (r'N="a\$b"', "a$b"),
    ('O="x" junk', "x"),
    ("P=a=b=c", "a=b=c"),
    ("Q=", ""),
    ('R=""', ""),
]


def _install_fn(name: str) -> str:
    """One function from install.sh, which carries its own copies of the
    host.sh helpers (the `curl | bash` path has no checkout to source)."""
    m = re.search(rf"^{name}\(\) \{{.*?^\}}$", (REPO_ROOT / "install.sh").read_text(), re.M | re.S)
    assert m, f"install.sh has no {name}()"
    return m.group(0)


def _read_forms(tmp_path: Path, reader: str) -> list[str]:
    """Each _ENV_FORMS key read back by `reader` (shell defining read_one KEY)."""
    env = tmp_path / "forms.env"
    env.write_text("".join(line + "\n" for line, _ in _ENV_FORMS))
    keys = " ".join(line.removeprefix("export ").split("=", 1)[0] for line, _ in _ENV_FORMS)
    out = _lib(tmp_path, f'{reader.replace("ENV_FILE", str(env))}\n'
                         f'for k in {keys}; do read_one "$k"; printf "\\0"; done')
    return out.split("\0")[:-1]


def test_env_readers_read_values_as_compose_does(tmp_path):
    want = [value for _, value in _ENV_FORMS]
    assert _read_forms(tmp_path, 'read_one() { sp_env_get "ENV_FILE" "$1"; }') == want
    fn = tmp_path / "install_env_get.sh"
    fn.write_text(_install_fn("env_get") + "\n")
    assert _read_forms(tmp_path, f'. "{fn}"; read_one() {{ env_get "$1" "ENV_FILE"; }}') == want


def test_env_writers_keep_every_line_and_the_value_verbatim(tmp_path):
    """A .env whose last line has no newline (an editor saved it so) got the
    new key glued onto that line: the old value corrupted, the new key lost.
    The value never reaches awk through -v, which rewrites backslashes."""
    value = r"p\w$d 'q' \"x\""
    fn = tmp_path / "install_env_set.sh"
    fn.write_text(_install_fn("env_set") + "\n")
    for name, writer in (("host.sh", 'sp_env_set "$PWD/.env" "$1" "$2"'),
                         ("install.sh", f'. "{fn}"; env_set "$1" "$2"')):
        work = tmp_path / name
        work.mkdir()
        (work / ".env").write_text("SPOREPRINT_API_KEY=my-mobile-key")  # no final newline
        _lib(tmp_path, f'cd "{work}"; set_one() {{ {writer}; }}; '
                       "set_one SPOREPRINT_MQTT_HMAC_KEY abc; set_one TZ Europe/Berlin; "
                       'set_one TZ America/Denver; set_one SPOREPRINT_X "$SP_TEST_VALUE"',
             extra_env={"SP_TEST_VALUE": value})
        text = (work / ".env").read_text()
        assert text == ("SPOREPRINT_API_KEY=my-mobile-key\nSPOREPRINT_MQTT_HMAC_KEY=abc\n"
                        f"TZ=America/Denver\nSPOREPRINT_X={value}\n"), name


def test_install_sh_appends_keys_to_an_env_without_a_final_newline(upgraded_install):
    """The upgrade path: an existing .env without TZ or the signing key,
    whose last line was saved with no newline. Each key the run adds lands on
    its own line and the operator's last setting keeps its value."""
    env = upgraded_install.root / ".env"
    assert _env_value(env, "SPOREPRINT_API_KEY") == "my-mobile-key"
    assert _env_value(env, "TZ") == _HOST_TZ
    assert re.fullmatch(r"[0-9a-f]{64}", _key(env) or "")
    assert env.read_text().endswith("\n")


def test_install_sh_hashes_a_quoted_password_as_compose_reads_it(operator_install):
    """compose strips the quotes around SPOREPRINT_MQTT_PASSWORD="…"; the
    passwd entry install.sh writes must be for that same bare value."""
    passwd = (operator_install.root / "config" / "mosquitto" / "passwd").read_text()
    assert "server:fakehash-of-quoted pw\n" in passwd and "sp-3p:fakehash-of-plug pw\n" in passwd


def test_rotate_appends_to_an_env_without_a_final_newline(tmp_path):
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_PASSWORD=old\nSPOREPRINT_API_KEY=my-mobile-key")
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh", "sp-cmd",
               bindir=_fake_bin(tmp_path, docker_daemon=False), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(root / ".env", "SPOREPRINT_API_KEY") == "my-mobile-key"
    assert re.fullmatch(r"[0-9a-f]{48}", _env_value(root / ".env", "SPOREPRINT_MQTT_CMD_PASSWORD") or "")


def test_setup_sh_uses_the_shared_host_helpers():
    body = (REPO_ROOT / "setup.sh").read_text()
    code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    assert "scripts/lib/host.sh" in body
    # sp_issue_server_cert builds the SAN with sp_server_san.
    for helper in ("sp_issue_server_cert", "sp_cert_reissue_reason", "sp_host_ipv4s",
                   "sp_host_timezone", "sp_ensure_signing_key", "sp_env_get", "sp_env_set"):
        assert helper in code, f"setup.sh does not call {helper}"
    # No hand-rolled DNS-only SAN left behind.
    assert "subjectAltName=DNS:sporeprint.local,DNS:%s" not in code


# ── rotate-mqtt-creds.sh: the plugs' login, and passwd before .env ───────


def test_rotate_default_leaves_the_plug_login_alone(tmp_path):
    """A bare run used to rotate sp-3p too: the broker reload dropped every
    smart plug (relays frozen as they were, out of the server's reach) until
    the new password was typed into each. It is rotated only when named."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n"
                               "SPOREPRINT_MQTT_3P_PASSWORD=plug-pw\n")
    passwd = root / "config" / "mosquitto" / "passwd"
    passwd.write_text("sp-3p:fakehash-of-plug-pw\n")
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh",
               bindir=_fake_bin(tmp_path, docker_daemon=False), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(root / ".env", "SPOREPRINT_MQTT_3P_PASSWORD") == "plug-pw"
    assert re.findall(r"^sp-3p:.*$", passwd.read_text(), re.M) == ["sp-3p:fakehash-of-plug-pw"]
    for user in ("server", "sp-cmd", "sp-telemetry"):
        assert f"✓ rotated {user} " in res.stdout
    assert "sp-3p" not in res.stdout


def test_rotating_the_plug_login_prints_it_and_says_the_plugs_are_cut_off(tmp_path):
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_3P_PASSWORD=plug-pw\n")
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh", "sp-3p",
               bindir=_fake_bin(tmp_path, docker_daemon=True), log=tmp_path / "calls.log")
    assert res.returncode == 0, res.stderr + res.stdout
    new = _env_value(root / ".env", "SPOREPRINT_MQTT_3P_PASSWORD")
    assert new and new != "plug-pw"
    out = " ".join(res.stdout.split())
    assert new in out
    assert "every plug still using the old sp-3p password is off the broker" in out


@pytest.mark.parametrize("daemon", [True, False])
def test_rotate_changes_no_env_file_when_the_passwd_edit_fails(tmp_path, daemon):
    """.env used to get the new passwords before the broker's password file
    did: when that edit failed, the server came back with a password its
    broker did not know."""
    root = _make_repo(tmp_path)
    before = "SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n"
    (root / ".env").write_text(before)
    (root / "server" / ".env").write_text(before)
    bindir = _fake_bin(tmp_path, docker_daemon=daemon)
    if daemon:  # the broker-image run fails (pull error, daemon hiccup, ...)
        (bindir / "docker").write_text(
            '#!/usr/bin/env bash\necho "docker $*" >> "$FAKE_LOG"\n'
            'case "$1" in info) exit 0 ;; run) cat > /dev/null; exit 125 ;; esac\nexit 0\n')
    else:       # the host's mosquitto_passwd fails
        (bindir / "mosquitto_passwd").write_text(
            '#!/usr/bin/env bash\necho "mosquitto_passwd $*" >> "$FAKE_LOG"\nexit 1\n')
    log = tmp_path / "calls.log"
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh", "server", "sp-cmd", bindir=bindir, log=log)
    assert res.returncode != 0
    assert (root / ".env").read_text() == before
    assert (root / "server" / ".env").read_text() == before
    assert "HUP" not in log.read_text()
    assert "no .env file was changed" in res.stderr


# ── setup.sh (developer workstation), run in a throwaway copy ────────────


def _make_setup_repo(tmp_path: Path) -> Path:
    root = _make_repo(tmp_path)
    for rel in ("setup.sh", ".env.example", "config/mosquitto/mosquitto.conf",
                "config/mosquitto/acl.conf"):
        shutil.copy2(REPO_ROOT / rel, root / rel)
    return root


def _run_setup(root: Path, tmp_path: Path, answers: str) -> subprocess.CompletedProcess:
    """setup.sh with `answers` on stdin (Claude key, latitude, longitude),
    docker absent, the host's mosquitto_passwd and uv faked."""
    bindir = tmp_path / "fakebin"
    if not bindir.exists():
        _fake_bin(tmp_path, docker_daemon=False)
        _fake_host(bindir)
        (bindir / "uv").write_text('#!/usr/bin/env bash\necho "uv $* [in $PWD]" >> "$FAKE_LOG"\n'
                                   '[ "$1" = "--version" ] && echo "uv 0.9.0"\nexit 0\n')
        (bindir / "uv").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SPOREPRINT_") and k != "TZ"}
    env.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "calls.log"),
               HOME=str(tmp_path), FAKE_TZ="UTC", SP_ZONEINFO_DIR=str(_fake_zoneinfo(tmp_path)))
    return subprocess.run(["bash", str(root / "setup.sh")], cwd=root, env=env, input=answers,
                          capture_output=True, text=True, timeout=120, umask=0o022)


_CLAUDE_KEY = "sk-ant-api03-Ab_cD-123xyz"


def test_setup_sh_env_is_private_from_the_first_secret(tmp_path):
    """The Claude key went into a 0644 copy of .env.example and the file was
    only made 0600 at the end, so stopping at a later prompt left the key
    readable by every local user."""
    root = _make_setup_repo(tmp_path)
    res = _run_setup(root, tmp_path, f"{_CLAUDE_KEY}\n")  # stops at the latitude prompt
    assert res.returncode != 0
    assert _env_value(root / ".env", "SPOREPRINT_CLAUDE_API_KEY") == _CLAUDE_KEY
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600


def test_setup_sh_writes_the_answers_and_the_locked_dev_environment(tmp_path):
    root = _make_setup_repo(tmp_path)
    res = _run_setup(root, tmp_path, f"{_CLAUDE_KEY}\n45.52\n-122.68\n")
    assert res.returncode == 0, res.stderr + res.stdout
    env = root / ".env"
    assert _env_value(env, "SPOREPRINT_CLAUDE_API_KEY") == _CLAUDE_KEY
    assert (_env_value(env, "SPOREPRINT_WEATHER_LAT"), _env_value(env, "SPOREPRINT_WEATHER_LON")) == \
        ("45.52", "-122.68")
    assert _env_value(env, "SPOREPRINT_MQTT_USERNAME") == "server"
    server_pw = _env_value(env, "SPOREPRINT_MQTT_PASSWORD")
    assert server_pw and f"server:fakehash-of-{server_pw}" in (
        root / "config" / "mosquitto" / "passwd").read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    calls = (tmp_path / "calls.log").read_text()
    assert f"uv sync --python 3.12 --extra dev [in {root}/server]" in calls
    assert not (root / "data").exists() and not (root / ".venv").exists()


def test_setup_sh_does_not_save_answers_it_cannot_use(tmp_path):
    """A key with characters no API key has (an `&` or `|` also broke the
    old sed edit) and a latitude that is not a number are refused, not
    written into .env."""
    root = _make_setup_repo(tmp_path)
    res = _run_setup(root, tmp_path, "sk-ant|api03&x y\nnorth\n12\n")
    assert res.returncode == 0, res.stderr + res.stdout
    env = root / ".env"
    assert _env_value(env, "SPOREPRINT_CLAUDE_API_KEY") == ""
    assert _env_value(env, "SPOREPRINT_WEATHER_LAT") == ""
    assert _env_value(env, "SPOREPRINT_WEATHER_LON") == ""
    res = _run_setup(_make_setup_repo(tmp_path / "range"), tmp_path / "range", "\n91\n10\n")
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(tmp_path / "range" / "SporePrint" / ".env", "SPOREPRINT_WEATHER_LAT") == ""


def _setup_code() -> str:
    body = (REPO_ROOT / "setup.sh").read_text()
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))


def test_setup_sh_installs_the_locked_server_env_on_the_image_python():
    """It used to pip-install ./server[dev] unlocked into a root .venv on
    whatever python3 the host had; the image installs server/uv.lock on its
    own Python."""
    image = re.search(r"^FROM python:(\d+\.\d+)", (REPO_ROOT / "server" / "Dockerfile").read_text(),
                      re.M).group(1)
    code = _setup_code()
    assert f"(cd server && uv sync --python {image} --extra dev)" in code
    assert "pip install" not in code and "venv" not in code.replace("server/.venv", "")


def test_setup_sh_has_no_dead_steps_or_stale_claims():
    """ui/ holds no package.json (the dashboard source is not in this repo),
    the app makes its own data directories (compose uses named volumes), and
    Settings ignores .env keys it does not use."""
    code = _setup_code()
    for stale in ("npm install", "ui/package.json", "HAVE_NODE", "mkdir -p data/",
                  "refuses keys", "source .venv/bin/activate"):
        assert stale not in code, stale


def test_setup_sh_edits_env_only_through_the_host_helpers():
    code = _setup_code()
    assert not re.search(r"\bsed\s+-i\b[^\n]*\.env", code)
    assert not re.search(r">>\s*\.env\b", code)
    # Any local reader is a thin wrapper over the shared one.
    for m in re.finditer(r"^(\w+)\(\)\s*\{([^\n]*)\}", code, re.M):
        if "env" in m.group(1).lower():
            assert "sp_env_get" in m.group(2) or "sp_env_set" in m.group(2), m.group(0)


def test_no_script_says_the_server_refuses_unknown_env_keys():
    """Settings uses extra="ignore": a copied root .env boots the server."""
    assert Settings.model_config.get("extra") == "ignore"
    for path in (REPO_ROOT / "setup.sh", *sorted((REPO_ROOT / "scripts").rglob("*.sh"))):
        text = " ".join(path.read_text().split())
        assert not re.search(r"refuses (keys|to start on)", text), path.name
