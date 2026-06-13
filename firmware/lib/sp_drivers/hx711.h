#pragma once
//
// hx711 — Avia HX711 load-cell ADC driver (Tier 3 yield scale).
//
// Config-flag enabled, never autodetected (a floating DOUT pin lies).
// NEVER spin-waits: is_ready() is a single pin read, and read_raw() is
// only legal when ready — a disconnected load cell therefore costs one
// pin read per loop pass instead of hanging the node (the old firmware's
// WDT-trip class). The 24-pulse clock-out takes ~60 µs; the DEVICE
// composition root must wrap read_raw() in noInterrupts()/interrupts()
// because PD_SCK held high > 60 µs power-cycles the chip mid-read.
//
// Returns sign-extended 24-bit raw counts; taring and gram conversion are
// node-app concerns (calibration lives in NVS, not here).
//
// Native-safe; host-tested against scripted pins.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/gpio.h"

namespace sp {

class Hx711 {
public:
    // Microsecond-scale delay hook so hosts can count pulses instead of
    // sleeping. The device adapter maps this to delayMicroseconds(1).
    using DelayUsFn = void (*)(uint32_t us);

    Hx711(GpioPin& dout, GpioPin& sck, DelayUsFn delay_us)
        : dout_(dout), sck_(sck), delay_us_(delay_us) {}

    void begin() {
        dout_.set_mode(PinMode::Input);
        sck_.set_mode(PinMode::Output);
        sck_.write(false);
    }

    // Data ready when DOUT is low. One pin read — call freely.
    bool is_ready() { return !dout_.read(); }

    // Clock out one 24-bit sample (gain-128 channel A: 25 pulses total).
    // Caller contract: only when is_ready(); wrap in a critical section on
    // device. Returns sign-extended counts.
    int32_t read_raw();

    const DriverHealth& health() const { return health_; }

private:
    GpioPin& dout_;
    GpioPin& sck_;
    DelayUsFn delay_us_;
    DriverHealth health_;
};

}  // namespace sp
