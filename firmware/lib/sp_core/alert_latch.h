#pragma once
//
// alert_latch — rate-limit node alerts to state changes.
//
// check_alerts() runs after every sensor read pass (default 30 s, 1 s
// minimum) and used to publish an alert for every pass a condition held: a
// fruiting chamber sitting at 100 % RH (or a dead SHT) produced 2,880
// alerts/day per condition, each forwarded to the cloud event channel,
// burying the real ones.
//
// AlertLatch fires once on ENTRY into a condition, then at most once per
// reminder interval while it persists, and re-arms only after the condition
// clears. ThresholdAlert adds hysteresis on top: a value that entered above
// `limit` must fall back below `limit - margin` before it counts as cleared,
// so chatter around the limit cannot re-fire it.
//
// Two-phase on purpose: due() says an alert should go out; the caller calls
// emitted() only when the publish actually succeeded, so an alert raised
// while MQTT is down is delivered on reconnect instead of being lost.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

#include "wrap_time.h"

namespace sp {

// Reminder cadence while a condition persists.
constexpr uint32_t kAlertReemitMs = 60UL * 60UL * 1000UL;

class AlertLatch {
public:
    explicit AlertLatch(uint32_t reemit_ms = kAlertReemitMs)
        : reemit_ms_(reemit_ms) {}

    // Feed the current condition; true when an alert should be published now.
    bool due(bool condition, uint32_t now_ms) {
        if (!condition) {
            active_ = false;
            pending_ = false;
            return false;
        }
        if (!active_) {  // entry
            active_ = true;
            pending_ = true;
        }
        if (pending_) return true;
        return elapsed_ms(now_ms, last_emit_ms_) >= reemit_ms_;
    }

    // The alert due() asked for was actually published.
    void emitted(uint32_t now_ms) {
        pending_ = false;
        last_emit_ms_ = now_ms;
    }

    bool active() const { return active_; }

private:
    uint32_t reemit_ms_;
    bool active_ = false;
    bool pending_ = false;
    uint32_t last_emit_ms_ = 0;
};

class ThresholdAlert {
public:
    enum class Dir : uint8_t { Above, Below };

    ThresholdAlert(Dir dir, float limit, float margin,
                   uint32_t reemit_ms = kAlertReemitMs)
        : dir_(dir), limit_(limit), margin_(margin), latch_(reemit_ms) {}

    // NaN compares false everywhere, so an invalid value clears the alert.
    bool due(float value, uint32_t now_ms) {
        bool in_alarm;
        if (dir_ == Dir::Above) {
            in_alarm = latch_.active() ? value > limit_ - margin_ : value > limit_;
        } else {
            in_alarm = latch_.active() ? value < limit_ + margin_ : value < limit_;
        }
        return latch_.due(in_alarm, now_ms);
    }

    void emitted(uint32_t now_ms) { latch_.emitted(now_ms); }
    bool active() const { return latch_.active(); }

private:
    Dir dir_;
    float limit_;
    float margin_;
    AlertLatch latch_;
};

}  // namespace sp
