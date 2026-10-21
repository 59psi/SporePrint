"""Builder cross-cluster behaviour.

- the Builder's Assistant system
  context names the camera the firmware actually drives (AI-Thinker ESP32-CAM,
  OV2640/OV3660/OV5640), says S3 camera boards are unsupported, lists every
  reserved GPIO and the complete MQTT contract including the broker ACL;
- POST /api/builder/guide maps generate_guide errors to
  503 (not configured) / 502 (upstream), keeping the body fields;
- firmware ZIP bundles carry library.json manifests and every file
  platformio.ini references, and tell the builder how to set the version.
"""

import asyncio
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
    # The S3 camera boards earlier BOMs listed have envs of their own, but
    # the assistant must never send anyone out to buy one.
    assert re.search(r"ESP32-S3 camera boards[^\n]*never recommend buying one", ctx)
    assert "`cam`" in ctx
    for env in ("cam_esp32s3", "cam_xiao_esp32s3", "cam_waveshare_s3"):
        assert f"`{env}`" in ctx, env


def _board_pins(name: str) -> dict[str, str]:
    text = (_REPO_FIRMWARE / "boards" / name).read_text()
    return dict(re.findall(r"#define (SP_\w+) (\S.*?)\s*(?://.*)?$", text, re.M))


async def test_context_matches_the_board_profiles():
    """Every GPIO a board profile reserves is in the context, as the pin
    maps define it: a guide must never wire onto one."""
    ctx = await builder_service._build_system_context()
    dev = _board_pins("board_profile_esp32dev.h")
    for pins in (f"SDA {dev['SP_PIN_I2C_SDA']}", f"SCL {dev['SP_PIN_I2C_SCL']}",
                 dev["SP_CHANNEL_PINS"].strip("{}"),
                 f"DOUT {dev['SP_PIN_HX711_DOUT']}", f"SCK {dev['SP_PIN_HX711_SCK']}",
                 f"reed switch {dev['SP_PIN_REED']}",
                 f"RX {dev['SP_UART_CO2_RX']}", f"TX {dev['SP_UART_CO2_TX']}",
                 f"BOOT / factory reset {dev['SP_PIN_FACTORY_RESET']}"):
        assert pins in ctx, pins
    # The S3 node's own map.
    s3 = _board_pins("board_profile_esp32s3.h")
    for pins in (f"SDA {s3['SP_PIN_I2C_SDA']}", f"SCL {s3['SP_PIN_I2C_SCL']}",
                 s3["SP_CHANNEL_PINS"].strip("{}"),
                 f"HX711 {s3['SP_PIN_HX711_DOUT']}/{s3['SP_PIN_HX711_SCK']}",
                 f"reed {s3['SP_PIN_REED']}"):
        assert pins in ctx, pins
    # The camera board's pins, none spare.
    cam = _board_pins("board_profile_esp32cam.h")
    assert f"factory reset {cam['SP_PIN_FACTORY_RESET']}" in ctx
    assert f"flash LED {cam['SP_PIN_FLASH']}" in ctx
    s3cam = _board_pins("board_profile_esp32s3cam.h")
    assert s3cam["SP_PIN_FLASH"] == "-1", "the context says the S3 camera boards have no flash LED"
    assert f"BOOT {s3cam['SP_PIN_FACTORY_RESET']} is the reset button" in ctx


def _context_line(ctx: str, start: str) -> str:
    return next(line for line in ctx.splitlines() if line.startswith(start))


async def test_s3_avoid_list_names_every_pin_the_board_profile_avoids():
    """The S3 line left out GPIO 47/48 (1.8 V I/O on the N32R16V) and the
    UART0 console pins 43/44, and gave no free-pin list, so a guide could
    wire a 3.3 V signal into a 1.8 V pad or onto the Serial log."""
    ctx = await builder_service._build_system_context()
    s3_line = _context_line(ctx, "ESP32-S3-DevKitC-1 node")
    profile = (_REPO_FIRMWARE / "boards" / "board_profile_esp32s3.h").read_text()
    comment = " ".join(line.lstrip("/ ").strip() for line in profile.splitlines()
                       if line.startswith("//"))
    avoided = comment.split("Pin choices avoid:", 1)[1].split("SDA/SCL match", 1)[0]
    # Numbers that are no GPIO: a voltage ("1.8 V"), part and revision names
    # ("N32R16V", "WROOM-2", "v1.1").
    avoided = re.sub(r"\d+(?:\.\d+)?\s*V\b", "", avoided)
    avoided = re.sub(r"\b[A-Za-z][\w.]*\d[\w.]*|[A-Za-z]+-\d+", "", avoided)
    for lo, hi in re.findall(r"(\d+)\s*[–-]\s*(\d+)", avoided):
        assert f"{lo}-{hi}" in s3_line, (lo, hi)
    singles = re.sub(r"(\d+)\s*[–-]\s*(\d+)", "", avoided)
    pins = re.findall(r"\d+", singles)
    assert {"47", "48", "38", "0", "3", "45", "46", "19", "20"} <= set(pins), pins
    avoid_part = s3_line.split("Avoid", 1)[1].split("Usually free", 1)[0]
    for pin in pins:
        assert re.search(rf"\b{pin}\b", avoid_part), f"S3 avoid list misses GPIO {pin}"
    assert "43, 44 (UART0" in avoid_part
    # Nothing the board uses or avoids is offered as free.
    free = {int(p) for p in re.findall(r"\d+", s3_line.split("Usually free:", 1)[1].split("(", 1)[0])}
    used = {int(_board_pins("board_profile_esp32s3.h")[k]) for k in (
        "SP_PIN_I2C_SDA", "SP_PIN_I2C_SCL", "SP_PIN_HX711_DOUT", "SP_PIN_HX711_SCK",
        "SP_PIN_REED", "SP_UART_CO2_RX", "SP_UART_CO2_TX", "SP_PIN_FACTORY_RESET")}
    used |= {int(p) for p in _board_pins("board_profile_esp32s3.h")["SP_CHANNEL_PINS"].strip("{}").split(",")}
    avoided_pins = {int(p) for p in pins} | set(range(26, 38)) | {43, 44}
    assert free and not free & (used | avoided_pins), free & (used | avoided_pins)


async def test_s3_ledc_sentence_matches_the_board_profile():
    """The contract described two banks taking all 8 LEDC channels; the node
    attaches one 4-channel bank on channels 0-3."""
    ctx = await builder_service._build_system_context()
    s3_line = _context_line(ctx, "ESP32-S3-DevKitC-1 node")
    assert "two banks" not in ctx
    assert "LEDC channels 0-3" in s3_line and "nothing else may claim LEDC" in s3_line
    profile = (_REPO_FIRMWARE / "boards" / "board_profile_esp32s3.h").read_text()
    assert "the bank takes channels 0-3" in profile
    assert _board_pins("board_profile_esp32s3.h")["SP_CHANNEL_COUNT"] == "4"


async def test_wroom_free_pins_say_which_can_read_analog():
    """GPIO 4 and 13 are ADC2, which reads nothing while WiFi runs: an analog
    probe belongs on 34/36/39 (ADC1)."""
    ctx = await builder_service._build_system_context()
    free = _context_line(ctx, "- Usually free:")
    assert "4 and 13 are ADC2" in free
    assert re.search(r"34, 36, 39 as inputs \(ADC1: use these for analog sensors\)", free)


def test_default_image_envs_match_the_shipped_platformio_ini():
    """The fallback for an unreadable platformio.ini listed 3 of the 7 envs."""
    assert builder_service.platformio_image_envs(_REPO_FIRMWARE / "platformio.ini") \
        == builder_service._DEFAULT_IMAGE_ENVS


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


def test_a_good_guide_is_200_and_saved_for_reading_back(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "k")
    _install(monkeypatch, SimpleNamespace(content=[TextBlock(type="text", text="## 1. Parts\nok")],
                                          stop_reason="end_turn"))
    r = client.post("/api/builder/guide", json={"request": "add a pump", "constraints": "12V"})
    assert r.status_code == 200, r.text
    guide_id = r.json()["guide_id"]
    assert isinstance(guide_id, int)
    listed = client.get("/api/builder/guides").json()
    assert [(g["id"], g["request"], g["constraints"]) for g in listed] == [(guide_id, "add a pump", "12V")]
    saved = client.get(f"/api/builder/guides/{guide_id}").json()
    assert saved["request"] == "add a pump" and "## 1. Parts" in saved["guide"]
    assert client.get(f"/api/builder/guides/{guide_id + 1}").status_code == 404


# ── firmware ZIP bundles ───────────────────────────────────────────────────


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(mr.router, prefix="/api/builder")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _fresh_firmware_listing(monkeypatch):
    """Each test lists its own firmware tree, never a cached one."""
    monkeypatch.setattr(builder_service, "_firmware_cache", {"data": [], "ts": 0})


@pytest.fixture
def repo_firmware(monkeypatch):
    assert _REPO_FIRMWARE.is_dir(), _REPO_FIRMWARE
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", _REPO_FIRMWARE)
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
def test_image_bundle_holds_every_file_its_build_needs(repo_firmware, api, node, image_dir):
    """Every file platformio.ini references, and every library's manifest."""
    names = set(_bundle(api, node).namelist())
    for lib in ("sp_core", "sp_drivers", "sp_device"):
        assert f"firmware/lib/{lib}/library.json" in names, lib
    files, dirs = _pio_references(repo_firmware / "platformio.ini")
    for f in files:
        assert f"firmware/{f}" in names, f
    for d in dirs:
        if d.startswith("src/") and image_dir and d != image_dir:
            continue  # the other image's sources — not this bundle's env
        assert any(n.startswith(f"firmware/{d}/") for n in names), d
    for must in ("platformio.ini", "VERSION.txt", "partitions.csv", "partitions_8mb.csv"):
        assert f"firmware/{must}" in names, must


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
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)
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
    assert builder_service.platformio_image_envs(tmp_path / "missing.ini") \
        == builder_service._DEFAULT_IMAGE_ENVS


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
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)
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
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)
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
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)

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
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)
    names = _bundle(api, "node").namelist()
    assert not any("secret" in n for n in names)


def test_per_file_endpoint_serves_manifests_and_partition_tables(repo_firmware, api):
    for path in ("lib/sp_core/library.json", "partitions.csv", "partitions_8mb.csv", "VERSION.txt"):
        r = api.get(f"/api/builder/firmware/{path}")
        assert r.status_code == 200, (path, r.text)
    assert api.get("/api/builder/firmware/test/fixtures/signing_vectors.json").status_code in (400, 404)
    assert api.get("/api/builder/firmware/lib/sp_testing/library.json").status_code == 404


# ── the root platformio.ini is screened like an extra_configs ini ──────────

_OTA_SECRET = "hunter2hunter2"
_WIFI_SECRET = "pa55-wifi"


def _firmware_with_private_ini(tmp_path) -> Path:
    fw = tmp_path / "firmware"
    (fw / "src" / "node").mkdir(parents=True)
    (fw / "src" / "node" / "main.cpp").write_text("int main(){}\n")
    (fw / "src" / "cam").mkdir(parents=True)
    (fw / "src" / "cam" / "main.cpp").write_text("int main(){}\n")
    (fw / "lib" / "sp_core").mkdir(parents=True)
    (fw / "lib" / "sp_core" / "core.h").write_text("#pragma once\n")
    (fw / "VERSION.txt").write_text("5.2.2\n")
    (fw / "platformio.ini").write_text(
        "[platformio]\ndefault_envs = node_esp32\n"
        "; a password is mentioned in this prose comment, which is kept\n"
        "[env:node_esp32]\n"
        "build_src_filter = +<node/>\n"
        "upload_protocol = espota\n"
        "upload_port = 192.168.1.50\n"
        f"upload_flags = --auth={_OTA_SECRET}\n"
        f";upload_flags = --auth={_OTA_SECRET}-old\n"
        "build_flags =\n"
        f"    -DWIFI_PASSWORD=\\\"{_WIFI_SECRET}\\\"\n"
        "    -DCORE_DEBUG_LEVEL=0\n"
        "monitor_speed = 115200\n"
        "[env:cam]\nbuild_src_filter = +<cam/>\n")
    return fw


def test_root_platformio_ini_never_publishes_upload_credentials(tmp_path, monkeypatch, api):
    """An espota password (or WiFi credentials) in the Pi checkout's
    platformio.ini was served by the per-file endpoint and zipped into every
    firmware bundle, though the same lines in an extra_configs ini are kept
    private."""
    fw = _firmware_with_private_ini(tmp_path)
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)

    served = api.get("/api/builder/firmware/platformio.ini")
    assert served.status_code == 200, served.text
    published = [served.text]
    for node in ("full", "node", "cam", "sp_core"):
        published.append(_bundle(api, node).read("firmware/platformio.ini").decode())
    for text in published:
        assert _OTA_SECRET not in text and _WIFI_SECRET not in text
        assert "192.168.1.50" not in text
        for key in ("upload_port", "upload_flags", "build_flags"):
            assert f"; {key}: withheld" in text, key
        # Everything else is the operator's file, as written.
        for kept in ("upload_protocol = espota", "monitor_speed = 115200",
                     "build_src_filter = +<node/>", "a password is mentioned in this prose"):
            assert kept in text, kept
    # Still a well-formed ini the bundle builds from.
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read_string(published[0])
    assert cp.get("env:node_esp32", "monitor_speed") == "115200"
    assert not cp.has_option("env:node_esp32", "upload_flags")
    # The listing reports the size of what is served.
    (ini_group,) = [g for g in api.get("/api/builder/firmware").json() if g["node"] == "platformio.ini"]
    ini_entry = next(f for f in ini_group["files"] if f["filename"] == "platformio.ini")
    assert ini_entry["size_bytes"] == len(served.content)


def test_the_shipped_platformio_ini_is_published_unchanged(repo_firmware, api):
    """The screen only withholds private options: the repo's own ini (whose
    comments mention secrets in prose) goes out byte for byte."""
    text = (repo_firmware / "platformio.ini").read_text(encoding="utf-8")
    assert builder_service.published_platformio_ini(text) == (text, [])
    r = api.get("/api/builder/firmware/platformio.ini")
    assert r.status_code == 200 and r.content == (repo_firmware / "platformio.ini").read_bytes()
    assert _bundle(api, "node").read("firmware/platformio.ini") == r.content


def test_ini_screen_follows_configparser_continuation_rules():
    text = ("[env:a]\n"
            "build_flags =\n"
            "    -DOK=1\n"
            "    ; -DAPI_KEY=abc (a commented-out flag)\n"
            "\n"
            "    -DMORE=2\n"
            "lib_deps = x\n"
            "# upload_port = /dev/ttyUSB0\n"
            "[env:b]\n"
            "  upload_command = scp $SOURCE pi:\n"
            "board = esp32dev\n"
            "[env:c]\n"
            "build_flags =\n"
            "    -DWIFI_PASSWORD=hunter2\n"
            "\n"
            "    -DKEEP_WITH_IT=0\n"
            "; trailing comment, kept\n"
            "monitor_speed = 9600\n")
    published, withheld = builder_service.published_platformio_ini(text)
    assert withheld == ["-dapi_key", "upload_port", "upload_command", "build_flags"]
    for gone in ("API_KEY", "ttyUSB0", "scp $SOURCE", "WIFI_PASSWORD", "-DKEEP_WITH_IT"):
        assert gone not in published, gone
    for kept in ("    -DOK=1\n", "    -DMORE=2\n", "lib_deps = x\n", "board = esp32dev\n",
                 "; trailing comment, kept\n", "monitor_speed = 9600\n"):
        assert kept in published, kept
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read_string(published)
    assert cp.get("env:a", "build_flags").split() == ["-DOK=1", "-DMORE=2"]
    assert cp.get("env:a", "lib_deps") == "x" and cp.get("env:b", "board") == "esp32dev"
    assert not cp.has_option("env:b", "upload_command")
    assert not cp.has_option("env:c", "build_flags") and cp.get("env:c", "monitor_speed") == "9600"


# ── a missing firmware tree is a 404, not a README-only ZIP ─────────────────


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_full_bundle_without_a_firmware_tree_is_404(tmp_path, monkeypatch, api, state):
    fw = tmp_path / "firmware"
    if state == "empty":
        fw.mkdir()
    monkeypatch.setattr(builder_service, "_FIRMWARE_DIR", fw)
    for node in ("full", "node", "cam", "sp_core"):
        assert api.get(f"/api/builder/firmware/bundle/{node}").status_code == 404, node
    assert api.get("/api/builder/firmware").json() == []


# ── bundles are built off the event loop ────────────────────────────────────


def test_zip_bundles_are_built_in_a_worker_thread(repo_firmware, api, monkeypatch):
    """A firmware or models ZIP is tens of ms of compression (more on a Pi):
    built on the event loop it stalled MQTT ingest and rule evaluation."""
    offloaded = []
    real_to_thread = asyncio.to_thread

    async def recording_to_thread(fn, *args, **kwargs):
        offloaded.append(fn)
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
    assert api.get("/api/builder/firmware/bundle/full").status_code == 200
    assert api.get("/api/builder/models-bundle.zip").status_code == 200
    assert builder_service.build_node_bundle in offloaded
    assert builder_service.build_models_bundle in offloaded
