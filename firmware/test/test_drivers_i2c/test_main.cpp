// test_drivers_i2c — Sensirion transport framing + every I²C driver against
// scripted bus transactions, including autodetect probe-order assertions.

#include <unity.h>

#include <stdint.h>
#include <string.h>

#include <vector>

#include "aht20.h"
#include "autodetect.h"
#include "bh1750.h"
#include "bme280.h"
#include "mock_hal.h"
#include "scd30.h"
#include "scd4x.h"
#include "sensirion_transport.h"
#include "sht3x.h"
#include "sht4x.h"
#include "ws_cam_exio.h"

using sp_testing::MockClock;
using sp_testing::MockI2cBus;

void setUp() {}
void tearDown() {}

// Append a CRC'd word to a byte vector (builds scripted sensor replies).
static void push_word(std::vector<uint8_t>& v, uint16_t w) {
    uint8_t b[2] = {(uint8_t)(w >> 8), (uint8_t)(w & 0xFF)};
    v.push_back(b[0]);
    v.push_back(b[1]);
    v.push_back(sp::crc8_sensirion(b, 2));
}

// MockI2cBus that also stamps every write with the mock clock, so tests can
// assert datasheet gaps BETWEEN transactions (a settle that happens after
// the wrong write is invisible to total_delayed_ms).
class TimedI2cBus : public MockI2cBus {
public:
    explicit TimedI2cBus(MockClock& clock) : clock_(clock) {}

    struct Stamp {
        uint8_t addr;
        std::vector<uint8_t> bytes;
        uint32_t at_ms;
    };
    std::vector<Stamp> writes;

    bool write(uint8_t addr, const uint8_t* wbuf, size_t wlen) override {
        writes.push_back({addr, std::vector<uint8_t>(wbuf, wbuf + wlen),
                          clock_.now_ms});
        return MockI2cBus::write(addr, wbuf, wlen);
    }

    // Time of the first write of `bytes` to `addr`; UINT32_MAX if never sent.
    uint32_t at(uint8_t addr, const std::vector<uint8_t>& bytes) const {
        for (const Stamp& w : writes)
            if (w.addr == addr && w.bytes == bytes) return w.at_ms;
        return UINT32_MAX;
    }

private:
    MockClock& clock_;
};

static std::vector<uint8_t> float_word_bytes(uint16_t hi, uint16_t lo) {
    std::vector<uint8_t> v;
    push_word(v, hi);
    push_word(v, lo);
    return v;
}

// ── transport ──────────────────────────────────────────────────

void test_crc8_datasheet_vector() {
    // Sensirion's published check vector: 0xBEEF → 0x92.
    const uint8_t data[2] = {0xBE, 0xEF};
    TEST_ASSERT_EQUAL_UINT8(0x92, sp::crc8_sensirion(data, 2));
}

void test_transport_rejects_bad_crc() {
    MockI2cBus bus;
    MockClock clock;
    sp::SensirionTransport xport(bus, clock, 0x44);

    bus.expect_write(0x44, {0x37, 0x80});
    std::vector<uint8_t> reply;
    push_word(reply, 0x1234);
    reply[2] ^= 0xFF;  // corrupt the CRC
    bus.expect_read(0x44, reply);

    uint16_t words[1];
    TEST_ASSERT_FALSE(xport.cmd_read(0x3780, 1, words, 1));
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_transport_cmd_arg_frames_crc() {
    MockI2cBus bus;
    MockClock clock;
    sp::SensirionTransport xport(bus, clock, 0x62);
    // set_asc(0) → cmd 0x2416, arg 0x0000, CRC(00 00) = 0x81.
    bus.expect_write(0x62, {0x24, 0x16, 0x00, 0x00, 0x81});
    TEST_ASSERT_TRUE(xport.cmd_arg(0x2416, 0));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

// ── SHT3x ──────────────────────────────────────────────────────

void test_sht3x_measure_conversion() {
    MockI2cBus bus;
    MockClock clock;
    sp::Sht3x sht(bus, clock);

    bus.expect_write(0x44, {0x24, 0x00});
    std::vector<uint8_t> reply;
    // raw temp 0x6666 → -45 + 175*0.4 = 25.0 °C ; raw rh 0x8000 → ~50 %.
    push_word(reply, 0x6666);
    push_word(reply, 0x8000);
    bus.expect_read(0x44, reply);

    float t = 0, rh = 0;
    TEST_ASSERT_TRUE(sht.measure(&t, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 25.0f, t);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 50.0f, rh);
    TEST_ASSERT_EQUAL_UINT32(1, sht.health().reads);
    TEST_ASSERT_EQUAL_UINT32(0, sht.health().fails);
    // Datasheet max measurement wait was honoured (16 ms settle).
    TEST_ASSERT_TRUE(clock.total_delayed_ms >= 15);
}

void test_sht3x_read_fail_counts() {
    MockI2cBus bus;
    MockClock clock;
    sp::Sht3x sht(bus, clock);
    bus.expect_write(0x44, {0x24, 0x00});
    bus.expect_read(0x44, {}, /*ack=*/false);
    float t, rh;
    TEST_ASSERT_FALSE(sht.measure(&t, &rh));
    TEST_ASSERT_EQUAL_UINT32(1, sht.health().fails);
    TEST_ASSERT_EQUAL_STRING("read error", sht.health().last_error);
}

void test_sht3x_probe_waits_out_soft_reset_before_serial_read() {
    // Datasheet t_SR max 1.5 ms: the SHT3x NACKs its address until the
    // soft reset completes. The serial read must not be issued inside that
    // window, or a present SHT31-D probes as absent.
    MockClock clock;
    TimedI2cBus bus(clock);
    sp::Sht3x sht(bus, clock);

    bus.expect_write(0x44, {0x30, 0xA2});
    bus.expect_write(0x44, {0x37, 0x80});
    std::vector<uint8_t> serial;
    push_word(serial, 0xBEEF);
    push_word(serial, 0xCAFE);
    bus.expect_read(0x44, serial);

    TEST_ASSERT_TRUE(sht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    const uint32_t reset_at = bus.at(0x44, {0x30, 0xA2});
    const uint32_t serial_at = bus.at(0x44, {0x37, 0x80});
    TEST_ASSERT_NOT_EQUAL(UINT32_MAX, serial_at);
    TEST_ASSERT_TRUE(serial_at - reset_at >= 2);
}

void test_sht3x_probe_reset_nack_is_absent() {
    MockI2cBus bus;
    MockClock clock;
    sp::Sht3x sht(bus, clock);
    bus.expect_write_nack(0x44);  // nothing at the address
    TEST_ASSERT_FALSE(sht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

// ── SHT4x ──────────────────────────────────────────────────────

void test_sht4x_single_byte_protocol_and_rh_formula() {
    MockI2cBus bus;
    MockClock clock;
    sp::Sht4x sht(bus, clock);

    bus.expect_write(0x44, {0xFD});  // single-byte command — NOT 16-bit
    std::vector<uint8_t> reply;
    push_word(reply, 0x6666);  // 25.0 °C (same temp formula as SHT3x)
    push_word(reply, 0x8000);  // SHT4x RH: -6 + 125*0.5 = 56.5 %
    bus.expect_read(0x44, reply);

    float t = 0, rh = 0;
    TEST_ASSERT_TRUE(sht.measure(&t, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 25.0f, t);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 56.5f, rh);
}

// ── SCD4x ──────────────────────────────────────────────────────

void test_scd4x_begin_disables_asc_and_persists_once() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);

    // stop periodic (acked → 500 ms wait)
    bus.expect_write(0x62, {0x3F, 0x86});
    // get ASC → 1 (factory default: ON — the chamber-poisoning setting)
    bus.expect_write(0x62, {0x23, 0x13});
    std::vector<uint8_t> asc_on;
    push_word(asc_on, 1);
    bus.expect_read(0x62, asc_on);
    // set ASC 0 (arg CRC 0x81) + persist
    bus.expect_write(0x62, {0x24, 0x16, 0x00, 0x00, 0x81});
    bus.expect_write(0x62, {0x36, 0x15});
    // start periodic
    bus.expect_write(0x62, {0x21, 0xB1});

    TEST_ASSERT_TRUE(scd.begin());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    // Datasheet waits honoured: 500 (stop) + 1 (get) + 1 (set gap) + 800
    // (persist) — at least 1300 ms total.
    TEST_ASSERT_TRUE(clock.total_delayed_ms >= 1300);
}

void test_scd4x_begin_skips_persist_when_asc_already_off() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, {0x23, 0x13});
    std::vector<uint8_t> asc_off;
    push_word(asc_off, 0);
    bus.expect_read(0x62, asc_off);
    bus.expect_write(0x62, {0x21, 0xB1});  // straight to start — no EEPROM wear
    TEST_ASSERT_TRUE(scd.begin());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_scd4x_begin_forces_asc_off_when_asc_read_fails() {
    // A NACK/CRC failure on get_automatic_self_calibration_enabled leaves
    // the stored value unknown — the factory default is ASC ON, so begin()
    // must still write ASC off (RAM) instead of skipping the block. No
    // persist: an EEPROM write isn't spent on a guess.
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, {0x23, 0x13});
    bus.expect_read(0x62, {}, /*ack=*/false);                // ASC read fails
    bus.expect_write(0x62, {0x24, 0x16, 0x00, 0x00, 0x81});  // ASC off anyway
    bus.expect_write(0x62, {0x21, 0xB1});                    // then start
    TEST_ASSERT_TRUE(scd.begin());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_scd4x_begin_asc_write_failure_is_reported() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, {0x23, 0x13});
    bus.expect_read(0x62, {}, /*ack=*/false);
    bus.expect_write_nack(0x62);  // set ASC NACKs
    TEST_ASSERT_FALSE(scd.begin());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("asc off failed", scd.health().last_error);
}

void test_scd4x_probe_stops_stale_periodic_mode_first() {
    // Warm reboot: the SCD4x is still in periodic mode (begin() started it
    // last boot and nothing cut its power). get_serial is idle-only, so
    // the probe must stop periodic mode and wait the datasheet 500 ms
    // BEFORE asking for the serial number.
    MockClock clock;
    TimedI2cBus bus(clock);
    sp::Scd4x scd(bus, clock);
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, {0x36, 0x82});
    std::vector<uint8_t> serial;
    push_word(serial, 1);
    push_word(serial, 2);
    push_word(serial, 3);
    bus.expect_read(0x62, serial);

    TEST_ASSERT_TRUE(scd.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    const uint32_t stop_at = bus.at(0x62, {0x3F, 0x86});
    const uint32_t serial_at = bus.at(0x62, {0x36, 0x82});
    TEST_ASSERT_NOT_EQUAL(UINT32_MAX, serial_at);
    TEST_ASSERT_TRUE(serial_at - stop_at >= 500);
}

void test_scd4x_probe_absent() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);
    bus.expect_write_nack(0x62);  // stop_periodic
    bus.expect_write_nack(0x62);  // get_serial
    TEST_ASSERT_FALSE(scd.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
    // No 500 ms stall for a part that isn't there.
    TEST_ASSERT_EQUAL_UINT32(0, clock.total_delayed_ms);
}

void test_scd4x_data_ready_and_read() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);

    bus.expect_write(0x62, {0xE4, 0xB8});
    std::vector<uint8_t> not_ready;
    push_word(not_ready, 0x8000);  // low 11 bits zero → not ready
    bus.expect_read(0x62, not_ready);
    TEST_ASSERT_FALSE(scd.data_ready());

    bus.expect_write(0x62, {0xE4, 0xB8});
    std::vector<uint8_t> ready;
    push_word(ready, 0x8006);
    bus.expect_read(0x62, ready);
    TEST_ASSERT_TRUE(scd.data_ready());

    bus.expect_write(0x62, {0xEC, 0x05});
    std::vector<uint8_t> meas;
    push_word(meas, 1234);    // CO₂ ppm raw
    push_word(meas, 0x6666);  // 25.0 °C
    push_word(meas, 0x8000);  // 50 %
    bus.expect_read(0x62, meas);

    uint16_t co2;
    float t, rh;
    TEST_ASSERT_TRUE(scd.read(&co2, &t, &rh));
    TEST_ASSERT_EQUAL_UINT16(1234, co2);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 25.0f, t);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 50.0f, rh);
}

// A data_ready bus failure (NACK / CRC) is a sensor fault, not "no data
// yet": it must show in health, or a CO2 sensor that fell off the bus looks
// healthy (reads/fails frozen) while its reading goes stale.
void test_scd4x_data_ready_bus_failure_is_a_health_fail() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);

    bus.expect_write_nack(0x62);
    TEST_ASSERT_FALSE(scd.data_ready());
    TEST_ASSERT_EQUAL_UINT32(1, scd.health().fails);
    TEST_ASSERT_EQUAL_STRING("data_ready error", scd.health().last_error);

    // CRC-corrupt reply: also a fault.
    bus.expect_write(0x62, {0xE4, 0xB8});
    bus.expect_read(0x62, {0x80, 0x06, 0x00});  // wrong CRC byte
    TEST_ASSERT_FALSE(scd.data_ready());
    TEST_ASSERT_EQUAL_UINT32(2, scd.health().fails);

    // "Not ready yet" is healthy and leaves the counters alone.
    bus.expect_write(0x62, {0xE4, 0xB8});
    std::vector<uint8_t> not_ready;
    push_word(not_ready, 0x8000);
    bus.expect_read(0x62, not_ready);
    TEST_ASSERT_FALSE(scd.data_ready());
    TEST_ASSERT_EQUAL_UINT32(2, scd.health().fails);
    TEST_ASSERT_EQUAL_UINT32(2, scd.health().reads);

    // The next good measurement clears the error.
    bus.expect_write(0x62, {0xEC, 0x05});
    std::vector<uint8_t> meas;
    push_word(meas, 900);
    push_word(meas, 0x6666);
    push_word(meas, 0x8000);
    bus.expect_read(0x62, meas);
    uint16_t co2;
    float t, rh;
    TEST_ASSERT_TRUE(scd.read(&co2, &t, &rh));
    TEST_ASSERT_NULL(scd.health().last_error);
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_scd4x_frc_success_and_failure() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd4x scd(bus, clock);

    // FRC frame for 800 ppm: cmd 0x362F + arg 0x0320 + CRC over the arg —
    // computed with the real helper so the script can't drift.
    const uint8_t arg[2] = {0x03, 0x20};
    const uint8_t arg_crc = sp::crc8_sensirion(arg, 2);
    const std::vector<uint8_t> frc_frame = {0x36, 0x2F, 0x03, 0x20, arg_crc};

    // Success: stop, FRC, result 0x8005, restart.
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, frc_frame);
    std::vector<uint8_t> ok_result;
    push_word(ok_result, 0x8005);
    bus.expect_read(0x62, ok_result);
    bus.expect_write(0x62, {0x21, 0xB1});
    TEST_ASSERT_TRUE(scd.recalibrate(800));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());

    // Failure: sensor answers 0xFFFF — periodic mode must STILL restart.
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, frc_frame);
    std::vector<uint8_t> bad_result;
    push_word(bad_result, 0xFFFF);
    bus.expect_read(0x62, bad_result);
    bus.expect_write(0x62, {0x21, 0xB1});
    TEST_ASSERT_FALSE(scd.recalibrate(800));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("frc failed", scd.health().last_error);
}

// ── SCD30 ──────────────────────────────────────────────────────

void test_scd30_float_decode() {
    // 439.09 ppm encodes as 0x43DB8B85-ish; build the exact bits for 439.09f
    // and assert the decode reproduces it.
    float ref = 439.09f;
    uint32_t bits;
    memcpy(&bits, &ref, sizeof(bits));
    float decoded = sp::Scd30::words_to_float((uint16_t)(bits >> 16),
                                              (uint16_t)(bits & 0xFFFF));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, ref, decoded);
}

void test_scd30_read_measurement_floats() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd30 scd(bus, clock);

    auto float_words = [](float f, std::vector<uint8_t>& v) {
        uint32_t bits;
        memcpy(&bits, &f, sizeof(bits));
        push_word(v, (uint16_t)(bits >> 16));
        push_word(v, (uint16_t)(bits & 0xFFFF));
    };

    bus.expect_write(0x61, {0x03, 0x00});
    std::vector<uint8_t> meas;
    float_words(812.5f, meas);  // CO₂
    float_words(21.4f, meas);   // temp
    float_words(88.2f, meas);   // RH
    bus.expect_read(0x61, meas);

    float co2, t, rh;
    TEST_ASSERT_TRUE(scd.read(&co2, &t, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 812.5f, co2);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 21.4f, t);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 88.2f, rh);
}

void test_scd30_stretch_timeout_is_read_fail() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd30 scd(bus, clock);
    bus.expect_write(0x61, {0x03, 0x00});
    bus.expect_read(0x61, {}, /*ack=*/false);  // stretch → bus timeout
    float co2, t, rh;
    TEST_ASSERT_FALSE(scd.read(&co2, &t, &rh));
    TEST_ASSERT_EQUAL_UINT32(1, scd.health().fails);
}

void test_scd30_data_ready_bus_failure_is_a_health_fail() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd30 scd(bus, clock);

    bus.expect_write_nack(0x61);
    TEST_ASSERT_FALSE(scd.data_ready());
    TEST_ASSERT_EQUAL_UINT32(1, scd.health().fails);
    TEST_ASSERT_EQUAL_STRING("data_ready error", scd.health().last_error);

    // Clock-stretch timeout on the reply: a fault too.
    bus.expect_write(0x61, {0x02, 0x02});
    bus.expect_read(0x61, {}, /*ack=*/false);
    TEST_ASSERT_FALSE(scd.data_ready());
    TEST_ASSERT_EQUAL_UINT32(2, scd.health().fails);

    // Word 0 = no new sample yet: healthy, counters untouched.
    bus.expect_write(0x61, {0x02, 0x02});
    std::vector<uint8_t> not_ready;
    push_word(not_ready, 0);
    bus.expect_read(0x61, not_ready);
    TEST_ASSERT_FALSE(scd.data_ready());
    TEST_ASSERT_EQUAL_UINT32(2, scd.health().reads);

    bus.expect_write(0x61, {0x02, 0x02});
    std::vector<uint8_t> ready;
    push_word(ready, 1);
    bus.expect_read(0x61, ready);
    TEST_ASSERT_TRUE(scd.data_ready());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_scd30_frc_success_and_failure() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd30 scd(bus, clock);

    // FRC frame for 800 ppm: cmd 0x5204 + arg 0x0320 + CRC over the arg —
    // computed with the real helper so the script can't drift.
    const uint8_t arg[2] = {0x03, 0x20};
    const uint8_t arg_crc = sp::crc8_sensirion(arg, 2);

    // Success is a single in-place write: continuous mode keeps running
    // through an SCD30 FRC (no stop/restart dance, unlike the SCD4x).
    bus.expect_write(0x61, {0x52, 0x04, 0x03, 0x20, arg_crc});
    TEST_ASSERT_TRUE(scd.recalibrate(800));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    // The >3 ms post-write command gap was honoured.
    TEST_ASSERT_TRUE(clock.total_delayed_ms >= 3);

    // Failure: the write NACKs.
    bus.expect_write_nack(0x61);
    TEST_ASSERT_FALSE(scd.recalibrate(800));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("frc failed", scd.health().last_error);
}

void test_scd30_out_of_range_rejected() {
    MockI2cBus bus;
    MockClock clock;
    sp::Scd30 scd(bus, clock);
    auto float_words = [](float f, std::vector<uint8_t>& v) {
        uint32_t bits;
        memcpy(&bits, &f, sizeof(bits));
        push_word(v, (uint16_t)(bits >> 16));
        push_word(v, (uint16_t)(bits & 0xFFFF));
    };
    bus.expect_write(0x61, {0x03, 0x00});
    std::vector<uint8_t> meas;
    float_words(-12.0f, meas);  // negative CO₂ — corrupt
    float_words(21.0f, meas);
    float_words(50.0f, meas);
    bus.expect_read(0x61, meas);
    float co2, t, rh;
    TEST_ASSERT_FALSE(scd.read(&co2, &t, &rh));
    TEST_ASSERT_EQUAL_STRING("out-of-range", scd.health().last_error);
}

void test_scd30_nan_rejected() {
    // A CRC-valid quiet-NaN word pair (0x7FC0 0x0000) makes every "<"/">"
    // comparison false — it must still fail the range check, in each slot.
    const uint16_t kNanHi = 0x7FC0, kNanLo = 0x0000;
    uint32_t ok_bits[3];
    const float ok[3] = {812.5f, 21.4f, 88.2f};
    memcpy(ok_bits, ok, sizeof(ok_bits));
    for (int slot = 0; slot < 3; ++slot) {
        MockI2cBus bus;
        MockClock clock;
        sp::Scd30 scd(bus, clock);
        bus.expect_write(0x61, {0x03, 0x00});
        std::vector<uint8_t> meas;
        for (int i = 0; i < 3; ++i) {
            std::vector<uint8_t> w =
                (i == slot) ? float_word_bytes(kNanHi, kNanLo)
                            : float_word_bytes((uint16_t)(ok_bits[i] >> 16),
                                               (uint16_t)(ok_bits[i] & 0xFFFF));
            meas.insert(meas.end(), w.begin(), w.end());
        }
        bus.expect_read(0x61, meas);
        float co2 = 1, t = 1, rh = 1;
        TEST_ASSERT_FALSE(scd.read(&co2, &t, &rh));
        TEST_ASSERT_EQUAL_STRING("out-of-range", scd.health().last_error);
        TEST_ASSERT_EQUAL_UINT32(1, scd.health().fails);
    }
}

// ── BH1750 ─────────────────────────────────────────────────────

void test_bh1750_lux_conversion() {
    MockI2cBus bus;
    sp::Bh1750 bh(bus);
    bus.expect_write(0x23, {0x01});
    bus.expect_write(0x23, {0x10});
    TEST_ASSERT_TRUE(bh.begin());
    bus.expect_read(0x23, {0x27, 0x10});  // 10000 counts → 8333.3 lux
    float lux;
    TEST_ASSERT_TRUE(bh.read(&lux));
    TEST_ASSERT_FLOAT_WITHIN(0.5f, 8333.3f, lux);
}

// ── autodetect ─────────────────────────────────────────────────

void test_autodetect_sht4x_wins_at_0x44() {
    MockI2cBus bus;
    MockClock clock;
    // SHT4x probe at 0x44 answers with a CRC-valid serial.
    bus.expect_write(0x44, {0x89});
    std::vector<uint8_t> serial;
    push_word(serial, 0x1234);
    push_word(serial, 0x5678);
    bus.expect_read(0x44, serial);
    // SCD4x probe (0x62 stop_periodic, then get_serial) NACKs; SCD30
    // probe NACKs.
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x61);
    // BH1750 at 0x23 ACKs power-on.
    bus.expect_write(0x23, {0x01});
    // Appended probes: AHT2x status read @0x38, BMx280 chip-ID @0x76/0x77.
    bus.expect_write_nack(0x38);
    bus.expect_write_nack(0x76);
    bus.expect_write_nack(0x77);

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::Sht4x, (int)d.temp_rh);
    TEST_ASSERT_EQUAL_UINT8(0x44, d.temp_rh_addr);
    TEST_ASSERT_EQUAL_INT((int)sp::Co2Kind::None, (int)d.co2);
    TEST_ASSERT_TRUE(d.bh1750);
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_autodetect_sht3x_after_sht4x_miss() {
    MockClock clock;
    TimedI2cBus bus(clock);
    // 0x44: SHT4x probe gets garbage (an SHT3x ignores 0x89 → NACK on read);
    // the SHT3x probe must then open with the SOFT RESET (0x30A2) before
    // its serial read — the state-clearing step the plan requires.
    bus.expect_write(0x44, {0x89});
    bus.expect_read(0x44, {}, /*ack=*/false);
    bus.expect_write(0x44, {0x30, 0xA2});  // soft reset FIRST
    bus.expect_write(0x44, {0x37, 0x80});
    std::vector<uint8_t> serial;
    push_word(serial, 0xBEEF);
    push_word(serial, 0xCAFE);
    bus.expect_read(0x44, serial);
    // SCD4x answers — after the stale-periodic-mode stop.
    bus.expect_write(0x62, {0x3F, 0x86});
    bus.expect_write(0x62, {0x36, 0x82});
    std::vector<uint8_t> scd_serial;
    push_word(scd_serial, 1);
    push_word(scd_serial, 2);
    push_word(scd_serial, 3);
    bus.expect_read(0x62, scd_serial);
    // BH1750 absent at both addresses.
    bus.expect_write_nack(0x23);
    bus.expect_write_nack(0x5C);
    // Appended probes: AHT2x status read @0x38, BMx280 chip-ID @0x76/0x77.
    bus.expect_write_nack(0x38);
    bus.expect_write_nack(0x76);
    bus.expect_write_nack(0x77);

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::Sht3x, (int)d.temp_rh);
    TEST_ASSERT_EQUAL_INT((int)sp::Co2Kind::Scd4x, (int)d.co2);
    TEST_ASSERT_FALSE(d.bh1750);
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    // Datasheet gaps between transactions: SHT3x soft reset (1.5 ms max)
    // before the serial read; SCD4x stop_periodic (500 ms) before get_serial.
    TEST_ASSERT_TRUE(bus.at(0x44, {0x37, 0x80}) - bus.at(0x44, {0x30, 0xA2}) >= 2);
    TEST_ASSERT_TRUE(bus.at(0x62, {0x36, 0x82}) - bus.at(0x62, {0x3F, 0x86}) >= 500);
}

void test_autodetect_nothing_attached() {
    MockI2cBus bus;
    MockClock clock;
    // Every probe NACKs: SHT4x@44, SHT3x reset@44, SHT4x@45, SHT3x reset@45,
    // SCD4x stop@62 + get_serial@62, SCD30@61, BH1750@23, BH1750@5C,
    // AHT2x status@38, BMx280 chip-ID@76 and @77.
    bus.expect_write_nack(0x44);
    bus.expect_write_nack(0x44);
    bus.expect_write_nack(0x45);
    bus.expect_write_nack(0x45);
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x61);
    bus.expect_write_nack(0x23);
    bus.expect_write_nack(0x5C);
    bus.expect_write_nack(0x38);
    bus.expect_write_nack(0x76);
    bus.expect_write_nack(0x77);

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::None, (int)d.temp_rh);
    TEST_ASSERT_EQUAL_INT((int)sp::Co2Kind::None, (int)d.co2);
    TEST_ASSERT_FALSE(d.bh1750);
    TEST_ASSERT_FALSE(d.aht20);
    TEST_ASSERT_EQUAL_INT((int)sp::BaroKind::None, (int)d.baro);
    TEST_ASSERT_TRUE(bus.script_consumed());
}

// ── Waveshare ESP32-S3-CAM I/O expander ────────────────────────

void test_ws_cam_exio_powers_the_camera() {
    // Direction first (every EXIO but EXIO7 / CHG_DET an output), then the
    // levels: TP_RST, LCD_RST, SD_CS, BAT_EN, PWR_LED high; CAM_PWDN (EXIO3)
    // and PA_CTRL (EXIO4) low — Waveshare's protocol, register 0x02 / 0x03.
    MockI2cBus bus;
    bus.expect_write(0x24, {0x02, 0x7F});
    bus.expect_write(0x24, {0x03, 0x67});
    sp::WsCamExio exio(bus);
    TEST_ASSERT_TRUE(exio.camera_power_on());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    TEST_ASSERT_EQUAL_UINT8(0, sp::WsCamExio::kCameraOnLevels & sp::WsCamExio::kCamPwdn);
    TEST_ASSERT_EQUAL_UINT8(0, sp::WsCamExio::kOutputs & sp::WsCamExio::kChgDet);
}

void test_ws_cam_exio_absent_expander_reports_false() {
    MockI2cBus bus;
    bus.expect_write_nack(0x24);
    sp::WsCamExio exio(bus);
    TEST_ASSERT_FALSE(exio.camera_power_on());
    TEST_ASSERT_TRUE(bus.script_consumed());
    // A NACKed level write after an ACKed direction write is a failure too.
    bus.expect_write(0x24, {0x02, 0x7F});
    bus.expect_write_nack(0x24);
    TEST_ASSERT_FALSE(exio.camera_power_on());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

// ── CRC-8 catalogue check value ────────────────────────────────

void test_crc8_catalogue_check_value() {
    // poly 0x31 / init 0xFF / no reflection / no xorout is CRC-8/NRSC-5 in
    // the CRC catalogue: check("123456789") = 0xF7. Pins the CRC the AHT2x
    // shares with the Sensirion family independently of the 0xBEEF vector.
    const uint8_t data[9] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    TEST_ASSERT_EQUAL_UINT8(0xF7, sp::crc8_sensirion(data, 9));
}

// ── AHT20 ──────────────────────────────────────────────────────

// 7-byte AHT20 result frame: status, 20-bit RH, 20-bit T, CRC.
static std::vector<uint8_t> aht_frame(uint8_t status, uint32_t s_rh,
                                      uint32_t s_t) {
    std::vector<uint8_t> f = {
        status,
        (uint8_t)(s_rh >> 12),
        (uint8_t)(s_rh >> 4),
        (uint8_t)(((s_rh & 0x0F) << 4) | ((s_t >> 16) & 0x0F)),
        (uint8_t)(s_t >> 8),
        (uint8_t)s_t};
    f.push_back(sp::crc8_sensirion(f.data(), 6));
    return f;
}

void test_aht20_decode_datasheet_formulas() {
    // RH = S_RH / 2^20 * 100 ; T = S_T / 2^20 * 200 - 50.
    float t = 0, rh = 0;
    std::vector<uint8_t> f = aht_frame(0x1C, 0x80000, 0x66666);
    TEST_ASSERT_EQUAL_INT((int)sp::Aht20::Decode::Ok,
                          (int)sp::Aht20::decode(f.data(), &t, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 50.0f, rh);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 30.0f, t);  // 419430/2^20*200-50

    // Chamber-range sample: 0xF0000 → 93.75 %RH; 0x5C28F → 22.0 °C.
    f = aht_frame(0x18, 0xF0000, 0x5C28F);
    TEST_ASSERT_EQUAL_INT((int)sp::Aht20::Decode::Ok,
                          (int)sp::Aht20::decode(f.data(), &t, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 93.75f, rh);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 22.0f, t);
}

void test_aht20_decode_rejects_busy_crc_and_range() {
    float t = 7, rh = 7;
    std::vector<uint8_t> f = aht_frame(0x9C, 0x80000, 0x66666);  // busy bit
    TEST_ASSERT_EQUAL_INT((int)sp::Aht20::Decode::Busy,
                          (int)sp::Aht20::decode(f.data(), &t, &rh));
    f = aht_frame(0x1C, 0x80000, 0x66666);
    f[6] ^= 0x01;  // corrupt CRC
    TEST_ASSERT_EQUAL_INT((int)sp::Aht20::Decode::BadCrc,
                          (int)sp::Aht20::decode(f.data(), &t, &rh));
    // S_T = 0xFFFFF → ~150 °C: CRC-valid but outside -40..85 °C.
    f = aht_frame(0x1C, 0x80000, 0xFFFFF);
    TEST_ASSERT_EQUAL_INT((int)sp::Aht20::Decode::OutOfRange,
                          (int)sp::Aht20::decode(f.data(), &t, &rh));
    // Outputs untouched on every rejection.
    TEST_ASSERT_EQUAL_FLOAT(7.0f, t);
    TEST_ASSERT_EQUAL_FLOAT(7.0f, rh);
}

// Aosong v1.1 register initialisation (sample code AHT20_Start_Init /
// JH_Reset_REG) for one register: write {reg, 0, 0}, read 3 bytes back,
// write {0xB0 | reg, byte[1], byte[2]}.
static void expect_aht_reg_init(MockI2cBus& bus, uint8_t reg, uint8_t b1,
                                uint8_t b2) {
    bus.expect_write(0x38, {reg, 0x00, 0x00});
    bus.expect_read(0x38, {0x18, b1, b2});
    bus.expect_write(0x38, {(uint8_t)(0xB0 | reg), b1, b2});
}

void test_aht20_probe_inits_uncalibrated_part_then_requires_crc() {
    MockClock clock;
    TimedI2cBus bus(clock);
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x10});                // (status & 0x18) != 0x18
    // v1.1: registers 0x1B, 0x1C, 0x1E, in that order.
    expect_aht_reg_init(bus, 0x1B, 0x12, 0x34);
    expect_aht_reg_init(bus, 0x1C, 0x56, 0x78);
    expect_aht_reg_init(bus, 0x1E, 0x9A, 0xBC);
    // Still uncalibrated afterwards: the v1.0 init as well.
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x10});
    bus.expect_write(0x38, {0xBE, 0x08, 0x00});
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});   // trigger
    bus.expect_read(0x38, aht_frame(0x1C, 0x80000, 0x66666));
    sp::Aht20 aht(bus, clock);
    TEST_ASSERT_TRUE(aht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    // Settles: 5 ms before each read-back, 10 ms before each write-back
    // (the read is not stamped: write-back − request = 15 ms), 10 ms after
    // the last register, 10 ms after 0xBE; 80 ms conversion before the read.
    TEST_ASSERT_EQUAL_UINT32(15, bus.at(0x38, {0xBB, 0x12, 0x34}) -
                                     bus.at(0x38, {0x1B, 0x00, 0x00}));
    TEST_ASSERT_EQUAL_UINT32(15, bus.at(0x38, {0xBE, 0x9A, 0xBC}) -
                                     bus.at(0x38, {0x1E, 0x00, 0x00}));
    TEST_ASSERT_TRUE(bus.at(0x38, {0xBE, 0x08, 0x00}) -
                         bus.at(0x38, {0xBE, 0x9A, 0xBC}) >= 10);
    TEST_ASSERT_TRUE(bus.at(0x38, {0xAC, 0x33, 0x00}) -
                         bus.at(0x38, {0xBE, 0x08, 0x00}) >= 10);
    TEST_ASSERT_TRUE(clock.total_delayed_ms >= 3 * 15 + 10 + 10 + 80);
}

void test_aht20_probe_v11_init_that_sets_calibration_skips_0xbe() {
    // A v1.1 part reporting 0x08 (bit 4 clear): the register init alone
    // brings it up; with the calibration bit then set, no 0xBE is sent.
    MockClock clock;
    MockI2cBus bus;
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x08});
    expect_aht_reg_init(bus, 0x1B, 0x00, 0x00);
    expect_aht_reg_init(bus, 0x1C, 0x00, 0x00);
    expect_aht_reg_init(bus, 0x1E, 0x08, 0x00);
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x18});
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    bus.expect_read(0x38, aht_frame(0x18, 0x80000, 0x66666));
    sp::Aht20 aht(bus, clock);
    TEST_ASSERT_TRUE(aht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_aht20_probe_initialised_part_skips_init() {
    // 0x18 / 0x1C: registers initialised and calibrated — straight to the
    // measurement, ~80 ms.
    MockClock clock;
    MockI2cBus bus;
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x1C});
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    bus.expect_read(0x38, aht_frame(0x1C, 0x80000, 0x66666));
    sp::Aht20 aht(bus, clock);
    TEST_ASSERT_TRUE(aht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_UINT32(80, clock.total_delayed_ms);
}

void test_aht20_probe_register_init_nack_is_absent() {
    MockClock clock;
    MockI2cBus bus;
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x00});
    bus.expect_write_nack(0x38);  // {0x1B, 0, 0} refused
    sp::Aht20 aht(bus, clock);
    TEST_ASSERT_FALSE(aht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_aht20_probe_rejects_ack_without_valid_frame() {
    // Something ACKs at 0x38 (a PCF8574A expander, say) but its "frame"
    // fails the CRC — not an AHT2x.
    MockI2cBus bus;
    MockClock clock;
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x18});
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    bus.expect_read(0x38, {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF});
    sp::Aht20 aht(bus, clock);
    TEST_ASSERT_FALSE(aht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_aht20_probe_absent() {
    MockI2cBus bus;
    MockClock clock;
    bus.expect_write_nack(0x38);
    sp::Aht20 aht(bus, clock);
    TEST_ASSERT_FALSE(aht.probe());
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_aht20_async_measurement_state_machine() {
    MockI2cBus bus;
    MockClock clock;
    sp::Aht20 aht(bus, clock);
    float t = 0, rh = 0;

    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(1000));
    TEST_ASSERT_TRUE(aht.busy());
    TEST_ASSERT_FALSE(aht.start(1001));  // one conversion at a time

    // Before the 80 ms conversion time: no bus traffic at all.
    TEST_ASSERT_FALSE(aht.update(1050, &t, &rh));
    TEST_ASSERT_TRUE(bus.script_consumed());

    // At 80 ms the part still reports busy → poll again later, no failure.
    bus.expect_read(0x38, aht_frame(0x9C, 0, 0));
    TEST_ASSERT_FALSE(aht.update(1080, &t, &rh));
    TEST_ASSERT_EQUAL_UINT32(0, aht.health().fails);

    bus.expect_read(0x38, aht_frame(0x1C, 0xF0000, 0x5C28F));
    TEST_ASSERT_TRUE(aht.update(1095, &t, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 93.75f, rh);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 22.0f, t);
    TEST_ASSERT_FALSE(aht.busy());
    TEST_ASSERT_EQUAL_UINT32(1, aht.health().reads);
    TEST_ASSERT_EQUAL_UINT32(0, aht.health().fails);
    // A sample is returned exactly once.
    TEST_ASSERT_FALSE(aht.update(1200, &t, &rh));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    // Nothing on the main path ever blocks.
    TEST_ASSERT_EQUAL_UINT32(0, clock.total_delayed_ms);
}

void test_aht20_respects_self_heating_interval() {
    MockI2cBus bus;
    MockClock clock;
    sp::Aht20 aht(bus, clock);
    float t, rh;
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(0));
    bus.expect_read(0x38, aht_frame(0x1C, 0x80000, 0x66666));
    TEST_ASSERT_TRUE(aht.update(80, &t, &rh));
    // < 2 s since the last trigger: refused without touching the bus.
    TEST_ASSERT_FALSE(aht.start(1999));
    TEST_ASSERT_TRUE(bus.script_consumed());
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(2000));
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_aht20_stuck_busy_past_grace_is_a_failure() {
    MockI2cBus bus;
    MockClock clock;
    sp::Aht20 aht(bus, clock);
    float t, rh;
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(0));
    bus.expect_read(0x38, aht_frame(0x9C, 0, 0));
    TEST_ASSERT_FALSE(aht.update(150, &t, &rh));  // busy, inside grace
    TEST_ASSERT_EQUAL_UINT32(0, aht.health().fails);
    bus.expect_read(0x38, aht_frame(0x9C, 0, 0));
    TEST_ASSERT_FALSE(aht.update(200, &t, &rh));  // 80 + 120 ms: give up
    TEST_ASSERT_EQUAL_UINT32(1, aht.health().fails);
    TEST_ASSERT_EQUAL_STRING("busy timeout", aht.health().last_error);
    TEST_ASSERT_FALSE(aht.busy());
}

void test_aht20_uncalibrated_sample_dropped_and_init_rerun() {
    MockI2cBus bus;
    MockClock clock;
    sp::Aht20 aht(bus, clock);
    float t = 5, rh = 5;
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(0));
    // CRC-valid, but the calibration bit is clear (the part reset). The
    // sample (collected late, at 2 s) is dropped and the init sequence
    // starts in the same pass.
    bus.expect_read(0x38, aht_frame(0x10, 0x80000, 0x66666));
    bus.expect_write(0x38, {0x1B, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2000, &t, &rh));
    TEST_ASSERT_EQUAL_STRING("not calibrated", aht.health().last_error);
    TEST_ASSERT_EQUAL_FLOAT(5.0f, t);
    TEST_ASSERT_TRUE(aht.initializing());
    TEST_ASSERT_TRUE(bus.script_consumed());

    // Each later pass runs only the steps that are due — the 5 / 10 ms
    // settles are measured, never slept.
    TEST_ASSERT_FALSE(aht.update(2004, &t, &rh));   // 5 ms not yet up
    TEST_ASSERT_TRUE(bus.script_consumed());
    bus.expect_read(0x38, {0x18, 0x11, 0x22});
    TEST_ASSERT_FALSE(aht.update(2005, &t, &rh));
    TEST_ASSERT_FALSE(aht.update(2014, &t, &rh));   // 10 ms not yet up
    // Write-back of 0x1B, then 0x1C's request chains in the same pass.
    bus.expect_write(0x38, {0xBB, 0x11, 0x22});
    bus.expect_write(0x38, {0x1C, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2015, &t, &rh));
    bus.expect_read(0x38, {0x18, 0x33, 0x44});
    TEST_ASSERT_FALSE(aht.update(2020, &t, &rh));
    bus.expect_write(0x38, {0xBC, 0x33, 0x44});
    bus.expect_write(0x38, {0x1E, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2030, &t, &rh));
    bus.expect_read(0x38, {0x18, 0x08, 0x00});
    TEST_ASSERT_FALSE(aht.update(2035, &t, &rh));
    bus.expect_write(0x38, {0xBE, 0x08, 0x00});   // 0xB0 | 0x1E
    TEST_ASSERT_FALSE(aht.update(2045, &t, &rh));
    // No trigger while the sequence runs (it is not a failure either).
    const uint32_t fails = aht.health().fails;
    TEST_ASSERT_FALSE(aht.start(2046));
    TEST_ASSERT_EQUAL_UINT32(fails, aht.health().fails);
    TEST_ASSERT_TRUE(bus.script_consumed());
    // 10 ms after the last register: status re-read; calibrated now, so no
    // v1.0 0xBE init.
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x18});
    TEST_ASSERT_FALSE(aht.update(2055, &t, &rh));
    TEST_ASSERT_FALSE(aht.initializing());
    // The next trigger goes out normally.
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(2100));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
    TEST_ASSERT_EQUAL_UINT32(0, clock.total_delayed_ms);
}

void test_aht20_runtime_init_falls_back_to_0xbe_and_retries_after_nack() {
    MockI2cBus bus;
    MockClock clock;
    sp::Aht20 aht(bus, clock);
    float t, rh;
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(0));
    bus.expect_read(0x38, aht_frame(0x00, 0x80000, 0x66666));
    bus.expect_write_nack(0x38);  // {0x1B, 0, 0} refused
    TEST_ASSERT_FALSE(aht.update(80, &t, &rh));
    TEST_ASSERT_EQUAL_STRING("init failed", aht.health().last_error);
    TEST_ASSERT_TRUE(aht.initializing());  // triggers stay off
    TEST_ASSERT_FALSE(aht.update(500, &t, &rh));  // nothing runs by itself
    TEST_ASSERT_TRUE(bus.script_consumed());

    // The next read pass restarts the sequence instead of triggering.
    bus.expect_write(0x38, {0x1B, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.start(2000));
    TEST_ASSERT_TRUE(bus.script_consumed());
    bus.expect_read(0x38, {0x00, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2005, &t, &rh));
    bus.expect_write(0x38, {0xBB, 0x00, 0x00});
    bus.expect_write(0x38, {0x1C, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2015, &t, &rh));
    bus.expect_read(0x38, {0x00, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2020, &t, &rh));
    bus.expect_write(0x38, {0xBC, 0x00, 0x00});
    bus.expect_write(0x38, {0x1E, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2030, &t, &rh));
    bus.expect_read(0x38, {0x00, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2035, &t, &rh));
    bus.expect_write(0x38, {0xBE, 0x00, 0x00});
    TEST_ASSERT_FALSE(aht.update(2045, &t, &rh));
    // Still uncalibrated after the registers: the v1.0 init, 10 ms settle.
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x00});
    bus.expect_write(0x38, {0xBE, 0x08, 0x00});
    TEST_ASSERT_FALSE(aht.update(2055, &t, &rh));
    TEST_ASSERT_TRUE(aht.initializing());
    TEST_ASSERT_FALSE(aht.update(2064, &t, &rh));
    TEST_ASSERT_TRUE(aht.initializing());
    TEST_ASSERT_FALSE(aht.update(2065, &t, &rh));
    TEST_ASSERT_FALSE(aht.initializing());
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(4000));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_aht20_read_nack_and_trigger_nack_are_failures() {
    MockI2cBus bus;
    MockClock clock;
    sp::Aht20 aht(bus, clock);
    float t, rh;
    bus.expect_write_nack(0x38);
    TEST_ASSERT_FALSE(aht.start(0));
    TEST_ASSERT_EQUAL_STRING("trigger failed", aht.health().last_error);
    TEST_ASSERT_FALSE(aht.busy());
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    TEST_ASSERT_TRUE(aht.start(5000));
    bus.expect_read(0x38, {}, /*ack=*/false);
    TEST_ASSERT_FALSE(aht.update(5080, &t, &rh));
    TEST_ASSERT_EQUAL_STRING("read error", aht.health().last_error);
    TEST_ASSERT_EQUAL_UINT32(2, aht.health().fails);
    TEST_ASSERT_FALSE(aht.busy());
}

// ── BME280 / BMP280 ────────────────────────────────────────────

// Trimming registers 0x88..0xA1: the BMP280 datasheet's worked-example
// T1..T3 / P1..P9 (BST-BMP280-DS001 §3.12) + reserved 0xA0 + dig_H1 = 75.
static const std::vector<uint8_t> kBmeCalib88 = {
    0x70, 0x6B, 0x43, 0x67, 0x18, 0xFC, 0x7D, 0x8E, 0x43,
    0xD6, 0xD0, 0x0B, 0x27, 0x0B, 0x8C, 0x00, 0xF9, 0xFF,
    0x8C, 0x3C, 0xF8, 0xC6, 0x70, 0x17, 0x00, 0x4B};
// 0xE1..0xE7: H2 = 370, H3 = 0, H4 = 303, H5 = 50, H6 = 30 (a typical part).
static const std::vector<uint8_t> kBmeCalibE1 = {0x72, 0x01, 0x00, 0x12,
                                                 0x2F, 0x03, 0x1E};

static sp::Bme280::Calib bme_calib() {
    sp::Bme280::Calib c;
    TEST_ASSERT_TRUE(sp::Bme280::parse_calib(kBmeCalib88.data(),
                                             kBmeCalibE1.data(), &c));
    return c;
}

void test_bme280_parse_calib_register_layout() {
    sp::Bme280::Calib c = bme_calib();
    TEST_ASSERT_EQUAL_UINT16(27504, c.t1);
    TEST_ASSERT_EQUAL_INT16(26435, c.t2);
    TEST_ASSERT_EQUAL_INT16(-1000, c.t3);
    TEST_ASSERT_EQUAL_UINT16(36477, c.p1);
    TEST_ASSERT_EQUAL_INT16(-10685, c.p2);
    TEST_ASSERT_EQUAL_INT16(3024, c.p3);
    TEST_ASSERT_EQUAL_INT16(2855, c.p4);
    TEST_ASSERT_EQUAL_INT16(140, c.p5);
    TEST_ASSERT_EQUAL_INT16(-7, c.p6);
    TEST_ASSERT_EQUAL_INT16(15500, c.p7);
    TEST_ASSERT_EQUAL_INT16(-14600, c.p8);
    TEST_ASSERT_EQUAL_INT16(6000, c.p9);
    TEST_ASSERT_EQUAL_UINT8(75, c.h1);
    TEST_ASSERT_EQUAL_INT16(370, c.h2);
    TEST_ASSERT_EQUAL_UINT8(0, c.h3);
    TEST_ASSERT_EQUAL_INT16(303, c.h4);
    TEST_ASSERT_EQUAL_INT16(50, c.h5);
    TEST_ASSERT_EQUAL_INT8(30, c.h6);

    // dig_H4 / dig_H5 are 12-bit SIGNED values split over 0xE4..0xE6: the
    // MSB register sign-extends (Bosch API unpacking).
    std::vector<uint8_t> e1 = {0x00, 0x00, 0x00, 0xF0, 0x5A, 0x81, 0xFF};
    sp::Bme280::Calib n;
    TEST_ASSERT_TRUE(sp::Bme280::parse_calib(kBmeCalib88.data(), e1.data(), &n));
    TEST_ASSERT_EQUAL_INT16(-246, n.h4);   // 0xF0 → -16 * 16 | 0xA
    TEST_ASSERT_EQUAL_INT16(-2027, n.h5);  // 0x81 → -127 * 16 | 0x5
    TEST_ASSERT_EQUAL_INT8(-1, n.h6);

    // A blank (all-zero) trim read is not a sensor.
    std::vector<uint8_t> zero(26, 0x00);
    TEST_ASSERT_FALSE(sp::Bme280::parse_calib(zero.data(), nullptr, &n));
    std::vector<uint8_t> ff(26, 0xFF);
    TEST_ASSERT_FALSE(sp::Bme280::parse_calib(ff.data(), nullptr, &n));
}

void test_bme280_compensation_matches_bmp280_datasheet_example() {
    // BST-BMP280-DS001 §3.12 worked example (the BME280 uses the identical
    // T/P compensation): adc_T 519888, adc_P 415148 → T 25.08 °C,
    // t_fine 128422, p 100653.27 Pa.
    sp::Bme280::Calib c = bme_calib();
    int32_t t_fine = 0;
    TEST_ASSERT_EQUAL_INT32(2508, sp::Bme280::compensate_t(519888, c, &t_fine));
    TEST_ASSERT_EQUAL_INT32(128422, t_fine);
    uint32_t p = sp::Bme280::compensate_p(415148, t_fine, c);
    // Integer (Q24.8) path: 25767233 / 256 = 100653.25 Pa.
    TEST_ASSERT_EQUAL_UINT32(25767233u, p);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 100653.27f, (float)p / 256.0f);
}

void test_bme280_humidity_compensation_matches_double_formula() {
    // No worked humidity example in the datasheet: the integer (Q22.10)
    // path is pinned bit-exact, and checked against the datasheet's
    // double-precision formula (§8.1) computed offline for the same trim.
    sp::Bme280::Calib c = bme_calib();
    int32_t t_fine = 0;
    sp::Bme280::compensate_t(519888, c, &t_fine);
    struct { int32_t adc; uint32_t q10; float pct_double; } v[] = {
        {28000, 49630, 48.4694f},
        {31000, 67082, 65.5126f},
        {36000, 95973, 93.7270f},   // fruiting-chamber humidity
        {40000, 102400, 100.0f},    // clamps at 100 %
    };
    for (auto& e : v) {
        uint32_t q = sp::Bme280::compensate_h(e.adc, t_fine, c);
        TEST_ASSERT_EQUAL_UINT32(e.q10, q);
        TEST_ASSERT_FLOAT_WITHIN(0.01f, e.pct_double, (float)q / 1024.0f);
    }
    // Never negative: a tiny ADC value clamps at 0.
    TEST_ASSERT_EQUAL_UINT32(0, sp::Bme280::compensate_h(0, t_fine, c));
}

void test_bme280_identify_by_chip_id() {
    struct { uint8_t id; sp::BaroKind want; } cases[] = {
        {0x60, sp::BaroKind::Bme280},
        {0x58, sp::BaroKind::Bmp280},
        {0x57, sp::BaroKind::Bmp280},
        {0x56, sp::BaroKind::Bmp280},
        {0x61, sp::BaroKind::None},  // BME680 — different part
        {0x55, sp::BaroKind::None},  // BMP180 — different part
    };
    for (auto& c : cases) {
        MockI2cBus bus;
        bus.expect_write(0x77, {0xD0});
        bus.expect_read(0x77, {c.id});
        TEST_ASSERT_EQUAL_INT((int)c.want, (int)sp::Bme280::identify(bus, 0x77));
        TEST_ASSERT_TRUE(bus.script_consumed());
    }
    MockI2cBus bus;
    bus.expect_write_nack(0x76);
    TEST_ASSERT_EQUAL_INT((int)sp::BaroKind::None,
                          (int)sp::Bme280::identify(bus, 0x76));
}

static void script_bme_begin(MockI2cBus& bus, uint8_t addr, bool humidity) {
    bus.expect_write(addr, {0xE0, 0xB6});  // soft reset
    bus.expect_write(addr, {0xF3});
    bus.expect_read(addr, {0x01});         // NVM copy still running
    bus.expect_write(addr, {0xF3});
    bus.expect_read(addr, {0x00});         // done
    bus.expect_write(addr, {0x88});
    bus.expect_read(addr, kBmeCalib88);
    if (humidity) {
        bus.expect_write(addr, {0xE1});
        bus.expect_read(addr, kBmeCalibE1);
        bus.expect_write(addr, {0xF2, 0x01});  // osrs_h ×1
    }
    bus.expect_write(addr, {0xF5, 0x00});      // filter off
    bus.expect_write(addr, {0xF4, 0x24});      // ×1 / ×1, sleep
}

void test_bme280_begin_and_forced_measurement() {
    MockI2cBus bus;
    MockClock clock;
    sp::Bme280 bme(bus, clock, 0x76, sp::BaroKind::Bme280);
    script_bme_begin(bus, 0x76, true);
    TEST_ASSERT_TRUE(bme.begin());

    bus.expect_write(0x76, {0xF2, 0x01});  // re-asserted every pass
    bus.expect_write(0x76, {0xF4, 0x25});  // forced
    bus.expect_write(0x76, {0xF3});
    bus.expect_read(0x76, {0x00});         // not measuring
    bus.expect_write(0x76, {0xF7});
    // adc_P 415148 = 0x655AC, adc_T 519888 = 0x7EED0, adc_H 36000 = 0x8CA0.
    bus.expect_read(0x76, {0x65, 0x5A, 0xC0, 0x7E, 0xED, 0x00, 0x8C, 0xA0});
    uint32_t before = clock.total_delayed_ms;
    float t = 0, p = 0, rh = 0;
    TEST_ASSERT_TRUE(bme.measure(&t, &p, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 25.08f, t);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 100653.27f, p);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 93.727f, rh);
    // The datasheet max conversion time (9.3 ms) is waited out, and the
    // pass stays well inside the 50 ms per-call budget.
    uint32_t waited = clock.total_delayed_ms - before;
    TEST_ASSERT_TRUE(waited >= 10 && waited < 50);
    TEST_ASSERT_EQUAL_UINT32(1, bme.health().reads);
    TEST_ASSERT_EQUAL_UINT32(0, bme.health().fails);
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_bmp280_has_no_humidity() {
    MockI2cBus bus;
    MockClock clock;
    sp::Bme280 bmp(bus, clock, 0x77, sp::BaroKind::Bmp280);
    TEST_ASSERT_FALSE(bmp.has_humidity());
    script_bme_begin(bus, 0x77, false);  // no 0xE1 trim, no ctrl_hum
    TEST_ASSERT_TRUE(bmp.begin());
    bus.expect_write(0x77, {0xF4, 0x25});
    bus.expect_write(0x77, {0xF3});
    bus.expect_read(0x77, {0x00});
    bus.expect_write(0x77, {0xF7});
    bus.expect_read(0x77, {0x65, 0x5A, 0xC0, 0x7E, 0xED, 0x00});  // 6 bytes
    float t = 0, p = 0, rh = -1.0f;
    TEST_ASSERT_TRUE(bmp.measure(&t, &p, &rh));
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 100653.27f, p);
    TEST_ASSERT_EQUAL_FLOAT(-1.0f, rh);  // untouched — no humidity element
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_bme280_skipped_sample_and_busy_are_failures() {
    MockI2cBus bus;
    MockClock clock;
    sp::Bme280 bme(bus, clock, 0x76, sp::BaroKind::Bme280);
    script_bme_begin(bus, 0x76, true);
    TEST_ASSERT_TRUE(bme.begin());
    float t = 1, p = 1, rh = 1;

    // Data registers still at their reset value 0x80000: no conversion ran.
    bus.expect_write(0x76, {0xF2, 0x01});
    bus.expect_write(0x76, {0xF4, 0x25});
    bus.expect_write(0x76, {0xF3});
    bus.expect_read(0x76, {0x00});
    bus.expect_write(0x76, {0xF7});
    bus.expect_read(0x76, {0x80, 0x00, 0x00, 0x80, 0x00, 0x00, 0x80, 0x00});
    TEST_ASSERT_FALSE(bme.measure(&t, &p, &rh));
    TEST_ASSERT_EQUAL_STRING("no sample", bme.health().last_error);

    // Still measuring after the datasheet max + one retry.
    bus.expect_write(0x76, {0xF2, 0x01});
    bus.expect_write(0x76, {0xF4, 0x25});
    bus.expect_write(0x76, {0xF3});
    bus.expect_read(0x76, {0x08});
    bus.expect_write(0x76, {0xF3});
    bus.expect_read(0x76, {0x08});
    TEST_ASSERT_FALSE(bme.measure(&t, &p, &rh));
    TEST_ASSERT_EQUAL_STRING("busy", bme.health().last_error);
    TEST_ASSERT_EQUAL_UINT32(2, bme.health().fails);
    TEST_ASSERT_EQUAL_FLOAT(1.0f, p);  // outputs untouched
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_bme280_measure_retries_begin_until_it_succeeds() {
    MockI2cBus bus;
    MockClock clock;
    sp::Bme280 bme(bus, clock, 0x76, sp::BaroKind::Bme280);
    float t, p, rh;
    bus.expect_write_nack(0x76);  // reset NACK — begin fails
    TEST_ASSERT_FALSE(bme.measure(&t, &p, &rh));
    TEST_ASSERT_EQUAL_STRING("reset failed", bme.health().last_error);
    TEST_ASSERT_TRUE(bus.script_consumed());
}

void test_autodetect_finds_aht20_and_bmp280_combo_board() {
    // The "AHT20 + BMP280" combo board alone on the bus: AHT20 @0x38 and the
    // BMP280 strapped to 0x77.
    MockI2cBus bus;
    MockClock clock;
    bus.expect_write_nack(0x44);
    bus.expect_write_nack(0x44);
    bus.expect_write_nack(0x45);
    bus.expect_write_nack(0x45);
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x61);
    bus.expect_write_nack(0x23);
    bus.expect_write_nack(0x5C);
    bus.expect_write(0x38, {0x71});
    bus.expect_read(0x38, {0x18});
    bus.expect_write(0x38, {0xAC, 0x33, 0x00});
    bus.expect_read(0x38, aht_frame(0x1C, 0x80000, 0x66666));
    bus.expect_write_nack(0x76);
    bus.expect_write(0x77, {0xD0});
    bus.expect_read(0x77, {0x58});

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::None, (int)d.temp_rh);
    TEST_ASSERT_TRUE(d.aht20);
    TEST_ASSERT_EQUAL_INT((int)sp::BaroKind::Bmp280, (int)d.baro);
    TEST_ASSERT_EQUAL_UINT8(0x77, d.baro_addr);
    TEST_ASSERT_EQUAL_STRING("bmp280", sp::baro_kind_str(d.baro));
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_crc8_datasheet_vector);
    RUN_TEST(test_transport_rejects_bad_crc);
    RUN_TEST(test_transport_cmd_arg_frames_crc);
    RUN_TEST(test_sht3x_measure_conversion);
    RUN_TEST(test_sht3x_read_fail_counts);
    RUN_TEST(test_sht3x_probe_waits_out_soft_reset_before_serial_read);
    RUN_TEST(test_sht3x_probe_reset_nack_is_absent);
    RUN_TEST(test_sht4x_single_byte_protocol_and_rh_formula);
    RUN_TEST(test_scd4x_begin_disables_asc_and_persists_once);
    RUN_TEST(test_scd4x_begin_skips_persist_when_asc_already_off);
    RUN_TEST(test_scd4x_begin_forces_asc_off_when_asc_read_fails);
    RUN_TEST(test_scd4x_begin_asc_write_failure_is_reported);
    RUN_TEST(test_scd4x_probe_stops_stale_periodic_mode_first);
    RUN_TEST(test_scd4x_probe_absent);
    RUN_TEST(test_scd4x_data_ready_and_read);
    RUN_TEST(test_scd4x_data_ready_bus_failure_is_a_health_fail);
    RUN_TEST(test_scd4x_frc_success_and_failure);
    RUN_TEST(test_scd30_float_decode);
    RUN_TEST(test_scd30_read_measurement_floats);
    RUN_TEST(test_scd30_stretch_timeout_is_read_fail);
    RUN_TEST(test_scd30_data_ready_bus_failure_is_a_health_fail);
    RUN_TEST(test_scd30_frc_success_and_failure);
    RUN_TEST(test_scd30_out_of_range_rejected);
    RUN_TEST(test_scd30_nan_rejected);
    RUN_TEST(test_bh1750_lux_conversion);
    RUN_TEST(test_autodetect_sht4x_wins_at_0x44);
    RUN_TEST(test_autodetect_sht3x_after_sht4x_miss);
    RUN_TEST(test_autodetect_nothing_attached);
    RUN_TEST(test_crc8_catalogue_check_value);
    RUN_TEST(test_ws_cam_exio_powers_the_camera);
    RUN_TEST(test_ws_cam_exio_absent_expander_reports_false);
    RUN_TEST(test_aht20_decode_datasheet_formulas);
    RUN_TEST(test_aht20_decode_rejects_busy_crc_and_range);
    RUN_TEST(test_aht20_probe_inits_uncalibrated_part_then_requires_crc);
    RUN_TEST(test_aht20_probe_v11_init_that_sets_calibration_skips_0xbe);
    RUN_TEST(test_aht20_probe_initialised_part_skips_init);
    RUN_TEST(test_aht20_probe_register_init_nack_is_absent);
    RUN_TEST(test_aht20_probe_rejects_ack_without_valid_frame);
    RUN_TEST(test_aht20_probe_absent);
    RUN_TEST(test_aht20_async_measurement_state_machine);
    RUN_TEST(test_aht20_respects_self_heating_interval);
    RUN_TEST(test_aht20_stuck_busy_past_grace_is_a_failure);
    RUN_TEST(test_aht20_uncalibrated_sample_dropped_and_init_rerun);
    RUN_TEST(test_aht20_runtime_init_falls_back_to_0xbe_and_retries_after_nack);
    RUN_TEST(test_aht20_read_nack_and_trigger_nack_are_failures);
    RUN_TEST(test_bme280_parse_calib_register_layout);
    RUN_TEST(test_bme280_compensation_matches_bmp280_datasheet_example);
    RUN_TEST(test_bme280_humidity_compensation_matches_double_formula);
    RUN_TEST(test_bme280_identify_by_chip_id);
    RUN_TEST(test_bme280_begin_and_forced_measurement);
    RUN_TEST(test_bmp280_has_no_humidity);
    RUN_TEST(test_bme280_skipped_sample_and_busy_are_failures);
    RUN_TEST(test_bme280_measure_retries_begin_until_it_succeeds);
    RUN_TEST(test_autodetect_finds_aht20_and_bmp280_combo_board);
    return UNITY_END();
}
