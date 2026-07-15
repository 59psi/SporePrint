#include "scd30.h"

#include <string.h>

namespace sp {

namespace {
constexpr uint16_t kCmdStartContinuous = 0x0010;  // arg = pressure (0 = off)
constexpr uint16_t kCmdDataReady = 0x0202;
constexpr uint16_t kCmdReadMeasurement = 0x0300;
constexpr uint16_t kCmdSetAsc = 0x5306;           // arg 0 = off
constexpr uint16_t kCmdForcedRecal = 0x5204;      // arg = reference ppm
constexpr uint16_t kCmdFirmwareVersion = 0xD100;
constexpr uint32_t kCmdGapMs = 3;  // datasheet: >3 ms between write and read
}  // namespace

float Scd30::words_to_float(uint16_t hi, uint16_t lo) {
    uint32_t bits = ((uint32_t)hi << 16) | lo;
    float f;
    memcpy(&f, &bits, sizeof(f));
    return f;
}

bool Scd30::probe() {
    uint16_t version = 0;
    return xport_.cmd_read(kCmdFirmwareVersion, kCmdGapMs, &version, 1);
}

bool Scd30::begin() {
    if (!xport_.cmd_arg(kCmdSetAsc, 0)) return false;
    if (!xport_.cmd_arg(kCmdStartContinuous, 0)) return false;
    return true;
}

bool Scd30::data_ready() {
    uint16_t word = 0;
    if (!xport_.cmd_read(kCmdDataReady, kCmdGapMs, &word, 1)) return false;
    return word == 1;
}

bool Scd30::read(float* co2_ppm, float* temp_c, float* rh) {
    uint16_t words[6];
    if (!xport_.cmd_read(kCmdReadMeasurement, kCmdGapMs, words, 6)) {
        health_.fail("read error");
        return false;
    }
    float co2 = words_to_float(words[0], words[1]);
    float temp = words_to_float(words[2], words[3]);
    float hum = words_to_float(words[4], words[5]);
    // Datasheet range checks — a mid-stretch corrupted read that somehow
    // passed CRC must still not become telemetry.
    if (co2 < 0.0f || co2 > 40000.0f || temp < -40.0f || temp > 70.0f ||
        hum < 0.0f || hum > 100.0f) {
        health_.fail("out-of-range");
        return false;
    }
    *co2_ppm = co2;
    *temp_c = temp;
    *rh = hum;
    health_.ok();
    return true;
}

bool Scd30::recalibrate(uint16_t reference_ppm) {
    // Set forced recalibration value (datasheet cmd 0x5204): the argument
    // word is the reference CO₂ concentration in ppm. Applied in-place —
    // continuous mode keeps running, so no stop/start dance and nothing to
    // read back; the ack is the whole result.
    if (!xport_.cmd_arg(kCmdForcedRecal, reference_ppm)) {
        health_.fail("frc failed");
        return false;
    }
    clock_.delay_ms(kCmdGapMs);  // same >3 ms post-write gap as every command
    return true;
}

}  // namespace sp
