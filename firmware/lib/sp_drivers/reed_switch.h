#pragma once
//
// reed_switch — debounced door-sensor input (Tier 3, GPIO 35 + magnet).
//
// Default convention: a contact that is CLOSED while the magnet is present
// (a bare normally-open reed, or an alarm door contact wired COM + its "NC"
// terminal), wired GPIO→GND with a pull-up: pin LOW = magnet near = door
// CLOSED. On the canonical WROOM-32 board the reed sits on GPIO 35, which is
// input-only with NO internal pull (true of GPIO 34-39) — an EXTERNAL 10K to
// 3V3 is required, and the InputPullup mode call below is a harmless no-op
// there. On the S3 (GPIO 12) the internal pull-up is real.
//
// `invert` (NVS reed_inv, portal checkbox, cmd/config peripherals.reed_inv):
// for a contact that is OPEN while the magnet is present (an alarm contact
// wired on its NO lead) — pin HIGH = door CLOSED. Default false = the
// convention above, so nodes that never set it behave exactly as before.
//
// 50 ms debounce via a settle deadline; the node app turns change events into
// door-open telemetry/alerts. Health counts debounced edges (a GPIO reed has
// no failing reads). That count is informational only: a correctly wired
// switch on a door that stays shut legitimately produces no edges, so an
// unwired or dead reed is electrically indistinguishable from a closed door
// and is deliberately NOT flagged (never listed in expected_missing).
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

    explicit ReedSwitch(GpioPin& pin, uint32_t debounce_ms = 50,
                        bool invert = false)
        : pin_(pin), debounce_ms_(debounce_ms), invert_(invert) {}

    void begin(uint32_t now_ms) {
        pin_.set_mode(PinMode::InputPullup);
        rebaseline(now_ms);
    }

    // Change the level convention at runtime (cmd/config). The stored state
    // is re-read under the new convention WITHOUT an event: the door did not
    // move, only its interpretation was corrected.
    void set_invert(bool invert, uint32_t now_ms) {
        if (invert == invert_) return;
        invert_ = invert;
        rebaseline(now_ms);
    }

    bool inverted() const { return invert_; }

    // Poll every loop pass; returns a debounced edge at most once per change.
    Event update(uint32_t now_ms) {
        bool closed_now = read_closed();
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
    // LOW = closed by default; HIGH = closed when inverted.
    bool read_closed() { return pin_.read() == invert_; }

    void rebaseline(uint32_t now_ms) {
        stable_closed_ = read_closed();
        candidate_closed_ = stable_closed_;
        settle_at_ms_ = now_ms;
    }

    GpioPin& pin_;
    uint32_t debounce_ms_;
    bool invert_;
    bool stable_closed_ = true;
    bool candidate_closed_ = true;
    uint32_t settle_at_ms_ = 0;
    DriverHealth health_;
};

}  // namespace sp
