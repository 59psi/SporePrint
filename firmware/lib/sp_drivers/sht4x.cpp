#include "sht4x.h"

#include "sensirion_transport.h"  // crc8_sensirion

namespace sp {

namespace {
constexpr uint8_t kCmdMeasureHigh = 0xFD;
constexpr uint8_t kCmdReadSerial = 0x89;
constexpr uint32_t kMeasureMs = 10;  // datasheet: max 8.3 ms high precision
constexpr uint32_t kSerialMs = 1;
}  // namespace

bool Sht4x::cmd_read6(uint8_t cmd, uint32_t delay_ms, uint16_t words[2]) {
    if (!bus_.write(addr_, &cmd, 1)) return false;
    clock_.delay_ms(delay_ms);
    uint8_t raw[6];
    if (!bus_.read(addr_, raw, sizeof(raw))) return false;
    for (int i = 0; i < 2; ++i) {
        const uint8_t* w = raw + i * 3;
        if (crc8_sensirion(w, 2) != w[2]) return false;
        words[i] = (uint16_t)((w[0] << 8) | w[1]);
    }
    return true;
}

bool Sht4x::probe() {
    uint16_t serial[2];
    return cmd_read6(kCmdReadSerial, kSerialMs, serial);
}

bool Sht4x::measure(float* temp_c, float* rh) {
    uint16_t words[2];
    if (!cmd_read6(kCmdMeasureHigh, kMeasureMs, words)) {
        health_.fail("read error");
        return false;
    }
    *temp_c = -45.0f + 175.0f * (float)words[0] / 65535.0f;
    // SHT4x RH formula differs from SHT3x (offset −6, span 125).
    *rh = -6.0f + 125.0f * (float)words[1] / 65535.0f;
    if (*rh < 0.0f) *rh = 0.0f;
    if (*rh > 100.0f) *rh = 100.0f;
    health_.ok();
    return true;
}

}  // namespace sp
