#pragma once
//
// bme280 — Bosch BME280 (pressure + temperature + humidity) and BMP280
// (pressure + temperature) driver, I²C 0x76 (SDO low — most GY-BME280 /
// GY-BMP280 modules) or 0x77 (SDO high — Adafruit boards, the BMP280 on
// "AHT20 + BMP280" combo boards).
//
// Why it exists: the architecture diagram showed an optional BME280 on the
// climate node ("BME280 Pressure", later "Optional BME280") from the initial
// release until 2026-09, and the shopping alternates listed an AHT20 + BMP280
// combo — but no firmware ever drove either. Pressure rides in telemetry as
// the additive `pressure_hpa` key; a BME280's temp/RH is a FALLBACK source
// only (below SHT3x/SHT4x and AHT20 — its humidity element is slow and
// drifts near condensation, which a fruiting chamber lives at).
//
// Identification is by the chip-ID register 0xD0, which tells the two apart
// (and rejects look-alikes at the same addresses):
//   0x60 BME280 · 0x58 BMP280 (0x56 / 0x57 = BMP280 engineering samples)
//   0x61 BME680 / 0x55 BMP180 — different parts, NOT supported, rejected
// Cheap "BME280" listings frequently ship a BMP280: it is detected as one,
// publishes pressure only, and never pretends to have humidity.
//
// Measurement: forced mode, ×1 oversampling on every channel, IIR filter off
// — the datasheet's "weather monitoring" setting. One read pass writes
// ctrl_hum + ctrl_meas (re-asserted every time, so a part that browned out
// and lost its config recovers on the next pass), waits the datasheet
// maximum conversion time (9.3 ms), checks the status register and burst-
// reads the data block. Well inside the 50 ms per-call budget.
//
// Compensation is the datasheet's integer code verbatim (32-bit T and H,
// 64-bit P), with signed left shifts written as multiplications. Pinned in
// the host tests against the BMP280 datasheet's worked example (T 25.08 °C,
// t_fine 128422, p 100653.27 Pa) and, for humidity, against the datasheet's
// double-precision formula.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/clock.h"
#include "sp_hal/i2c_bus.h"

namespace sp {

enum class BaroKind : uint8_t { None, Bme280, Bmp280 };

const char* baro_kind_str(BaroKind k);

class Bme280 {
public:
    static constexpr uint8_t kAddrPrimary = 0x76;  // SDO → GND
    static constexpr uint8_t kAddrAlt = 0x77;      // SDO → VDDIO

    // Trimming parameters (datasheet table 16 / 18).
    struct Calib {
        uint16_t t1 = 0;
        int16_t t2 = 0, t3 = 0;
        uint16_t p1 = 0;
        int16_t p2 = 0, p3 = 0, p4 = 0, p5 = 0, p6 = 0, p7 = 0, p8 = 0, p9 = 0;
        uint8_t h1 = 0;
        int16_t h2 = 0;
        uint8_t h3 = 0;
        int16_t h4 = 0, h5 = 0;
        int8_t h6 = 0;
    };

    Bme280(I2cBus& bus, Clock& clock, uint8_t addr, BaroKind kind)
        : bus_(bus), clock_(clock), addr_(addr), kind_(kind) {}

    // Chip-ID read at `addr`: which part answered (None = no ACK, or an ID
    // this driver does not speak).
    static BaroKind identify(I2cBus& bus, uint8_t addr);

    // Soft reset, wait for the NVM copy, read + sanity-check the trimming
    // parameters, configure (filter off, sleep). measure() retries this
    // itself while it has not succeeded.
    bool begin();

    // One forced-mode conversion. Pressure in Pa; temp in °C; *rh is set
    // only for a BME280 (has_humidity()) and left untouched for a BMP280.
    bool measure(float* temp_c, float* pressure_pa, float* rh);

    bool has_humidity() const { return kind_ == BaroKind::Bme280; }
    BaroKind kind() const { return kind_; }
    uint8_t addr() const { return addr_; }
    const DriverHealth& health() const { return health_; }

    // ── pure helpers, exposed for the host tests ──
    // c88 = registers 0x88..0xA1 (26 bytes); ce1 = 0xE1..0xE7 (7 bytes, BME280
    // only — pass nullptr for a BMP280). False on an obviously blank trim set.
    static bool parse_calib(const uint8_t c88[26], const uint8_t* ce1, Calib* out);
    // °C × 100 (5123 = 51.23 °C); also yields t_fine for P and H.
    static int32_t compensate_t(int32_t adc_t, const Calib& c, int32_t* t_fine);
    // Pa in Q24.8 (value / 256 = Pa); 0 = the datasheet's divide-by-zero guard.
    static uint32_t compensate_p(int32_t adc_p, int32_t t_fine, const Calib& c);
    // %RH in Q22.10 (value / 1024 = %RH), clamped 0..100 %.
    static uint32_t compensate_h(int32_t adc_h, int32_t t_fine, const Calib& c);

private:
    bool write_reg(uint8_t reg, uint8_t value);
    bool read_regs(uint8_t reg, uint8_t* buf, size_t len);

    I2cBus& bus_;
    Clock& clock_;
    uint8_t addr_;
    BaroKind kind_;
    Calib calib_;
    bool ready_ = false;
    DriverHealth health_;
};

}  // namespace sp
