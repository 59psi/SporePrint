#pragma once
//
// publish_cadence — when the periodic publishes are due (srv-hw#22).
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

}  // namespace sp
