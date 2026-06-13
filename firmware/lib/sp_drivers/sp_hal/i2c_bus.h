#pragma once
//
// sp_hal::I2cBus — the only way drivers touch I²C.
//
// Device adapter wraps Wire (sp_device/arduino_i2c_bus); host tests use a
// scripted mock that can also assert probe ORDER, which makes autodetect
// itself host-testable. Both phases return false on NACK or timeout —
// drivers treat any false as a read-fail, never as data.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

namespace sp {

class I2cBus {
public:
    virtual ~I2cBus() = default;
    // Write wlen bytes to addr. False on NACK/timeout.
    virtual bool write(uint8_t addr, const uint8_t* wbuf, size_t wlen) = 0;
    // Read rlen bytes from addr. False on NACK/timeout/short read.
    virtual bool read(uint8_t addr, uint8_t* rbuf, size_t rlen) = 0;
};

}  // namespace sp
