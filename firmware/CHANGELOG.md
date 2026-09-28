# Firmware Changelog

ESP32 firmware for SporePrint nodes (unified node + camera images).
Kept in lockstep with the Pi server + cloud repo via `scripts/bump.sh`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **CO₂ calibration for every supported sensor.** `cmd/config
  {"calibrate_co2": <ppm>}` now dispatches to whichever CO₂ sensor the
  node actually has: SCD4x FRC (`0x362F`, unchanged), SCD30 FRC
  (`0x5204`, applied in continuous mode — no stop/restart dance), or
  MH-Z19C zero-point calibration (`0x87` — always targets 400 ppm fresh
  air; the ppm argument is ignored and the log says so). Previously the
  command was silently dropped on SCD30 / MH-Z19C nodes. The boolean v1
  form is still refused with the explanatory log.
- **HX711 tare + scale calibration → real grams.** `cmd/config
  {"tare": true}` stores the current raw counts as the tare point;
  `{"calibrate_scale": <known_grams>}` derives counts-per-gram from a
  known mass (rejects non-positive / non-finite results). Both persist to
  NVS (`hx711_tare`, plus `hx711_scale_m` as fixed-point
  milli-counts-per-gram — KvStore has no float accessor). Calibrated
  nodes publish `weight_g` (0.1 g resolution) in telemetry; uncalibrated
  nodes keep publishing `scale_raw` so operators see counts during setup.
- **Reed switch health reporting.** The reed appears in the node health
  `sensors` block (debounced edges count as reads). It is deliberately NOT
  listed in `expected_missing`: a correctly wired switch on a door that
  stays shut produces no edges, so `reads=0` cannot tell a dead reed from a
  closed door. BH1750 stays opportunistic (autodetect posture) and is not
  listed either.
- Host tests for all of the above: SCD30 FRC framing + CRC + NACK
  health-fail, MH-Z19C zero-cal / ABC-on / ABC-off frames byte-for-byte,
  HX711 grams math including the uncalibrated (scale == 0) guard.
- **Hardware audit (2026-09).** Everything below is additive on the wire:
  new payload keys are optional, the signing vectors are unchanged, and
  every NVS key added reads as the old behavior when missing.
  - **Heartbeat on its own clock** (srv-hw#22). `status/heartbeat` goes out
    every min(`publish_interval_ms`, 5 min) instead of riding in the
    telemetry block, so a node set to publish every 15 min–1 h no longer
    flaps offline/online against the Pi's 900 s sweep. Telemetry + health
    keep the operator's interval; at the 60 s default nothing changes.
  - **Secure MQTT never downgrades silently** (fw-node#2). With TLS ticked
    and no Pi CA pinned the node still falls back to plaintext by default,
    but now logs an ERROR, raises a `tls_downgrade` alert (value = the
    plaintext port; entry + hourly), reports `tls:false` +
    `tls_fallback:true` in the heartbeat, and retries the CA fetch from
    `loop()` after 1, 2, 4, 8, then every 15 min. The first success pins the
    CA and moves the live link to TLS 8883 without a reboot. A `401` from
    `/api/provision/ca` is logged as the Pi's API-key gate.
  - **"Require TLS"** portal checkbox (NVS `tls_req`, default off): with no
    pinned CA, MQTT stays down (fail closed — the 10-min safe mode takes the
    channels off) while the CA fetch retries; the first success brings the
    link up on TLS.
  - **Heartbeat `tls` (bool) and `board`** on node + cam (e.g.
    `esp32-wroom-32`, `esp32-s3-devkitc-1-n32r16v`, `esp32-cam-ai-thinker`)
    — which transport is really in use, and which image an OTA push needs.
  - **Reed invert** (NVS `reed_inv`, default off): for a door contact wired
    on its NO lead (open while the magnet is present → pin HIGH with the
    door shut). Portal checkbox under the door switch, and
    `cmd/config {"peripherals": {"reed_inv": true}}` — applied live, no
    reboot; the door state is re-read without a spurious door event.
  - **New env `node_esp32s3_n32r16v`** for the Espressif
    ESP32-S3-DevKitC-1-N32R16V (32 MB octal flash + 16 MB octal PSRAM,
    1.8 V): opi_opi SDK build, OPI bootloader, 32 MB image header and
    `partitions_32mb.csv` (4 MB OTA slots; everything in the low 16 MB, the
    upper 16 MB left free). Same pin map as `node_esp32s3`. The
    `node_esp32s3` image does not boot on this board.
  - **Tier-3 peripherals without a factory reset**: portal fieldset
    (MH-Z19C, HX711, reed) and `cmd/config {"peripherals": {...}}` — a
    change to the driver set saves and reboots ~1.5 s later; an unchanged
    request does nothing.
  - **Per-channel max-on** `cmd/config {"max_on_sec": {"<channel>": N}}`,
    persisted as NVS `mo_<channel>`: switch channels 1–1800 s, dim channels
    0 (none)–86400 s.
  - **Camera sensors**: OV3660 (what the BOM 2-pack now ships) and OV5640
    alongside the OV2640, auto-detected by PID; additive cam health
    `camera.sensor` / `sensor_pid` / `jpeg_quality`, heartbeat
    `camera_sensor`, upload header `X-Camera-Sensor`.
  - Host suites `test_core_sensing`, `test_core_link`,
    `test_core_provision`, `test_core_boot`, `test_core_tls`.

### Changed

- `Mhz19::begin()` takes `abc_enabled` (default `false`) instead of
  hardcoding ABC off — the chamber posture is unchanged, but bench rigs
  in ventilated rooms can now opt in to Winsen auto-baseline.
- **Hardware audit (2026-09):**
  - **Setup portal no longer opens on a WiFi hiccup** (fw-node#9), node AND
    camera: a provisioned device whose settings have connected before
    boots offline, buffers, and re-begins WiFi every 60 s instead of
    opening the open `SporePrint-Setup` AP for 10 min. Open it on purpose
    by holding BOOT (node) / shorting the IO13 header pin to GND (cam — the
    AI-Thinker board has no button on GPIO 13) 3–10 s, then releasing;
    > 10 s still factory-resets. Both gestures time only
    densely-sampled passes, and no MQTT connect, CA fetch or capture starts
    while the button is held. Settings just saved in the portal that never
    connect reopen the portal, as before.
  - **OTA rollback works** (fw-node#12), node and camera: a new image is on
    probation until MQTT has been up 60 s continuously; a crash, WDT or
    power loss before then boots the previous image. An operator restart
    confirms the image only if it reached MQTT that boot.
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
  - **Telemetry**: `ts` is epoch seconds once NTP has synced (uptime
    before); frames replayed from the offline buffer carry `"replay": true`
    and go out before the live frame. A CO2 / lux / scale reading with no
    fresh sample for max(3× read interval, 30 s) is dropped and raises one
    `sensor_failure` alert (MH-Z19C: 3-min preheat grace).
  - **`expected_missing`**: `temp_rh` only on climate-personality nodes;
    `mhz19` / `hx711` when enabled but not delivering (each also alerts);
    never the reed switch.
  - **Alerts are latched**: once on entry, then at most hourly, re-armed
    after clearing with hysteresis (temp 1 °F, RH 2 %, CO2 200 ppm).
  - `calibrate_co2` refuses targets outside 400–2000 ppm and non-integers;
    `tare` / `calibrate_scale` average 8 fresh HX711 samples (~1 s, 3 s
    timeout) and refuse a calibration below 1 count/g.
  - **SCD4x / SCD30 `data_ready()` bus failures** (NACK, stretch timeout,
    CRC) now count as driver health failures (`last_error` "data_ready
    error") instead of looking healthy while the reading goes stale.
  - **Portal**: node id 1–32 of `[A-Za-z0-9_-]` and equal to the MQTT
    username when one is set (blank = the username); blank password fields
    keep the saved secret (WiFi only on the same SSID; "Open network"
    clears it); pre-filled values are HTML-escaped; a refused form comes
    back with what was typed.
  - **MQTT connects fit the 30 s loop WDT** (TCP 3 s, TLS handshake 6 s,
    CONNACK 3 s; DNS up to 15 s), are skipped while WiFi is down, and
    retry 5 s after the previous attempt ENDS.
  - **Camera**: the flash stays on through the exposure (fresh frame at
    capture time, `X-Flash-Used: 1` true); no `server_url` → uploads go to
    `http://<portal Pi address>:8000`; `https://` uploads require the
    pinned Pi CA (never unverified TLS); `X-Timestamp` omitted until NTP
    syncs; JPEG quality steps +2 (to 20) after a dropped frame.
  - **Drivers**: SHT3x detected reliably (2 ms soft-reset wait); SCD4x
    found after warm reboots/OTA (stop periodic before probing, ~0.5 s
    extra boot); SCD4x ASC forced off even when the ASC read fails; SCD30
    NaN readings rejected.
  - **Build**: `SPOREPRINT_FW_VERSION` comes from the environment variable
    (release workflow) else `VERSION.txt` else `"dev"`
    (`scripts/fw_version.py`, attached via `extra_configs =
    scripts/*.ini` so a tree without `scripts/` still builds) — local
    builds no longer heartbeat an empty version (docs#28). Libraries pinned
    exactly: PubSubClient 2.8, ArduinoJson 7.4.3 (device + native).

### No pin changes

No GPIO / I2C / PWM pin reassignments. Per `feedback_firmware_pin_changes`,
no wiring diagrams, schematics, BOM, or setup guides need updating. (The new
`node_esp32s3_n32r16v` env reuses the `node_esp32s3` pin map.)

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
