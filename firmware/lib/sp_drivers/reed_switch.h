#pragma once
//
// reed_switch — debounced door-sensor input (Tier 3, GPIO 35 + magnet).
//
// Normally-open reed wired GPIO→GND with a pull-up: pin LOW = magnet near =
// door CLOSED. On the canonical WROOM-32 board the reed sits on GPIO 35, which
// is input-only with NO internal pull (true of GPIO 34-39) — an EXTERNAL 10K to
// 3V3 is required, and the InputPullup mode call below is a harmless no-op
// there. On the S3 (GPIO 12) the internal pull-up is real. 50 ms debounce via
// a settle deadline; the
// node app turns change events into door-open telemetry/alerts and (later)
// automation suspension. Health counts debounced edges (a GPIO reed has
// no failing reads) — an enabled switch stuck at reads=0 flags a dead or
// mis-wired reed in the node health block.
//
// Native-safe; host-tested with scripted pin + manual clock. Header-only.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/gpio.h"
#include "wrap_time.h"

namespace sp {

class ReedSwitch {
public:
    enum class Event : uint8_t { None, Opened, Closed };

    explicit ReedSwitch(GpioPin& pin, uint32_t debounce_ms = 50)
        : pin_(pin), debounce_ms_(debounce_ms) {}

    void begin(uint32_t now_ms) {
        pin_.set_mode(PinMode::InputPullup);
        stable_closed_ = !pin_.read();  // LOW = closed
        candidate_closed_ = stable_closed_;
        settle_at_ms_ = now_ms;
    }

    // Poll every loop pass; returns a debounced edge at most once per change.
    Event update(uint32_t now_ms) {
        bool closed_now = !pin_.read();
        if (closed_now != candidate_closed_) {
            candidate_closed_ = closed_now;
            settle_at_ms_ = now_ms + debounce_ms_;
            return Event::None;
        }
        if (candidate_closed_ != stable_closed_ &&
            deadline_reached(now_ms, settle_at_ms_)) {
            stable_closed_ = candidate_closed_;
            health_.ok();  // a debounced edge is the reed's "read"
            return stable_closed_ ? Event::Closed : Event::Opened;
        }
        return Event::None;
    }

    bool is_closed() const { return stable_closed_; }

    const DriverHealth& health() const { return health_; }

private:
    GpioPin& pin_;
    uint32_t debounce_ms_;
    bool stable_closed_ = true;
    bool candidate_closed_ = true;
    uint32_t settle_at_ms_ = 0;
    DriverHealth health_;
};

}  // namespace sp
