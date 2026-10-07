# Firmware Changelog

ESP32 firmware for SporePrint nodes (unified node + camera images).
Kept in lockstep with the Pi server + cloud repo via `scripts/bump.sh`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.2.0] - 2026-10-07

### Changed

- Lockstep version bump in step with the cloud parent — no firmware code
  changes in this release.

## [5.1.2] - 2026-10-06

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [5.1.1] - 2026-10-06

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [Unreleased]

## [5.1.0] - 2026-10-06

Two passes since 5.0.0: the **2026-09 hardware audit** and the **2026-10
follow-ups** (Arduino-ESP32 core 3.3.12, a driver for every sensor the BOM
ever recommended, the ESP32-S3 camera boards, coredump acknowledgements and
signed OTA manifests). Everything is additive on the wire: new payload keys
are optional, the signing vectors are unchanged, and every NVS key added
reads as the old behavior when missing.

### Upgrade notes

- **OTA from a 2.x node is supported on every board** — no USB re-flash.
  Push the first 3.x image from the Pi as usual. Bench step per board before
  a fleet push: OTA one node from 2.x, confirm the heartbeat, then pull power
  before 60 s on a second node and confirm it returns on 2.x (details under
  *Platform*).
- **Building needs PlatformIO Core ≥ 6.2.0 and `git`**; the first build
  downloads the pinned platform (about 1 GB).
- **Secure MQTT nodes:** a node from 5.0.0 or earlier pins a fetched CA
  without checking that TLS works; this image pins only after a working TLS
  connection, and a CA an older image stored is re-verified (see *Secure
  MQTT*). Run the Pi's `./install.sh` first so its broker certificate names
  every Pi IPv4.

### Platform: Arduino-ESP32 core 3.3.12 / ESP-IDF 5.5.5

Was core 2.0.17 / ESP-IDF 4.4 on `platformio/espressif32@6.13.0`, both
end-of-life. The platform is pinned to the versioned pioarduino release URL
`…/releases/download/55.03.312-1/platform-espressif32.zip` (not immutable;
the release workflow checks it against `firmware/toolchain.lock.json`). Same four
images, same pins, same partition tables, same MQTT payloads and signing
vectors; PubSubClient 2.8 and ArduinoJson 7.4.3 unchanged. The port:

- **PWM** stays 25 kHz / 10-bit on every relay and lighting channel:
  `ledcAttachChannel(pin, 25000, 10, i)` binds bank index *i* to LEDC
  channel *i* (the 2.x `ledcSetup`/`ledcAttachPin` map), all four on one
  timer; writes are by pin. 25 kHz is an exact divider at 10 bits on
  both clocks the core uses (ESP32 80 MHz APB: 3.125; S3 40 MHz XTAL:
  1.5625). A refused attach is logged and its gate held LOW.
- **Task WDT**: IDF 5 refuses a second `esp_task_wdt_init` and takes a
  config struct — `sp_device/task_wdt.h` reconfigures the core's
  watchdog (30 s node / 90 s cam, panic, same idle-task subscription).
  The one pet site outside `loop()`, the OTA flash, pets it only once the
  loop task is subscribed (IDF 5 logs an error for an unsubscribed pet);
  the coredump upload no longer pets it (see *Coredumps*).
- **Connect timeouts**: on 3.x `setTimeout()` on a network client is
  Stream's millisecond read timeout and no longer bounds the connect —
  left as it was, the TLS client's 30 s default connect would have
  outlasted the 30 s loop WDT again (fw-node#8). Now
  `setConnectionTimeout(3000)`; the handshake setter still takes seconds.
- **DNS** is capped at 15 s again: 3.x's `hostByName()` waits for lwIP to
  give up (7 s per configured DNS server, up to 21 s). The MQTT clients
  and the Pi-CA fetch resolve through `sp_device/bounded_dns.h` (lwIP
  lookup + 15 s wait, the 2.x behavior) and connect to the address,
  handing the host name to TLS so SNI and certificate checks are
  unchanged. mbedTLS 3.6 also verifies an IP broker host against the
  certificate's IP SAN entries (2.28 matched DNS entries only;
  `install.sh` writes both).
- **Default node id** (`node-xxxx`, used while no `node_id` is stored)
  comes from the eFuse station MAC via `esp_read_mac()`. Config loads
  before WiFi starts, and 3.x's `WiFi.macAddress()` returns without
  filling the buffer until the station interface exists (2.x read the
  eFuse MAC there) — the id would have been random per boot.
- **C++ dialect**: every source now builds at the framework's own
  gnu++2a and the native tests at gnu++20 (the libraries no longer force
  `-std=gnu++17`). Below C++20 the linker resolved `std::string` members
  from the prebuilt ESP-Matter archive and pulled ~300 KB of Matter into
  the image.
- **Network OTA keeps the Pi's handshake** (see *OTA*).
- **OTA from a 2.x node.** A node keeps its 2.x bootloader and partition
  table (OTA never touches either) and its 2.x app receives the first 3.x
  image. ESP-IDF bootloaders boot apps from newer ESP-IDF releases (the one
  ESP32 exception, `CONFIG_ESP_SYSTEM_ESP32_SRAM1_REGION_AS_IRAM`, is off in
  this SDK); each 3.x image's header (chip id, min chip rev v0.0, max rev
  unset) and its six segments were checked against IDF 4.4.7's verifier
  and loader (no overlap with the 2.x bootloader's RAM on ESP32, S3 quad
  or the N32R16V's OPI bootloader; the new RTC-slow segment is an
  accepted load region); the partition-table binary is byte-identical;
  NVS keeps page format `0xfe` in both IDF releases, so every Preferences
  key survives the hop and a rollback; flash HPM (the only S3 mode needing
  a "DC-aware" bootloader) is compiled out at 80 MHz. The 2.x bootloader
  is built with `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`, so a 3.x image
  that fails before its 60 s MQTT probation still boots the previous
  slot.
- The comments inside `partitions*.csv` still describe the 2.x core's
  reasons; the files stay byte-identical on purpose (fleet layout).

### Boards and envs

- **New env `node_esp32s3_n32r16v`** (built by `firmware-ci.yml` and
  shipped as `node_esp32s3_n32r16v.zip` by `firmware-release.yml`) for the
  Espressif ESP32-S3-DevKitC-1-N32R16V (32 MB octal flash + 16 MB octal
  PSRAM, 1.8 V): opi_opi SDK build, OPI bootloader, 32 MB image header and
  `partitions_32mb.csv` (4 MB OTA slots; everything in the low 16 MB, the
  upper 16 MB left free). Same pin map as `node_esp32s3`. The
  `node_esp32s3` image does not boot on this board.
- **ESP32-S3 camera boards** (the BOM's camera from 2026-04-15 to
  2026-06-11): three new envs build the same cam image for them, from
  `boards/board_profile_esp32s3cam.h` (pin maps tabled in the build guide,
  §8b, and `docs/drivers.md`):
  - `cam_esp32s3`: Freenove ESP32-S3-WROOM CAM (and Freenove clones),
    the ESP32-S3-EYE pin map Freenove's own example selects, XCLK at
    Freenove's 10 MHz, Freenove's orientation (mirror; OV2640 also
    flipped).
  - `cam_xiao_esp32s3`: Seeed XIAO ESP32S3 Sense (stock camera or the
    OV5640 add-on), the core's `CAMERA_MODEL_XIAO_ESP32S3` map, USB CDC
    serial.
  - `cam_waveshare_s3`: Waveshare ESP32-S3-CAM-OV5640 / -OV3660, pins
    from Waveshare's schematic and BSP. The sensor's PWDN sits on the
    board's CH32V003 I/O expander (I²C 0x24), so the cam opens the board
    I²C bus with ESP-IDF's driver (`src/cam/idf_i2c_bus.h`, not Wire,
    which would add ~16 KB to every cam image), powers the sensor through
    the new `sp_drivers/ws_cam_exio.cpp` (Waveshare's register protocol),
    and hands the bus to the camera driver (`sccb_i2c_port`).
  - None has a flash LED: `cam_policy.h flash_for_capture()` turns a
    flash request off and the upload reports `X-Flash-Used: 0`. The
    reset / portal button is BOOT (GPIO 0). Heartbeat `board`:
    `freenove-esp32-s3-wroom-cam`, `xiao-esp32s3-sense`,
    `waveshare-esp32-s3-cam`. 8 MB table, octal-PSRAM SDK (`qio_opi`).
- **Heartbeat `board`** on node + cam (e.g. `esp32-wroom-32`,
  `esp32-s3-devkitc-1-n32r16v`, `esp32-cam-ai-thinker`): which image an OTA
  push needs.

### Sensors and drivers

- **A driver for every sensor the BOM ever recommended** (inventory, with
  bus, driver file, autodetect, telemetry keys, tests and status per part:
  [`docs/drivers.md`](docs/drivers.md)). All additive. No pin changes, no new
  NVS keys or portal fields, and nodes without these parts publish exactly
  what they did before.
  - **AHT20 / AHT21 / AHT25** (I²C 0x38, `sp_drivers/aht20.cpp`): the cheap
    SHT31-D alternate the cloud shopping list carried from 2026-05 with "no
    driver". Autodetected by one CRC-valid measurement, because an ACK alone
    at 0x38 proves nothing. The 80 ms conversion runs as a non-blocking
    trigger in the read pass and is collected by a pump in `loop()`. It
    never re-triggers within 2 s (the datasheet's self-heating limit).
    Initialisation follows Aosong's v1.1 rule: when `(status & 0x18) !=
    0x18` it re-initialises registers 0x1B / 0x1C / 0x1E (the vendor's
    sample-code routine), then sends the v1.0 `0xBE` init only if the
    calibration bit is still clear. An uncalibrated sample is dropped and
    the same sequence runs as a non-blocking step machine from `loop()`
    (5 / 10 ms settles measured, never slept); no trigger goes out until it
    finishes. It supplies temp/RH only when no SHT is fitted; when it goes
    stale it raises `sensor_failure` (AHT20).
  - **BME280 / BMP280** (I²C 0x76 / 0x77, `sp_drivers/bme280.cpp`): the
    "Optional BME280" the architecture diagram showed on the climate node
    from 2026-04 to 2026-09, and the BMP280 on AHT20 + BMP280 combo boards.
    Identified by chip ID; BME680 and BMP180 are rejected rather than
    misread, and a BMP280 sold as a BME280 never claims humidity. Forced
    mode ×1, filter off, about 10 ms per read pass. The Bosch integer
    compensation is pinned to the BMP280 datasheet's worked example. New
    additive telemetry key **`pressure_hpa`** (hPa = mbar, one decimal),
    persisted by the Pi (`SENSOR_FIELDS`). A BME280's temp/RH is a fallback
    below SHT and AHT20. Health name `bme280` or `bmp280`; staleness raises
    `sensor_failure`.
  - Autodetect appends the AHT2x probe (0x38) and the BMx280 probe
    (0x76 / 0x77) after the original order; no two supported parts share an
    address unless the probe tells them apart. Temp/RH priority:
    SHT3x/SHT4x, then AHT20, then BME280, then the SCD fallback.
    `expected_missing: temp_rh` now counts AHT20 and BME280 (not BMP280) as
    temp/RH sensors.
  - **MH-Z19B**: the original spec's UART CO₂ part, and the BOM's budget
    alternate until 2026-06. The MH-Z19C driver already speaks every frame
    it uses; the B manual's frames and example reply (608 ppm) are now
    pinned byte for byte.
  - **SCD30 clock stretching on core 3.x.** Sensirion specifies stretches of
    up to 30 ms (150 ms once a day) and recommends 50 kHz or slower. Core
    2.0.17 raised the I²C SCL timeout to the controller's maximum; core
    3.3.12 adds every Wire device with `scl_wait_us = 0`, which ESP-IDF 5.5
    turns into 2 ms, and Wire exposes no setter, so an SCD30 would have
    failed reads and gone stale. `src/node/stretch_i2c_bus.h` gives 0x61 its
    own IDF device on the same bus, at 50 kHz, with the timeout at the
    hardware ceiling: 13.1 ms on ESP32 (as on 2.x) and 52 ms on ESP32-S3.
    Every other address stays on Wire unchanged. On the classic ESP32 that
    13.1 ms is short of Sensirion's 30 ms, so the SCD30 on `node_esp32` is
    listed as partial until a bench run shows how often a longer stretch
    fails a read (counted, never data).
- **CO₂ calibration for every supported sensor.** `cmd/config
  {"calibrate_co2": <ppm>}` now dispatches to whichever CO₂ sensor the
  node actually has: SCD4x FRC (`0x362F`, unchanged), SCD30 FRC
  (`0x5204`, applied in continuous mode — no stop/restart dance), or
  MH-Z19C zero-point calibration (`0x87` — always targets 400 ppm fresh
  air; the ppm argument is ignored and the log says so). Previously the
  command was silently dropped on SCD30 / MH-Z19C nodes. The boolean v1
  form is still refused with the explanatory log. `calibrate_co2` refuses
  targets outside 400–2000 ppm and non-integers.
- **HX711 tare + scale calibration → real grams.** `cmd/config
  {"tare": true}` stores the current raw counts as the tare point;
  `{"calibrate_scale": <known_grams>}` derives counts-per-gram from a
  known mass (rejects non-positive / non-finite results). Both average 8
  fresh HX711 samples (~1 s, 3 s timeout) and refuse a calibration below
  1 count/g, and both persist to NVS (`hx711_tare`, plus `hx711_scale_m` as
  fixed-point milli-counts-per-gram — KvStore has no float accessor).
  Calibrated nodes publish `weight_g` (0.1 g resolution) in telemetry;
  uncalibrated nodes keep publishing `scale_raw` so operators see counts
  during setup.
- **Reed switch health reporting.** The reed appears in the node health
  `sensors` block (debounced edges count as reads). It is deliberately NOT
  listed in `expected_missing`: a correctly wired switch on a door that
  stays shut produces no edges, so `reads=0` cannot tell a dead reed from a
  closed door. BH1750 stays opportunistic (autodetect posture) and is not
  listed either.
- **Reed invert** (NVS `reed_inv`, default off): for a door contact wired
  on its NO lead (open while the magnet is present → pin HIGH with the
  door shut). Portal checkbox under the door switch, and
  `cmd/config {"peripherals": {"reed_inv": true}}` — applied live, no
  reboot; the door state is re-read without a spurious door event.
- **`expected_missing`**: `temp_rh` only on climate-personality nodes;
  `mhz19` / `hx711` when enabled but not delivering (each also alerts);
  never the reed switch.
- **Staleness**: a CO2 / lux / scale reading with no fresh sample for
  max(3× read interval, 30 s) is dropped and raises one `sensor_failure`
  alert (MH-Z19C: 3-min preheat grace). **SCD4x / SCD30 `data_ready()` bus
  failures** (NACK, stretch timeout, CRC) now count as driver health
  failures (`last_error` "data_ready error") instead of looking healthy
  while the reading goes stale.
- **Driver fixes**: SHT3x detected reliably (2 ms soft-reset wait); SCD4x
  found after warm reboots/OTA (stop periodic before probing, ~0.5 s
  extra boot); SCD4x ASC forced off even when the ASC read fails; SCD30
  NaN readings rejected.
- `Mhz19::begin()` takes `abc_enabled` (default `false`) instead of
  hardcoding ABC off — the chamber posture is unchanged, but bench rigs
  in ventilated rooms can now opt in to Winsen auto-baseline.

### Camera

- **Camera sensors**: OV3660 (what the BOM 2-pack now ships) and OV5640
  alongside the OV2640, auto-detected by PID; additive cam health
  `camera.sensor` / `sensor_pid` / `jpeg_quality`, heartbeat
  `camera_sensor`, upload header `X-Camera-Sensor`.
- The flash stays on through the exposure (fresh frame at capture time,
  `X-Flash-Used: 1` true); no `server_url` → uploads go to
  `http://<portal Pi address>:8000`; `https://` uploads require the pinned
  Pi CA (never unverified TLS); `X-Timestamp` omitted until NTP syncs; JPEG
  quality steps +2 (to 20) after a dropped frame.
- The camera's portal shows neither the optional-peripherals fieldset nor
  the "Node personality" select (it has no channel bank and ignored it); a
  stored personality is left untouched.
- The ESP32-S3 camera boards: see *Boards and envs*.

### Provisioning and the setup portal

- **Setup portal no longer opens on a WiFi hiccup** (fw-node#9), node AND
  camera: a provisioned device whose settings have connected before
  boots offline, buffers, and re-begins WiFi every 60 s instead of
  opening the open `SporePrint-Setup` AP for 10 min. Open it on purpose
  by holding BOOT (node, and the S3 camera boards) / shorting the IO13
  header pin to GND (AI-Thinker cam — the board has no button on GPIO 13)
  3–10 s, then releasing; > 10 s still factory-resets. Both gestures time
  only densely-sampled passes, and no MQTT connect, CA fetch or capture
  starts while the button is held. Settings just saved in the portal that
  never connect reopen the portal, as before.
- **Tier-3 peripherals without a factory reset**: portal fieldset
  (MH-Z19C, HX711, reed) and `cmd/config {"peripherals": {...}}` — a
  change to the driver set saves and reboots ~1.5 s later; an unchanged
  request does nothing.
- **Portal rules**: node id 1–32 of `[A-Za-z0-9_-]` and equal to the MQTT
  username when one is set (blank = the username); blank password fields
  keep the saved secret (WiFi only on the same SSID; "Open network"
  clears it); pre-filled values are HTML-escaped; a refused form comes
  back with what was typed.

### Secure MQTT

- **Never downgrades silently** (fw-node#2). With TLS ticked and no Pi CA
  pinned the node still falls back to plaintext by default, but now logs an
  ERROR, raises a `tls_downgrade` alert (value = the plaintext port; entry +
  hourly), reports `tls:false` + `tls_fallback:true` in the heartbeat, and
  retries the CA fetch from `loop()` after 1, 2, 4, 8, then every 15 min,
  moving the live link to TLS 8883 without a reboot once a CA verifies
  (below). A `401` from `/api/provision/ca` is logged as the Pi's API-key
  gate.
- **A fetched CA is pinned only after it works** (final review). The CA
  from `/api/provision/ca` — at boot or at runtime — is a candidate held
  in RAM: MQTT tries TLS 8883 with it, and only a CONNACK writes it to NVS
  (`broker_ca`, then the new verified marker `broker_ca_ok`) and keeps the
  node on TLS. A failed trial persists nothing, goes back to the working
  plaintext link (or stays fail-closed with "Require TLS"), names the
  reason in the log and the `tls_downgrade` alert message (cert name
  mismatch / different CA, 8883 unreachable, TLS error, login refused —
  a new reason is announced at once, a repeated one hourly) and backs off
  before the next fetch + trial. Previously the CA was pinned and the link
  switched before any TLS connection had worked, so a broker certificate
  that did not list the node's broker host (e.g. an IP host) locked a
  working node out of MQTT and into safe mode until someone factory-reset
  it. A CA stored by an older image (no `broker_ca_ok`) gets the same
  trial instead of blind trust, so a node that image locked out recovers
  once this image is on it (e.g. via network OTA on the LAN); a verified
  pin is never downgraded. Heartbeat `tls` stays false and `ca_fp` absent
  until the TLS link is up.
- **"Require TLS"** portal checkbox (NVS `tls_req`, default off): with no
  pinned CA, MQTT stays down (fail closed — the 10-min safe mode takes the
  channels off) while the CA fetch retries; a verified trial brings the
  link up on TLS.
- **Heartbeat `tls` (bool)** on node + cam: which transport is really in
  use. **Heartbeat `ca_fp`** on node + cam, only while the MQTT link is
  TLS: lowercase hex SHA-256 of the CA PEM it trusts (the exact bytes the
  Pi served, so `hashlib.sha256(pem.encode()).hexdigest()` of the Pi's
  `ca.crt`). Lets the Pi flag a node that trust-on-first-use pinned some
  other CA. Optional; older Pis ignore it.

### Commands, safety and the MQTT link

- **Signed commands** (fw-node#11), node and camera: a second delivery of
  the same signed frame on the same topic inside the replay window is
  rejected, and an optional signed `"topic"` member must equal the
  arrival topic. The Pi now signs `"topic"` and a random `"nonce"` into
  every command frame, so redirection protection is active and two
  identical commands in the same second (on/off/on) are no longer
  mistaken for a replay. Older firmware verifies these frames unchanged.
- **Safety**: `aux` max-on backstop 60 s by default (fae / exhaust /
  circulation stay 30 min, lighting none); an explicit `"state":"off"`
  always wins over `pwm`/`level`; dim channels accept `pwm` as a 10-bit
  level alias; 10 min without MQTT → every channel off (safe mode,
  reported as `safety_cutoff` on reconnect); every channel off at OTA
  start; channel pins driven off before Serial at boot.
- **Per-channel max-on** `cmd/config {"max_on_sec": {"<channel>": N}}`,
  persisted as NVS `mo_<channel>`: switch channels 1–1800 s, dim channels
  0 (none)–86400 s.
- **Alerts are latched**: once on entry, then at most hourly, re-armed
  after clearing with hysteresis (temp 1 °F, RH 2 %, CO2 200 ppm).
- **MQTT connects fit the 30 s loop WDT** (TCP 3 s, TLS handshake 6 s,
  CONNACK 3 s; DNS up to 15 s), are skipped while WiFi is down, and
  retry 5 s after the previous attempt ENDS.

### Telemetry and heartbeat

- **Heartbeat on its own clock** (srv-hw#22). `status/heartbeat` goes out
  every min(`publish_interval_ms`, 5 min) instead of riding in the
  telemetry block, so a node set to publish every 15 min–1 h no longer
  flaps offline/online against the Pi's 900 s sweep. Telemetry + health
  keep the operator's interval; at the 60 s default nothing changes.
- **`ts`** is epoch seconds once NTP has synced (uptime before); frames
  replayed from the offline buffer carry `"replay": true` and go out before
  the live frame.

### OTA

- **OTA rollback works** (fw-node#12), node and camera: a new image is on
  probation until MQTT has been up 60 s continuously; a crash, WDT or
  power loss before then boots the previous image. An operator restart
  confirms the image only if it reached MQTT that boot.
- **Network OTA keeps the Pi's handshake.** arduino-esp32 3.3's
  `ArduinoOTA` only answers a PBKDF2-SHA256 challenge (64-hex fields);
  the Pi's OTA push (and every Pi in the field) answers the MD5 one, so a
  node on the stock library would refuse every Pi push after its first
  3.x image. `sp_device/ota_service.cpp` now speaks the 2.x espota
  exchange byte-for-byte (`sp_core/espota.h`, host-tested incl. the Pi's
  own `auth_response()` vector): same port 3232, same `AUTH <32-hex>`
  challenge (now from the hardware RNG), same lockstep TCP pull,
  `<hostname>.local` + `_arduino._tcp` mDNS as before, same
  `start/success/error` events. espota.py from the 3.x platform still
  pushes to it (a 32-hex nonce selects its MD5 path). Garbage datagrams
  the 2.x parser read as "command 0" are now ignored.
- **Signed OTA manifests (optional, additive).** An image built with
  `SPOREPRINT_OTA_PUBKEY_B64` in its build environment (base64 of the
  32-byte Ed25519 release key the Pi pins; `scripts/fw_version.py` compiles
  it in and fails the build on a malformed key) accepts **`cmd/ota_manifest
  {manifest_b64, sig_b64}`** — the Pi server's v1 release manifest format,
  with `artifact` = the PlatformIO env (new `SP_FW_ARTIFACT` define) and
  `sha256` / `size` of `firmware.bin`.
  - `sp_core/ota_manifest.h`: Ed25519 over the exact bytes (vendored
    **Monocypher 4.0.3**, unmodified, `lib/sp_core/vendor/monocypher`, BSD-2 /
    CC0: byte-identical to the release tarball, whose checksums and per-file
    SHA-256 its README records and `server/tests/test_firmware_vendor.py`
    enforces; images link only `crypto_ed25519_check` and its helpers), the
    canonical byte form, the v1 field grammar, and the node policy — its own
    env only, not older than the running image or the newest
    manifest-verified update (NVS `ota_floor`).
  - `sp_core/ota_gate.h`: a verified manifest arms the next push for 5 min.
    That push must be a firmware image of the signed size; every flashed
    byte is hashed and the update is aborted before `Update.end()` on a
    mismatch (`ERR manifest_sha256_mismatch` to the pusher, `ota` error
    event). One arming covers one push.
  - OTA events gain `manifest_armed {version, sha256}`, `manifest_rejected
    {reason}`, error reasons `manifest_required` / `manifest_size_mismatch` /
    `manifest_not_firmware` / `manifest_sha256_mismatch`, and `success
    {manifest}` after a verified update.
  - Unsigned pushes still flash; `SPOREPRINT_OTA_REQUIRE_MANIFEST=1` at
    build time refuses them (ignored when no key is built in). Local builds
    and Builder ZIPs build without a key and ignore manifests.
  - **Release images are signed.** `firmware-release.yml` builds every env
    with the release verify key compiled in and ships each
    `<env>.zip` with `firmware.bin`, `bootloader.bin`, `partitions.bin`,
    `<env>.manifest.json` and its `.sig`; the release notes print the key
    to pin on the Pi. `../scripts/verify_firmware_release.py` checks a
    zip the way the Pi and the node do (the workflow runs it on every zip
    before publishing). The signing key never reaches the PlatformIO
    builds. Details: `../docs/firmware-security.md` → *Signed
    firmware releases*, and `README.md` → *Releases* for flashing (a USB
    flash erases the whole flash first: the zips carry no `otadata`).
  - `ota_manifest` is a reserved channel name; `sp_core/base64_codec.h`
    (strict RFC 4648 decode + the encoder that moved out of the uploader);
    `sp::Sha256` streaming hash in `sp_core/sha256.h`.

### Coredumps

**Coredumps are erased only after the Pi has stored them.** The uploader
used to erase the `coredump` partition as soon as the last QoS 0 chunk
left the node, so a Pi restart, a full disk or one lost chunk destroyed
the only copy of the crash. Now (`sp_core/coredump_drain.h`, the pure
state machine; `sp_device/coredump_uploader.cpp`, the flash/MQTT adapter):

- `setup()` only finds and hashes the dump; `loop()` uploads it, 4 chunks
  per pass and only while MQTT is up — it no longer runs synchronously at
  boot (and is no longer a WDT pet site; `task_wdt.h`).
- Every chunk carries **`coredump_id`**, the lowercase hex SHA-256 of the
  whole dump (additive key; older Pis ignore it).
- The node erases the dump only on **`cmd/coredump_ack
  {"coredump_id"}`** naming that exact id, through the normal command
  verification (HMAC, topic binding, replay guard). With a signing key
  provisioned it waits up to 2 min for NTP before the first upload, so the
  ack can verify.
- No ack within 30 s, or an upload cut short → retry after 1, 2, 4 ... 15
  min. At most 3 complete uploads per boot and 6 per dump (counted in NVS,
  `cd_id` / `cd_up`), then the dump is **kept** in flash with no more
  uploads until the next panic replaces it. A Pi without ack support
  therefore stores a dump at most 6 times and the node never loses it.
- `coredump_ack` is a reserved channel name.

### Build, images and tests

- **Version**: `SPOREPRINT_FW_VERSION` comes from the environment variable
  (release workflow) else `VERSION.txt` else `"dev"`
  (`scripts/fw_version.py`, attached via `extra_configs =
  scripts/*.ini` so a tree without `scripts/` still builds) — local
  builds no longer heartbeat an empty version (docs#28). Libraries pinned
  exactly: PubSubClient 2.8, ArduinoJson 7.4.3 (device + native).
- **`scripts/image_guard.py`** (post-build, every env, attached with the
  version script): fails the build if a partition table differs from the
  pinned fleet layout, if `firmware.bin` leaves < 64 KiB of the smallest
  app slot, if any ESP-Matter object is linked, or if the cam image links
  the Arduino LEDC attach (the camera's XCLK owns LEDC timer 0 /
  channel 0 through ESP-IDF, invisible to that allocator).
- **Image sizes** with everything in this release (`firmware.bin` as
  `scripts/image_guard.py` measures it, 2026-10-06 integration build):
  `node_esp32` 1,314,896 B (83.6 % of its slot, 257,968 B free), `cam`
  1,346,144 B (85.6 %, 226,720 B free), `node_esp32s3` 1,292,896 B,
  `node_esp32s3_n32r16v` 1,298,752 B, `cam_esp32s3` 1,305,296 B,
  `cam_xiao_esp32s3` 1,274,896 B, `cam_waveshare_s3` 1,299,232 B; 0 compiler
  warnings, every image guard passes. The manifest check costs ~21 KB.
  Along the way: on core 2.x the four images were 1.12 / 1.16 / 1.07 /
  1.08 MB (`node_esp32` / `cam` / `node_esp32s3` / `node_esp32s3_n32r16v`);
  right after the core-3 port, `node_esp32` ≈ 1.28 MB (82 %) and `cam`
  ≈ 1.32 MB (84 %) of the 1.5 MB slot (~280 / ~250 KB to spare),
  `node_esp32s3` ≈ 1.26 MB of 3 MB and `node_esp32s3_n32r16v` ≈ 1.27 MB of
  4 MB; after the driver pass and before the coredump and manifest work,
  `node_esp32` 1,290,544 B (82.1 %, 282,320 B free), `node_esp32s3`
  1,268,752 B, `node_esp32s3_n32r16v` 1,274,576 B, `cam` 1,321,216 B (the S3
  camera envs left the AI-Thinker image unchanged), `cam_esp32s3`
  1,281,216 B, `cam_xiao_esp32s3` 1,250,896 B, `cam_waveshare_s3`
  1,275,312 B, each S3 camera in a 3 MB slot.
- **Native suites**: new `test_core_sensing`, `test_core_link`,
  `test_core_provision`, `test_core_boot`, `test_core_tls` (audit), plus
  host tests for the calibration work (SCD30 FRC framing + CRC + NACK
  health-fail, MH-Z19C zero-cal / ABC-on / ABC-off frames byte-for-byte,
  HX711 grams math including the uncalibrated (scale == 0) guard), and
  **`test_core_coredump`** (20 tests) and **`test_core_ota_manifest`**
  (15 tests: RFC 8032 vectors, a malleated S + L signature refused as the
  Pi refuses it, every case of `test/fixtures/ota_manifest_vectors.json` —
  a byte-identical copy of the Pi's — grammar edges, policy, gate).
  `test_core_espota` adds MD5 vectors for all 256 byte values, the padding
  edges one block in and one million 'a', plus a UTF-8 password answer from
  the Pi's `auth_response()`. 309 native tests pass.

### Bench-pending

- The ESP32-S3 camera boards: first capture on each board, the Freenove
  orientation, the Waveshare expander write.
- The SCD30 on a WROOM-32 (`node_esp32`): how often a stretch past 13.1 ms
  fails a read.
- Coredumps and manifests: a real panic → upload → ack → erase on each
  board, a power cut between upload and ack (the dump must survive), and
  one signed push plus one tampered push on a node built with a test key.
- OTA from 2.x: the per-board check under *Upgrade notes*.

### No pin changes

No GPIO / I²C / PWM pin reassignments on any existing env. The new
`node_esp32s3_n32r16v` env reuses the `node_esp32s3` pin map; the three S3
camera envs drive the cameras on their own boards (no wiring), and their pin
maps are in the build guide (§8b), `boards/board_profile_esp32s3cam.h` and
`docs/drivers.md`.

## [5.0.0] - 2026-07-16

Version-lockstep bump to 5.0.0 (`scripts/bump.sh` moves cloud, Pi server, and
firmware together). **No functional firmware change in this release** — the
v5.0.0 pass was production-wiring on the cloud + Pi-server side, and the ESP32
node/camera images were already fully wired in the v2 firmware train (v4.2.0).
The image matrix (`node_esp32` / `node_esp32s3` / `cam`), the HMAC signing, and
the NVS layout are unchanged; `VERSION.txt` now reports `5.0.0` so OTA-drift
detection and the cloud `/status` + `/firmware` build panels stay in lockstep.

### No pin changes

No GPIO / I2C / PWM pin reassignments.

## [4.2.0] - 2026-06-12

### Added
- **Ground-up v2 rewrite.** One unified node image (`node_esp32` /
  `node_esp32s3`) replaces the climate/relay/lighting trio — the channel
  personality is chosen in the setup portal and the I²C sensor set
  autodetects at boot (SHT3x + SHT4x at 0x44/0x45, SCD4x, SCD30, BH1750;
  MH-Z19C / HX711 / reed switch by config flag). The camera (`cam`,
  AI-Thinker) is its own image. The MQTT contract is byte-compatible with
  v1; heartbeats gain additive `type` / `roles` / `fw_image` fields.
- Captive portal v2 collects everything provisioning needs: WiFi, the
  Pi's address, MQTT credentials, node id, personality, OTA password,
  the command signing key, NTP host, and a Secure MQTT (TLS) toggle.
- Opt-in TLS MQTT: the node pins the Pi's CA (one fetch of
  /api/provision/ca at provision time, trust-on-first-use) and connects
  on 8883 via WiFiClientSecure. A failed CA fetch falls back to plaintext
  loudly — never TLS-without-verification.
- Host-native test suite (`pio test -e native`): 69 cases including
  byte-for-byte canonicalizer + signature parity against the shared
  golden vectors, driver protocol suites on transaction-scripted mock
  buses, actuator safety state-machine coverage, and the cam URL
  allow-list.
- NVS migration: first boot copies a v1 node's provisioning out of its
  per-role namespace into the unified store (sanitizing v1's
  quote-corrupted HMAC keys) so an OTA to v2 never de-provisions a node.

### Changed
- Command verification is a raw-token canonicalizer over the exact wire
  bytes — number/string lexemes are never re-serialized, which is what
  makes the Python parity byte-exact (including nested objects and float
  timestamps the v1 canonicalizer could not handle).
- The watchdog arms only after provisioning completes (v1 armed a 10 s
  panic WDT before the captive portal, making first-boot setup
  effectively impossible) and is petted from exactly one place per loop.
- MQTT publishes stream directly into the client (no intermediate
  buffer), so log batches and coredump chunks arrive parseable — v1
  truncated both at 512 bytes.
- The offline telemetry buffer is byte-capped (16 KB, evict-oldest with
  drop counters) instead of entry-capped (1000 entries could exceed free
  heap during a long broker outage).
- `calibrate_co2` performs a real SCD4x forced recalibration against a
  target ppm; the v1 boolean form (which enabled automatic
  self-calibration — wrong for chambers that never see fresh air) is
  refused with an explanatory log. ASC/ABC auto-baselines are disabled on
  SCD4x, SCD30, and MH-Z19C for the same reason.
- Camera factory reset moves GPIO 0 → GPIO 13 (v1 shared GPIO 0 with the
  camera XCLK); a failed camera init now boots degraded with MQTT health
  reporting instead of restart-looping before the portal could appear.

### Fixed
- v1's build-flag HMAC provisioning corrupted keys via a preprocessor
  double-stringify (provisioned nodes rejected every signed command;
  unprovisioned builds wrote a poisoned 2-character key that silently
  enabled strict mode). The path is deleted — keys travel through the
  portal.
- `server_url` validation requires a genuine dotted-quad IPv4 before any
  RFC1918 allowance — "10.attacker.com" no longer passes.
- Release builds carry a real firmware version (the release workflow
  exports SPOREPRINT_FW_VERSION from the tag; v1 release binaries
  heartbeated an empty string).

## [4.1.6] - 2026-06-11

### Changed
- No firmware code changes in this release. The hardware guides, enclosure
  models, and wiring diagrams were updated to match the boards the firmware
  actually targets (ESP32-WROOM-32 via `esp32dev`, AI-Thinker ESP32-CAM via
  `esp32cam`) — see the repo CHANGELOG. A ground-up firmware revision with
  broader sensor support is planned next.

## [4.1.5] - 2026-05-03

Lockstep version bump only — no firmware changes.

## [4.1.4] - 2026-05-03

Lockstep version bump only — no firmware changes.

## [4.1.3] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.1.2] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.1.1] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.1.0] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.0.7] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.0.6] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.0.5] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.0.4] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.0.3] - 2026-05-02

Lockstep version bump only — no firmware changes.

## [4.0.2] - 2026-05-01

Lockstep version bump only — no firmware changes.

## [4.0.1] - 2026-05-01

Lockstep version bump only — no firmware changes in this release. v4.0.1 is a parent-cloud hotfix release (landing page + runtime env aliasing + middleware healthcheck unblocking). No GPIO / I2C / PWM pin changes, no `partitions.csv` change, no `coredump.{h,cpp}` or `log_forward.{h,cpp}` change. The `VERSION.txt` bump is for the lockstep heartbeat string only.

## [4.0.0] - 2026-04-30

Major version bump in lockstep with the cloud parent + Pi server v4. Firmware-side this release is purely additive: a 64 KB coredump partition, on-boot coredump upload over MQTT, and a 32-entry log-forward ring buffer drained on `SP_LOG()` calls. No GPIO / I2C / PWM pin assignment changes — the only mechanical change is the new `partitions.csv`.

### Added

- **`partitions.csv`** — explicit 4 MB partition layout reserving a 64 KB coredump slot at offset `0x3F0000`. Replaces the previous default partition table; required so the ESP32 can persist a coredump across resets without colliding with the OTA1 / SPIFFS regions.
- **`lib/sporeprint_common/coredump.{h,cpp}`** — coredump helpers exposing `isPresent()`, `readChunked()`, `erase()`, and `uploadIfPresent()`. Each node's `setup()` calls `coredump::uploadIfPresent(*mqtt)` once Wi-Fi + MQTT are up; if a coredump is present, it is read in chunks, published over MQTT to the Pi server (which forwards to the cloud relay's new `ota_step` / coredump channel), then erased so the next reset has a clean slot.
- **`lib/sporeprint_common/log_forward.{h,cpp}`** — `SP_LOG()` macro backed by a 32-entry × 200-byte ring buffer drained over MQTT. Replaces ad-hoc `Serial.printf` for diagnostic events that need to reach the operator without a USB cable. Ring buffer is opt-in per node via `LogForward::attachMqtt(mqtt)` in `setup()`.

### Changed

- **All four nodes (climate, relay, lighting, cam)** now wire up `LogForward::attachMqtt(mqtt)` and `coredump::uploadIfPresent(*mqtt)` in their `setup()` once MQTT is connected. Same call shape on every node so the diagnostic surface is uniform across the fleet.
- **`platformio.ini`** — `board_build.partitions = partitions.csv` on every node env so the new partition table is flashed alongside the firmware bundle.

### Fixed

- (none — pure additive release.)

### Removed

- (none.)

### No pin changes

No GPIO / I2C / PWM pin reassignments in this release. Per `feedback_firmware_pin_changes`, the only mechanical change is the new `partitions.csv` — no wiring diagrams, schematics, BOM, or setup guides need updating.

## [3.4.10] - 2026-04-24

Lockstep version bump — no firmware changes. The cloud repo introduced a cache-protocol scaffold unrelated to the firmware path.

## [3.4.9] - 2026-04-24

The archaeology sweep of v3.4.8 (see `analysis/02-security.md` in the parent repo) identified the firmware as the remaining weak plane. This release closes the Critical and every High / Medium finding that lives on-device.

### Added

- **HMAC-SHA256 verification of inbound MQTT command frames** (`sporeprint_common/frame_verify.h`). The cloud+Pi already signed end-to-end; signing now extends past the broker to the firmware itself. Closes Sentinel finding C-1.
  - Shared canonical-JSON serialization matches the Python `json.dumps(..., sort_keys=True, separators=(",", ":"))` byte-for-byte.
  - 30-second replay window enforced against NTP-disciplined wall clock.
  - Migration-period behavior: if `hmac_key` is not yet in NVS, logs a loud `[SEC] WARNING` on every accepted unsigned command — visible drive toward provisioning, does not brick upgrades.
  - Build-flag provisioning: `-DSPOREPRINT_PROVISION_HMAC=<hex>` writes key into NVS on first boot. Never overwrites existing NVS. Use `scripts/provision-node.sh` to generate a key + get flashing instructions.
- **NTP sync at WiFi connect** (`wifi_manager.cpp`). Enables meaningful `ts` freshness on signed command frames. pool.ntp.org + time.google.com.
- **`esp_task_wdt` parity** on climate (30 s), lighting (10 s), and cam (60 s) nodes. Relay already had it; now all four reboot on a main-task deadlock rather than silently freezing. Closes Sentinel M-6.
- **`esp_reset_reason()` + reconnect counters** emitted in every heartbeat (`heartbeat.cpp`). Unblocks "is this node cycling every 10 min?" remote diagnosis without Serial-cable access.
- **`frame_verify` uses mbedtls** (part of ESP-IDF) so no new dependency is added to `lib_deps`.
- **`firmware/VERSION.txt`** tracks the firmware semver; `scripts/bump.sh` writes it and exports `SPOREPRINT_FW_VERSION` before invoking `pio run`. Replaces the hard-coded `"0.1.0"` string that had been in every heartbeat regardless of actual build.
- **`captureFail` counter + EMA latency** on cam_node. Previously declared but never incremented; now increments on null frame-buffer, on empty `server_url`, and on non-200 HTTP response. Capture latency is exponentially smoothed (α=0.2).
- **Per-channel `safety_cutoffs` counter** on relay_node. Increments on both timed-off and max-on-exceeded safety cutoffs. Previously dead telemetry.

### Changed — firmware safety + correctness

- **Relay command handler refuses bare `{}` payloads** (`relay_node/main.cpp`). Previously defaulted to `on=true, pwm=255` which, paired with a retained broker message surviving a reboot, could latch a heater at full power until the 30-min max-on cutoff. Now rejects frames with neither `state` nor `pwm`. Closes Sentinel M-5.
- **`millis()` wrap-safe `offAt` compare** on relay_node. `now >= offAt` is naïvely non-wrap-safe and misbehaves once per ~49.7-day wrap; replaced with `(long)(now - offAt) >= 0` which stays correct across the wrap for windows shorter than 24.8 days. Max-on compare was already naturally wrap-safe. Closes Sentinel L-1.
- **MQTT inbound buffer 1024 B** to match `setBufferSize(1024)` on the publish side (`mqtt_manager.cpp::_handleMessage`). Previously a 512-byte stack buffer silently truncated frames >511 B into garbled JSON. Signed command frames from v3.4.9 land in the 600-900 B range so this matters in practice. Oversize frames are now explicitly dropped with a Serial log. Closes Sentinel L-2.
- **Case-insensitive `state` parsing** on relay_node (previously case-sensitive — `"ON"` silently fell through to default behavior). Per the MQTT contract `state` may be `on`/`off`/`ON`/`OFF`.
- **`server_url` allow-list on cam_node** (`cam_node/main.cpp::onCommand`). Previously accepted any string from MQTT and persisted to NVS, so a LAN actor with broker creds could redirect every captured frame. Now validates: http/https scheme, no userinfo / query / fragment, host in {paired Pi, sporeprint.local, sporeprint.ai, RFC1918 ranges}, length ≤128. Closes Sentinel H-1.

### Deployment

New provisioning flow: `sporeprint/scripts/provision-node.sh`

```
./scripts/provision-node.sh           # read or generate SPOREPRINT_MQTT_HMAC_KEY
./scripts/provision-node.sh --rotate  # force-generate a fresh key
```

Then re-flash each node with `SPOREPRINT_PROVISION_HMAC=<key> pio run -e <env> -t upload`.

### Build — no behavior change

- `platformio.ini` grows a `build_flags` block that reads `SPOREPRINT_FW_VERSION` and `SPOREPRINT_PROVISION_HMAC` from the environment. Both are optional at build time — empty values compile cleanly but disable the feature.
- `scripts/bump.sh` writes `firmware/VERSION.txt` and exports `SPOREPRINT_FW_VERSION` as part of the release flow so local and CI builds stamp the right version.

### Known follow-ups

- **Per-node HMAC keys** (currently a single shared key across the Pi + all four nodes). Rotation compromise scope is per-Pi. Per-node scheme lands in v3.5.0 alongside cloud-mediated provisioning.
- **Secure boot v2 + flash encryption + signed OTA** (Sentinel H-2 + H-3). Requires board-level key custody + rollback-counter tooling; scoped as a separate hardening PR after v3.4.9 stabilizes in-field.
- **Unity/Catch2 firmware test harness**. 0 tests today; coverage for `offline_buffer`, `frame_verify::canonicalize`, the clamps, and the wrap-safe timer compare is the next-most-valuable addition.
