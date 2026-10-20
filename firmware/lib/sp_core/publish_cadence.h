#pragma once
//
// publish_cadence — when the periodic publishes are due.
//
// Telemetry (+ health) follows the operator-tunable publish_interval_ms
// (cmd/config, clamped 5 s .. 1 h). The status heartbeat must NOT: the Pi
// marks a node offline — and pages — when no status/* frame arrived for 900 s
// (server/app/main.py _NODE_OFFLINE_THRESHOLD_SECONDS), so a heartbeat that
// only rode along with telemetry flapped every node set to publish every
// 15 min or more offline/online, once per cycle.
//
// The heartbeat runs on its own clock: min(publish_interval_ms, 5 min)
// (CLAUDE.md §5a "Heartbeat every 5 min"). At the 60 s default both fire on
// the same pass, exactly as before.
//
// Wrap-safe (elapsed-ms math). Native-safe: no Arduino headers.

#include <stdint.h>

#include "wrap_time.h"

namespace sp {

class PublishCadence {
public:
    // Longest gap between heartbeats — a third of the Pi's 900 s offline
    // threshold, so two lost heartbeats still don't page.
    static constexpr uint32_t kMaxHeartbeatIntervalMs = 5UL * 60UL * 1000UL;

    struct Due {
        bool telemetry = false;  // telemetry + health
        bool heartbeat = false;  // status/heartbeat
    };

    explicit PublishCadence(uint32_t publish_interval_ms)
        : publish_ms_(publish_interval_ms) {}

    // Both clocks count from `now_ms` (default: 0, i.e. boot — the first
    // publish happens one interval after power-on, as it always has).
    void begin(uint32_t now_ms) {
        last_publish_ms_ = now_ms;
        last_heartbeat_ms_ = now_ms;
    }

    // cmd/config publish_interval_ms (already clamped by the caller). Takes
    // effect from the last publish; the heartbeat clock is unaffected.
    void set_publish_interval(uint32_t ms) { publish_ms_ = ms; }
    uint32_t publish_interval_ms() const { return publish_ms_; }

    uint32_t heartbeat_interval_ms() const {
        return publish_ms_ < kMaxHeartbeatIntervalMs ? publish_ms_
                                                     : kMaxHeartbeatIntervalMs;
    }

    Due update(uint32_t now_ms) {
        Due d;
        if (elapsed_ms(now_ms, last_publish_ms_) >= publish_ms_) {
            last_publish_ms_ = now_ms;
            d.telemetry = true;
        }
        if (elapsed_ms(now_ms, last_heartbeat_ms_) >= heartbeat_interval_ms()) {
            last_heartbeat_ms_ = now_ms;
            d.heartbeat = true;
        }
        return d;
    }

private:
    uint32_t publish_ms_;
    uint32_t last_publish_ms_ = 0;
    uint32_t last_heartbeat_ms_ = 0;
};

// The lighting bank's level report (one telemetry document for every dim
// channel) during a ramp. A ramp moves the level one LSB at a time — 0 →
// 1023 over 60 s is ~17 steps a second per channel — and the report went out
// on every step of every channel, each one a full live telemetry frame on
// the Pi (store, socket emit, cloud forward, rule evaluation). The LEDC duty
// still follows every step; the REPORT now goes out at most once per pass
// and, while only ramp steps are pending, at most once per
// kRampReportIntervalMs. A change that is not a ramp step (the ramp reached
// its target, a timer or max-on cutoff) is reported on the same pass.
class DimReportThrottle {
public:
    static constexpr uint32_t kRampReportIntervalMs = 1000;

    // A dim channel changed this pass; `ramp_step`: an intermediate step of a
    // ramp that is still running.
    void note_change(bool ramp_step) {
        dirty_ = true;
        if (!ramp_step) urgent_ = true;
    }

    // The level report should go out now (call once per pass, after every
    // channel has ticked). Signed difference: a `now` taken before a report
    // that a command sent later in the same pass reads as no time elapsed.
    bool due(uint32_t now_ms) const {
        if (!dirty_) return false;
        return urgent_ || !reported_ ||
               (int32_t)(now_ms - last_report_ms_) >=
                   (int32_t)kRampReportIntervalMs;
    }

    // A level report went out (any path: this throttle, a command, a scene).
    void reported(uint32_t now_ms) {
        dirty_ = false;
        urgent_ = false;
        reported_ = true;
        last_report_ms_ = now_ms;
    }

private:
    bool dirty_ = false;
    bool urgent_ = false;
    bool reported_ = false;
    uint32_t last_report_ms_ = 0;
};

}  // namespace sp
