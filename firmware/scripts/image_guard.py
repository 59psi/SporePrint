"""PlatformIO post-script: check every image against what the field fleet can
take over the air.

OTA rewrites one app slot and nothing else: it can never change a node's
partition table or its bootloader. So, on every build (`pio run`, firmware CI,
the release workflow, a Builder ZIP), after firmware.bin is written:

1. The partition table is the fleet's. Each shipped partitions*.csv is pinned
   below (name, type, subtype, offset, size, flags — comments may change, the
   layout may not). A board added later gets its own table, pinned here when
   it ships. Changing a pinned layout would build images that a field node's
   real table does not match.
2. firmware.bin fits the SMALLEST app slot with at least MIN_HEADROOM bytes
   to spare (an OTA writes whichever slot is idle, so every slot must take the
   image). The platform's own size check only compares against ota_0, with no
   margin.
3. No ESP-Matter object is linked. The arduino-esp32 3.x prebuilt libraries
   include Matter archives that also define std::string members; a
   translation unit compiled below C++20 (where libstdc++ declares those
   members `extern template`) gets them resolved from the Matter archive,
   which drags ~300 KB of Matter — static constructors included — into the
   image. The firmware therefore builds at the framework's own dialect; this
   check keeps it that way.
4. An env with `custom_camera_owns_ledc = yes` (the cam image) links no
   Arduino LEDC attach. The camera driver generates XCLK on LEDC timer 0 /
   channel 0 through ESP-IDF directly; the core's ledcAttach() /
   analogWrite() allocate channels and timers from the Arduino HAL's own
   bookkeeping, which does not know about the camera's, and would hand out
   that same channel 0 / timer 0. (The node image binds its four channels
   with ledcAttachChannel and has no camera.)

A failure stops the build (exit 1) with the reason; a pass prints one line.
"""

import os
import re

Import("env")  # noqa: F821 — SCons global injected by PlatformIO

# (name, type, subtype, offset, size, flags) per shipped table.
FLEET_TABLES = {
    # 4 MB — node_esp32 + cam (WROOM-32 / ESP32-CAM fleets, since v1).
    "partitions.csv": [
        ("nvs", "data", "nvs", 0x9000, 0x5000, ""),
        ("otadata", "data", "ota", 0xE000, 0x2000, ""),
        ("app0", "app", "ota_0", 0x10000, 0x180000, ""),
        ("app1", "app", "ota_1", 0x190000, 0x180000, ""),
        ("spiffs", "data", "spiffs", 0x310000, 0xE0000, ""),
        ("coredump", "data", "coredump", 0x3F0000, 0x10000, ""),
    ],
    # 8 MB — node_esp32s3 (S3 N8 / N8R8 / N16R8) and the ESP32-S3 camera
    # envs (cam_esp32s3, cam_xiao_esp32s3, cam_waveshare_s3).
    "partitions_8mb.csv": [
        ("nvs", "data", "nvs", 0x9000, 0x5000, ""),
        ("otadata", "data", "ota", 0xE000, 0x2000, ""),
        ("app0", "app", "ota_0", 0x10000, 0x300000, ""),
        ("app1", "app", "ota_1", 0x310000, 0x300000, ""),
        ("spiffs", "data", "spiffs", 0x610000, 0x1D0000, ""),
        ("coredump", "data", "coredump", 0x7E0000, 0x20000, ""),
    ],
    # 32 MB octal — node_esp32s3_n32r16v (everything in the low 16 MB).
    "partitions_32mb.csv": [
        ("nvs", "data", "nvs", 0x9000, 0x5000, ""),
        ("otadata", "data", "ota", 0xE000, 0x2000, ""),
        ("app0", "app", "ota_0", 0x10000, 0x400000, ""),
        ("app1", "app", "ota_1", 0x410000, 0x400000, ""),
        ("spiffs", "data", "spiffs", 0x810000, 0x7D0000, ""),
        ("coredump", "data", "coredump", 0xFE0000, 0x20000, ""),
    ],
}

# Spare room every image must leave in its app slot.
MIN_HEADROOM = 64 * 1024

_MATTER_MEMBER = re.compile(r"libespressif__esp_matter\.a\(([^)]+)\)")
# A linked (kept) function's symbol line in the memory-map part of the map.
_LEDC_ATTACH = re.compile(r"^\s+0x[0-9a-f]+\s+(ledcAttach(?:Channel)?)\s*$", re.M)


def _size(text):
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if text[-1:].upper() in ("K", "M"):
        return int(text[:-1]) * (1024 if text[-1].upper() == "K" else 1024 * 1024)
    return int(text)


def _read_table(path):
    rows = []
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = [t.strip() for t in line.split(",")]
            while len(tokens) < 6:
                tokens.append("")
            name, ptype, subtype, offset, size, flags = tokens[:6]
            rows.append((name, ptype, subtype, _size(offset), _size(size), flags))
    return rows


def _fmt(rows):
    return "\n".join(
        "    %-9s %-5s %-9s 0x%06X 0x%06X %s" % r for r in rows)


def _fail(message):
    print("SporePrint image guard: FAILED — " + message)
    env.Exit(1)  # noqa: F821


def _check(target, source, env):  # noqa: ARG001 — SCons action signature
    name = env.subst("$PIOENV")
    csv = env.subst("$PARTITIONS_TABLE_CSV")
    table_name = os.path.basename(csv)

    pinned = FLEET_TABLES.get(table_name)
    if pinned is None:
        _fail("%s uses %s, which is not a pinned fleet table — add its layout "
              "to scripts/image_guard.py FLEET_TABLES when the board ships"
              % (name, table_name))
        return
    rows = _read_table(csv)
    if rows != pinned:
        _fail("%s does not match the fleet layout pinned in "
              "scripts/image_guard.py. OTA cannot repartition a field node.\n"
              "  pinned:\n%s\n  found:\n%s" % (table_name, _fmt(pinned), _fmt(rows)))
        return

    slots = [size for (_n, ptype, sub, _o, size, _f) in rows
             if ptype == "app" and (sub.startswith("ota_") or sub == "factory")]
    slot = min(slots)
    image = os.path.getsize(env.subst("$BUILD_DIR/${PROGNAME}.bin"))
    headroom = slot - image
    if headroom < MIN_HEADROOM:
        _fail("%s firmware.bin is %d bytes; the %s app slot is %d bytes "
              "(headroom %d, need >= %d). Shrink the image — the partition "
              "table cannot change for a fleet."
              % (name, image, table_name, slot, headroom, MIN_HEADROOM))
        return

    map_path = env.subst("$BUILD_DIR/${PROGNAME}.map")
    linked = "no map file"
    if os.path.isfile(map_path):
        with open(map_path, encoding="utf-8", errors="replace") as fp:
            text = fp.read()
        members = sorted(set(_MATTER_MEMBER.findall(text)))
        if members:
            _fail("%s links %d ESP-Matter object(s) (%s ...). A source built "
                  "below the framework's C++ dialect pulls them in — see "
                  "scripts/image_guard.py." % (name, len(members),
                                               ", ".join(members[:3])))
            return
        linked = "no Matter objects"
        camera_ledc = env.GetProjectOption("custom_camera_owns_ledc", "no")
        if camera_ledc.strip().lower() in ("yes", "true", "1"):
            memory_map = text[text.find("Linker script and memory map"):]
            attach = sorted(set(_LEDC_ATTACH.findall(memory_map)))
            if attach:
                _fail("%s links %s, but the camera owns LEDC timer 0 / "
                      "channel 0 for XCLK — the Arduino LEDC HAL would hand "
                      "the same channel out (see scripts/image_guard.py)."
                      % (name, ", ".join(attach)))
                return
            linked += ", no Arduino LEDC attach (camera XCLK)"

    print("SporePrint image guard: %s %d B in a %d B app slot (%.1f%%, "
          "headroom %d B); %s = fleet layout; %s"
          % (name, image, slot, 100.0 * image / slot, headroom, table_name,
             linked))


env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", _check)  # noqa: F821
