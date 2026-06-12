#pragma once
//
// reed_switch — debounced door-sensor input (Tier 3, GPIO 35 + magnet).
//
// Normally-open reed wired GPIO→GND with the internal pullup: pin LOW =
// magnet near = door CLOSED. 50 ms debounce via a settle deadline; the
// node app turns change events into door-open telemetry/alerts and (later)
// automation suspension.
//
// Native-safe; host-tested with scripted pin + manual clock. Header-only.

#include <stdint.h>

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
            return stable_closed_ ? Event::Closed : Event::Opened;
        }
        return Event::None;
    }

    bool is_closed() const { return stable_closed_; }

private:
    GpioPin& pin_;
    uint32_t debounce_ms_;
    bool stable_closed_ = true;
    bool candidate_closed_ = true;
    uint32_t settle_at_ms_ = 0;
};

}  // namespace sp
