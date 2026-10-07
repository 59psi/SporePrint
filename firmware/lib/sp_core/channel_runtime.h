#pragma once
//
// channel_runtime — per-channel actuator state machine.
//
// One Channel drives one MOSFET output in one of two wire dialects:
//   switch — relay-bank channels (fae/exhaust/circulation/aux). Accepts
//            {state:"on"/"off", pwm:0-255, duration_sec}; reports
//            {channel,state,pwm,trigger} per-channel. Default 30-min max-on
//            safety cutoff (the load-bearing backstop for misters/pumps).
//   dim    — lighting-bank channels (white/blue/red/far_red). Accepts
//            {level:0-1023, state:"off", ramp_sec, duration_sec}; `pwm` is
//            accepted as a 10-bit level alias when `level` is absent (the
//            Pi automation's RuleAction only has pwm, documented 0-1023 for
//            lighting). Reports in the aggregate lighting telemetry doc.
//            No max-on by default
//            (lights legitimately run 12 h). ramp_sec is a linear ramp —
//            the automation engine has always sent it; the old firmware
//            silently dropped it.
//
// Safety invariants (host-tested in test_core_channel):
//   * empty commands are rejected, never defaulted to ON — a retained
//     broker message latching a channel at 255 was the old firmware's
//     highest-consequence bug
//   * an explicit "state":"off" always wins over any pwm/level value — the
//     Pi clears its safety watchdog on an off it sends
//   * the off-timer is only ever armed for a channel that ends up ON
//   * duration_sec <= 0 is ignored with a reason; > 3600 clamps
//   * re-ON while already on does NOT restart the max-on clock
//   * all deadline math is millis-wrap-safe
//   * health counters live HERE, mutated by the same code that changes
//     state — there is no parallel struct for a composition root to forget
//
// Pure logic: no Arduino, no I/O. The composition root maps duty() onto
// LEDC writes and timestamps come in as parameters.

#include <stdint.h>
#include <string.h>

#include "clamps.h"
#include "wrap_time.h"

namespace sp {

enum class ChannelMode : uint8_t { Switch, Dim };

constexpr size_t kChannelNameMax = 23;
constexpr uint32_t kDefaultMaxOnMs = 30UL * 60UL * 1000UL;  // switch mode

// Channel names become MQTT topic suffixes and command keys — they must be
// safe as both, and must not shadow the fixed command endpoints.
bool channel_name_valid(const char* name);

// Operator override of a channel's max-on backstop, in seconds (cmd/config
// {"max_on_sec": {"<channel>": N}}, persisted in NVS). Switch channels must
// keep a backstop: 1 s .. kDefaultMaxOnMs (larger values clamp). Dim
// channels accept 0 (no cutoff) .. 24 h. Returns false — *out_ms untouched —
// for values that cannot be honoured (negative; 0 on a switch channel).
constexpr uint32_t kMaxDimMaxOnSec = 24UL * 3600UL;
bool max_on_override_ms(ChannelMode mode, int32_t sec, uint32_t* out_ms,
                        bool* clamped);

struct ChannelConfig {
    char name[kChannelNameMax + 1] = {0};
    ChannelMode mode = ChannelMode::Switch;
    // 0 = no cutoff. Switch-mode configs of 0 are coerced to the default —
    // a switch channel without a max-on backstop is not a supported state.
    uint32_t max_on_ms = kDefaultMaxOnMs;
};

struct ChannelHealth {
    uint32_t cycle_count = 0;     // off→on transitions
    uint32_t on_time_sec = 0;     // accumulated completed-run seconds
    uint32_t safety_cutoffs = 0;  // duration expiries + max-on trips
};

// Neutral parsed command (the JSON → struct parse lives at the MQTT edge).
struct ChannelCommand {
    bool has_state = false;
    bool state_on = false;
    bool has_pwm = false;       // switch dialect, 0-255
    int32_t pwm = 0;
    bool has_level = false;     // dim dialect, 0-1023
    int32_t level = 0;
    bool has_duration = false;
    int32_t duration_sec = 0;
    bool has_ramp = false;      // dim dialect only
    int32_t ramp_sec = 0;
};

// Result of applying a command or ticking the clock.
enum class ChannelEvent : uint8_t {
    None = 0,
    Changed,         // output changed — caller re-publishes + writes duty
    Rejected,        // command refused (reason() explains)
};

class Channel {
public:
    void configure(const ChannelConfig& cfg);

    // Apply a parsed command at `now_ms`. On Rejected, reason() holds a
    // static string for the log line.
    ChannelEvent apply(const ChannelCommand& cmd, uint32_t now_ms);

    // Advance time: duration expiry, max-on cutoff, ramp interpolation.
    // Returns Changed when the output moved (cutoffs set reason()).
    ChannelEvent tick(uint32_t now_ms);
    // Firmware-imposed off (link-loss safe mode, OTA start): output off,
    // off-timer and ramp disarmed, counted as a safety cutoff. Returns
    // Changed only when the channel was on; `reason` must be static.
    ChannelEvent force_off(uint32_t now_ms, const char* reason);

    // Operator max-on override at runtime (does not reset channel state; a
    // running channel past the new limit is cut on the next tick()). Same
    // coercion as configure(): a switch channel cannot drop its backstop.
    void set_max_on_ms(uint32_t max_on_ms);

    bool is_on() const { return on_; }
    uint8_t pwm8() const { return pwm8_; }       // switch-mode output
    uint16_t level10() const { return level10_; }  // dim-mode output
    // Unified 10-bit duty for the LEDC write site.
    uint16_t duty10() const {
        return cfg_.mode == ChannelMode::Switch ? (uint16_t)(pwm8_ << 2) | (pwm8_ >> 6)
                                                : level10_;
    }
    const ChannelConfig& config() const { return cfg_; }
    const ChannelHealth& health() const { return health_; }
    // Live on-time including the current run (for health reports).
    uint32_t on_time_sec_live(uint32_t now_ms) const;
    const char* reason() const { return reason_; }
    // True when the last Changed event was a safety cutoff (reporting hook).
    bool last_change_was_cutoff() const { return last_was_cutoff_; }

private:
    void set_output(bool on, uint8_t pwm8, uint16_t level10, uint32_t now_ms);

    ChannelConfig cfg_;
    ChannelHealth health_;
    bool on_ = false;
    uint8_t pwm8_ = 0;
    uint16_t level10_ = 0;
    uint32_t on_since_ms_ = 0;
    bool off_timer_armed_ = false;
    uint32_t off_at_ms_ = 0;
    // Dim ramp state.
    bool ramping_ = false;
    uint16_t ramp_from_ = 0;
    uint16_t ramp_to_ = 0;
    uint32_t ramp_start_ms_ = 0;
    uint32_t ramp_end_ms_ = 0;
    const char* reason_ = "";
    bool last_was_cutoff_ = false;
};

}  // namespace sp
