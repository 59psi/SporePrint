// test_drivers_i2c — Sensirion transport framing + every I²C driver against
// scripted bus transactions, including autodetect probe-order assertions.

#include <unity.h>

#include <string.h>

#include "autodetect.h"
#include "bh1750.h"
#include "mock_hal.h"
#include "scd30.h"
#include "scd4x.h"
#include "sensirion_transport.h"
#include "sht3x.h"
#include "sht4x.h"

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
    // SCD4x probe (0x62 get_serial) NACKs; SCD30 probe NACKs.
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x61);
    // BH1750 at 0x23 ACKs power-on.
    bus.expect_write(0x23, {0x01});

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::Sht4x, (int)d.temp_rh);
    TEST_ASSERT_EQUAL_UINT8(0x44, d.temp_rh_addr);
    TEST_ASSERT_EQUAL_INT((int)sp::Co2Kind::None, (int)d.co2);
    TEST_ASSERT_TRUE(d.bh1750);
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_autodetect_sht3x_after_sht4x_miss() {
    MockI2cBus bus;
    MockClock clock;
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
    // SCD4x answers.
    bus.expect_write(0x62, {0x36, 0x82});
    std::vector<uint8_t> scd_serial;
    push_word(scd_serial, 1);
    push_word(scd_serial, 2);
    push_word(scd_serial, 3);
    bus.expect_read(0x62, scd_serial);
    // BH1750 absent at both addresses.
    bus.expect_write_nack(0x23);
    bus.expect_write_nack(0x5C);

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::Sht3x, (int)d.temp_rh);
    TEST_ASSERT_EQUAL_INT((int)sp::Co2Kind::Scd4x, (int)d.co2);
    TEST_ASSERT_FALSE(d.bh1750);
    TEST_ASSERT_TRUE(bus.script_consumed());
    TEST_ASSERT_EQUAL_STRING("", bus.error.c_str());
}

void test_autodetect_nothing_attached() {
    MockI2cBus bus;
    MockClock clock;
    // Every probe NACKs: SHT4x@44, SHT3x reset@44, SHT4x@45, SHT3x reset@45,
    // SCD4x@62, SCD30@61, BH1750@23, BH1750@5C.
    bus.expect_write_nack(0x44);
    bus.expect_write_nack(0x44);
    bus.expect_write_nack(0x45);
    bus.expect_write_nack(0x45);
    bus.expect_write_nack(0x62);
    bus.expect_write_nack(0x61);
    bus.expect_write_nack(0x23);
    bus.expect_write_nack(0x5C);

    sp::DetectedSensors d = sp::autodetect_i2c(bus, clock);
    TEST_ASSERT_EQUAL_INT((int)sp::TempRhKind::None, (int)d.temp_rh);
    TEST_ASSERT_EQUAL_INT((int)sp::Co2Kind::None, (int)d.co2);
    TEST_ASSERT_FALSE(d.bh1750);
    TEST_ASSERT_TRUE(bus.script_consumed());
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_crc8_datasheet_vector);
    RUN_TEST(test_transport_rejects_bad_crc);
    RUN_TEST(test_transport_cmd_arg_frames_crc);
    RUN_TEST(test_sht3x_measure_conversion);
    RUN_TEST(test_sht3x_read_fail_counts);
    RUN_TEST(test_sht4x_single_byte_protocol_and_rh_formula);
    RUN_TEST(test_scd4x_begin_disables_asc_and_persists_once);
    RUN_TEST(test_scd4x_begin_skips_persist_when_asc_already_off);
    RUN_TEST(test_scd4x_data_ready_and_read);
    RUN_TEST(test_scd4x_frc_success_and_failure);
    RUN_TEST(test_scd30_float_decode);
    RUN_TEST(test_scd30_read_measurement_floats);
    RUN_TEST(test_scd30_stretch_timeout_is_read_fail);
    RUN_TEST(test_scd30_out_of_range_rejected);
    RUN_TEST(test_bh1750_lux_conversion);
    RUN_TEST(test_autodetect_sht4x_wins_at_0x44);
    RUN_TEST(test_autodetect_sht3x_after_sht4x_miss);
    RUN_TEST(test_autodetect_nothing_attached);
    return UNITY_END();
}
