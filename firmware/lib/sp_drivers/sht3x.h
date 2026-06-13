#pragma once
//
// sht3x — Sensirion SHT3x-D temperature/humidity driver (canonical SHT31-D,
// Adafruit 2857). Polling (no-clock-stretch) single-shot measurements only:
// the ESP32 I²C peripheral cannot ride out long stretches.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sensirion_transport.h"

namespace sp {

struct DriverHealth {
    uint32_t reads = 0;
    uint32_t fails = 0;
    const char* last_error = nullptr;  // static strings only

    void ok() { ++reads; last_error = nullptr; }
    void fail(const char* why) {
        ++reads;
        ++fails;
        last_error = why;
    }
};

class Sht3x {
public:
    static constexpr uint8_t kAddrPrimary = 0x44;
    static constexpr uint8_t kAddrAlt = 0x45;

    Sht3x(I2cBus& bus, Clock& clock, uint8_t addr = kAddrPrimary)
        : xport_(bus, clock, addr) {}

    // Soft-reset then read the serial word pair — CRC-valid serial = present.
    // The soft reset also clears any half-parsed command state left by an
    // SHT4x probe on the same address (the 0x44 disambiguation dance).
    bool probe();

    // Single-shot high-repeatability measurement (polling mode, ~16 ms).
    bool measure(float* temp_c, float* rh);

    const DriverHealth& health() const { return health_; }

private:
    SensirionTransport xport_;
    DriverHealth health_;
};

}  // namespace sp
