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


# ── rotate-mqtt-creds.sh vs the bare-metal server/.env ───────────────────


def test_rotate_keeps_the_bare_metal_server_env_bootable(tmp_path):
    """Bare metal runs uvicorn from server/, which loads server/.env as a
    dotenv — and Settings refuses unknown non-empty keys there ("Extra inputs
    are not permitted"). Rotating all four shared accounts mirrored the
    sp-cmd / sp-telemetry / sp-3p passwords into server/.env, so the next
    server start crash-looped. Only what the server reads belongs there."""
    root = _make_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n")
    (root / "server" / ".env").write_text("SPOREPRINT_MQTT_USERNAME=server\nSPOREPRINT_MQTT_PASSWORD=old\n")
    res = _run(root / "scripts" / "rotate-mqtt-creds.sh",
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
                 zoneinfo: Path | None = None) -> subprocess.CompletedProcess:
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
    return subprocess.run(["bash", str(root / "install.sh")], cwd=root, env=env,
                          capture_output=True, text=True, timeout=120)


def test_install_sh_writes_the_host_timezone(tmp_path):
    root = _make_install_repo(tmp_path)
    res = _run_install(root, tmp_path, fake_tz="America/Denver", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(root / ".env", "TZ") == "America/Denver"


def test_install_sh_resolves_a_legacy_zone_alias(tmp_path):
    """Raspberry Pi OS bookworm offers US/Pacific; the Debian trixie server
    image ships canonical zones only (the aliases moved to tzdata-legacy),
    and glibc runs an unknown TZ on UTC without a word."""
    root = _make_install_repo(tmp_path)
    res = _run_install(root, tmp_path, fake_tz="US/Pacific", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(root / ".env", "TZ") == "America/Los_Angeles"


def test_install_sh_warns_an_upgrade_that_schedules_leave_utc(tmp_path):
    """An existing install ran every schedule on UTC; operators may have
    typed UTC times to compensate. The upgrade must say so."""
    root = _make_install_repo(tmp_path)
    (root / ".env").write_text("SPOREPRINT_ALLOW_UNAUTHENTICATED=true\n")
    res = _run_install(root, tmp_path, fake_tz="America/Denver", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(root / ".env", "TZ") == "America/Denver"
    assert "ran on UTC" in res.stdout and "TZ=UTC" in res.stdout
    # A fresh install has nothing to migrate.
    fresh = _make_install_repo(tmp_path / "fresh")
    res = _run_install(fresh, tmp_path / "fresh", fake_tz="America/Denver",
                       zoneinfo=_fake_zoneinfo(tmp_path / "fresh"))
    assert res.returncode == 0, res.stderr + res.stdout
    assert "ran on UTC" not in res.stdout


def test_install_sh_keeps_the_operator_timezone(tmp_path):
    root = _make_install_repo(tmp_path)
    (root / ".env").write_text("TZ=Europe/Berlin\n")
    res = _run_install(root, tmp_path, fake_tz="America/Denver", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert _env_value(root / ".env", "TZ") == "Europe/Berlin"


def test_install_sh_never_writes_an_unknown_zone(tmp_path):
    root = _make_install_repo(tmp_path)
    res = _run_install(root, tmp_path, fake_tz="Mars/Olympus_Mons", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert not _env_value(root / ".env", "TZ")
    assert "UTC" in res.stdout  # the operator is told schedules stay on UTC


def test_install_sh_provisions_the_command_signing_key(tmp_path):
    """Once paired, cloud_url is set and mqtt_require_signing=auto REFUSES
    every unsigned cmd/* publish: a Pi without a key lost all actuation after
    pairing + restart. With a key the Pi signs everything — nodes that have
    no key accept signed frames (hmac_verify.cpp NoKey → AcceptUnsigned) and
    keyed nodes verify them — so the installer always provisions one."""
    root = _make_install_repo(tmp_path)
    zi = _fake_zoneinfo(tmp_path)
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=zi)
    assert res.returncode == 0, res.stderr + res.stdout
    key = _key(root / ".env")
    assert key and re.fullmatch(r"[0-9a-f]{64}", key)
    assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600
    assert key not in res.stdout  # never echoed into install logs
    # …and a re-run keeps it (nodes may hold it by then).
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=zi)
    assert res.returncode == 0, res.stderr + res.stdout
    assert _key(root / ".env") == key


def test_install_sh_reuses_the_key_nodes_already_hold(tmp_path):
    root = _make_install_repo(tmp_path)
    legacy = "ef" * 32
    (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={legacy}\n")
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert _key(root / ".env") == legacy


def test_install_sh_keeps_the_root_signing_key(tmp_path):
    root = _make_install_repo(tmp_path)
    current, stale = "12" * 32, "34" * 32
    (root / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={current}\n")
    (root / "server" / ".env").write_text(f"SPOREPRINT_MQTT_HMAC_KEY={stale}\n")
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    assert _key(root / ".env") == current


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


def test_setup_sh_certificate_covers_the_host_ips_like_install_sh(tmp_path):
    """fw-node#14: setup.sh issued DNS-only SANs, so a node given the Pi's IP
    as its Secure-MQTT broker host never verified the broker (mbedTLS 2.28
    string-matches DNS SANs only). Its helper must produce exactly the SAN
    install.sh puts in the real certificate."""
    root = _make_install_repo(tmp_path)
    res = _run_install(root, tmp_path, fake_tz="UTC", zoneinfo=_fake_zoneinfo(tmp_path))
    assert res.returncode == 0, res.stderr + res.stdout
    issued = _cert_san(root / "config" / "mosquitto" / "certs" / "server.crt")
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


def test_setup_sh_uses_the_shared_host_helpers():
    body = (REPO_ROOT / "setup.sh").read_text()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "scripts/lib/host.sh" in body
    for helper in ("sp_server_san", "sp_host_ipv4s", "sp_host_timezone", "sp_ensure_signing_key"):
        assert helper in code, f"setup.sh does not call {helper}"
    # No hand-rolled DNS-only SAN left behind.
    assert "subjectAltName=DNS:sporeprint.local,DNS:%s" not in code
