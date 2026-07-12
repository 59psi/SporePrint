#pragma once
//
// mhz19 — Winsen MH-Z19C NDIR CO₂ driver (UART 9600, monitoring-tier
// alternate). Config-flag enabled, never autodetected: UART has no
// enumeration semantics, RX floats when nothing is wired, and the sensor
// needs ~3 minutes of warmup — a boot-time probe gives false negatives.
//
// Protocol: fixed 9-byte frames, 0xFF start, checksum = (0xFF − sum of
// bytes 1..7) + 1. Replies are accumulated NON-BLOCKING across update()
// calls against a millis deadline; a checksum-invalid reply is a sensor
// fail, never 0 ppm. ABC (auto baseline correction) is caller-controlled
// at begin() and defaults OFF — same chamber-never-sees-400ppm poisoning
// as Sensirion ASC. Calibration is operator-driven zero-point cal (0x87)
// with the sensor sitting in fresh ~400 ppm air.
//
// Native-safe; host-tested against a scripted UART.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/clock.h"
#include "sp_hal/uart_port.h"

namespace sp {

class Mhz19 {
public:
    Mhz19(UartPort& uart, Clock& clock) : uart_(uart), clock_(clock) {}

    // Send the ABC on/off frame (default off — the chamber posture).
    // Fire-and-forget (the sensor doesn't ack it in a way worth blocking
    // on).
    void begin(bool abc_enabled = false);

    // Zero-point calibration (datasheet cmd 0x87): the sensor latches its
    // CURRENT reading as the 400 ppm baseline — only send with the sensor
    // in fresh air after ≥20 min of runtime. Fire-and-forget, like
    // begin().
    void calibrate_zero();

    // Kick off a CO₂ read if idle. Returns true if a request went out.
    bool request_read();

    // Pump the receive state machine. Returns true exactly once per
    // completed, checksum-valid reply; *co2_ppm is set then. Call every
    // loop pass; handles resync and the 100 ms reply deadline.
    bool update(uint32_t now_ms, uint16_t* co2_ppm);

    bool awaiting_reply() const { return awaiting_; }
    const DriverHealth& health() const { return health_; }

    // Exposed for tests.
    static uint8_t checksum(const uint8_t frame[9]);

private:
    void send_frame(uint8_t cmd, uint8_t b3);

    UartPort& uart_;
    Clock& clock_;
    DriverHealth health_;
    uint8_t rx_[9];
    uint8_t rx_len_ = 0;
    bool awaiting_ = false;
    uint32_t deadline_ms_ = 0;
};

}  // namespace sp
