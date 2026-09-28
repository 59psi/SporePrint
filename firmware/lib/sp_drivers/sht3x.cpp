#include "sht3x.h"

namespace sp {

namespace {
constexpr uint16_t kCmdSoftReset = 0x30A2;
constexpr uint16_t kCmdReadSerial = 0x3780;
// Single-shot, high repeatability, clock stretching DISABLED (polling).
constexpr uint16_t kCmdMeasureHighRep = 0x2400;
constexpr uint32_t kSoftResetMs = 2;     // datasheet: max 1.5 ms
constexpr uint32_t kSerialDelayMs = 1;
constexpr uint32_t kMeasureMs = 16;      // datasheet: max 15.5 ms high-rep
}  // namespace

bool Sht3x::probe() {
    if (!xport_.cmd(kCmdSoftReset)) return false;
    // The reset must complete BEFORE the next transaction: the SHT3x NACKs
    // its address until it is back in idle (up to 1.5 ms), and a serial
    // read issued straight after the reset ACK (~0.1 ms later at 100 kHz)
    // would NACK and make a present SHT31-D look absent. cmd_read's own
    // settle runs AFTER its command write, so it cannot cover this gap.
    clock_.delay_ms(kSoftResetMs);
    // Serial read with CRC — a CRC-valid reply is the presence criterion
    // (a NACKing or garbage device fails here).
    uint16_t serial[2];
    return xport_.cmd_read(kCmdReadSerial, kSerialDelayMs, serial, 2);
}

bool Sht3x::measure(float* temp_c, float* rh) {
    uint16_t words[2];
    if (!xport_.cmd_read(kCmdMeasureHighRep, kMeasureMs, words, 2)) {
        health_.fail("read error");
        return false;
    }
    *temp_c = -45.0f + 175.0f * (float)words[0] / 65535.0f;
    *rh = 100.0f * (float)words[1] / 65535.0f;
    if (*rh < 0.0f) *rh = 0.0f;
    if (*rh > 100.0f) *rh = 100.0f;
    health_.ok();
    return true;
}

}  // namespace sp
