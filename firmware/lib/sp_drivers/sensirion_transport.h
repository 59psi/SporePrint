#pragma once
//
// sensirion_transport — shared wire framing for the Sensirion I²C family
// (SHT3x, SCD4x, SCD30; SHT4x uses single-byte commands and talks to the
// bus directly, but reuses crc8_sensirion + word helpers).
//
// All four parts share one transaction shape: 16-bit big-endian command,
// then data as 16-bit big-endian words EACH followed by CRC-8 (poly 0x31,
// init 0xFF — datasheet check vector: 0xBEEF → 0x92). The transport
// CRC-checks every word at this layer so no driver ever sees garbage —
// which is also what makes autodetect probes trustworthy.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include "sp_hal/clock.h"
#include "sp_hal/i2c_bus.h"

namespace sp {

uint8_t crc8_sensirion(const uint8_t* data, size_t len);

class SensirionTransport {
public:
    SensirionTransport(I2cBus& bus, Clock& clock, uint8_t addr)
        : bus_(bus), clock_(clock), addr_(addr) {}

    uint8_t addr() const { return addr_; }

    // Bare 16-bit command, no data.
    bool cmd(uint16_t c);

    // Command + one argument word (with CRC).
    bool cmd_arg(uint16_t c, uint16_t arg);

    // Command, settle delay, then read n words — every word CRC-verified.
    bool cmd_read(uint16_t c, uint32_t delay_ms, uint16_t* words, size_t n);

    // Read n CRC'd words without a preceding command (SCD30 measurement
    // reads re-address the chip directly).
    bool read_words(uint16_t* words, size_t n);

    static constexpr size_t kMaxWords = 9;  // SCD30 measurement = 6 words

private:
    I2cBus& bus_;
    Clock& clock_;
    uint8_t addr_;
};

}  // namespace sp
