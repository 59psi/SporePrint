// test_core_link — the MQTT/WiFi-loss failsafe policy (fw-node#7).
//
// CLAUDE.md §5c: "10min MQTT watchdog → safe mode". The node had no
// disconnected-duration tracking at all: a dead Pi/broker left the lighting
// bank lit indefinitely and relays running to their max-on, and a WiFi drop
// the Arduino core refuses to auto-retry (AUTH_FAIL et al.) left the node
// dark until power-cycled. LinkWatchdog is the pure policy; the composition
// root turns its actions into channel force_off()s and WiFi.begin().

#include <unity.h>

#include <stdint.h>

#include "link_watchdog.h"

void setUp() {}
void tearDown() {}

static const uint32_t kSafe = sp::LinkWatchdog::kSafeModeAfterMs;
static const uint32_t kRetry = sp::LinkWatchdog::kWifiRetryMs;

void test_constants_match_spec() {
    TEST_ASSERT_EQUAL_UINT32(10UL * 60UL * 1000UL, kSafe);
    TEST_ASSERT_EQUAL_UINT32(60UL * 1000UL, kRetry);
}

void test_healthy_link_takes_no_action() {
    sp::LinkWatchdog w;
    w.begin(0);
    for (uint32_t t = 0; t < 3UL * kSafe; t += 1000) {
        sp::LinkWatchdog::Actions a = w.update(t, true, true);
        TEST_ASSERT_FALSE(a.enter_safe_mode);
        TEST_ASSERT_FALSE(a.exit_safe_mode);
        TEST_ASSERT_FALSE(a.wifi_retry);
    }
    TEST_ASSERT_FALSE(w.safe_mode());
}

void test_mqtt_loss_enters_safe_mode_once_after_ten_minutes() {
    sp::LinkWatchdog w;
    w.begin(0);
    w.update(1000, true, true);  // last seen connected at t=1000
    int entered = 0;
    for (uint32_t t = 2000; t <= 1000 + kSafe - 1; t += 1000) {
        sp::LinkWatchdog::Actions a = w.update(t, true, false);
        TEST_ASSERT_FALSE(a.enter_safe_mode);
    }
    TEST_ASSERT_FALSE(w.safe_mode());
    sp::LinkWatchdog::Actions a = w.update(1000 + kSafe, true, false);
    TEST_ASSERT_TRUE(a.enter_safe_mode);
    TEST_ASSERT_TRUE(w.safe_mode());
    // Latched: no repeat while still disconnected.
    for (uint32_t t = 1000 + kSafe + 1000; t < 1000 + 5UL * kSafe; t += 7000) {
        a = w.update(t, true, false);
        if (a.enter_safe_mode) ++entered;
    }
    TEST_ASSERT_EQUAL_INT(0, entered);
}

void test_reconnect_exits_safe_mode_once() {
    sp::LinkWatchdog w;
    w.begin(0);
    w.update(kSafe, true, false);
    TEST_ASSERT_TRUE(w.safe_mode());
    sp::LinkWatchdog::Actions a = w.update(kSafe + 5000, true, true);
    TEST_ASSERT_TRUE(a.exit_safe_mode);
    TEST_ASSERT_FALSE(w.safe_mode());
    a = w.update(kSafe + 6000, true, true);
    TEST_ASSERT_FALSE(a.exit_safe_mode);
    // The outage length is reported for the recovery log line.
    TEST_ASSERT_EQUAL_UINT32(kSafe + 5000, w.last_outage_ms());
    // The 10-minute clock restarts from the last connected pass.
    a = w.update(kSafe + 6000 + kSafe - 1, true, false);
    TEST_ASSERT_FALSE(a.enter_safe_mode);
    a = w.update(kSafe + 6000 + kSafe, true, false);
    TEST_ASSERT_TRUE(a.enter_safe_mode);
}

void test_never_connected_after_boot_still_enters_safe_mode() {
    // Broker unreachable from boot: channels are already off, but the policy
    // must still latch so a later connect is reported as a recovery.
    sp::LinkWatchdog w;
    w.begin(5000);
    TEST_ASSERT_FALSE(w.update(5000 + kSafe - 1, true, false).enter_safe_mode);
    TEST_ASSERT_TRUE(w.update(5000 + kSafe, true, false).enter_safe_mode);
}

void test_wifi_down_retries_every_minute() {
    sp::LinkWatchdog w;
    w.begin(0);
    w.update(10000, true, true);  // WiFi last up at 10 s
    int retries = 0;
    uint32_t last_retry = 0;
    for (uint32_t t = 11000; t <= 10000 + 5UL * kRetry; t += 1000) {
        sp::LinkWatchdog::Actions a = w.update(t, false, false);
        if (a.wifi_retry) {
            if (retries > 0) {
                TEST_ASSERT_EQUAL_UINT32(kRetry, t - last_retry);
            } else {
                TEST_ASSERT_EQUAL_UINT32(10000 + kRetry, t);
            }
            last_retry = t;
            ++retries;
        }
    }
    TEST_ASSERT_EQUAL_INT(5, retries);
    // WiFi back: retries stop.
    TEST_ASSERT_FALSE(w.update(10000 + 6UL * kRetry, true, false).wifi_retry);
    TEST_ASSERT_FALSE(w.update(10000 + 8UL * kRetry, true, false).wifi_retry);
}

void test_millis_wrap_is_safe() {
    sp::LinkWatchdog w;
    uint32_t t0 = 0xFFFFFFFFu - 60000u;
    w.begin(t0);
    w.update(t0, true, true);
    // 9 minutes later (wrapped) — no safe mode yet.
    uint32_t t9 = t0 + 9UL * 60UL * 1000UL;
    TEST_ASSERT_TRUE(t9 < t0);
    TEST_ASSERT_FALSE(w.update(t9, true, false).enter_safe_mode);
    TEST_ASSERT_TRUE(w.update(t0 + kSafe, true, false).enter_safe_mode);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_constants_match_spec);
    RUN_TEST(test_healthy_link_takes_no_action);
    RUN_TEST(test_mqtt_loss_enters_safe_mode_once_after_ten_minutes);
    RUN_TEST(test_reconnect_exits_safe_mode_once);
    RUN_TEST(test_never_connected_after_boot_still_enters_safe_mode);
    RUN_TEST(test_wifi_down_retries_every_minute);
    RUN_TEST(test_millis_wrap_is_safe);
    return UNITY_END();
}
