#pragma once
//
// sp_hal::GpioPin — single-pin interface for the bit-banged peripherals
// (HX711 data/clock, reed switch input).
//
// Native-safe: no Arduino headers.

#include <stdint.h>

namespace sp {

enum class PinMode : uint8_t { Input, InputPullup, Output };

class GpioPin {
public:
    virtual ~GpioPin() = default;
    virtual void set_mode(PinMode mode) = 0;
    virtual bool read() = 0;
    virtual void write(bool level) = 0;
};

}  // namespace sp
