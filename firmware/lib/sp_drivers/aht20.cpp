#include "aht20.h"

#include "sensirion_transport.h"  // crc8_sensirion — same CRC-8 (0x31 / 0xFF)
#include "wrap_time.h"

namespace sp {

namespace {
constexpr uint8_t kCmdStatus = 0x71;
constexpr uint8_t kStatusBusy = 0x80;
constexpr uint8_t kStatusCalibrated = 0x08;
// v1.1 power-on rule: both bits set = the part's registers are initialised.
constexpr uint8_t kStatusInitMask = 0x18;
constexpr uint32_t kInitMs = 10;          // datasheet: wait 10 ms after 0xBE
constexpr uint32_t kProbeRetryMs = 20;    // one extra wait if still busy
constexpr float kTempMinC = -40.0f;       // datasheet operating range
constexpr float kTempMaxC = 85.0f;

// Aosong v1.1 sample code, AHT20_Start_Init / JH_Reset_REG.
constexpr uint8_t kInitRegs[3] = {0x1B, 0x1C, 0x1E};
constexpr uint8_t kCmdRegWrite = 0xB0;    // 0xB0 | reg writes it back
constexpr uint32_t kRegReadbackMs = 5;    // after {reg, 0, 0}
constexpr uint32_t kRegWritebackMs = 10;  // after the 3-byte read-back
constexpr uint32_t kRegDoneMs = 10;       // after the last register
constexpr uint8_t kStepStatus = 3 * 3;    // after the 3 × 3 register steps
constexpr uint8_t kStepDone = kStepStatus + 1;
}  // namespace

const char* aht20_decode_str(Aht20::Decode d) {
    switch (d) {
        case Aht20::Decode::Ok:         return "ok";
        case Aht20::Decode::Busy:       return "busy timeout";
        case Aht20::Decode::BadCrc:     return "crc";
        case Aht20::Decode::OutOfRange: return "out-of-range";
    }
    return "crc";
}

Aht20::Decode Aht20::decode(const uint8_t raw[7], float* temp_c, float* rh) {
    if ((raw[0] & kStatusBusy) != 0) return Decode::Busy;
    if (crc8_sensirion(raw, 6) != raw[6]) return Decode::BadCrc;
    const uint32_t s_rh = ((uint32_t)raw[1] << 12) | ((uint32_t)raw[2] << 4) |
                          ((uint32_t)raw[3] >> 4);
    const uint32_t s_t = (((uint32_t)raw[3] & 0x0Fu) << 16) |
                         ((uint32_t)raw[4] << 8) | (uint32_t)raw[5];
    const float t = (float)s_t / 1048576.0f * 200.0f - 50.0f;
    float h = (float)s_rh / 1048576.0f * 100.0f;
    // Written "inside the range" so a NaN (impossible from integer math,
    // but cheap to rule out) fails instead of slipping through.
    if (!(t >= kTempMinC && t <= kTempMaxC)) return Decode::OutOfRange;
    if (h > 100.0f) h = 100.0f;
    *temp_c = t;
    *rh = h;
    return Decode::Ok;
}

bool Aht20::read_status(uint8_t* status) {
    const uint8_t cmd = kCmdStatus;
    if (!bus_.write(kAddr, &cmd, 1)) return false;
    return bus_.read(kAddr, status, 1);
}

bool Aht20::init_step(uint32_t* wait_ms) {
    *wait_ms = 0;
    if (init_step_ < kStepStatus) {
        const uint8_t reg = kInitRegs[init_step_ / 3];
        switch (init_step_ % 3) {
            case 0: {
                const uint8_t cmd[3] = {reg, 0x00, 0x00};
                if (!bus_.write(kAddr, cmd, sizeof(cmd))) return false;
                *wait_ms = kRegReadbackMs;
                break;
            }
            case 1:
                if (!bus_.read(kAddr, init_buf_, sizeof(init_buf_))) return false;
                *wait_ms = kRegWritebackMs;
                break;
            default: {
                const uint8_t cmd[3] = {(uint8_t)(kCmdRegWrite | reg),
                                        init_buf_[1], init_buf_[2]};
                if (!bus_.write(kAddr, cmd, sizeof(cmd))) return false;
                if (init_step_ + 1 == kStepStatus) *wait_ms = kRegDoneMs;
                break;
            }
        }
        ++init_step_;
        return true;
    }
    // Registers done: the v1.0 init, only if calibration is still off.
    uint8_t status = 0;
    if (!read_status(&status)) return false;
    if ((status & kStatusCalibrated) == 0) {
        const uint8_t cmd[3] = {0xBE, 0x08, 0x00};
        if (!bus_.write(kAddr, cmd, sizeof(cmd))) return false;
        *wait_ms = kInitMs;
    }
    init_step_ = kStepDone;
    return true;
}

bool Aht20::run_init_blocking() {
    init_step_ = 0;
    while (init_step_ != kStepDone) {
        uint32_t wait = 0;
        if (!init_step(&wait)) return false;
        if (wait != 0) clock_.delay_ms(wait);  // datasheet settles, boot only
    }
    return true;
}

void Aht20::begin_init(uint32_t now_ms) {
    needs_init_ = true;
    init_running_ = true;
    init_step_ = 0;
    init_last_ms_ = now_ms;
    init_wait_ms_ = 0;
}

void Aht20::pump_init(uint32_t now_ms) {
    // Runs every step that is due; zero-settle steps chain in one pass
    // (each is a single short transaction).
    while (init_running_ && elapsed_ms(now_ms, init_last_ms_) >= init_wait_ms_) {
        if (init_step_ == kStepDone) {
            init_running_ = false;
            needs_init_ = false;
            return;
        }
        uint32_t wait = 0;
        if (!init_step(&wait)) {
            // Left for start() to restart; needs_init_ keeps triggers off.
            init_running_ = false;
            health_.fail("init failed");
            return;
        }
        init_last_ms_ = now_ms;
        init_wait_ms_ = wait;
    }
}

bool Aht20::trigger() {
    const uint8_t cmd[3] = {0xAC, 0x33, 0x00};
    return bus_.write(kAddr, cmd, sizeof(cmd));
}

bool Aht20::probe() {
    uint8_t status = 0;
    if (!read_status(&status)) return false;  // NACK → absent
    if ((status & kStatusInitMask) != kStatusInitMask && !run_init_blocking())
        return false;
    if (!trigger()) return false;
    clock_.delay_ms(kConvertMs);
    uint8_t raw[7];
    float t, h;
    for (int attempt = 0; attempt < 2; ++attempt) {
        if (!bus_.read(kAddr, raw, sizeof(raw))) return false;
        Decode d = decode(raw, &t, &h);
        if (d == Decode::Ok) return true;
        if (d != Decode::Busy) return false;  // CRC / range: not an AHT2x
        clock_.delay_ms(kProbeRetryMs);
    }
    return false;
}

bool Aht20::start(uint32_t now_ms) {
    if (awaiting_) return false;
    if (started_once_ && elapsed_ms(now_ms, started_ms_) < kMinIntervalMs)
        return false;
    if (needs_init_) {
        // The calibration bit read 0 on the last sample: no trigger until
        // the init sequence has run (update() pumps it). A sequence that
        // failed on the bus is restarted here.
        if (!init_running_) {
            begin_init(now_ms);
            pump_init(now_ms);
        }
        return false;
    }
    if (!trigger()) {
        health_.fail("trigger failed");
        return false;
    }
    awaiting_ = true;
    started_once_ = true;
    started_ms_ = now_ms;
    return true;
}

bool Aht20::update(uint32_t now_ms, float* temp_c, float* rh) {
    if (init_running_) pump_init(now_ms);
    if (!awaiting_) return false;
    if (elapsed_ms(now_ms, started_ms_) < kConvertMs) return false;

    uint8_t raw[7];
    if (!bus_.read(kAddr, raw, sizeof(raw))) {
        awaiting_ = false;
        health_.fail("read error");
        return false;
    }
    float t, h;
    Decode d = decode(raw, &t, &h);
    if (d == Decode::Busy) {
        // Still converting: poll again on a later pass, until the grace
        // window runs out — a stuck busy bit is a failure, not "no data".
        if (elapsed_ms(now_ms, started_ms_) >= kConvertMs + kBusyGraceMs) {
            awaiting_ = false;
            health_.fail(aht20_decode_str(d));
        }
        return false;
    }
    awaiting_ = false;
    if (d != Decode::Ok) {
        health_.fail(aht20_decode_str(d));
        return false;
    }
    if ((raw[0] & kStatusCalibrated) == 0) {
        // The part lost its calibration state (brown-out / reset): this
        // sample is untrimmed — drop it and run the init sequence (from
        // this and the following passes) before the next trigger.
        health_.fail("not calibrated");
        begin_init(now_ms);
        pump_init(now_ms);
        return false;
    }
    *temp_c = t;
    *rh = h;
    health_.ok();
    return true;
}

}  // namespace sp
