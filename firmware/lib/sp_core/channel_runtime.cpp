#include "channel_runtime.h"

namespace sp {

namespace {

// Names that are MQTT command endpoints or report topics in their own
// right — a channel named "config" would shadow cmd/config.
const char* const kReservedNames[] = {
    "config", "scene",  "status", "health",   "telemetry",
    "logs",   "ota",    "alert",  "coredump", "heartbeat",
};

}  // namespace

bool channel_name_valid(const char* name) {
    if (name == nullptr || name[0] == '\0') return false;
    size_t len = strlen(name);
    if (len > kChannelNameMax) return false;
    for (size_t i = 0; i < len; ++i) {
        char ch = name[i];
        bool ok = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
                  (ch >= '0' && ch <= '9') || ch == '_' || ch == '-';
        if (!ok) return false;
    }
    for (const char* r : kReservedNames) {
        if (strcmp(name, r) == 0) return false;
    }
    return true;
}

void Channel::configure(const ChannelConfig& cfg) {
    cfg_ = cfg;
    // A switch channel without a max-on backstop is not a supported state.
    if (cfg_.mode == ChannelMode::Switch && cfg_.max_on_ms == 0) {
        cfg_.max_on_ms = kDefaultMaxOnMs;
    }
    on_ = false;
    pwm8_ = 0;
    level10_ = 0;
    on_since_ms_ = 0;
    off_timer_armed_ = false;
    ramping_ = false;
    reason_ = "";
    last_was_cutoff_ = false;
}

void Channel::set_output(bool on, uint8_t pwm8, uint16_t level10, uint32_t now_ms) {
    bool was_on = on_;
    on_ = on;
    pwm8_ = on ? pwm8 : 0;
    level10_ = on ? level10 : 0;

    if (on && !was_on) {
        on_since_ms_ = now_ms;
        ++health_.cycle_count;
    }
    if (!on && was_on) {
        health_.on_time_sec += elapsed_ms(now_ms, on_since_ms_) / 1000;
        off_timer_armed_ = false;
        ramping_ = false;
    }
}

uint32_t Channel::on_time_sec_live(uint32_t now_ms) const {
    uint32_t total = health_.on_time_sec;
    if (on_) total += elapsed_ms(now_ms, on_since_ms_) / 1000;
    return total;
}

ChannelEvent Channel::apply(const ChannelCommand& cmd, uint32_t now_ms) {
    last_was_cutoff_ = false;

    const bool dialect_ok =
        cfg_.mode == ChannelMode::Switch ? (cmd.has_state || cmd.has_pwm)
                                         : (cmd.has_state || cmd.has_level);
    if (!dialect_ok) {
        // Never default an empty/foreign-dialect payload to ON — a retained
        // `{}` latching a channel at full power was the old firmware's
        // worst failure mode.
        reason_ = cfg_.mode == ChannelMode::Switch
                      ? "payload lacks state and pwm"
                      : "payload lacks state and level";
        return ChannelEvent::Rejected;
    }

    bool on = on_;
    uint8_t pwm = pwm8_;
    uint16_t level = level10_;

    if (cfg_.mode == ChannelMode::Switch) {
        if (cmd.has_state) {
            on = cmd.state_on;
            pwm = on ? 255 : 0;
        }
        if (cmd.has_pwm) {
            pwm = clamp_pwm8(cmd.pwm);
            on = pwm > 0;
        }
    } else {
        if (cmd.has_level) {
            level = clamp_level10(cmd.level);
            on = level > 0;
        }
        if (cmd.has_state && !cmd.state_on) {
            level = 0;
            on = false;
        } else if (cmd.has_state && cmd.state_on && !cmd.has_level) {
            // "on" without a level restores full brightness — symmetric
            // with the switch dialect's state-only command.
            level = 1023;
            on = true;
        }

        if (cmd.has_ramp && on && cmd.ramp_sec > 0) {
            int32_t ramp_s = cmd.ramp_sec > kMaxDurationSec ? kMaxDurationSec
                                                            : cmd.ramp_sec;
            ramp_from_ = level10_;
            ramp_to_ = level;
            ramp_start_ms_ = now_ms;
            ramp_end_ms_ = now_ms + (uint32_t)ramp_s * 1000UL;
            ramping_ = true;
            // Output starts moving from the CURRENT level; the target is
            // reached by tick().
            set_output(true, pwm, ramp_from_, now_ms);
            // Arm duration AFTER ramp setup so duration applies to the lit
            // state as a whole.
            if (cmd.has_duration && cmd.duration_sec > 0) {
                int32_t d = cmd.duration_sec > kMaxDurationSec ? kMaxDurationSec
                                                               : cmd.duration_sec;
                off_at_ms_ = now_ms + (uint32_t)d * 1000UL;
                off_timer_armed_ = true;
            }
            reason_ = "";
            return ChannelEvent::Changed;
        }
        ramping_ = false;
    }

    if (cmd.has_duration) {
        if (cmd.duration_sec > 0) {
            int32_t d = cmd.duration_sec > kMaxDurationSec ? kMaxDurationSec
                                                           : cmd.duration_sec;
            off_at_ms_ = now_ms + (uint32_t)d * 1000UL;
            off_timer_armed_ = true;
        }
        // duration_sec <= 0: ignored — the rest of the command still
        // applies, matching the old handler's logged-and-skipped behavior.
    }

    set_output(on, pwm, level, now_ms);
    reason_ = "";
    return ChannelEvent::Changed;
}

ChannelEvent Channel::tick(uint32_t now_ms) {
    last_was_cutoff_ = false;

    // Timed off — wrap-safe. An explicit duration is the user/rule saying
    // "don't stay on past T"; honouring it counts as a safety cutoff.
    if (off_timer_armed_ && deadline_reached(now_ms, off_at_ms_)) {
        set_output(false, 0, 0, now_ms);
        ++health_.safety_cutoffs;
        reason_ = "auto-off (timer expired)";
        last_was_cutoff_ = true;
        return ChannelEvent::Changed;
    }

    // Max-on backstop (switch mode always has one; dim mode only if
    // configured). Re-ON while running does not restart this clock.
    if (on_ && cfg_.max_on_ms > 0 &&
        elapsed_ms(now_ms, on_since_ms_) > cfg_.max_on_ms) {
        set_output(false, 0, 0, now_ms);
        ++health_.safety_cutoffs;
        reason_ = "auto-off (max-on exceeded)";
        last_was_cutoff_ = true;
        return ChannelEvent::Changed;
    }

    // Dim ramp interpolation.
    if (ramping_) {
        if (deadline_reached(now_ms, ramp_end_ms_)) {
            ramping_ = false;
            level10_ = ramp_to_;
            on_ = level10_ > 0;
            if (!on_) set_output(false, 0, 0, now_ms);
            reason_ = "";
            return ChannelEvent::Changed;
        }
        uint32_t span = elapsed_ms(ramp_end_ms_, ramp_start_ms_);
        uint32_t pos = elapsed_ms(now_ms, ramp_start_ms_);
        int32_t delta = (int32_t)ramp_to_ - (int32_t)ramp_from_;
        uint16_t lvl = (uint16_t)((int32_t)ramp_from_ +
                                  (int64_t)delta * (int64_t)pos / (int64_t)span);
        if (lvl != level10_) {
            level10_ = lvl;
            reason_ = "";
            return ChannelEvent::Changed;
        }
    }

    return ChannelEvent::None;
}

}  // namespace sp
