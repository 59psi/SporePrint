# Firmware tests

Host-native test suites — no ESP32, no Arduino. Run with:

```
pio test -e native
```

## What's covered (v2)

| Suite | Proves |
|---|---|
| `test_core_canonical` | Byte-for-byte canonicalizer parity against every golden signing vector, plus fail-closed edges (non-ASCII, dup keys, escaped keys, depth, trailing garbage) |
| `test_core_hmac` | SHA-256/HMAC standard vectors, full `verify_frame` against the golden vectors, exact ±30 s replay-window edges, every rejection path, constant-time compare, destination binding (signed `"topic"` member) and the replay guard (a second delivery of one signed frame on one topic is rejected) |
| `test_core_buffer` | Byte-capped FIFO semantics — eviction order, oversize rejection, flush backpressure (the v1 entry-count buffer could OOM the heap) |
| `test_core_channel` | Actuator state machine — empty-payload rejection, clamps (incl. the CO2-calibration target range), duration vs max-on dominance, millis-wrap boundaries, dim ramps, channel naming, command routing, scenes |
| `test_core_sensing` | Reading freshness / staleness windows, latched alerts with hysteresis, the averaged HX711 tare / calibration capture |
| `test_core_link` | MQTT-loss safe mode (10 min) and WiFi re-begin (60 s) policy, and the heartbeat cadence — min(publish interval, 5 min), never past the Pi's 900 s offline threshold |
| `test_core_provision` | Portal form policy — HTML escaping, WiFi-password keep, node id / MQTT-username rule, IPv4-literal detection, the `peripherals` command incl. the live `reed_inv` option vs a driver-set change that needs a reboot |
| `test_core_boot` | Portal-at-boot policy, portal-save re-verification, BOOT/reset-button hold incl. sparse-sampling safety, OTA `ImageConfirm` + `reached_broker`, connect-attempt WDT budget |
| `test_core_tls` | Secure MQTT with no pinned CA — plaintext fallback vs "Require TLS" fail-closed, CA-fetch backoff (1/2/4/8/15 min, wrap-safe), the runtime fetch's WDT budget and no MQTT connect in a fetch pass, TOFU PEM acceptance; verify-before-commit (`TlsPinMachine`: a fetched or unverified-stored CA is only tried, committed after a CONNACK, reverted to plaintext / fail-closed with a reason and backoff on failure, a verified pin never downgraded), trial-failure classification, the reason-aware `tls_downgrade` latch, the `ca_fp` fingerprint |
| `test_wire_contract` | Exact key sets + literals of every device→Pi document (telemetry incl. `replay` and the BME280/BMP280 `pressure_hpa`, alert incl. `tls_downgrade`, switch report, dim levels, heartbeat incl. the optional `tls` / `tls_fallback` / `board` / `ca_fp`, health, log entry) |
| `test_drivers_i2c` | Sensirion transport CRC (datasheet vector 0xBEEF→0x92, plus the CRC-8/NRSC-5 catalogue check value the AHT2x shares), SHT3x/SHT4x/SCD4x/SCD30/BH1750/AHT20/BME280/BMP280 against transaction-scripted mock buses — including autodetect probe ORDER (SHT4x-first at 0x44 with the SHT3x soft-reset between; AHT2x at 0x38 and BMx280 at 0x76/0x77 appended), inter-transaction timing via a timed mock bus, SCD4x/SCD30 `data_ready()` bus faults counted as health failures, the AHT20's CRC-gated probe, its Aosong v1.1 register init (0x1B / 0x1C / 0x1E, then the v1.0 `0xBE` fallback) as a boot transaction script and as the non-blocking runtime re-init, and its non-blocking 80 ms conversion pump (busy grace, calibration bit, 2 s self-heating limit), the Waveshare ESP32-S3-CAM I/O expander's camera power-up writes, and BME280/BMP280 chip-ID identification, trim-register unpacking (signed H4/H5) and Bosch integer compensation against the BMP280 datasheet's worked example (25.08 °C, t_fine 128422, 100653.27 Pa) and the datasheet's double-precision humidity formula |
| `test_drivers_misc` | MH-Z19C UART state machine (trickle, resync, checksum-fail ≠ 0 ppm, timeout) and the MH-Z19B manual's frames + example reply byte-for-byte (one driver serves both), HX711 bit-exact 25-pulse reads + sign extension, reed debounce incl. the inverted (NO-wired) convention and a live invert change without a spurious event |
| `test_core_espota` | The network-OTA handshake the Pi's push speaks (`sp_core/espota.h`): vendored MD5 against RFC 1321 plus the 55/56/64-byte padding edges, the auth answer against a vector from the Pi's own `auth_response()`, invitation / answer parsing for the exact datagrams the Pi push and espota.py send, and the garbage the 2.x ArduinoOTA parser read as "command 0" |
| `test_core_coredump` | Coredump store-then-ack (`sp_core/coredump_drain.h`): the dump id (streamed SHA-256 against the FIPS vectors, equal to one-shot at every split), RFC 4648 base64 and the exact chunk key set, no upload while MQTT is down, the bounded wait for NTP when a signed ack could not verify yet, a few chunks per loop pass, erase only on an ack naming the exact id (also a late one, also mid-upload), missed-ack and interrupted-upload backoff (1, 2, 4 ... 15 min), the per-boot and per-dump (NVS) upload caps after which the dump is kept, millis() wrap, NVS bookkeeping with no write on a clean boot |
| `test_core_ota_manifest` | Signed OTA manifests (`sp_core/ota_manifest.h`, `ota_gate.h`): the vendored Monocypher Ed25519 against RFC 8032 §7.1 tests 1-3 and the fixture seed deriving the fixture key; every case of `test/fixtures/ota_manifest_vectors.json` (valid / tampered / signed-but-invalid); the v1 field grammar edge by edge and canonical re-encoding; the node policy (own env only, no downgrade below the running image or the NVS floor); the gate (one arming per push, 5-minute expiry, size / filesystem refusals, required-manifest refusal, SHA-256 match vs mismatch); strict base64 decoding |
| `test_cam_url` | `server_url` allow-list incl. the closed "10.attacker.com" hole; camera policy for the default upload URL, X-Timestamp only when synced, pinned-CA-or-refuse HTTPS, per-sensor profiles, per-board orientation (Freenove ESP32-S3) and flash (none on the S3 camera boards), and JPEG-quality backoff |

`test/fixtures/ota_manifest_vectors.json` is likewise a byte-identical copy
of `server/tests/fixtures/ota_manifest_vectors.json` (the Pi's
`tests/test_node_ota_manifest.py` and the firmware CI diff the two).

`test/fixtures/signing_vectors.json` is a **byte-identical copy** of
`server/tests/fixtures/signing_vectors.json` — the same golden file the
Pi and cloud Python suites assert. CI (`firmware-ci.yml`) diffs the copies
and fails on drift; it also greps `lib/sp_core` + `lib/sp_drivers` for
Arduino includes so the host-testable layers stay host-testable.

Which part each driver covers, and its status, is in
[`../docs/drivers.md`](../docs/drivers.md) (the driver inventory).

## Architecture that makes this possible

- `lib/sp_core` and `lib/sp_drivers` compile with no Arduino headers.
- Hardware enters through the `sp_hal` interfaces (I2cBus / UartPort /
  GpioPin / Clock); `lib/sp_testing/mock_hal.h` provides scripted mocks
  whose transaction scripts double as protocol assertions.
- HMAC is injected (`mbedTLS` could bind on-device; the vendored
  `sha256_host` is the verified default everywhere).

Hardware-in-the-loop testing remains a manual per-release step — see the
bench checklist in the release notes.
