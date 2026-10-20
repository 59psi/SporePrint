#pragma once
//
// hx711 — Avia HX711 load-cell ADC driver (Tier 3 yield scale).
//
// Config-flag enabled, never autodetected (a floating DOUT pin lies).
// NEVER spin-waits: is_ready() is a single pin read, and read() is only
// legal when ready — a disconnected load cell therefore costs one pin read
// per loop pass instead of hanging the node (the old firmware's WDT-trip
// class). The 24-pulse clock-out takes ~60 µs; the DEVICE composition root
// must wrap read() in noInterrupts()/interrupts() because PD_SCK held high
// > 60 µs power-cycles the chip mid-read.
//
// DOUT is pulled up: an absent or unplugged module then reads HIGH — never
// ready, so its reading goes stale and it is listed missing — instead of a
// floating input that reads LOW and passes for a ready ADC clocking out
// noise. A fitted module drives DOUT push-pull, so the pull-up is harmless.
// read() also refuses what no load cell produces: the rail codes 0x7FFFFF /
// 0x800000 (input saturated — an open bridge wire) and a run of identical
// codes (DOUT held low by an unpowered module clocks out the same zeros;
// a live 24-bit ADC's noise never repeats a code kStuckRun times in a row).
//
// Returns sign-extended 24-bit raw counts; taring and calibration policy
// are node-app concerns (calibration lives in NVS, not here) — but the
// pure counts→grams math is exposed as to_grams() so hosts can test it.
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

    // The saturation codes (sign-extended): the input sits at a rail.
    static constexpr int32_t kRailHigh = 0x7FFFFF;
    static constexpr int32_t kRailLow = -0x800000;
    // Identical consecutive codes that mark a stuck DOUT line.
    static constexpr uint32_t kStuckRun = 8;

    Hx711(GpioPin& dout, GpioPin& sck, DelayUsFn delay_us)
        : dout_(dout), sck_(sck), delay_us_(delay_us) {}

    void begin() {
        dout_.set_mode(PinMode::InputPullup);  // absent module reads not-ready
        sck_.set_mode(PinMode::Output);
        sck_.write(false);
    }

    // Data ready when DOUT is low. One pin read — call freely.
    bool is_ready() { return !dout_.read(); }

    // Clock out one 24-bit sample (gain-128 channel A: 25 pulses total),
    // unvalidated, health untouched — the bit-level primitive under read().
    // Caller contract: only when is_ready(); wrap in a critical section on
    // device. Returns sign-extended counts.
    int32_t read_raw();

    // Clock out one sample and validate it (same caller contract). False —
    // a health failure, *counts untouched — for a rail code or the
    // kStuckRun-th identical code in a row; true with the counts otherwise.
    bool read(int32_t* counts);

    const DriverHealth& health() const { return health_; }

    // Pure tare/scale → grams conversion (scale = counts per gram).
    // scale == 0 means uncalibrated: returns false, *grams untouched —
    // the node app publishes raw counts instead so setup can proceed.
    static bool to_grams(int32_t raw, int32_t tare, float scale,
                         float* grams) {
        if (scale == 0.0f) return false;
        *grams = (float)(raw - tare) / scale;
        return true;
    }

private:
    GpioPin& dout_;
    GpioPin& sck_;
    DelayUsFn delay_us_;
    DriverHealth health_;
    bool have_last_ = false;
    int32_t last_code_ = 0;
    uint32_t same_run_ = 0;  // consecutive identical codes, capped at kStuckRun
};

}  // namespace sp
