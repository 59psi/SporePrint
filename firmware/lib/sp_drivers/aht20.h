#pragma once
//
// aht20 — Aosong AHT20 / AHT21 / AHT25 temperature + humidity driver
// (I²C 0x38; Adafruit 4566, the AHT20 half of the common "AHT20 + BMP280"
// combo boards). A cheaper SHT31-D alternate the shopping alternates listed
// from v4.0 until 2026-10 with no driver behind it — now driven.
//
// Protocol (Aosong AHT20 datasheet v1.0/v1.1):
//   status   0x71, then read 1 byte: bit7 = busy, bit3 = calibration enabled
//   init     when (status & 0x18) != 0x18 (v1.1 power-on rule), the
//            register initialisation from Aosong's v1.1 sample code
//            ("AHT20_Start_Init"), for each of 0x1B, 0x1C, 0x1E:
//              write {reg, 0x00, 0x00}; wait 5 ms; read 3 bytes;
//              wait 10 ms; write {0xB0 | reg, byte[1], byte[2]}
//            then wait 10 ms. If bit3 still reads 0 after that, the v1.0
//            init 0xBE 0x08 0x00 + 10 ms (which is the same register-0x1E
//            write: 0xB0 | 0x1E = 0xBE). Parts reporting 0x18 / 0x1C skip
//            both.
//   trigger  0xAC 0x33 0x00, conversion takes ~80 ms
//   result   7 bytes: status, 20-bit RH, 20-bit T (sharing byte 3), CRC-8
//   CRC      poly 0x31, init 0xFF over the first 6 bytes — the same CRC the
//            Sensirion family uses (crc8_sensirion)
//   RH % = S_RH / 2^20 × 100        T °C = S_T / 2^20 × 200 − 50
//
// The 80 ms conversion is longer than any single driver call may block (the
// 50 ms loop budget, sp_hal/clock.h), so steady-state reads are a two-step
// state machine: start() triggers a conversion, update() is pumped every
// loop pass and returns the sample once the conversion time has passed and
// the busy bit is clear. A busy part past its deadline, a NACK, a CRC
// mismatch, an out-of-range value or a sample taken with the calibration bit
// clear is a read FAIL, never data. A calibration-bit-clear sample (the part
// browned out or reset) also starts the init sequence above, run as a
// non-blocking step machine from update() (each step one short bus
// transaction, the 5 / 10 ms settles measured on the clock instead of
// slept); start() refuses to trigger until it has finished.
//
// Self-heating: the datasheet keeps it under 0.1 °C at no more than one
// measurement every 2 s, so start() refuses to re-trigger sooner (the node
// read interval can be clamped down to 1 s).
//
// probe() is boot-only and blocks ~90 ms (one full conversion), ~155 ms when
// the part needs the register init first: an ACK alone at 0x38 is not proof
// (PCF8574A expanders and FT62xx touch controllers live there too), so
// presence means a CRC-valid measurement.
//
// AHT10 (same address, older init command 0xE1, no CRC byte) is NOT
// supported and fails the CRC-gated probe — it was never recommended.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sht3x.h"  // DriverHealth
#include "sp_hal/clock.h"
#include "sp_hal/i2c_bus.h"

namespace sp {

class Aht20 {
public:
    static constexpr uint8_t kAddr = 0x38;
    static constexpr uint32_t kConvertMs = 80;       // datasheet
    static constexpr uint32_t kBusyGraceMs = 120;    // past kConvertMs → fail
    static constexpr uint32_t kMinIntervalMs = 2000; // self-heating limit

    Aht20(I2cBus& bus, Clock& clock) : bus_(bus), clock_(clock) {}

    // Boot-only presence check: status read, the init sequence when the
    // status asks for it (blocking, ~65 ms), then one CRC-validated
    // measurement.
    bool probe();

    // Trigger a conversion. False when one is already running, the last
    // one started less than kMinIntervalMs ago, the init sequence is still
    // running (it is restarted here if it failed last time), or the
    // trigger NACKed (counted as a health failure).
    bool start(uint32_t now_ms);

    // Pump: returns true exactly once per completed, valid sample. Cheap
    // (no bus traffic) until the conversion time has passed. Also advances
    // a pending init sequence, one due step at a time.
    bool update(uint32_t now_ms, float* temp_c, float* rh);

    bool busy() const { return awaiting_; }
    // The re-init sequence is running (or failed and waits for start()).
    bool initializing() const { return needs_init_; }
    const DriverHealth& health() const { return health_; }

    enum class Decode : uint8_t { Ok, Busy, BadCrc, OutOfRange };

    // Pure decode of a 7-byte result frame (exposed for tests).
    static Decode decode(const uint8_t raw[7], float* temp_c, float* rh);

private:
    bool read_status(uint8_t* status);
    bool trigger();

    // Init sequence: steps 0-8 = the three register initialisations (3
    // transactions each), step 9 = status re-read + the v1.0 0xBE init if
    // still uncalibrated. One step per call; *wait_ms = the settle before
    // the next step. False = bus error (sequence abandoned).
    bool init_step(uint32_t* wait_ms);
    bool run_init_blocking();               // probe(): steps with delay_ms
    void begin_init(uint32_t now_ms);       // runtime: steps from update()
    void pump_init(uint32_t now_ms);

    I2cBus& bus_;
    Clock& clock_;
    DriverHealth health_;
    bool awaiting_ = false;
    bool needs_init_ = false;      // set by an uncalibrated sample
    bool init_running_ = false;    // runtime step machine active
    uint8_t init_step_ = 0;
    uint8_t init_buf_[3] = {0, 0, 0};
    uint32_t init_last_ms_ = 0;
    uint32_t init_wait_ms_ = 0;
    bool started_once_ = false;
    uint32_t started_ms_ = 0;
};

const char* aht20_decode_str(Aht20::Decode d);

}  // namespace sp
