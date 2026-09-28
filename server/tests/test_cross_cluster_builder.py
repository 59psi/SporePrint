"""Builder cross-cluster follow-ups (hardware audit, pass 2).

- srv-hw#14 / docs#21 / fw-drivers-cam#7: the Builder's Assistant system
  context names the camera the firmware actually drives (AI-Thinker ESP32-CAM,
  OV2640/OV3660/OV5640), says S3 camera boards are unsupported, lists every
  reserved GPIO and the complete MQTT contract including the broker ACL;
- claude-model #3: POST /api/builder/guide maps generate_guide errors to
  503 (not configured) / 502 (upstream), keeping the body fields;
- srv-hw#18: firmware ZIP bundles carry library.json manifests and every file
  platformio.ini references, and tell the builder how to set the version.
"""

import configparser
import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import TextBlock
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.builder.service as builder_service
from app.builder import models_router as mr
from app.config import settings
from app.db import get_db

_REPO_FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"


# ── Builder's Assistant system context ─────────────────────────────────────


async def test_context_names_only_the_supported_camera():
    ctx = await builder_service._build_system_context()
    assert "ESP32-S3 CAM" not in ctx
    assert "AI-Thinker ESP32-CAM" in ctx
    for sensor in ("OV2640", "OV3660", "OV5640"):
        assert sensor in ctx
    assert re.search(r"ESP32-S3 camera boards[^\n]*NOT supported", ctx)
    assert "`cam`" in ctx


async def test_context_lists_every_reserved_gpio():
    ctx = await builder_service._build_system_context()
    for pins in ("SDA 21", "SCL 22", "25, 26, 27, 14", "DOUT 32", "SCK 33",
                 "reed switch 35", "RX 16", "TX 17", "BOOT / factory reset 0"):
        assert pins in ctx, pins
    # The S3 node's own map, and the camera board's lack of spare pins.
    for pins in ("SDA 8", "SCL 9", "4, 5, 6, 7", "HX711 10/11", "reed 12"):
        assert pins in ctx, pins
    assert "factory reset 13" in ctx


def _board_pins(name: str) -> dict[str, str]:
    text = (_REPO_FIRMWARE / "boards" / name).read_text()
    return dict(re.findall(r"#define (SP_\w+) (\S.*?)\s*(?://.*)?$", text, re.M))


async def test_context_matches_the_board_profiles():
    """Guard against the context drifting from the real pin maps."""
    ctx = await builder_service._build_system_context()
    dev = _board_pins("board_profile_esp32dev.h")
    assert f"SDA {dev['SP_PIN_I2C_SDA']}" in ctx
    assert f"DOUT {dev['SP_PIN_HX711_DOUT']}" in ctx
    assert f"reed switch {dev['SP_PIN_REED']}" in ctx
    assert dev["SP_CHANNEL_PINS"].strip("{}") in ctx
    s3 = _board_pins("board_profile_esp32s3.h")
    assert f"SDA {s3['SP_PIN_I2C_SDA']}" in ctx
    assert s3["SP_CHANNEL_PINS"].strip("{}") in ctx
    cam = _board_pins("board_profile_esp32cam.h")
    assert f"factory reset {cam['SP_PIN_FACTORY_RESET']}" in ctx
    assert f"flash LED {cam['SP_PIN_FLASH']}" in ctx


def _acl_node_publish_topics() -> set[str]:
    """Topic bases a node may publish under its own id (acl.conf patterns)."""
    acl = (_REPO_FIRMWARE.parent / "config" / "mosquitto" / "acl.conf").read_text()
    found = re.findall(r"^pattern (?:readwrite|write) sporeprint/%u/(\S+)$", acl, re.M)
    return {t.removesuffix("/#") for t in found}


async def test_context_states_the_complete_mqtt_contract():
    ctx = await builder_service._build_system_context()
    for base in _acl_node_publish_topics():
        assert f"`{base}" in ctx, base
    for cmd in ("cmd/{channel}", "cmd/scene", "cmd/config", "status/heartbeat",
                "telemetry/{channel}", "coredump/chunk"):
        assert cmd in ctx, cmd
    assert "acl.conf" in ctx and "mqtt.py" in ctx
    assert "never sends pwm/level with \"off\"" in ctx


async def test_context_names_a_registered_cameras_sensor():
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, status, config) "
            "VALUES ('cam-01', 'camera', 'online', '{\"camera_sensor\": \"ov3660\"}')")
        await db.commit()
    ctx = await builder_service._build_system_context()
    assert re.search(r"\*\*cam-01\*\* \(camera\)[^\n]*OV3660", ctx)


# ── POST /api/builder/guide status codes ───────────────────────────────────


def _install(monkeypatch, reply):
    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_final_message(self):
            return reply

    class _Messages:
        def stream(self, **kwargs):
            return _Stream()

    class _Client:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(builder_service.anthropic, "AsyncAnthropic", _Client)


def test_guide_without_a_key_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "")
    r = client.post("/api/builder/guide", json={"request": "add a pump"})
    assert r.status_code == 503
    assert r.json()["error"] == "Claude API key not configured"
    assert r.json()["code"] == "not_configured"


def test_truncated_guide_is_502_and_keeps_the_partial_guide(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "k")
    _install(monkeypatch, SimpleNamespace(content=[TextBlock(type="text", text="## 1. Parts")],
                                          stop_reason="max_tokens"))
    r = client.post("/api/builder/guide", json={"request": "add a pump", "constraints": "12V"})
    assert r.status_code == 502
    body = r.json()
    assert body["truncated"] is True and body["guide"] == "## 1. Parts"
    assert body["request"] == "add a pump" and body["constraints"] == "12V"
    assert body["code"] == "truncated"


def test_refused_or_failed_guide_is_502(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "k")
    _install(monkeypatch, SimpleNamespace(content=[], stop_reason="refusal"))
    assert client.post("/api/builder/guide", json={"request": "x"}).status_code == 502

    class _Boom:
        def __init__(self, *a, **kw):
            raise RuntimeError("network down")

    monkeypatch.setattr(builder_service.anthropic, "AsyncAnthropic", _Boom)
    r = client.post("/api/builder/guide", json={"request": "x"})
    assert r.status_code == 502 and r.json()["code"] == "upstream_error"


def test_good_guide_is_200(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "k")
    _install(monkeypatch, SimpleNamespace(content=[TextBlock(type="text", text="## 1. Parts\nok")],
                                          stop_reason="end_turn"))
    r = client.post("/api/builder/guide", json={"request": "add a pump"})
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["guide_id"], int)


# ── firmware ZIP bundles ───────────────────────────────────────────────────


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(mr.router, prefix="/api/builder")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def repo_firmware(monkeypatch):
    assert _REPO_FIRMWARE.is_dir(), _REPO_FIRMWARE
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", _REPO_FIRMWARE)
    monkeypatch.setattr(mr, "_firmware_cache", {"data": [], "ts": 0})
    return _REPO_FIRMWARE


def _bundle(api, node) -> zipfile.ZipFile:
    r = api.get(f"/api/builder/firmware/bundle/{node}")
    assert r.status_code == 200, r.text
    return zipfile.ZipFile(io.BytesIO(r.content))


def _pio_references(ini: Path) -> tuple[set[str], set[str]]:
    """(files, directories) platformio.ini needs, relative to the project —
    including every config its `extra_configs` globs merge in."""
    project = ini.parent
    main = configparser.ConfigParser(interpolation=None, strict=False)
    main.read(ini)
    extra = [p for pat in main.get("platformio", "extra_configs", fallback="").split()
             for p in sorted(project.glob(pat))]
    files = {p.relative_to(project).as_posix() for p in extra}
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read([ini, *extra])
    dirs = set()
    for section in cp.sections():
        for key, value in cp.items(section):
            tokens = [t for t in re.split(r"[\s,]+", value) if t and "${" not in t]
            if key in ("board_build.partitions", "board_build.embed_files",
                       "board_build.embed_txtfiles"):
                files.update(tokens)
            elif key == "extra_scripts":
                files.update(re.sub(r"^(pre|post):", "", t) for t in tokens)
            elif key in ("build_flags", "lib_extra_dirs"):
                flat = " ".join(tokens)
                dirs.update(re.findall(r"-I\s*([^\s-][^\s]*)", flat))
                if key == "lib_extra_dirs":
                    dirs.update(tokens)
            elif key == "build_src_filter":
                dirs.update("src/" + d.rstrip("/") for d in re.findall(r"\+<([^>]+)>", value))
    return files, dirs


@pytest.mark.parametrize("node, image_dir", [("node", "src/node"), ("cam", "src/cam"), ("full", None)])
def test_image_bundle_contains_everything_platformio_ini_references(repo_firmware, api, node, image_dir):
    names = set(_bundle(api, node).namelist())
    files, dirs = _pio_references(repo_firmware / "platformio.ini")
    for f in files:
        assert f"firmware/{f}" in names, f
    for d in dirs:
        if d.startswith("src/") and image_dir and d != image_dir:
            continue  # the other image's sources — not this bundle's env
        assert any(n.startswith(f"firmware/{d}/") for n in names), d
    for must in ("platformio.ini", "VERSION.txt", "partitions.csv", "partitions_8mb.csv"):
        assert f"firmware/{must}" in names, must


@pytest.mark.parametrize("node", ["node", "cam", "full"])
def test_image_bundle_carries_every_library_manifest(repo_firmware, api, node):
    names = set(_bundle(api, node).namelist())
    for lib in ("sp_core", "sp_drivers", "sp_device"):
        assert f"firmware/lib/{lib}/library.json" in names, lib


@pytest.mark.parametrize("node", ["sp_core", "sp_drivers"])
def test_library_bundle_carries_its_manifest(repo_firmware, api, node):
    assert f"firmware/lib/{node}/library.json" in set(_bundle(api, node).namelist())


def test_bundle_readmes_name_every_env_and_the_version_source(repo_firmware, api):
    envs = builder_service.platformio_image_envs(repo_firmware / "platformio.ini")
    node_readme = _bundle(api, "node").read("firmware/src/node/README.md").decode()
    for env in envs["node"]:
        assert f"pio run -t upload -e {env}\n" in node_readme, env
    assert "-e node_esp32\n" in node_readme and "-e node_esp32s3\n" in node_readme
    cam_readme = _bundle(api, "cam").read("firmware/src/cam/README.md").decode()
    assert "-e cam\n" in cam_readme
    full_readme = _bundle(api, "full").read("firmware/README.md").decode()
    for readme in (node_readme, cam_readme, full_readme):
        assert "SPOREPRINT_FW_VERSION" in readme and "VERSION.txt" in readme


def test_readme_exports_the_version_when_platformio_ini_needs_it(tmp_path, monkeypatch, api):
    """Before scripts/fw_version.py the build flag expanded
    ${sysenv.SPOREPRINT_FW_VERSION} directly, so a bundle built as its README
    said heartbeated firmware_version ""."""
    fw = tmp_path / "firmware"
    (fw / "src" / "node").mkdir(parents=True)
    (fw / "src" / "node" / "main.cpp").write_text("int main(){}\n")
    (fw / "VERSION.txt").write_text("5.0.0\n")
    (fw / "platformio.ini").write_text(
        "[env:node_esp32]\nbuild_src_filter = +<node/>\n"
        "build_flags = -DSPOREPRINT_FW_VERSION='\"${sysenv.SPOREPRINT_FW_VERSION}\"'\n")
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", fw)
    readme = _bundle(api, "node").read("firmware/src/node/README.md").decode()
    assert 'export SPOREPRINT_FW_VERSION="$(cat VERSION.txt)"\npio run -t upload -e node_esp32' in readme


def test_image_envs_follow_extends(tmp_path):
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[base]\nboard = esp32dev\n"
        "[env:a]\nextends = base\nbuild_src_filter = +<node/>\n"
        "[env:b]\nextends = env:a\n"
        "[env:c]\nbuild_src_filter = +<cam/>\n"
        "[env:native]\nplatform = native\n")
    assert builder_service.platformio_image_envs(ini) == {"node": ["a", "b"], "cam": ["c"]}
    assert builder_service.platformio_image_envs(tmp_path / "missing.ini")["cam"] == ["cam"]


def test_bundle_includes_extra_scripts_platformio_ini_names(tmp_path, monkeypatch, api):
    fw = tmp_path / "firmware"
    (fw / "src" / "node").mkdir(parents=True)
    (fw / "src" / "node" / "main.cpp").write_text("int main(){}\n")
    (fw / "scripts").mkdir()
    (fw / "scripts" / "version.py").write_text("Import('env')\n")
    (fw / "boards").mkdir()
    (fw / "boards" / "board.h").write_text("#pragma once\n")
    (fw / "custom_parts.csv").write_text("nvs,data,nvs,,0x5000\n")
    (fw / "platformio.ini").write_text(
        "[env:node_esp32]\n"
        "extra_scripts = pre:scripts/version.py\n"
        "board_build.partitions = custom_parts.csv\n"
        "build_flags = -I boards\n"
        "build_src_filter = +<node/>\n")
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", fw)
    names = set(_bundle(api, "node").namelist())
    assert "firmware/scripts/version.py" in names
    assert "firmware/custom_parts.csv" in names
    assert "firmware/boards/board.h" in names


def test_bundle_follows_extra_configs_to_their_scripts(tmp_path, monkeypatch, api):
    """The firmware attaches its version pre-script from scripts/*.ini
    (`[platformio] extra_configs`), not from platformio.ini itself."""
    fw = tmp_path / "firmware"
    (fw / "src" / "node").mkdir(parents=True)
    (fw / "src" / "node" / "main.cpp").write_text("int main(){}\n")
    (fw / "scripts").mkdir()
    (fw / "scripts" / "fw_version.py").write_text("Import('env')\n")
    (fw / "scripts" / "fw_version.ini").write_text(
        "[esp32_base]\nextra_scripts = pre:scripts/fw_version.py\n")
    (fw / "platformio.ini").write_text(
        "[platformio]\nextra_configs = scripts/*.ini\n"
        "[esp32_base]\nboard = esp32dev\n"
        "[env:node_esp32]\nextends = esp32_base\nbuild_src_filter = +<node/>\n")
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", fw)
    names = set(_bundle(api, "node").namelist())
    assert {"firmware/scripts/fw_version.ini", "firmware/scripts/fw_version.py"} <= names
    readme = _bundle(api, "node").read("firmware/src/node/README.md").decode()
    assert "export SPOREPRINT_FW_VERSION" not in readme  # the script reads VERSION.txt


def test_extra_configs_holding_secrets_are_never_published(tmp_path, monkeypatch, api):
    """A local override ini (OTA --auth password, upload_port, WiFi creds in
    build_flags) matched by the same scripts/*.ini glob must not be zipped or
    served; the shared fw_version.ini still is."""
    fw = tmp_path / "firmware"
    (fw / "src" / "node").mkdir(parents=True)
    (fw / "src" / "node" / "main.cpp").write_text("int main(){}\n")
    scripts = fw / "scripts"
    scripts.mkdir()
    (scripts / "fw_version.py").write_text("Import('env')\n")
    (scripts / "fw_version.ini").write_text(
        "; comments are not vetted: a password is mentioned here\n"
        "[esp32_base]\nextra_scripts = pre:scripts/fw_version.py\n")
    (scripts / "ota.ini").write_text(
        "[env:node_esp32]\nupload_protocol = espota\nupload_flags = --auth=hunter2\n")
    (scripts / "wifi.ini").write_text(
        "[esp32_base]\nbuild_flags = -DWIFI_PASSWORD=\\\"hunter2\\\"\n")
    (scripts / "my_local.ini").write_text("[esp32_base]\nboard = esp32dev\n")
    (scripts / "leak.py").write_text("TOKEN = 'x'\n")
    (scripts / "tools.ini").write_text(
        "[esp32_base]\nextra_scripts = post:scripts/leak.py\nupload_port = 10.0.0.9\n")
    (scripts / "broken.ini").write_text("not an ini [[[\n")
    (fw / "platformio.ini").write_text(
        "[platformio]\nextra_configs = scripts/*.ini\n"
        "[esp32_base]\nboard = esp32dev\n"
        "[env:node_esp32]\nextends = esp32_base\nbuild_src_filter = +<node/>\n")
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", fw)

    names = set(_bundle(api, "node").namelist()) | set(_bundle(api, "full").namelist())
    assert {"firmware/scripts/fw_version.ini", "firmware/scripts/fw_version.py"} <= names
    for private in ("ota.ini", "wifi.ini", "my_local.ini", "tools.ini", "leak.py", "broken.ini"):
        assert f"firmware/scripts/{private}" not in names, private
        assert api.get(f"/api/builder/firmware/scripts/{private}").status_code in (400, 404), private
    assert api.get("/api/builder/firmware/scripts/fw_version.ini").status_code == 200


def test_bundle_never_follows_a_reference_outside_the_firmware_dir(tmp_path, monkeypatch, api):
    fw = tmp_path / "firmware"
    (fw / "src" / "node").mkdir(parents=True)
    (fw / "src" / "node" / "main.cpp").write_text("int main(){}\n")
    (tmp_path / "secret.py").write_text("TOKEN = 'x'\n")
    (fw / "platformio.ini").write_text("[env:node_esp32]\nextra_scripts = ../secret.py\n")
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", fw)
    names = _bundle(api, "node").namelist()
    assert not any("secret" in n for n in names)


def test_per_file_endpoint_serves_manifests_and_partition_tables(repo_firmware, api):
    for path in ("lib/sp_core/library.json", "partitions.csv", "partitions_8mb.csv", "VERSION.txt"):
        r = api.get(f"/api/builder/firmware/{path}")
        assert r.status_code == 200, (path, r.text)
    assert api.get("/api/builder/firmware/test/fixtures/signing_vectors.json").status_code in (400, 404)
    assert api.get("/api/builder/firmware/lib/sp_testing/library.json").status_code == 404
