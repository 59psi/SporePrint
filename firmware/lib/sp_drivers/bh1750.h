#pragma once
//
// bh1750 — ROHM BH1750 ambient light driver (Adafruit 4681).
// Single-byte opcodes, 2-byte big-endian result, lux = raw / 1.2.
// Continuous high-res mode; reads are 2-byte transactions, no waiting.
//
// Re-armed on every read: the BH1750 has no status register, and one that
// lost power (a loose connector) wakes in power-down and answers 0x0000 — a
// "healthy" 0 lx — for as long as nobody restarts it. read() therefore
// re-sends power-on + continuous high-res after each read (two 1-byte
// writes). While it runs that is harmless: the result register keeps the
// last conversion until the next one completes (~120-180 ms, well inside
// any read interval). It also finishes a begin() that failed at boot.
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

    // Read the last conversion, then re-arm continuous mode (see above).
    // A failed re-arm is not a read failure: the next read shows whether
    // the part is still on the bus.
    bool read(float* lux);

    const DriverHealth& health() const { return health_; }

private:
    I2cBus& bus_;
    uint8_t addr_;
    DriverHealth health_;
};

}  // namespace sp
