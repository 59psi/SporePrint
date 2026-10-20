#include "hx711.h"

namespace sp {

int32_t Hx711::read_raw() {
    uint32_t value = 0;
    for (int i = 0; i < 24; ++i) {
        sck_.write(true);
        delay_us_(1);
        value = (value << 1) | (dout_.read() ? 1u : 0u);
        sck_.write(false);
        delay_us_(1);
    }
    // 25th pulse selects gain 128 / channel A for the next conversion.
    sck_.write(true);
    delay_us_(1);
    sck_.write(false);

    // Sign-extend 24 → 32 bits.
    if (value & 0x800000u) value |= 0xFF000000u;
    return (int32_t)value;
}

bool Hx711::read(int32_t* counts) {
    const int32_t raw = read_raw();
    if (have_last_ && raw == last_code_) {
        if (same_run_ < kStuckRun) ++same_run_;
    } else {
        same_run_ = 1;
    }
    have_last_ = true;
    last_code_ = raw;
    if (raw == kRailHigh || raw == kRailLow) {
        health_.fail("saturated (rail code)");
        return false;
    }
    if (same_run_ >= kStuckRun) {
        health_.fail("stuck (identical samples)");
        return false;
    }
    *counts = raw;
    health_.ok();
    return true;
}

}  // namespace sp
