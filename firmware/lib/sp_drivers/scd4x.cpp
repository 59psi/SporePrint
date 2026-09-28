#include "scd4x.h"

namespace sp {

namespace {
constexpr uint16_t kCmdStartPeriodic = 0x21B1;
constexpr uint16_t kCmdStopPeriodic = 0x3F86;
constexpr uint16_t kCmdDataReady = 0xE4B8;
constexpr uint16_t kCmdReadMeasurement = 0xEC05;
constexpr uint16_t kCmdGetSerial = 0x3682;
constexpr uint16_t kCmdSetAsc = 0x2416;
constexpr uint16_t kCmdGetAsc = 0x2313;
constexpr uint16_t kCmdPersistSettings = 0x3615;
constexpr uint16_t kCmdForcedRecal = 0x362F;

constexpr uint32_t kStopPeriodicMs = 500;   // datasheet
constexpr uint32_t kPersistMs = 800;        // datasheet
constexpr uint32_t kForcedRecalMs = 400;    // datasheet
constexpr uint32_t kShortDelayMs = 1;
}  // namespace

bool Scd4x::probe() {
    // get_serial_number is an idle-mode-only command: a sensor still in
    // periodic mode from before a warm reboot (OTA, WDT/panic, EN button,
    // portal restart — anything that doesn't cut its 3V3) NACKs it and
    // would look absent. Stop periodic first (Sensirion's reference
    // bring-up sequence); an ACK means the datasheet 500 ms wait must pass
    // before the next command. A NACK (absent part) still falls through to
    // the serial read, which is the presence criterion either way.
    if (xport_.cmd(kCmdStopPeriodic)) clock_.delay_ms(kStopPeriodicMs);
    uint16_t serial[3];
    return xport_.cmd_read(kCmdGetSerial, kShortDelayMs, serial, 3);
}

bool Scd4x::begin() {
    // The sensor may still be in periodic mode from before a reboot —
    // config commands only work in idle, so stop first (NACK here is fine
    // if it was already idle, but the wait must still happen after an ack).
    if (xport_.cmd(kCmdStopPeriodic)) clock_.delay_ms(kStopPeriodicMs);

    // ASC off — and persist only when the stored setting is KNOWN to
    // differ, because persist_settings is an EEPROM write with a wear
    // budget. If the ASC read itself fails (NACK / CRC) the stored value is
    // unknown: still write ASC off to RAM for this session (the factory
    // default is ON — skipping the write would leave the baseline drag this
    // driver exists to prevent), but don't spend an EEPROM write on a guess.
    uint16_t asc = 1;
    const bool got_asc = xport_.cmd_read(kCmdGetAsc, kShortDelayMs, &asc, 1);
    if (!got_asc || asc != 0) {
        if (!xport_.cmd_arg(kCmdSetAsc, 0)) {
            health_.fail("asc off failed");
            return false;
        }
        clock_.delay_ms(kShortDelayMs);
        if (got_asc && xport_.cmd(kCmdPersistSettings))
            clock_.delay_ms(kPersistMs);
    }

    if (!xport_.cmd(kCmdStartPeriodic)) return false;
    return true;
}

bool Scd4x::data_ready() {
    uint16_t word = 0;
    if (!xport_.cmd_read(kCmdDataReady, kShortDelayMs, &word, 1)) return false;
    return (word & 0x07FF) != 0;
}

bool Scd4x::read(uint16_t* co2_ppm, float* temp_c, float* rh) {
    uint16_t words[3];
    if (!xport_.cmd_read(kCmdReadMeasurement, kShortDelayMs, words, 3)) {
        health_.fail("read error");
        return false;
    }
    *co2_ppm = words[0];
    *temp_c = -45.0f + 175.0f * (float)words[1] / 65535.0f;
    *rh = 100.0f * (float)words[2] / 65535.0f;
    health_.ok();
    return true;
}

bool Scd4x::recalibrate(uint16_t reference_ppm) {
    if (!xport_.cmd(kCmdStopPeriodic)) {
        health_.fail("frc: stop failed");
        return false;
    }
    clock_.delay_ms(kStopPeriodicMs);

    bool ok = false;
    uint16_t result = 0xFFFF;
    if (xport_.cmd_arg(kCmdForcedRecal, reference_ppm)) {
        clock_.delay_ms(kForcedRecalMs);
        if (xport_.read_words(&result, 1) && result != 0xFFFF) {
            ok = true;  // result = 0x8000 + correction offset
        }
    }
    if (!ok) health_.fail("frc failed");

    // Always restart periodic mode — a failed FRC must not leave the
    // sensor idle and the telemetry stream dark.
    xport_.cmd(kCmdStartPeriodic);
    return ok;
}

}  // namespace sp
