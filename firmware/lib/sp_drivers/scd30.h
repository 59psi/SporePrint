#pragma once
//
// scd30 — Sensirion SCD30 NDIR CO₂ driver (alternate, Adafruit 4867).
//
// The awkward one in the family: its measurement read can clock-stretch up
// to ~150 ms, far beyond what the ESP32 I²C peripheral tolerates. The
// driver contract is therefore NEVER READ BLIND — poll the data-ready word
// (0x0202) and only then read the measurement, with the documented ≥3 ms
// command-to-read gaps. A stretch/timeout mid-read is a read-fail, never
// data.
//
// Measurement payload is 6 CRC'd words = 3 big-endian IEEE-754 floats
// (CO₂ ppm, temp °C, RH %). ASC is disabled at begin() for the same
// chamber-never-sees-fresh-air reason as the SCD4x.
//
// Native-safe; float decode covered by a constructed datasheet-style
// vector in the host tests.

#include <stdint.h>

#include "sensirion_transport.h"
#include "sht3x.h"  // DriverHealth

namespace sp {

class Scd30 {
public:
    static constexpr uint8_t kAddr = 0x61;

    Scd30(I2cBus& bus, Clock& clock) : xport_(bus, clock, kAddr) {}

    // Firmware-version read — CRC-valid reply = present.
    bool probe();

    // Disable ASC, start continuous measurement (no pressure compensation).
    bool begin();

    bool data_ready();

    // Read the measurement triple (call only when data_ready()).
    bool read(float* co2_ppm, float* temp_c, float* rh);

    const DriverHealth& health() const { return health_; }

    // Exposed for tests: assemble a big-endian IEEE-754 float from words.
    static float words_to_float(uint16_t hi, uint16_t lo);

private:
    SensirionTransport xport_;
    DriverHealth health_;
};

}  // namespace sp
