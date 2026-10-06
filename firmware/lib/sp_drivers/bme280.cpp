#include "bme280.h"

namespace sp {

namespace {
constexpr uint8_t kRegChipId = 0xD0;
constexpr uint8_t kRegReset = 0xE0;
constexpr uint8_t kRegCalib0 = 0x88;  // 0x88..0xA1, 26 bytes
constexpr uint8_t kRegCalib1 = 0xE1;  // 0xE1..0xE7, 7 bytes (BME280 only)
constexpr uint8_t kRegCtrlHum = 0xF2;
constexpr uint8_t kRegStatus = 0xF3;
constexpr uint8_t kRegCtrlMeas = 0xF4;
constexpr uint8_t kRegConfig = 0xF5;
constexpr uint8_t kRegData = 0xF7;  // press[3] temp[3] (hum[2])

constexpr uint8_t kChipIdBme280 = 0x60;
constexpr uint8_t kResetWord = 0xB6;
constexpr uint8_t kStatusMeasuring = 0x08;
constexpr uint8_t kStatusImUpdate = 0x01;

constexpr uint8_t kCtrlHumX1 = 0x01;       // osrs_h ×1
constexpr uint8_t kConfigFilterOff = 0x00; // t_sb unused in forced mode
constexpr uint8_t kCtrlMeasSleep = 0x24;   // osrs_t ×1, osrs_p ×1, sleep
constexpr uint8_t kCtrlMeasForced = 0x25;  // osrs_t ×1, osrs_p ×1, forced

constexpr uint32_t kStartupMs = 2;   // datasheet t_startup
constexpr uint32_t kMeasureMs = 10;  // datasheet max at ×1/×1/×1: 9.3 ms
constexpr uint32_t kRetryMs = 2;
constexpr int kNvmPolls = 5;

constexpr int32_t kAdcSkipped20 = 0x80000;  // T/P register reset value
constexpr int32_t kAdcSkipped16 = 0x8000;   // H register reset value

constexpr float kTempMinC = -40.0f;  // datasheet operating range
constexpr float kTempMaxC = 85.0f;
constexpr float kPressMinPa = 30000.0f;   // 300 hPa
constexpr float kPressMaxPa = 110000.0f;  // 1100 hPa

uint16_t le_u16(const uint8_t* b) { return (uint16_t)(b[0] | (b[1] << 8)); }
int16_t le_s16(const uint8_t* b) { return (int16_t)le_u16(b); }
}  // namespace

const char* baro_kind_str(BaroKind k) {
    switch (k) {
        case BaroKind::None:   return "none";
        case BaroKind::Bme280: return "bme280";
        case BaroKind::Bmp280: return "bmp280";
    }
    return "none";
}

BaroKind Bme280::identify(I2cBus& bus, uint8_t addr) {
    const uint8_t reg = kRegChipId;
    uint8_t id = 0;
    if (!bus.write(addr, &reg, 1) || !bus.read(addr, &id, 1))
        return BaroKind::None;
    if (id == kChipIdBme280) return BaroKind::Bme280;
    if (id == 0x56 || id == 0x57 || id == 0x58) return BaroKind::Bmp280;
    return BaroKind::None;
}

bool Bme280::parse_calib(const uint8_t c88[26], const uint8_t* ce1,
                         Calib* out) {
    Calib c;
    c.t1 = le_u16(c88 + 0);
    c.t2 = le_s16(c88 + 2);
    c.t3 = le_s16(c88 + 4);
    c.p1 = le_u16(c88 + 6);
    c.p2 = le_s16(c88 + 8);
    c.p3 = le_s16(c88 + 10);
    c.p4 = le_s16(c88 + 12);
    c.p5 = le_s16(c88 + 14);
    c.p6 = le_s16(c88 + 16);
    c.p7 = le_s16(c88 + 18);
    c.p8 = le_s16(c88 + 20);
    c.p9 = le_s16(c88 + 22);
    // c88[24] is register 0xA0 (reserved).
    c.h1 = c88[25];
    if (ce1 != nullptr) {
        c.h2 = le_s16(ce1 + 0);
        c.h3 = ce1[2];
        // dig_H4 / dig_H5 are 12-bit signed values split across 0xE4..0xE6
        // (Bosch BME280_SensorAPI's unpacking: the MSB register is signed).
        c.h4 = (int16_t)((int16_t)(int8_t)ce1[3] * 16 | (ce1[4] & 0x0F));
        c.h5 = (int16_t)((int16_t)(int8_t)ce1[5] * 16 | (ce1[4] >> 4));
        c.h6 = (int8_t)ce1[6];
    }
    // A blank (all-0x00) or floating (all-0xFF) trim read is not a sensor.
    if (c.t1 == 0 || c.p1 == 0) return false;
    if (c.t1 == 0xFFFF && c.p1 == 0xFFFF) return false;
    *out = c;
    return true;
}

// Datasheet §4.2.3 integer compensation. Intermediates are 64-bit (identical
// results wherever the datasheet's 32-bit code does not overflow, and no
// signed-overflow UB where it would); signed left shifts are multiplications.
int32_t Bme280::compensate_t(int32_t adc_t, const Calib& c, int32_t* t_fine) {
    const int64_t t1 = c.t1;
    int64_t var1 = ((((int64_t)adc_t >> 3) - t1 * 2) * (int64_t)c.t2) >> 11;
    int64_t d = ((int64_t)adc_t >> 4) - t1;
    int64_t var2 = (((d * d) >> 12) * (int64_t)c.t3) >> 14;
    *t_fine = (int32_t)(var1 + var2);
    return (int32_t)(((int64_t)*t_fine * 5 + 128) >> 8);
}

uint32_t Bme280::compensate_p(int32_t adc_p, int32_t t_fine, const Calib& c) {
    int64_t var1 = (int64_t)t_fine - 128000;
    int64_t var2 = var1 * var1 * (int64_t)c.p6;
    var2 = var2 + var1 * (int64_t)c.p5 * 131072;         // << 17
    var2 = var2 + (int64_t)c.p4 * 34359738368LL;          // << 35
    var1 = ((var1 * var1 * (int64_t)c.p3) >> 8) + var1 * (int64_t)c.p2 * 4096;
    var1 = ((((int64_t)1) << 47) + var1) * (int64_t)c.p1 >> 33;
    if (var1 == 0) return 0;  // datasheet divide-by-zero guard
    int64_t p = 1048576 - (int64_t)adc_p;
    p = ((p * 2147483648LL - var2) * 3125) / var1;        // p << 31
    var1 = ((int64_t)c.p9 * (p >> 13) * (p >> 13)) >> 25;
    var2 = ((int64_t)c.p8 * p) >> 19;
    p = ((p + var1 + var2) >> 8) + (int64_t)c.p7 * 16;    // << 4
    return (uint32_t)p;
}

uint32_t Bme280::compensate_h(int32_t adc_h, int32_t t_fine, const Calib& c) {
    int64_t v = (int64_t)t_fine - 76800;
    int64_t a = ((int64_t)adc_h * 16384 - (int64_t)c.h4 * 1048576 -
                 (int64_t)c.h5 * v + 16384) >> 15;
    int64_t b = (((((((v * (int64_t)c.h6) >> 10) *
                     (((v * (int64_t)c.h3) >> 11) + 32768)) >> 10) +
                   2097152) * (int64_t)c.h2 + 8192) >> 14);
    v = a * b;
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int64_t)c.h1) >> 4);
    if (v < 0) v = 0;
    if (v > 419430400) v = 419430400;
    return (uint32_t)(v >> 12);
}

bool Bme280::write_reg(uint8_t reg, uint8_t value) {
    const uint8_t buf[2] = {reg, value};
    return bus_.write(addr_, buf, sizeof(buf));
}

bool Bme280::read_regs(uint8_t reg, uint8_t* buf, size_t len) {
    return bus_.write(addr_, &reg, 1) && bus_.read(addr_, buf, len);
}

bool Bme280::begin() {
    ready_ = false;
    if (!write_reg(kRegReset, kResetWord)) {
        health_.fail("reset failed");
        return false;
    }
    clock_.delay_ms(kStartupMs);
    // The trimming parameters are copied from NVM after a reset; reading
    // them mid-copy returns garbage.
    uint8_t status = kStatusImUpdate;
    for (int i = 0; i < kNvmPolls; ++i) {
        if (!read_regs(kRegStatus, &status, 1)) {
            health_.fail("read error");
            return false;
        }
        if ((status & kStatusImUpdate) == 0) break;
        clock_.delay_ms(kRetryMs);
    }
    if ((status & kStatusImUpdate) != 0) {
        health_.fail("nvm copy timeout");
        return false;
    }
    uint8_t c88[26];
    uint8_t ce1[7];
    if (!read_regs(kRegCalib0, c88, sizeof(c88)) ||
        (has_humidity() && !read_regs(kRegCalib1, ce1, sizeof(ce1)))) {
        health_.fail("read error");
        return false;
    }
    if (!parse_calib(c88, has_humidity() ? ce1 : nullptr, &calib_)) {
        health_.fail("bad calibration");
        return false;
    }
    // ctrl_hum only takes effect after a ctrl_meas write — write it first.
    if ((has_humidity() && !write_reg(kRegCtrlHum, kCtrlHumX1)) ||
        !write_reg(kRegConfig, kConfigFilterOff) ||
        !write_reg(kRegCtrlMeas, kCtrlMeasSleep)) {
        health_.fail("config failed");
        return false;
    }
    ready_ = true;
    return true;
}

bool Bme280::measure(float* temp_c, float* pressure_pa, float* rh) {
    if (!ready_ && !begin()) return false;  // begin() recorded the failure

    if ((has_humidity() && !write_reg(kRegCtrlHum, kCtrlHumX1)) ||
        !write_reg(kRegCtrlMeas, kCtrlMeasForced)) {
        health_.fail("trigger failed");
        return false;
    }
    clock_.delay_ms(kMeasureMs);

    uint8_t status = 0;
    if (!read_regs(kRegStatus, &status, 1)) {
        health_.fail("read error");
        return false;
    }
    if ((status & kStatusMeasuring) != 0) {
        clock_.delay_ms(kRetryMs);
        if (!read_regs(kRegStatus, &status, 1) ||
            (status & kStatusMeasuring) != 0) {
            health_.fail("busy");
            return false;
        }
    }

    uint8_t d[8];
    const size_t n = has_humidity() ? 8 : 6;
    if (!read_regs(kRegData, d, n)) {
        health_.fail("read error");
        return false;
    }
    const int32_t adc_p = (int32_t)(((uint32_t)d[0] << 12) |
                                    ((uint32_t)d[1] << 4) | (d[2] >> 4));
    const int32_t adc_t = (int32_t)(((uint32_t)d[3] << 12) |
                                    ((uint32_t)d[4] << 4) | (d[5] >> 4));
    const int32_t adc_h =
        has_humidity() ? (int32_t)(((uint32_t)d[6] << 8) | d[7]) : 0;
    // Register reset values = "no conversion happened" (the forced trigger
    // was lost) — never compensate those into a plausible-looking reading.
    if (adc_t == kAdcSkipped20 || adc_p == kAdcSkipped20 ||
        (has_humidity() && adc_h == kAdcSkipped16)) {
        health_.fail("no sample");
        return false;
    }

    int32_t t_fine = 0;
    const float t = (float)compensate_t(adc_t, calib_, &t_fine) / 100.0f;
    const uint32_t p_q8 = compensate_p(adc_p, t_fine, calib_);
    const float p = (float)p_q8 / 256.0f;
    if (p_q8 == 0 || !(t >= kTempMinC && t <= kTempMaxC) ||
        !(p >= kPressMinPa && p <= kPressMaxPa)) {
        health_.fail("out-of-range");
        return false;
    }
    *temp_c = t;
    *pressure_pa = p;
    if (has_humidity())
        *rh = (float)compensate_h(adc_h, t_fine, calib_) / 1024.0f;
    health_.ok();
    return true;
}

}  // namespace sp
