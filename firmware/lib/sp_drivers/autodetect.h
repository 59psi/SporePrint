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
// UART CO₂ (MH-Z19C), HX711, and the reed switch are config-flag
// peripherals — never probed here (floating pins lie; UART can't
// enumerate; MH-Z19C needs ~3 min warmup).
//
// Native-safe; probe ORDER is asserted by the host tests via the
// transaction-scripted mock bus.

#include <stdint.h>

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
};

// Probe the climate-sensor addresses (0x44/0x45 SHT, 0x62 SCD4x, 0x61
// SCD30, 0x23/0x5C BH1750). Each probe is CRC- or ACK-gated and bounded by
// the bus timeout — a few ms per address, plus the SCD4x's datasheet
// 500 ms stop_periodic wait when one is present (boot-only, pre-WDT: the
// probe must stop a periodic mode left running by a warm reboot before
// get_serial will answer).
DetectedSensors autodetect_i2c(I2cBus& bus, Clock& clock);

const char* temp_rh_kind_str(TempRhKind k);
const char* co2_kind_str(Co2Kind k);

}  // namespace sp
