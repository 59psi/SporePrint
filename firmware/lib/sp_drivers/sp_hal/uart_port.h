#pragma once
//
// sp_hal::UartPort — byte-stream interface for UART sensors (MH-Z19C).
// Reads are non-blocking: the driver accumulates reply bytes across loop
// passes against a millis deadline instead of stalling the loop.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

namespace sp {

class UartPort {
public:
    virtual ~UartPort() = default;
    virtual size_t available() = 0;
    // Read up to maxlen bytes; returns bytes actually read (may be 0).
    virtual size_t read(uint8_t* buf, size_t maxlen) = 0;
    virtual size_t write(const uint8_t* buf, size_t len) = 0;
    virtual void flush_input() = 0;
};

}  // namespace sp
