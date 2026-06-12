#pragma once
//
// sp_hal::Clock — time + bounded delays for drivers.
//
// Drivers may delay only for datasheet command-settling times, and no
// single driver call may hold the loop longer than ~50 ms (the WDT budget
// contract) — anything longer must be a data-ready-polled state machine
// across update() calls. Host tests use a manual clock so "waiting" is
// instant and assertable.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

namespace sp {

class Clock {
public:
    virtual ~Clock() = default;
    virtual uint32_t millis() = 0;
    virtual void delay_ms(uint32_t ms) = 0;
};

}  // namespace sp
