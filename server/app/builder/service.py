import configparser
import json
import logging
import re
import time
from pathlib import Path

import anthropic

from ..config import settings
from ..db import get_db
from ..vision.service import claude_response_text, claude_stop_reason

log = logging.getLogger(__name__)

# A 9-section guide with firmware + OpenSCAD code, plus the model's thinking,
# overran the old 4096 cap. This is above the SDK's non-streaming ceiling, so
# the request is streamed.
_GUIDE_MAX_TOKENS = 32_000

# The firmware tree (docker-compose mounts it read-only at /firmware).
_FIRMWARE_DIR = (Path("/firmware") if Path("/firmware").exists()
                 else Path(__file__).resolve().parents[3] / "firmware")

# PlatformIO envs per firmware image, used when platformio.ini can't be read.
_DEFAULT_IMAGE_ENVS = {"node": ["node_esp32", "node_esp32s3"], "cam": ["cam"]}


# ─── platformio.ini ──────────────────────────────────────────────────────


def _read_platformio_ini(ini: Path) -> configparser.ConfigParser | None:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        if not cp.read(ini, encoding="utf-8"):
            return None
    except (configparser.Error, OSError, UnicodeDecodeError) as e:
        log.warning("Cannot parse %s: %s", ini, e)
        return None
    return cp


def _ini_tokens(value: str) -> list[str]:
    """Whitespace/comma separated values, minus ${...} interpolations."""
    return [t for t in re.split(r"[\s,]+", value) if t and "${" not in t]


# An `extra_configs` ini is published (zipped into the Builder bundles, served
# by the per-file endpoint) only when it reads as shared build config. A local
# override ini is a common PlatformIO pattern for an OTA --auth password in
# upload_flags, an upload_port, or WiFi / MQTT credentials in build_flags, and
# the firmware dir is mounted into the server as-is. Such a file isn't needed
# for a bundle to build: its glob then matches nothing.
_PRIVATE_CONFIG_NAME = re.compile(
    r"secret|private|local|override|credential|passw|token|auth|user", re.I)
_PRIVATE_CONFIG_KEYS = frozenset({"upload_flags", "upload_port", "upload_command",
                                  "monitor_port", "test_port"})
_SECRET_TEXT = re.compile(r"passw|secret|token|api[_-]?key|psk|--auth|\bauth\b", re.I)


def _is_private_config(ini: Path) -> bool:
    """True when an extra_configs ini may carry operator secrets or local
    settings: a telling file name, an upload / port option, a credential-like
    key or value (comments are not read), or content that can't be parsed and
    so can't be vetted."""
    if _PRIVATE_CONFIG_NAME.search(ini.stem):
        return True
    cp = _read_platformio_ini(ini)
    if cp is None:
        return True
    for section in cp.sections():
        for key, value in cp.items(section):
            if (key in _PRIVATE_CONFIG_KEYS or _SECRET_TEXT.search(key)
                    or _SECRET_TEXT.search(value or "")):
                return True
    return False


def platformio_references(ini: Path, *, project: Path | None = None,
                          _seen: set[Path] | None = None) -> tuple[set[str], set[str]]:
    """(files, directories) platformio.ini names, relative to its project dir.

    Files: partition tables, extra_scripts (pre:/post: stripped), embedded
    files, and the configs `[platformio] extra_configs` globs pull in — which
    are parsed for the same references (the firmware attaches its version
    pre-script through scripts/*.ini) — except one that may hold secrets or
    local settings (_is_private_config), which is neither returned nor
    followed. Directories: -I include dirs in
    build_flags and lib_extra_dirs. Source dirs selected by build_src_filter
    are the caller's business (each bundle carries its own image). Paths are
    returned as written; callers must keep them inside the project.
    """
    project = ini.parent if project is None else project
    seen = set() if _seen is None else _seen
    seen.add(ini.resolve())
    cp = _read_platformio_ini(ini)
    files: set[str] = set()
    dirs: set[str] = set()
    if cp is None:
        return files, dirs
    for section in cp.sections():
        for key, value in cp.items(section):
            tokens = _ini_tokens(value)
            if key in ("board_build.partitions", "board_build.embed_files",
                       "board_build.embed_txtfiles"):
                files.update(tokens)
            elif key == "extra_scripts":
                files.update(re.sub(r"^(pre|post):", "", t) for t in tokens)
            elif key == "build_flags":
                dirs.update(re.findall(r"-I\s*([^\s-]\S*)", " ".join(tokens)))
            elif key == "lib_extra_dirs":
                dirs.update(tokens)
            elif key == "extra_configs":
                for pattern in tokens:
                    try:
                        matches = sorted(project.glob(pattern))
                    except (ValueError, NotImplementedError):  # absolute pattern
                        continue
                    for match in matches:
                        if not match.is_file() or _is_private_config(match):
                            continue
                        try:
                            rel = match.relative_to(project).as_posix()
                        except ValueError:
                            continue
                        files.add(rel)
                        if match.resolve() not in seen:
                            more_files, more_dirs = platformio_references(
                                match, project=project, _seen=seen)
                            files |= more_files
                            dirs |= more_dirs
    return files, dirs


def _ini_option(cp: configparser.ConfigParser, section: str, key: str, _depth: int = 0) -> str | None:
    """`key` from `section`, following PlatformIO `extends` (a few levels)."""
    if not cp.has_section(section) or _depth > 8:
        return None
    if cp.has_option(section, key):
        return cp.get(section, key)
    for parent in _ini_tokens(cp.get(section, "extends", fallback="")):
        value = _ini_option(cp, parent, key, _depth + 1)
        if value is not None:
            return value
    return None


def platformio_image_envs(ini: Path) -> dict[str, list[str]]:
    """{"node": [env, ...], "cam": [env, ...]} from each env's build_src_filter."""
    cp = _read_platformio_ini(ini)
    if cp is None:
        return {k: list(v) for k, v in _DEFAULT_IMAGE_ENVS.items()}
    envs: dict[str, list[str]] = {"node": [], "cam": []}
    for section in cp.sections():
        if not section.startswith("env:"):
            continue
        src_filter = _ini_option(cp, section, "build_src_filter") or ""
        for image in re.findall(r"\+<([^>/]+)/?>", src_filter):
            if image in envs:
                envs[image].append(section[len("env:"):])
    return {k: v or list(_DEFAULT_IMAGE_ENVS[k]) for k, v in envs.items()}


# ─── Builder's Assistant system context ──────────────────────────────────

# What the shipped firmware actually supports. Kept in step with
# firmware/boards/board_profile_*.h, sp_core/personality.h, sp_core/
# scene_table.h and config/mosquitto/acl.conf by
# tests/test_cross_cluster_builder.py. A guide built on the wrong camera, a
# reserved GPIO or a topic the broker ACL denies cannot work.
_HARDWARE_CONTRACT = """## Firmware Images and Boards (PlatformIO envs)
- Unified node — one image for every sensor/actuator node: {node_envs}. ESP32-WROOM-32 DevKit is the canonical board; ESP32-S3-DevKitC-1 builds are bench-verification pending. The channel-bank personality is chosen in the setup portal:
  - climate: sensors only, no channels
  - relay: 4 switch channels fae, exhaust, circulation, aux (25 kHz PWM, pwm 0-255; aux drives the misting pump and cuts off after 60 s unless cmd/config max_on_sec raises it)
  - lighting: 4 dim channels white, blue, red, far_red (10-bit level 0-1023) plus scenes colonization_dark, pinning_daylight, fruiting_standard, cordyceps_blue, lions_mane_gentle
- Sensors autodetected on the I2C bus at boot: SHT3x/SHT4x temp+RH (0x44/0x45), SCD4x CO2 (0x62) or SCD30 (0x61), BH1750 lux (0x23/0x5C). Optional peripherals, enabled in the setup portal or by cmd/config {{"peripherals": {{"mhz19": bool, "hx711": bool, "reed": bool}}}}: MH-Z19C CO2 (UART), HX711 load-cell scale, door reed switch.
- Camera node — env {cam_envs}: AI-Thinker ESP32-CAM ONLY. Its image sensor is auto-detected at boot: OV2640, OV3660 (what the current BOM 2-pack ships) or OV5640. ESP32-S3 camera boards (ESP32-S3-CAM, Freenove, XIAO ESP32S3 Sense, Waveshare) are NOT supported by the shipped firmware — never recommend one; a second camera is another AI-Thinker ESP32-CAM.

## Reserved GPIOs — never assign these to new hardware
ESP32-WROOM-32 node (node_esp32):
- I2C sensor bus SDA 21, SCL 22 (add new I2C sensors on this bus at a free address)
- Channel-bank MOSFET gates 25, 26, 27, 14
- HX711 load cell DOUT 32, SCK 33
- Door reed switch 35 (input-only, external pull-up)
- MH-Z19C CO2 on UART2 RX 16, TX 17
- BOOT / factory reset 0
- Also off-limits: 6-11 (SPI flash); strapping pins 2, 5, 12, 15 need care; 34-39 are input-only with no pull-ups
- Usually free: 4, 13, 18, 19, 23 (and 34, 36, 39 as inputs)
ESP32-S3-DevKitC-1 node (node_esp32s3 and variants): SDA 8, SCL 9; channels 4, 5, 6, 7; HX711 10/11; reed 12; MH-Z19C RX 16 / TX 17; BOOT 0. Avoid 0, 3, 45, 46 (strapping), 19, 20 (USB), 26-37 (flash/PSRAM), 38 (RGB LED). All 8 LEDC channels are taken by the two banks.
AI-Thinker ESP32-CAM (cam): every camera pin is in use (0, 5, 18, 19, 21, 22, 23, 25, 26, 27, 32, 34, 35, 36, 39), the flash LED 4 and factory reset 13 — there are no spare GPIOs; put new sensors and actuators on a node.

## MQTT Contract (topics under sporeprint/{{node_id}}/)
Node → Pi. The broker ACL (config/mosquitto/acl.conf) lets a node publish ONLY these, under its own id — anything else is silently dropped:
- `telemetry` — JSON {{ts, temp_f, temp_c, humidity, co2_ppm, lux, dew_point_f, weight_g, door_open, ...}}; ts is Unix epoch seconds once NTP-synced (uptime seconds before); frames flushed from the offline buffer carry "replay": true
- `telemetry/{{channel}}` — one channel's switch state {{channel, state, pwm, trigger}}
- `status` — retained online/offline (also the LWT); `status/heartbeat` — {{uptime_sec, free_heap, firmware_version, wifi_rssi, ...}}
- `health` — per-component health; the only place a node lists its channel names
- `alert` — {{type, value, message, sensor}}
- `ota` — OTA lifecycle events
- `logs` — forwarded log batches (write-only)
- `coredump/chunk` — panic-dump upload (write-only)
Pi → node (the node subscribes cmd/#, matches the suffix exactly, and verifies the HMAC signature once provisioned with a key):
- `cmd/{{channel}}` — {{state: "on"|"off", pwm, level, duration_sec, ramp_sec}}; "off" always wins, and the Pi never sends pwm/level with "off"
- `cmd/scene` — {{scene: <name>}} (lighting personality only)
- `cmd/config` — {{read_interval_ms, publish_interval_ms, calibrate_co2, tare, calibrate_scale, max_on_sec: {{<channel>: seconds}}, peripherals: {{...}}}}
- Camera: {{capture: true, flash: bool}} takes a frame now; {{server_url: ...}} sets the upload URL. Frames are HTTP POSTed as raw JPEG to /api/vision/frame with X-Node-Id, X-Timestamp (only when NTP-synced) and X-Camera-Sensor.
A new node topic needs BOTH a `pattern write sporeprint/%u/<topic>` line in config/mosquitto/acl.conf AND a handler branch in server/app/mqtt.py; prefer adding keys to the telemetry JSON (older servers ignore unknown keys). Shelly/Tasmota smart plugs stay on their own shellies/# and tasmota/# trees.
"""


def _hardware_contract() -> str:
    envs = platformio_image_envs(_FIRMWARE_DIR / "platformio.ini")
    return _HARDWARE_CONTRACT.format(
        node_envs=", ".join(f"`{e}`" for e in envs["node"]),
        cam_envs=", ".join(f"`{e}`" for e in envs["cam"]),
    )


def _node_line(n: dict) -> str:
    line = (f"- **{n['node_id']}** ({n['node_type']}) — {n.get('status') or '?'}, "
            f"FW {n.get('firmware_version') or '?'}, IP {n.get('ip_address') or '?'}")
    try:
        config = json.loads(n.get("config") or "{}")
    except (TypeError, ValueError):
        config = {}
    sensor = config.get("camera_sensor") if isinstance(config, dict) else None
    if isinstance(sensor, str) and sensor:
        line += f", camera sensor {sensor.upper()}"
    return line


async def _build_system_context() -> str:
    """Build a context doc of current system state for the Builder's Assistant."""
    context_parts = ["# SporePrint System State\n"]

    # Registered hardware nodes
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes ORDER BY node_id")
        nodes = [dict(r) for r in await cursor.fetchall()]
        if nodes:
            context_parts.append("## Registered Hardware Nodes")
            context_parts.extend(_node_line(n) for n in nodes)
            context_parts.append("")

        # Smart plugs
        cursor = await db.execute("SELECT * FROM smart_plugs ORDER BY plug_id")
        plugs = [dict(r) for r in await cursor.fetchall()]
        if plugs:
            context_parts.append("## Smart Plugs")
            for p in plugs:
                context_parts.append(
                    f"- **{p['plug_id']}** ({p['plug_type']}) — {p.get('device_role') or 'unknown role'}, "
                    f"MQTT: {p['mqtt_topic_prefix']}"
                )
            context_parts.append("")

    context_parts.append(_hardware_contract())
    context_parts.append("""## Available Power Supply Voltages
- 5V (USB/buck converter)
- 12V (LED strips, fans, solenoids)
- 3.3V (ESP32 logic)

## Operator Equipment
- Bambu Lab H2D 3D printer (OpenSCAD parametric designs)
- Flow hood, agar work capability
- IRLZ44N MOSFETs in stock
- Noctua fans, peristaltic pumps available
""")

    return "\n".join(context_parts)


def _guide_error(code: str, message: str, **extra) -> dict:
    """An error result. `code` lets the router pick the HTTP status:
    not_configured → 503; refusal / truncated / empty / upstream_error → 502."""
    return {"error": message, "code": code, **extra}


async def generate_guide(request: str, constraints: str = "") -> dict:
    """Generate a detailed hardware integration guide using Claude."""
    if not settings.claude_api_key:
        return _guide_error("not_configured", "Claude API key not configured")

    system_context = await _build_system_context()

    system_prompt = f"""You are the SporePrint Builder's Assistant — an expert embedded systems engineer
and mycologist helping the operator add new hardware to their automated mushroom grow closet.

{system_context}

When the operator describes what they want to add, generate a DETAILED implementation guide
with these sections (use markdown headers):

## 1. Parts List
Specific components, model numbers, approximate cost. Be specific about ratings.

## 2. Wiring Diagram
ASCII diagram showing ESP32 GPIO connections, voltage levels, required passive components
(resistors, capacitors, flyback diodes for solenoids, etc.). Use only GPIOs the reserved list
above leaves free.

## 3. Firmware Changes
Complete PlatformIO code snippets: sensor driver initialization, MQTT topics, command handler,
NVS configuration keys. Match existing code style from the sp_core/sp_device libraries.

## 4. MQTT Integration
New topics, payload formats, QoS levels. Follow the MQTT contract above, including the ACL
and server/app/mqtt.py changes any new topic needs.

## 5. Backend Integration
New telemetry parser additions, API endpoints if needed, automation rule templates.

## 6. 3D-Printable Mount
OpenSCAD parametric design for Bambu Lab printer. Include mounting holes and dimensions
for the specific components.

## 7. Automation Rules
Pre-built YAML-style rule templates using the new hardware.

## 8. Safety Notes
Current ratings, thermal limits, waterproofing needs, failsafes required.

## 9. Test Procedure
Step-by-step verification checklist.

Be thorough, practical, and specific. The operator is experienced with ESP32 and electronics."""

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

        user_msg = f"Request: {request}"
        if constraints:
            user_msg += f"\n\nConstraints: {constraints}"

        async with client.messages.stream(
            model=settings.claude_model,
            max_tokens=_GUIDE_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            message = await stream.get_final_message()

        stop_reason = claude_stop_reason(message)
        if stop_reason == "refusal":
            return _guide_error("refusal", "Claude declined to generate this guide (refusal)")
        guide_text = claude_response_text(message)
        if stop_reason == "max_tokens":
            # A guide cut off mid-section must not be saved as if complete.
            log.warning("Builder guide truncated at max_tokens; not saved")
            return _guide_error(
                "truncated",
                "The guide was cut off at the output limit and was not saved. "
                "Try narrowing the request.",
                truncated=True,
                request=request,
                constraints=constraints,
                guide=guide_text,
            )
        if not guide_text.strip():
            return _guide_error("empty", "Claude returned an empty guide")

        # Save guide
        guide_id = await _save_guide(request, constraints, guide_text)

        return {
            "guide_id": guide_id,
            "request": request,
            "constraints": constraints,
            "guide": guide_text,
            "generated_at": time.time(),
        }

    except Exception as e:
        log.error("Builder guide generation failed: %s", e)
        return _guide_error("upstream_error", str(e))


async def _save_guide(request: str, constraints: str, guide: str) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO builder_guides (request, constraints, guide, created_at) VALUES (?, ?, ?, ?)",
            (request, constraints, guide, time.time()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_guides() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, request, constraints, created_at FROM builder_guides ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def get_guide(guide_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM builder_guides WHERE id = ?", (guide_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
