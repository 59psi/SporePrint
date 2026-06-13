#pragma once
//
// sht4x — Sensirion SHT4x temperature/humidity driver (SHT40/41/45).
//
// Shares I²C address 0x44 with the SHT3x family but speaks a DIFFERENT
// protocol: single-BYTE commands (0xFD measure, 0x89 serial) instead of
// 16-bit. This is exactly why the v4.1 "SHT45 is a drop-in" BOM promotion
// silently failed — same address, different command set. Autodetect
// disambiguates by probing SHT4x first (0x89 + CRC), then soft-resetting
// and probing SHT3x.
//
// Data framing (words + CRC-8 0x31) matches the rest of the family, so the
// shared crc helper applies; only command emission differs. RH conversion
// also differs from SHT3x: rh = -6 + 125 * raw / 65535.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/clock.h"
#include "sp_hal/i2c_bus.h"

namespace sp {

class Sht4x {
public:
    static constexpr uint8_t kAddrPrimary = 0x44;
    static constexpr uint8_t kAddrAlt = 0x45;  // SHT45-AD1B variant

    Sht4x(I2cBus& bus, Clock& clock, uint8_t addr = kAddrPrimary)
        : bus_(bus), clock_(clock), addr_(addr) {}

    // Read the 32-bit serial via 0x89 — CRC-valid reply = SHT4x present.
    bool probe();

    // High-precision measurement (0xFD, ~9 ms).
    bool measure(float* temp_c, float* rh);

    const DriverHealth& health() const { return health_; }

private:
    bool cmd_read6(uint8_t cmd, uint32_t delay_ms, uint16_t words[2]);

    I2cBus& bus_;
    Clock& clock_;
    uint8_t addr_;
    DriverHealth health_;
};

}  // namespace sp
