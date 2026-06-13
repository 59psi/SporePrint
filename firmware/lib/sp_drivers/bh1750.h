#pragma once
//
// bh1750 — ROHM BH1750 ambient light driver (Adafruit 4681).
// Single-byte opcodes, 2-byte big-endian result, lux = raw / 1.2.
// Continuous high-res mode: start once, read any time after first
// conversion (~180 ms); reads are 2-byte transactions, no waiting.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/i2c_bus.h"

namespace sp {

class Bh1750 {
public:
    static constexpr uint8_t kAddrLow = 0x23;   // ADDR pin low (default)
    static constexpr uint8_t kAddrHigh = 0x5C;  // ADDR pin high

    explicit Bh1750(I2cBus& bus, uint8_t addr = kAddrLow)
        : bus_(bus), addr_(addr) {}

    // Power-on opcode ACK = present.
    bool probe();

    // Power on + continuous high-res mode (1 lx resolution).
    bool begin();

    bool read(float* lux);

    const DriverHealth& health() const { return health_; }

private:
    I2cBus& bus_;
    uint8_t addr_;
    DriverHealth health_;
};

}  // namespace sp
