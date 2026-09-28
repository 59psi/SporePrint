#pragma once
//
// freshness — "when did this sensor last give us a good sample?"
//
// The node used to latch have_co2 / have_lux / have_hx711 true on the first
// good read and never clear them, so a CO2 sensor that fell off the bus (or
// an MH-Z19C that stopped answering) kept publishing its last value every
// minute as if it were fresh. Frozen at 600 ppm, the Pi's FAE and 3000 ppm
// emergency-exhaust rules never fired while real CO2 climbed; frozen high,
// FAE ran forever. ReadingFreshness is the per-sensor clock the composition
// root checks each read pass: past the window, the reading is dropped from
// telemetry and a sensor_failure alert goes out.
//
// arm() starts the clock when the driver is created, so a declared sensor
// that never produces a single sample (unwired HX711, MH-Z19C on the wrong
// pins) goes stale too — declared-but-missing is an alert, not silence.
//
// Wrap-safe: once stale it stays stale until mark_ok(), so the unsigned
// elapsed math wrapping after ~49.7 days can never flip it back to fresh.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

#include "wrap_time.h"

namespace sp {

// Minimum staleness window. SCD4x publishes every 5 s and SCD30 every 2 s;
// with the 1 s minimum read interval a 3x-cadence window alone would flag a
// healthy periodic sensor between samples.
constexpr uint32_t kMinStaleWindowMs = 30000;

// A reading is stale when no good sample arrived within 3 read passes (and
// never sooner than kMinStaleWindowMs).
inline uint32_t stale_window_ms(uint32_t read_interval_ms) {
    uint32_t w = read_interval_ms * 3u;  // read interval clamps to <= 10 min
    return w < kMinStaleWindowMs ? kMinStaleWindowMs : w;
}

class ReadingFreshness {
public:
    // Start the clock (driver created). Never-armed trackers are never stale.
    void arm(uint32_t now_ms) {
        armed_ = true;
        last_ok_ms_ = now_ms;
        stale_ = false;
    }

    // A good sample arrived.
    void mark_ok(uint32_t now_ms) {
        armed_ = true;
        ever_ok_ = true;
        last_ok_ms_ = now_ms;
        stale_ = false;
    }

    // Evaluate at `now_ms`; returns is_stale(). Latches until mark_ok().
    bool check_stale(uint32_t now_ms, uint32_t window_ms) {
        if (armed_ && !stale_ && elapsed_ms(now_ms, last_ok_ms_) > window_ms)
            stale_ = true;
        return stale_;
    }

    bool is_stale() const { return stale_; }
    bool ever_ok() const { return ever_ok_; }

private:
    bool armed_ = false;
    bool ever_ok_ = false;
    bool stale_ = false;
    uint32_t last_ok_ms_ = 0;
};

}  // namespace sp
