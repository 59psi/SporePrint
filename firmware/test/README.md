# Firmware tests

v3.4.9 opens this directory with a placeholder `native` PlatformIO
environment + scaffold. The aim:

1. **Native-host tests** run without an ESP32 — pure-C++ unit tests of
   the logic that doesn't touch hardware. Build with:
   ```
   pio test -e native
   ```
2. **Unity** is the Arduino-native test framework; installed
   automatically when the `test_framework = unity` line in
   `platformio.ini` is the default.

## What belongs here

Priority order (highest-consequence first):

1. **`frame_verify::canonicalize`** — HMAC body canonicalization. The
   byte-for-byte match with the Python `json.dumps(sort_keys=True,
   separators=(",", ":"))` is load-bearing; drift silently breaks every
   signed command. A single round-trip test catches future refactors.
2. **`OfflineBuffer::buffer`** + flush — FIFO eviction at
   `BUFFER_MAX_ENTRIES = 1000`; ordering preserved; flush is no-op when
   MQTT is disconnected.
3. **Relay duration clamp** — extract the clamp block from
   `relay_node/main.cpp` into a pure function `clamp_duration_sec(int)`
   and unit-test the bounds ([1, 3600], negative → ignored, zero →
   ignored).
4. **`climate_node::clampULong`** — already a pure helper; assert bounds
   and the `below-min` / `above-max` / `in-range` paths.
5. **`millis()`-wrap compare** — model two timestamps across the
   UINT32_MAX boundary and assert `(long)(now - deadline) >= 0` vs the
   buggy `now >= deadline`.

## Current state

The `native` env builds a stub test that ensures the harness is wired.
The five tests above are the v3.5.0 target; tracking issue links go
here as they're added.

## Why so little today

The Arduino core's coupling to `Arduino.h` / `String` / `Serial` makes
host-compile tests require mock headers. We have `frame_verify::canonicalize`
isolated enough that it can be tested without the full Arduino mock, but
`OfflineBuffer` depends on `MqttManager` which depends on `PubSubClient`,
and a proper mock harness is a larger yak.

v3.4.9's posture: framework in place, real tests follow. The v3.4.9
archaeology-sweep commit message calls this out explicitly so it doesn't
become another piece of "declared but never used" infrastructure.
