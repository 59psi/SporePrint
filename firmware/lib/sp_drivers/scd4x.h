#pragma once
//
// scd4x — Sensirion SCD40/41/43 CO₂ driver (canonical SCD41, Adafruit 5190).
//
// Periodic mode is the ONLY mode used: SCD40 has no single-shot, and
// variant detection only exists on newer chip firmware — periodic works on
// every family member.
//
// ASC (automatic self-calibration) is forced OFF at begin(): ASC assumes
// the sensor sees fresh ~400 ppm air weekly, which a fruiting chamber
// never does — left on (the factory default!) it silently drags the
// baseline down over weeks. Calibration is operator-driven via forced
// recalibration (FRC) against a known reference ppm — wired to the
// `cmd/config {calibrate_co2: <target_ppm>}` command. The old firmware's
// handler *enabled ASC* when asked to calibrate, the exact opposite of
// correct for this domain.
//
// Reads are data-ready gated; each call is a couple of short transactions
// well inside the 50 ms loop budget. begin()/recalibrate() block longer
// (500/800 ms datasheet waits) but only run at boot or on explicit command.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sensirion_transport.h"
#include "sht3x.h"  // DriverHealth

namespace sp {

class Scd4x {
public:
    static constexpr uint8_t kAddr = 0x62;

    Scd4x(I2cBus& bus, Clock& clock) : xport_(bus, clock, kAddr), clock_(clock) {}

    // Serial-number probe (works in idle mode only — call before begin()).
    bool probe();

    // Stop any stale periodic mode, disable ASC, persist the ASC setting
    // if it changed (EEPROM-wear-aware), start periodic measurement.
    bool begin();

    // True when a fresh measurement is available.
    bool data_ready();

    // Read the current measurement (call only when data_ready()).
    bool read(uint16_t* co2_ppm, float* temp_c, float* rh);

    // Forced recalibration against a reference ppm. Blocks ~900 ms
    // (datasheet stop/FRC waits). Returns false if the sensor reports
    // 0xFFFF (FRC failed — e.g. insufficient prior runtime). Restarts
    // periodic mode either way.
    bool recalibrate(uint16_t reference_ppm);

    const DriverHealth& health() const { return health_; }

private:
    SensirionTransport xport_;
    Clock& clock_;
    DriverHealth health_;
};

}  // namespace sp
