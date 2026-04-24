# Firmware Changelog

ESP32 firmware for SporePrint nodes (relay / climate / lighting / cam).
Kept in lockstep with the Pi server + cloud repo via `scripts/bump.sh`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
