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
    health_.ok();
    return (int32_t)value;
}

}  // namespace sp
