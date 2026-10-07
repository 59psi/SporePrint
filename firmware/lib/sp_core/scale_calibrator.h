#pragma once
//
// scale_calibrator — averaged, post-command HX711 tare / calibration.
//
// The old cmd/config handlers used the cached `hx711_raw`, refreshed only
// once per read pass (30 s by default), as a single unaveraged sample. Tare
// right after emptying the platform saved a reading taken with the load
// still on; calibrate_scale within 30 s of placing the mass used the EMPTY
// reading, so the delta was noise — and a +4-count noise delta over 200 g
// (0.02 counts/g) passed the `> 0` guard and was persisted to NVS, putting
// every later weight_g off by ~1000x.
//
// This state machine is started by the command and fed FRESH samples by the
// loop (one HX711 pin read per pass, never a spin-wait): the first sample is
// discarded (a conversion that was already sitting in the chip may predate
// the command), the next kSamples are averaged, and a calibration whose
// counts-per-gram is below a physical floor is refused instead of saved.
//
// Native-safe: no Arduino headers.

#include <math.h>
#include <stdint.h>

#include "wrap_time.h"

namespace sp {

class ScaleCalibrator {
public:
    enum class Op : uint8_t { None, Tare, Calibrate };
    enum class Status : uint8_t { Idle, Collecting, Done, Rejected, TimedOut };

    static constexpr int kDiscard = 1;
    static constexpr int kSamples = 8;
    // 1 + 8 samples at the HX711's 10 SPS is ~0.9 s; 3 s bounds a stalled
    // or unwired chip.
    static constexpr uint32_t kTimeoutMs = 3000;
    // Physical floor for a real load cell on the HX711 (gain 128): even a
    // 200 kg cell yields ~10 counts/g, typical 1–20 kg cells 100–2000. A
    // value below 1 count/g is a mass that isn't on the platter, not a cell.
    static constexpr float kMinCountsPerGram = 1.0f;

    void start_tare(uint32_t now_ms) { begin(Op::Tare, now_ms); }

    // False (and nothing started) when known_g is not a positive finite mass.
    bool start_calibrate(float known_g, int32_t tare, uint32_t now_ms) {
        if (!(known_g > 0.0f) || !isfinite(known_g)) return false;
        known_g_ = known_g;
        tare_in_ = tare;
        begin(Op::Calibrate, now_ms);
        return true;
    }

    bool busy() const { return op_ != Op::None; }
    Op op() const { return op_; }
    // The operation the last terminal status belongs to.
    Op finished_op() const { return finished_op_; }

    // Feed one fresh HX711 sample (ignored while idle).
    void add_sample(int32_t raw) {
        if (op_ == Op::None) return;
        if (discarded_ < kDiscard) {
            ++discarded_;
            return;
        }
        if (n_ < kSamples) {
            sum_ += raw;
            ++n_;
        }
    }

    // Advance. Terminal statuses (Done / Rejected / TimedOut) are returned
    // exactly once; the calibrator is idle afterwards.
    Status poll(uint32_t now_ms) {
        if (op_ == Op::None) return Status::Idle;
        if (n_ >= kSamples) {
            mean_ = rounded_mean();
            finished_op_ = op_;
            op_ = Op::None;
            if (finished_op_ == Op::Tare) {
                tare_out_ = mean_;
                reason_ = "";
                return Status::Done;
            }
            scale_out_ = (float)((int64_t)mean_ - (int64_t)tare_in_) / known_g_;
            if (!isfinite(scale_out_) || scale_out_ < kMinCountsPerGram) {
                reason_ =
                    "implausible counts/g (mass not on the platter, cell "
                    "reversed, or tare stale)";
                return Status::Rejected;
            }
            reason_ = "";
            return Status::Done;
        }
        if (deadline_reached(now_ms, deadline_ms_)) {
            finished_op_ = op_;
            op_ = Op::None;
            reason_ = "no HX711 samples before the deadline";
            return Status::TimedOut;
        }
        return Status::Collecting;
    }

    int32_t tare() const { return tare_out_; }
    float scale() const { return scale_out_; }
    int32_t mean() const { return mean_; }
    const char* reason() const { return reason_; }

private:
    void begin(Op op, uint32_t now_ms) {
        op_ = op;
        discarded_ = 0;
        n_ = 0;
        sum_ = 0;
        deadline_ms_ = now_ms + kTimeoutMs;
        reason_ = "";
    }

    int32_t rounded_mean() const {
        // Round half away from zero (raw counts are signed).
        int64_t half = n_ / 2;
        int64_t q = sum_ >= 0 ? (sum_ + half) / n_ : (sum_ - half) / n_;
        return (int32_t)q;
    }

    Op op_ = Op::None;
    Op finished_op_ = Op::None;
    int discarded_ = 0;
    int n_ = 0;
    int64_t sum_ = 0;
    uint32_t deadline_ms_ = 0;
    float known_g_ = 0.0f;
    int32_t tare_in_ = 0;
    int32_t tare_out_ = 0;
    float scale_out_ = 0.0f;
    int32_t mean_ = 0;
    const char* reason_ = "";
};

}  // namespace sp
