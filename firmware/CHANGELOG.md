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
  `sensors` block (debounced edges count as reads — an enabled-but-dead
  switch shows `reads=0`) and in `expected_missing` when enabled but not
  constructed, matching mhz19/hx711. BH1750 stays opportunistic
  (autodetect posture) and is deliberately NOT in `expected_missing`.
- Host tests for all of the above: SCD30 FRC framing + CRC + NACK
  health-fail, MH-Z19C zero-cal / ABC-on / ABC-off frames byte-for-byte,
  HX711 grams math including the uncalibrated (scale == 0) guard.

### Changed

- `Mhz19::begin()` takes `abc_enabled` (default `false`) instead of
  hardcoding ABC off — the chamber posture is unchanged, but bench rigs
  in ventilated rooms can now opt in to Winsen auto-baseline.

### No pin changes

No GPIO / I2C / PWM pin reassignments. Per `feedback_firmware_pin_changes`,
no wiring diagrams, schematics, BOM, or setup guides need updating.

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
