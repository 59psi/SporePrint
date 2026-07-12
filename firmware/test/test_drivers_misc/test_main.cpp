// test_drivers_misc — the config-flag peripherals: MH-Z19C UART state
// machine, HX711 bit-bang, reed-switch debounce.

#include <unity.h>

#include "hx711.h"
#include "mhz19.h"
#include "mock_hal.h"
#include "reed_switch.h"

using sp_testing::MockClock;
using sp_testing::MockPin;
using sp_testing::MockUart;

void setUp() {}
void tearDown() {}

// ── MH-Z19C ────────────────────────────────────────────────────

static std::vector<uint8_t> mhz_reply(uint16_t ppm) {
    std::vector<uint8_t> f = {0xFF, 0x86, (uint8_t)(ppm >> 8),
                              (uint8_t)(ppm & 0xFF), 0, 0, 0, 0, 0};
    uint8_t frame[9];
    for (int i = 0; i < 9; ++i) frame[i] = f[i];
    f[8] = sp::Mhz19::checksum(frame);
    return f;
}

void test_mhz19_checksum() {
    // Read-CO₂ request frame from the datasheet: checksum 0x79.
    uint8_t req[9] = {0xFF, 0x01, 0x86, 0, 0, 0, 0, 0, 0};
    TEST_ASSERT_EQUAL_UINT8(0x79, sp::Mhz19::checksum(req));
}

void test_mhz19_begin_sends_abc_off() {
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);
    mhz.begin(false);
    TEST_ASSERT_EQUAL_INT(9, (int)uart.tx.size());
    TEST_ASSERT_EQUAL_UINT8(0x79, uart.tx[2]);  // ABC toggle command
    TEST_ASSERT_EQUAL_UINT8(0x00, uart.tx[3]);  // OFF — never auto-baseline
    // A bare begin() must stay OFF — the default argument can't drift.
    uart.tx.clear();
    mhz.begin();
    TEST_ASSERT_EQUAL_INT(9, (int)uart.tx.size());
    TEST_ASSERT_EQUAL_UINT8(0x00, uart.tx[3]);
}

void test_mhz19_begin_abc_on_when_asked() {
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);
    mhz.begin(true);
    TEST_ASSERT_EQUAL_INT(9, (int)uart.tx.size());
    TEST_ASSERT_EQUAL_UINT8(0x79, uart.tx[2]);
    TEST_ASSERT_EQUAL_UINT8(0xA0, uart.tx[3]);  // ON — caller opted in
    uint8_t frame[9];
    for (int i = 0; i < 9; ++i) frame[i] = uart.tx[i];
    TEST_ASSERT_EQUAL_UINT8(sp::Mhz19::checksum(frame), uart.tx[8]);
}

void test_mhz19_calibrate_zero_frame() {
    // Datasheet zero-point frame, byte-for-byte: FF 01 87 00 00 00 00 00 78.
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);
    mhz.calibrate_zero();
    const uint8_t expected[9] = {0xFF, 0x01, 0x87, 0x00, 0x00,
                                 0x00, 0x00, 0x00, 0x78};
    TEST_ASSERT_EQUAL_INT(9, (int)uart.tx.size());
    TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, uart.tx.data(), 9);
}

void test_mhz19_read_roundtrip_trickled() {
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);

    TEST_ASSERT_TRUE(mhz.request_read());
    TEST_ASSERT_EQUAL_UINT8(0x86, uart.tx[2]);

    // Reply bytes ARRIVE across loop passes (9600 baud ≈ 1 byte/ms): queue
    // each chunk just before its update() pass.
    auto reply = mhz_reply(1450);
    uint16_t ppm = 0;
    uart.queue_reply({reply.begin(), reply.begin() + 3});
    TEST_ASSERT_FALSE(mhz.update(10, &ppm));  // 3 bytes so far
    uart.queue_reply({reply.begin() + 3, reply.begin() + 6});
    TEST_ASSERT_FALSE(mhz.update(20, &ppm));  // 6 bytes
    uart.queue_reply({reply.begin() + 6, reply.end()});
    TEST_ASSERT_TRUE(mhz.update(30, &ppm));   // 9 — complete
    TEST_ASSERT_EQUAL_UINT16(1450, ppm);
    TEST_ASSERT_FALSE(mhz.awaiting_reply());
    TEST_ASSERT_EQUAL_UINT32(0, mhz.health().fails);
}

void test_mhz19_resyncs_on_noise() {
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);
    TEST_ASSERT_TRUE(mhz.request_read());
    // Garbage, then a clean frame.
    uart.queue_reply({0x00, 0x42, 0xFF, 0x13});
    uart.queue_reply(mhz_reply(900));
    uint16_t ppm = 0;
    // The 0xFF in the noise latches briefly but 0x13 != 0x86 resyncs.
    TEST_ASSERT_TRUE(mhz.update(10, &ppm));
    TEST_ASSERT_EQUAL_UINT16(900, ppm);
}

void test_mhz19_bad_checksum_is_fail_not_zero() {
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);
    TEST_ASSERT_TRUE(mhz.request_read());
    auto bad = mhz_reply(700);
    bad[8] ^= 0xFF;
    uart.queue_reply(bad);
    uint16_t ppm = 0xDEAD;
    TEST_ASSERT_FALSE(mhz.update(10, &ppm));
    TEST_ASSERT_EQUAL_UINT16(0xDEAD, ppm);  // never wrote a value
    TEST_ASSERT_EQUAL_STRING("checksum", mhz.health().last_error);
    TEST_ASSERT_FALSE(mhz.awaiting_reply());
}

void test_mhz19_timeout() {
    MockUart uart;
    MockClock clock;
    sp::Mhz19 mhz(uart, clock);
    clock.now_ms = 1000;
    TEST_ASSERT_TRUE(mhz.request_read());
    uint16_t ppm;
    TEST_ASSERT_FALSE(mhz.update(1050, &ppm));  // inside deadline — waiting
    TEST_ASSERT_TRUE(mhz.awaiting_reply());
    TEST_ASSERT_FALSE(mhz.update(1101, &ppm));  // 100 ms deadline passed
    TEST_ASSERT_FALSE(mhz.awaiting_reply());
    TEST_ASSERT_EQUAL_STRING("timeout", mhz.health().last_error);
    // A new request is possible after the timeout.
    TEST_ASSERT_TRUE(mhz.request_read());
}

// ── HX711 ──────────────────────────────────────────────────────

static void no_delay(uint32_t) {}

void test_hx711_ready_is_single_pin_read() {
    MockPin dout, sck;
    sp::Hx711 hx(dout, sck, no_delay);
    hx.begin();
    dout.level = true;  // high = not ready (disconnected cell floats high)
    TEST_ASSERT_FALSE(hx.is_ready());
    dout.level = false;
    TEST_ASSERT_TRUE(hx.is_ready());
}

void test_hx711_reads_24_bits_with_gain_pulse() {
    MockPin dout, sck;
    sp::Hx711 hx(dout, sck, no_delay);
    hx.begin();
    sck.writes.clear();

    // Script 0x123456 MSB-first on DOUT.
    uint32_t sample = 0x123456;
    for (int i = 23; i >= 0; --i) dout.read_script.push_back((sample >> i) & 1);

    int32_t raw = hx.read_raw();
    TEST_ASSERT_EQUAL_INT32(0x123456, raw);
    // 24 data pulses + 1 gain pulse = 25 rising edges (50 writes hi+lo).
    int rising = 0;
    for (bool w : sck.writes)
        if (w) ++rising;
    TEST_ASSERT_EQUAL_INT(25, rising);
}

void test_hx711_sign_extends_negative() {
    MockPin dout, sck;
    sp::Hx711 hx(dout, sck, no_delay);
    hx.begin();
    uint32_t sample = 0x800001;  // most negative + 1
    for (int i = 23; i >= 0; --i) dout.read_script.push_back((sample >> i) & 1);
    TEST_ASSERT_EQUAL_INT32((int32_t)0xFF800001, hx.read_raw());
}

void test_hx711_to_grams_math_and_uncalibrated_guard() {
    // (raw − tare) / scale: (152300 − 148000) / 21.5 counts/g = 200.0 g.
    float grams = 0.0f;
    TEST_ASSERT_TRUE(sp::Hx711::to_grams(152300, 148000, 21.5f, &grams));
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 200.0f, grams);

    // Negative deltas stay signed (mass removed after taring).
    TEST_ASSERT_TRUE(sp::Hx711::to_grams(147785, 148000, 21.5f, &grams));
    TEST_ASSERT_FLOAT_WITHIN(0.01f, -10.0f, grams);

    // scale == 0 = uncalibrated: refuse, leave *grams untouched — the
    // node app publishes scale_raw instead of a garbage weight_g.
    grams = 123.0f;
    TEST_ASSERT_FALSE(sp::Hx711::to_grams(152300, 148000, 0.0f, &grams));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 123.0f, grams);
}

// ── reed switch ────────────────────────────────────────────────

void test_reed_debounce() {
    MockPin pin;
    sp::ReedSwitch reed(pin, 50);
    pin.level = false;  // LOW = closed
    reed.begin(0);
    TEST_ASSERT_TRUE(reed.is_closed());

    // Door opens at t=100 — no event until the level holds 50 ms.
    pin.level = true;
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::None, (int)reed.update(100));
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::None, (int)reed.update(120));
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::Opened,
                          (int)reed.update(151));
    TEST_ASSERT_FALSE(reed.is_closed());
    // No repeat events while steady.
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::None, (int)reed.update(500));

    // A 20 ms bounce back to closed is swallowed.
    pin.level = false;
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::None, (int)reed.update(600));
    pin.level = true;
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::None, (int)reed.update(620));
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::None, (int)reed.update(700));
    TEST_ASSERT_FALSE(reed.is_closed());

    // Real close.
    pin.level = false;
    reed.update(800);
    TEST_ASSERT_EQUAL_INT((int)sp::ReedSwitch::Event::Closed,
                          (int)reed.update(851));
    TEST_ASSERT_TRUE(reed.is_closed());
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_mhz19_checksum);
    RUN_TEST(test_mhz19_begin_sends_abc_off);
    RUN_TEST(test_mhz19_begin_abc_on_when_asked);
    RUN_TEST(test_mhz19_calibrate_zero_frame);
    RUN_TEST(test_mhz19_read_roundtrip_trickled);
    RUN_TEST(test_mhz19_resyncs_on_noise);
    RUN_TEST(test_mhz19_bad_checksum_is_fail_not_zero);
    RUN_TEST(test_mhz19_timeout);
    RUN_TEST(test_hx711_ready_is_single_pin_read);
    RUN_TEST(test_hx711_reads_24_bits_with_gain_pulse);
    RUN_TEST(test_hx711_sign_extends_negative);
    RUN_TEST(test_hx711_to_grams_math_and_uncalibrated_guard);
    RUN_TEST(test_reed_debounce);
    return UNITY_END();
}
