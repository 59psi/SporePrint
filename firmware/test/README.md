# Firmware tests

Host-native test suites — no ESP32, no Arduino. Run with:

```
pio test -e native
```

## What's covered (v2)

| Suite | Proves |
|---|---|
| `test_core_canonical` | Byte-for-byte canonicalizer parity against every golden signing vector, plus fail-closed edges (non-ASCII, dup keys, escaped keys, depth, trailing garbage) |
| `test_core_hmac` | SHA-256/HMAC standard vectors, full `verify_frame` against the golden vectors, exact ±30 s replay-window edges, every rejection path, constant-time compare |
| `test_core_buffer` | Byte-capped FIFO semantics — eviction order, oversize rejection, flush backpressure (the v1 entry-count buffer could OOM the heap) |
| `test_core_channel` | Actuator state machine — empty-payload rejection, clamps, duration vs max-on dominance, millis-wrap boundaries, dim ramps, channel naming, command routing, scenes |
| `test_drivers_i2c` | Sensirion transport CRC (datasheet vector 0xBEEF→0x92), SHT3x/SHT4x/SCD4x/SCD30/BH1750 against transaction-scripted mock buses — including autodetect probe ORDER (SHT4x-first at 0x44 with the SHT3x soft-reset between) |
| `test_drivers_misc` | MH-Z19C UART state machine (trickle, resync, checksum-fail ≠ 0 ppm, timeout), HX711 bit-exact 25-pulse reads + sign extension, reed debounce |
| `test_cam_url` | `server_url` allow-list incl. the closed "10.attacker.com" hole |

`test/fixtures/signing_vectors.json` is a **byte-identical copy** of
`server/tests/fixtures/signing_vectors.json` — the same golden file the
Pi and cloud Python suites assert. CI (`firmware-ci.yml`) diffs the copies
and fails on drift; it also greps `lib/sp_core` + `lib/sp_drivers` for
Arduino includes so the host-testable layers stay host-testable.

## Architecture that makes this possible

- `lib/sp_core` and `lib/sp_drivers` compile with no Arduino headers.
- Hardware enters through the `sp_hal` interfaces (I2cBus / UartPort /
  GpioPin / Clock); `lib/sp_testing/mock_hal.h` provides scripted mocks
  whose transaction scripts double as protocol assertions.
- HMAC is injected (`mbedTLS` could bind on-device; the vendored
  `sha256_host` is the verified default everywhere).

Hardware-in-the-loop testing remains a manual per-release step — see the
bench checklist in the release notes.
