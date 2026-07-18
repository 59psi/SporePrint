#pragma once
//
// wrap_time — millis()-rollover-safe time comparisons.
//
// millis() wraps every ~49.7 days. The signed-difference idiom stays
// correct across the wrap for any window shorter than ~24.8 days; absolute
// comparisons (`now >= deadline`) misbehave exactly once per wrap — which
// for a relay driving a humidifier is the worst possible once. Covered by
// boundary tests in test_core_channel (test_wrap_helpers).
//
// Native-safe: no Arduino headers.

#include <stdint.h>

namespace sp {

// True when `now` has reached or passed `deadline` (wrap-safe).
inline bool deadline_reached(uint32_t now_ms, uint32_t deadline_ms) {
    return (int32_t)(now_ms - deadline_ms) >= 0;
}

// Elapsed milliseconds since `since` (wrap-safe unsigned subtraction).
inline uint32_t elapsed_ms(uint32_t now_ms, uint32_t since_ms) {
    return now_ms - since_ms;
}

}  // namespace sp
