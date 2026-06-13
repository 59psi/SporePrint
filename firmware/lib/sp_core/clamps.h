#pragma once
//
// clamps — bounds for every operator-tunable value that arrives over MQTT.
// A pathological payload must never busy-loop the node (read_interval 0),
// stall it for days (huge interval), or latch an actuator (negative /
// gigantic duration). Each clamp reports whether it had to intervene so
// call sites can log the adjustment instead of applying it silently.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

namespace sp {

struct ClampResult {
    uint32_t value;
    bool clamped;
};

inline ClampResult clamp_u32(uint32_t v, uint32_t lo, uint32_t hi) {
    if (v < lo) return {lo, true};
    if (v > hi) return {hi, true};
    return {v, false};
}

// Sensor read cadence: 1 s .. 10 min.
constexpr uint32_t kMinReadIntervalMs = 1000;
constexpr uint32_t kMaxReadIntervalMs = 600000;
inline ClampResult clamp_read_interval_ms(uint32_t v) {
    return clamp_u32(v, kMinReadIntervalMs, kMaxReadIntervalMs);
}

// Telemetry publish cadence: 5 s .. 1 h.
constexpr uint32_t kMinPublishIntervalMs = 5000;
constexpr uint32_t kMaxPublishIntervalMs = 3600000;
inline ClampResult clamp_publish_interval_ms(uint32_t v) {
    return clamp_u32(v, kMinPublishIntervalMs, kMaxPublishIntervalMs);
}

// Timed actuation: 1 s .. 1 h. Negative and zero are REJECTED (not clamped)
// at the parse site — a negative duration latching a channel on was the
// highest-consequence bug class in the old handler.
constexpr int32_t kMaxDurationSec = 3600;

// switch-mode PWM is 8-bit, dim-mode level is 10-bit.
inline uint8_t clamp_pwm8(int32_t v) {
    if (v < 0) return 0;
    if (v > 255) return 255;
    return (uint8_t)v;
}

inline uint16_t clamp_level10(int32_t v) {
    if (v < 0) return 0;
    if (v > 1023) return 1023;
    return (uint16_t)v;
}

}  // namespace sp
