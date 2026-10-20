"""Validate docker-compose.yml — catches image typos, missing services, wrong env vars."""

import ipaddress
import os
import re
import subprocess
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

from app.config import Settings
from app.host_allow import host_is_allowed
from app.vision import service as vision_service

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SERVER_DOCKERFILE = REPO_ROOT / "server" / "Dockerfile"
UI_DOCKERFILE = REPO_ROOT / "ui" / "Dockerfile"

# Standard (non-SPOREPRINT_) variables the server container reads: TZ for the
# automation schedules' local clock (glibc), FORWARDED_ALLOW_IPS for uvicorn.
NON_PREFIXED_SERVER_ENV = {"TZ", "FORWARDED_ALLOW_IPS"}

# .env.example keys the server container deliberately does not receive.
DOCUMENTED_BUT_NOT_FORWARDED = {
    # uvicorn's --host/--port in server/Dockerfile bind the container.
    "SPOREPRINT_HOST",
    "SPOREPRINT_PORT",
    # The smart-plug (sp-3p) broker credential: install.sh and the broker
    # scripts read it; the server never connects as sp-3p.
    "SPOREPRINT_MQTT_3P_PASSWORD",
    # The ui↔server `edge` network layout — compose reads these, not the server.
    "SPOREPRINT_EDGE_SUBNET",
    "SPOREPRINT_EDGE_UI_IP",
    "SPOREPRINT_EDGE_SERVER_IP",
}

_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

# Scripts that run throwaway eclipse-mosquitto containers (mosquitto_passwd
# for the broker's password file). They must use the exact image the broker
# runs, or a hash/format change between versions can lock the Pi out.
# install.sh carries its own copy (curl|bash path); everything else sources
# scripts/lib/broker.sh.
BROKER_IMAGE_OWNERS = (
    REPO_ROOT / "install.sh",
    REPO_ROOT / "scripts" / "lib" / "broker.sh",
)
BROKER_LIB_USERS = (
    REPO_ROOT / "setup.sh",
    REPO_ROOT / "scripts" / "add-node-mqtt-user.sh",
    REPO_ROOT / "scripts" / "rotate-mqtt-creds.sh",
)


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


def _bind_mounts(service: dict) -> dict[str, dict]:
    """target → long-syntax bind mount."""
    return {
        v["target"]: v
        for v in service.get("volumes", [])
        if isinstance(v, dict) and v.get("type") == "bind"
    }


def _server_env() -> dict[str, str]:
    env = _load_compose()["services"]["server"]["environment"]
    return dict(e.split("=", 1) for e in env)


def _interpolate(raw: str, dotenv: dict[str, str]) -> str:
    """Compose's `${VAR:-default}` / `${VAR}` against a .env (no shell vars)."""
    def sub(m: re.Match) -> str:
        value = dotenv.get(m.group(1), "")
        return m.group(2) if value == "" and m.group(2) is not None else value
    return _INTERPOLATION.sub(sub, raw)


def _compose_default(key: str) -> str:
    m = re.fullmatch(r"\$\{\w+:-(.*)\}", _server_env()[key])
    assert m, f"{key} has no `${{VAR:-default}}` default"
    return m.group(1)


def test_compose_has_all_services():
    services = _load_compose()["services"]
    for name in ("server", "mqtt", "ntfy", "ui"):
        assert name in services, f"Missing service: {name}"


def test_ntfy_image_is_correct():
    services = _load_compose()["services"]
    assert services["ntfy"]["image"] == "binwiederhier/ntfy:v2.28.0"


def test_mosquitto_image_is_correct():
    services = _load_compose()["services"]
    assert services["mqtt"]["image"] == "eclipse-mosquitto:2.1.2-alpine"


def test_every_image_is_pinned_to_an_exact_version():
    """install.sh runs `compose pull` on every update: a floating tag
    (`eclipse-mosquitto:2` silently moved 2.0.x → 2.1.x, with option
    deprecations) changes the broker without any code change or test."""
    for name, svc in _load_compose()["services"].items():
        image = svc.get("image")
        if image is None:
            continue  # built locally
        assert ":" in image, f"{name}: image {image!r} has no tag (implicit :latest)"
        tag = image.rsplit(":", 1)[1]
        assert re.match(r"^v?\d+\.\d+(\.\d+)?(-[a-z0-9.]+)?$", tag), (
            f"{name}: image tag {tag!r} is not an exact version"
        )


def test_scripts_use_the_same_broker_image_as_compose():
    image = _load_compose()["services"]["mqtt"]["image"]
    for script in BROKER_IMAGE_OWNERS:
        used = set(re.findall(r"eclipse-mosquitto:[\w.\-]+", script.read_text()))
        assert used == {image}, (
            f"{script.name} uses {sorted(used)} but the broker runs {image}"
        )
    for script in BROKER_LIB_USERS:
        body = script.read_text()
        assert "scripts/lib/broker.sh" in body, f"{script.name} no longer uses the shared broker helpers"
    # …and no other shell script pins a different broker image.
    for script in [*REPO_ROOT.glob("*.sh"), *(REPO_ROOT / "scripts").rglob("*.sh")]:
        used = set(re.findall(r"eclipse-mosquitto:[\w.\-]+", script.read_text()))
        assert used <= {image}, f"{script.name} uses {sorted(used)}; the broker runs {image}"


def test_server_env_vars_use_correct_prefix():
    services = _load_compose()["services"]
    env_list = services["server"]["environment"]
    for env in env_list:
        key = env.split("=")[0]
        if key in NON_PREFIXED_SERVER_ENV:
            continue
        assert key.startswith("SPOREPRINT_"), f"Env var {key} doesn't use SPOREPRINT_ prefix"


def test_server_schedules_run_on_the_operator_timezone():
    """Photoperiod, time_range and cron rules evaluate time.localtime(). With
    no TZ the container is on UTC, so a 06:00 lights-on ran at 23:00 PDT and
    Lion's Mane Night Cool (22:00-06:00) cooled the closet all afternoon.
    install.sh writes the host's zone into .env as TZ; unset stays UTC."""
    assert _server_env().get("TZ") == "${TZ:-UTC}"


def test_server_receives_every_operator_setting():
    """There is no env_file:, so a setting reaches the container only if it is
    listed. Each of these was documented, or read by the server, but could
    not be set on a Docker Pi."""
    env = _server_env()
    # Blank means the default model (config.py's blank-to-default validator).
    assert env.get("SPOREPRINT_CLAUDE_MODEL") == "${SPOREPRINT_CLAUDE_MODEL:-}"
    # Non-str settings get a real default: an EMPTY string fails int/bool
    # validation and the server crash-loops at boot.
    assert env.get("SPOREPRINT_VISION_AUTO_INTERVAL_MIN", "").startswith(
        "${SPOREPRINT_VISION_AUTO_INTERVAL_MIN:-")
    assert env.get("SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS", "").startswith(
        "${SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS:-")
    # uvicorn's trusted-proxy range, overridable from .env: editing the tracked
    # compose file or Dockerfile instead makes install.sh's `git pull
    # --ff-only` fail, and the Pi then silently keeps building old code.
    assert env.get("FORWARDED_ALLOW_IPS", "").startswith("${FORWARDED_ALLOW_IPS:-")


def test_compose_defaults_mirror_the_server_defaults():
    """A compose default that disagrees with the code would silently change
    behaviour for every Pi that leaves the key unset."""
    fields = Settings.model_fields
    interval = fields["vision_auto_interval_min"].default if "vision_auto_interval_min" in fields else None
    if interval is None:
        interval = vision_service._AUTO_ANALYSIS_MIN_INTERVAL_SECONDS // 60
    assert int(_compose_default("SPOREPRINT_VISION_AUTO_INTERVAL_MIN")) == interval
    strict = (fields["cloud_require_signed_integrations"].default
              if "cloud_require_signed_integrations" in fields else False)
    assert _compose_default("SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS") == str(bool(strict)).lower()
    assert _compose_default("SPOREPRINT_MQTT_REQUIRE_SIGNING") == fields["mqtt_require_signing"].default
    assert int(_compose_default("SPOREPRINT_WEATHER_POLL_MINUTES")) == fields["weather_poll_minutes"].default
    if "public_ui_url" in fields:
        assert _compose_default("SPOREPRINT_PUBLIC_UI_URL") == fields["public_ui_url"].default
    image_default = re.search(r"^ENV\s+FORWARDED_ALLOW_IPS=(\S+)", SERVER_DOCKERFILE.read_text(), re.M).group(1)
    assert _compose_default("FORWARDED_ALLOW_IPS") == image_default


def test_compose_defaults_boot_the_server(monkeypatch):
    """`docker compose up` with an .env that sets nothing must still produce
    an environment the server's Settings accept (an empty value for an
    int/bool/Literal field is a boot-time crash loop)."""
    for key in list(os.environ):
        if key.startswith("SPOREPRINT_"):
            monkeypatch.delenv(key)
    for key, raw in _server_env().items():
        monkeypatch.setenv(key, _interpolate(raw, {}))
    Settings(_env_file=None)


def test_every_server_setting_can_reach_the_container():
    """A Settings field compose does not list can never be set on a Docker
    Pi. Add new settings to the server environment (with a real default
    when the field is not a str), or exempt them here with the reason."""
    exempt = {
        "host", "port",       # uvicorn's --host/--port in server/Dockerfile
        "setup_complete",     # first-run wizard flag, stored by the UI in the DB
    }
    forwarded = set(_server_env())
    missing = {name for name in Settings.model_fields
               if f"SPOREPRINT_{name.upper()}" not in forwarded} - exempt
    assert not missing, f"settings compose never passes to the server: {sorted(missing)}"


def test_every_documented_setting_reaches_the_server():
    """.env.example is the operator's menu. A key documented there but not
    forwarded here is a knob that silently does nothing on a Docker Pi
    (SPOREPRINT_MQTT_HMAC_KEY and SPOREPRINT_CLAUDE_MODEL both were)."""
    documented = set(re.findall(r"^\s*#?\s*(SPOREPRINT_[A-Z0-9_]+|TZ)=", ENV_EXAMPLE.read_text(), re.M))
    missing = documented - set(_server_env()) - DOCUMENTED_BUT_NOT_FORWARDED
    assert not missing, f"documented in .env.example but never passed to the server: {sorted(missing)}"


def test_every_operator_setting_is_documented():
    text = ENV_EXAMPLE.read_text()
    for key, raw in _server_env().items():
        for var in _INTERPOLATION.findall(raw):
            assert var[0] in text, f"{key} reads ${{{var[0]}}}, which .env.example never mentions"


def test_env_example_is_a_valid_bare_metal_server_env():
    """Bare metal runs uvicorn from server/, which reads server/.env as a
    dotenv — and Settings refuses unknown non-empty keys there. A copied
    .env.example must still boot."""
    Settings(_env_file=str(ENV_EXAMPLE))


def test_ui_nginx_base_image_is_pinned_to_a_stable_release():
    """`FROM nginx:alpine` floats with mainline: every `compose up --build`
    could pull a new nginx under the LAN dashboard's proxy. Pin a stable
    (even-minor) release by tag AND multi-arch index digest, like the server."""
    froms = [line.split(None, 1)[1].strip() for line in UI_DOCKERFILE.read_text().splitlines()
             if line.strip().upper().startswith("FROM ")]
    assert len(froms) == 1, froms
    m = re.fullmatch(r"nginx:(\d+)\.(\d+)\.(\d+)-alpine@sha256:[0-9a-f]{64}", froms[0])
    assert m, f"ui/Dockerfile base {froms[0]!r} is not an exact nginx release + digest"
    assert int(m.group(2)) % 2 == 0, "odd nginx minors are mainline; the LAN proxy tracks stable"


def test_server_receives_the_command_signing_and_ota_keys():
    """server/.dockerignore excludes .env and there is no env_file:, so a
    setting reaches the container ONLY if it is listed here. Without these,
    scripts/provision-node.sh's key never reached the server: keyed nodes
    rejected every (unsigned) command, and a cloud-configured Pi in 'auto'
    mode refused every command with no way to supply the key."""
    env = _server_env()
    assert env.get("SPOREPRINT_MQTT_HMAC_KEY") == "${SPOREPRINT_MQTT_HMAC_KEY:-}"
    # An EMPTY value fails the Literal["auto","always","never"] check and the
    # server crash-loops at boot — the default must be spelled out.
    assert env.get("SPOREPRINT_MQTT_REQUIRE_SIGNING") == "${SPOREPRINT_MQTT_REQUIRE_SIGNING:-auto}"
    assert env.get("SPOREPRINT_OTA_PUBKEY_B64") == "${SPOREPRINT_OTA_PUBKEY_B64:-}"
    # The older name (still in operators' .env files); cloud/ota.py falls back to it.
    assert env.get("SPOREPRINT_OTA_PUBKEY") == "${SPOREPRINT_OTA_PUBKEY:-}"


def test_generated_broker_files_are_never_auto_created_as_directories():
    """passwd, certs and ca.crt are generated by install.sh. With the short
    `./a:/b` syntax a missing source is silently created by Docker as a
    root-owned DIRECTORY — the broker then dies ('pwfile is a directory')
    and a later install.sh cannot even write the file. Long syntax with
    create_host_path: false makes a bare `docker compose up` fail loudly."""
    services = _load_compose()["services"]
    required = {
        "mqtt": ("/mosquitto/config/passwd", "/mosquitto/certs"),
        "server": ("/certs/ca.crt",),
    }
    for svc_name, targets in required.items():
        mounts = _bind_mounts(services[svc_name])
        for target in targets:
            assert target in mounts, f"{svc_name}: no long-syntax bind for {target}"
            mount = mounts[target]
            assert mount.get("read_only") is True, f"{svc_name}:{target} must be read-only"
            assert (mount.get("bind") or {}).get("create_host_path") is False, (
                f"{svc_name}:{target} would be auto-created as a directory"
            )


def test_every_service_rotates_its_logs():
    """The json-file driver is unbounded by default; the broker logs every
    connect/disconnect to stdout. Months of that fill the Pi's SD card and
    SQLite then fails with 'database or disk is full'."""
    for name, svc in _load_compose()["services"].items():
        logging_cfg = svc.get("logging") or {}
        opts = logging_cfg.get("options") or {}
        assert opts.get("max-size"), f"{name}: no log max-size"
        assert opts.get("max-file"), f"{name}: no log max-file"


def test_server_publishes_the_ota_push_callback_port():
    """espota: the node connects BACK over TCP to the port the Pi advertises.
    Behind the compose bridge network that port must be fixed and
    published, or every push ends 'node … never connected back'."""
    from app.hardware import ota_push

    port = ota_push.CALLBACK_PORT
    assert port and port != 8000
    published = _published_ports(_load_compose()["services"]["server"])
    assert ("0.0.0.0", str(port), str(port)) in published, (
        f"server does not publish the OTA callback port {port}: {published}"
    )


def _published_ports(service: dict) -> list[tuple[str, str, str]]:
    """(host address, host port, container port) of each short-syntax port.
    A mapping without a host address yields '' for it."""
    out = []
    for raw in service.get("ports", []):
        assert isinstance(raw, str), f"use the short HOST:PORT:PORT syntax: {raw!r}"
        parts = raw.split(":")
        assert len(parts) in (2, 3), raw
        out.append(tuple(parts) if len(parts) == 3 else ("", *parts))
    return out


def test_every_port_is_published_on_ipv4_only():
    """Without a host address Docker publishes on [::] too. IPv6 has no NAT,
    so on a Pi with a global IPv6 address the unauthenticated (LAN-trust)
    API, ntfy, MQTT and the OTA callback port would be guarded only by the
    router's IPv6 firewall."""
    every = {name: _published_ports(svc) for name, svc in _load_compose()["services"].items()}
    assert sum(len(p) for p in every.values()) >= 6
    for name, published in every.items():
        for host, host_port, _container in published:
            assert host == "0.0.0.0", f"{name} publishes {host_port} on {host or 'every address'}"


def test_ui_port_mapping():
    services = _load_compose()["services"]
    ports = services["ui"]["ports"]
    assert any("3001:80" in str(p) for p in ports), f"UI should map to port 3001, got {ports}"


# ── X-Forwarded-For trust: exactly the ui container, never a gateway ─────

def _edge_layout(dotenv: dict[str, str] | None = None):
    compose = _load_compose()
    services = compose["services"]
    dotenv = dotenv or {}
    subnet = ipaddress.ip_network(
        _interpolate(compose["networks"]["edge"]["ipam"]["config"][0]["subnet"], dotenv))
    ui_ip = ipaddress.ip_address(
        _interpolate(services["ui"]["networks"]["edge"]["ipv4_address"], dotenv))
    server_ip = ipaddress.ip_address(
        _interpolate(services["server"]["networks"]["edge"]["ipv4_address"], dotenv))
    return subnet, ui_ip, server_ip


def test_forwarded_headers_are_trusted_only_from_the_ui_container():
    """FORWARDED_ALLOW_IPS=172.16.0.0/12 trusted every bridge gateway, and
    docker-proxy relays IPv6/loopback clients of the published :8000 from a
    gateway: such a client could forge X-Forwarded-For. The ui (nginx) now
    has a fixed address on a fixed subnet and only that address is trusted."""
    subnet, ui_ip, server_ip = _edge_layout()
    assert _compose_default("FORWARDED_ALLOW_IPS") == str(ui_ip)
    assert ui_ip in subnet and server_ip in subnet
    assert len({ui_ip, server_ip, next(subnet.hosts())}) == 3, (
        "ui, server and the gateway (first host) need distinct addresses"
    )
    image_default = re.search(r"^ENV\s+FORWARDED_ALLOW_IPS=(\S+)",
                              SERVER_DOCKERFILE.read_text(), re.M).group(1)
    assert image_default == str(ui_ip)


def test_edge_network_carries_only_the_ui_hop():
    services = _load_compose()["services"]
    # The ui reaches nothing but the server, so its fixed address is the
    # only one on the edge network apart from the server's.
    assert set(services["ui"]["networks"]) == {"edge"}
    # The server keeps the default network for mqtt/ntfy by name.
    assert set(services["server"]["networks"]) == {"default", "edge"}
    for name, svc in services.items():
        if name not in ("ui", "server"):
            assert "edge" not in (svc.get("networks") or {}), name


def test_edge_layout_is_overridable_from_env():
    """A fixed subnet can collide with another Docker network or the LAN;
    editing the tracked compose file breaks install.sh's `git pull
    --ff-only`, so .env must be able to move it."""
    subnet, ui_ip, server_ip = _edge_layout({
        "SPOREPRINT_EDGE_SUBNET": "10.99.7.0/28",
        "SPOREPRINT_EDGE_UI_IP": "10.99.7.2",
        "SPOREPRINT_EDGE_SERVER_IP": "10.99.7.3",
    })
    assert (str(subnet), str(ui_ip), str(server_ip)) == ("10.99.7.0/28", "10.99.7.2", "10.99.7.3")
    text = ENV_EXAMPLE.read_text()
    for key, value in (("SPOREPRINT_EDGE_SUBNET", str(_edge_layout()[0])),
                       ("SPOREPRINT_EDGE_UI_IP", str(_edge_layout()[1])),
                       ("SPOREPRINT_EDGE_SERVER_IP", str(_edge_layout()[2])),
                       ("FORWARDED_ALLOW_IPS", str(_edge_layout()[1]))):
        assert re.search(rf"^#\s*{key}={re.escape(value)}$", text, re.M), (
            f".env.example must document {key}={value}"
        )


# ── Host allow-list (DNS rebinding) ───────────────────────────────────────

def test_allowed_hosts_setting_reaches_the_server():
    assert _server_env().get("SPOREPRINT_ALLOWED_HOSTS") == "${SPOREPRINT_ALLOWED_HOSTS:-}"


def _server_probe() -> list[str]:
    return _load_compose()["services"]["server"]["healthcheck"]["test"]


def test_server_healthcheck_host_passes_the_host_allow_list():
    probe = _server_probe()[-1]
    m = re.search(r"GET (\S+) HTTP/1\.[01]\\r\\nHost: ([^\\]+)\\r\\n", probe)
    assert m, probe
    path, host = m.groups()
    assert path == "/api/health"
    assert host_is_allowed(host)


def test_server_healthcheck_is_a_bare_interpreter_start():
    """It runs every 10 s for the life of the Pi. `python -c "import
    urllib.request"` loaded site plus ~120 modules (http.client, email, ssl)
    per probe through a shell; a socket probe without site costs a fraction."""
    test = _server_probe()
    assert test[:5] == ["CMD", "python", "-I", "-S", "-c"], test[:5]
    assert "urllib" not in test[-1] and "import socket,sys;" in test[-1]


class _Health(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):  # noqa: N802 (http.server's handler name)
        self.send_response(self.status if self.path == "/api/health" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


def _probe_against(status: int) -> int:
    handler = type("Handler", (_Health,), {"status": status})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        probe = _server_probe()[-1]
        assert '("127.0.0.1",8000)' in probe, probe
        probe = probe.replace('("127.0.0.1",8000)', f'("127.0.0.1",{server.server_address[1]})')
        return subprocess.run([sys.executable, *_server_probe()[2:-1], probe],
                              capture_output=True, timeout=30).returncode
    finally:
        server.shutdown()
        server.server_close()


def test_server_healthcheck_passes_only_on_a_200():
    assert _probe_against(200) == 0
    assert _probe_against(503) == 1


# ── Broker healthcheck: the `server` password never on a command line ────

def _broker_probe() -> str:
    test = _load_compose()["services"]["mqtt"]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL" and len(test) == 2, test
    return test[1].replace("$$", "$")  # compose's escape for a literal $


def test_broker_healthcheck_keeps_the_password_off_every_command_line():
    """Container processes are host processes: `mosquitto_sub -P <password>`
    every 10 s put the `server` login in the Pi's process table, where any
    local user reads it. The password may appear only in the shell's own
    printf (a builtin, no new process) writing the options file."""
    script = _broker_probe()
    runs = [c for c in script.split(";") if re.search(r"(^|\s)mosquitto_sub\s", c)]
    assert len(runs) == 1, script
    assert "-P" not in runs[0] and "-u " not in runs[0], runs[0]
    for command in script.split(";"):
        if "SPOREPRINT_MQTT_PASSWORD" in command:
            assert command.strip().startswith("printf "), command


def test_broker_healthcheck_logs_in_from_a_removed_options_file(tmp_path):
    """Run the healthcheck under sh with mosquitto_sub and mktemp faked: the
    login reaches mosquitto_sub through $XDG_CONFIG_HOME/mosquitto_sub only,
    the file is gone afterwards, and mosquitto_sub's exit code is the check's."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "mktemp").write_text('#!/bin/sh\nd="$FAKE_TMP/probe.$$"; mkdir -m 700 "$d" && echo "$d"\n')
    (bindir / "mosquitto_sub").write_text(
        '#!/bin/sh\necho "$*" > "$FAKE_ARGV"\ncp "$XDG_CONFIG_HOME/mosquitto_sub" "$FAKE_CONF"\n'
        'exit "$FAKE_RC"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    (tmp_path / "shm").mkdir()
    for rc in (0, 5):
        env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_TMP": str(tmp_path / "shm"),
               "FAKE_ARGV": str(tmp_path / "argv"), "FAKE_CONF": str(tmp_path / "conf"),
               "FAKE_RC": str(rc), "SPOREPRINT_MQTT_PASSWORD": "pw with spaces-123"}
        result = subprocess.run(["sh", "-c", _broker_probe()], env=env, capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == rc, result.stderr
        assert "pw with" not in (tmp_path / "argv").read_text()
        assert (tmp_path / "conf").read_text() == "-u server\n-P pw with spaces-123\n"
        assert list((tmp_path / "shm").iterdir()) == []


def test_uv_lock_records_the_project_version():
    # server/Dockerfile installs with `uv export --locked`, which refuses a
    # lock whose own-project entry disagrees with pyproject.toml — a version
    # bump that skips uv.lock breaks the image build (5.1.0 hit it).
    server = REPO_ROOT / "server"
    project = tomllib.loads((server / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((server / "uv.lock").read_text())
    entry = next(p for p in lock["package"] if p["name"] == project["name"])
    assert entry["version"] == project["version"]

