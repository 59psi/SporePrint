# SporePrint firmware

PlatformIO monorepo for the ESP32 nodes: one unified node image, whose
channel-bank personality is chosen at provisioning and whose I²C sensors are
autodetected at boot, plus the camera image. Build environments, the pinned
platform and the reasons for each setting are documented inline in
[`platformio.ini`](platformio.ini). Board pin maps live in [`boards/`](boards/).

| Doc | What it covers |
|---|---|
| [`docs/drivers.md`](docs/drivers.md) | **Driver inventory**: every sensor, actuator and board the BOM recommends now or ever recommended → bus, driver file, autodetect, telemetry keys, native tests, status; the ESP32-S3 camera boards' pin maps and sources |
| [`test/README.md`](test/README.md) | The host-native test suites (`pio test -e native`) and what each one proves |
| [`CHANGELOG.md`](CHANGELOG.md) | Firmware release notes |
| [`../docs/firmware-security.md`](../docs/firmware-security.md) | Command signing, Secure MQTT, provisioning, OTA, signed manifests |

## Platform

- **Arduino-ESP32 core 3.3.12 on ESP-IDF 5.5.5**: the pioarduino platform
  release `55.03.312-1`, pinned by its immutable release URL in the
  `[esp32_base]` section (never the moving "stable" one). Core 2.0.17 /
  ESP-IDF 4.4 (`platformio/espressif32@6.13.0`) is end-of-life and no longer
  used.
- **PlatformIO Core 6.2.0 or newer, and git**, are required
  (`pip install -U platformio`). The first build downloads the platform and
  toolchains, about 1 GB.
- Libraries are pinned exactly: PubSubClient 2.8, ArduinoJson 7.4.3 (device
  envs and `native` alike).
- C++ dialect: the framework's own (C++20 with GNU extensions) for every
  source; the `native` env matches it with `-std=gnu++20`.
- PWM: 25 kHz, 10-bit LEDC on every relay and lighting channel
  (`ledcAttachChannel(pin, 25000, 10, i)`).

## Build

```bash
cd firmware
pio test -e native                    # host suites, no ESP32 needed
pio run -e node_esp32 -e node_esp32s3 -e node_esp32s3_n32r16v -e cam -e cam_esp32s3 -e cam_xiao_esp32s3 -e cam_waveshare_s3
pio run -t upload -e node_esp32       # flash one board over USB
```

| Env | Board | Image |
|---|---|---|
| `node_esp32` | ESP32-WROOM-32 38-pin DevKit (every wiring diagram) | unified node |
| `node_esp32s3` | ESP32-S3-DevKitC-1 N8 / N8R8 / N16R8 (own pin map) | unified node |
| `node_esp32s3_n32r16v` | ESP32-S3-DevKitC-1-N32R16V (octal flash + PSRAM; `node_esp32s3` does not boot on it) | unified node |
| `cam` | AI-Thinker ESP32-CAM (OV2640 / OV3660 / OV5640) | camera |
| `cam_esp32s3`, `cam_xiao_esp32s3`, `cam_waveshare_s3` | ESP32-S3 camera boards earlier BOMs listed | camera |
| `native` | host | Unity test suites |

Every device build runs two scripts from `scripts/` (attached through
`scripts/fw_version.ini`): `fw_version.py` defines the version (from
`SPOREPRINT_FW_VERSION`, else `VERSION.txt`, else `dev`) and the artifact
name, and compiles in the optional OTA verify key; `image_guard.py` fails the
build if a partition table differs from the fleet layout, if `firmware.bin`
leaves less than 64 KiB of its OTA slot, if any ESP-Matter code is linked, or
if a camera image links the Arduino LEDC allocator (the camera clock owns
LEDC timer 0 / channel 0). The Pi's Builder page serves the same tree as a
self-contained ZIP per image.

## Layout

- `lib/sp_core`: protocol and policy, no Arduino headers, host-tested
  (HMAC verification, channel runtime, offline buffer, boot / TLS policy, the
  espota OTA handshake, OTA manifests and gate, the coredump drain; vendored
  Monocypher in `vendor/`)
- `lib/sp_drivers`: sensor drivers over the injected HAL (`sp_hal/`), no
  Arduino headers, host-tested
- `lib/sp_device`: the Arduino / ESP-IDF layer (portal, MQTT, OTA service,
  TLS, bounded DNS, task watchdog, NVS, coredump uploader, log forwarding)
- `lib/sp_testing`: the mock HAL for the native suites
- `src/node`, `src/cam`: the two composition roots (`src/cam` also builds
  for the ESP32-S3 camera boards: envs `cam_esp32s3`, `cam_xiao_esp32s3`,
  `cam_waveshare_s3`)

Wiring, flashing and provisioning are in the
[hardware build guide](../docs/hardware-build-guide.md).

## OTA

- The Pi pushes images to a node (dashboard → Firmware, or
  `POST /api/hardware/nodes/{id}/ota`) over the espota protocol on port 3232.
  The node side is `lib/sp_device/ota_service.cpp`, which keeps core 2.x's
  MD5 handshake (`sp_core/espota.h`): core 3.x's own `ArduinoOTA` answers only
  a PBKDF2 handshake that Pis before 2026-10 do not speak (the current Pi's
  push answers both, by nonce length). OTA stays off until an OTA
  password of at least 12 characters is set in the setup portal.
- A new image is on probation until it has held MQTT for 60 s; a crash,
  watchdog reset or power loss before then boots the previous image.
- **Signed manifests (optional):** build with `SPOREPRINT_OTA_PUBKEY_B64`
  (base64 of the 32-byte Ed25519 release key the Pi pins) in the build
  environment and the image accepts `cmd/ota_manifest`, then flashes only
  the image that manifest names (its env, size and SHA-256, never older than
  the running image). `SPOREPRINT_OTA_REQUIRE_MANIFEST=1` additionally
  refuses unsigned pushes. Images built without the key (local builds,
  Builder ZIPs, this repo's own release workflow) ignore manifests. The
  firmware releases cut by the private release pipeline (2026-10 on) are
  built with the key and ship `<env>.manifest.json` + `.sig` in each zip.

### Updating nodes from a core 2.x image

Every release before the core-3 port ran core 2.0.17. Those nodes update
over the air as usual; no USB re-flash is needed. A node keeps its 2.x
bootloader and partition table (OTA never touches either) and its 2.x app
receives the first 3.x image:

- ESP-IDF bootloaders boot apps built with newer ESP-IDF releases, and each
  3.x image's header and segments pass the 2.x (IDF 4.4.7) bootloader's
  checks on the ESP32, the S3 and the N32R16V's octal bootloader.
- The partition-table binary is byte-identical, and NVS keeps its page
  format, so every setting survives the update and a rollback.
- The 2.x bootloader has app rollback enabled, so a 3.x image that fails
  its 60 s probation still boots the previous 2.x image.

This was established by checking the images and the IDF sources, not yet on
hardware. Before updating a whole fleet, do one bench check per board type:
update one node from 2.x and confirm its heartbeat reports the new version,
then update a second node and cut its power before 60 s have passed; it
must come back on the 2.x image.

## Coredumps

A panic leaves a dump in the `coredump` partition. The node uploads it on
`coredump/chunk` once MQTT is up (each chunk carries `coredump_id`, the
SHA-256 of the dump) and erases it only when the Pi answers
`cmd/coredump_ack` with that id, which the Pi sends after it has written the
dump to disk. Without an ack it retries with backoff (at most 3 uploads per
boot and 6 per dump) and then keeps the dump in flash.
