#pragma once
//
// autodetect — I²C sensor identification at boot.
//
// Posture: probe the known addresses and report what answered; every sensor
// that answers is used. What the node app then treats as MISSING is narrow
// (src/node/main.cpp publish_health / check_alerts):
//   * temp_rh — only a CLIMATE-personality node is expected to carry a
//     temp/RH sensor; one with no SHT on the bus lists `temp_rh` in
//     expected_missing (relay/lighting banks are sensorless by design)
//   * CO2 / lux found here are opportunistic: never listed when absent at
//     boot, but once found, a sensor that stops delivering goes stale and
//     raises a sensor_failure alert (freshness.h)
//   * the config-flag peripherals below are listed when enabled but not
//     delivering (mhz19, hx711) — except the reed switch, which cannot be
//     told apart from a closed door and is never listed
//
// The 0x44/0x45 dance: SHT3x and SHT4x share addresses but not protocols
// (the v4.1 BOM bug). Probe SHT4x FIRST — its single-byte 0x89 serial read
// with CRC validation cannot false-positive against an SHT3x (which NACKs
// or returns CRC garbage for that sequence). On failure, the SHT3x probe
// opens with a soft-reset that clears any half-parsed command state the
// 4x probe left behind.
//
// Probed after the original set (so the order above is unchanged):
//   0x38       AHT20 / AHT21 / AHT25 — CRC-gated: one real measurement
//              (~90 ms, boot-only) because an ACK at 0x38 proves nothing
//   0x76/0x77  BME280 / BMP280 — chip-ID gated (0x60 / 0x56-0x58); a BME680
//              or BMP180 at the same address is rejected, not misread
// No address in the supported set collides with another: SHT 0x44/0x45,
// SCD30 0x61, SCD4x 0x62, BH1750 0x23/0x5C, AHT2x 0x38, BMx280 0x76/0x77.
//
// UART CO₂ (MH-Z19B/C), HX711, and the reed switch are config-flag
// peripherals — never probed here (floating pins lie; UART can't
// enumerate; the MH-Z19 needs ~3 min warmup).
//
// Native-safe; probe ORDER is asserted by the host tests via the
// transaction-scripted mock bus.

#include <stdint.h>

#include "bme280.h"  // BaroKind
#include "sp_hal/clock.h"
#include "sp_hal/i2c_bus.h"

namespace sp {

enum class TempRhKind : uint8_t { None, Sht3x, Sht4x };
enum class Co2Kind : uint8_t { None, Scd4x, Scd30 };

struct DetectedSensors {
    TempRhKind temp_rh = TempRhKind::None;
    uint8_t temp_rh_addr = 0;
    Co2Kind co2 = Co2Kind::None;
    bool bh1750 = false;
    uint8_t bh1750_addr = 0;
    bool aht20 = false;  // 0x38 (fixed address)
    BaroKind baro = BaroKind::None;
    uint8_t baro_addr = 0;
};

// Probe the climate-sensor addresses (0x44/0x45 SHT, 0x62 SCD4x, 0x61
// SCD30, 0x23/0x5C BH1750, 0x38 AHT2x, 0x76/0x77 BMx280). Each probe is
// CRC-, chip-ID- or ACK-gated and bounded by the bus timeout — a few ms per
// address, plus the SCD4x's datasheet 500 ms stop_periodic wait and the
// AHT20's ~90 ms conversion when those are present (boot-only, pre-WDT: the
// SCD4x probe must stop a periodic mode left running by a warm reboot before
// get_serial will answer).
DetectedSensors autodetect_i2c(I2cBus& bus, Clock& clock);

const char* temp_rh_kind_str(TempRhKind k);
const char* co2_kind_str(Co2Kind k);

}  // namespace sp
