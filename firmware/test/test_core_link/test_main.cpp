// test_core_link — the MQTT/WiFi-loss failsafe policy (fw-node#7).
//
// CLAUDE.md §5c: "10min MQTT watchdog → safe mode". The node had no
// disconnected-duration tracking at all: a dead Pi/broker left the lighting
// bank lit indefinitely and relays running to their max-on, and a WiFi drop
// the Arduino core refuses to auto-retry (AUTH_FAIL et al.) left the node
// dark until power-cycled. LinkWatchdog is the pure policy; the composition
// root turns its actions into channel force_off()s and WiFi.begin().
//
// Also: the heartbeat cadence (srv-hw#22) — PublishCadence keeps the status
// heartbeat inside the Pi's offline threshold whatever the telemetry interval.

#include <unity.h>

#include <stdint.h>

#include "clamps.h"
#include "link_watchdog.h"
#include "publish_cadence.h"

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

// ── heartbeat cadence (srv-hw#22) ──────────────────────────────
//
// The Pi marks a node offline (and pages) when no status/* frame arrived for
// 900 s (server/app/main.py _NODE_OFFLINE_THRESHOLD_SECONDS). The node used to
// publish its heartbeat only inside the telemetry block, so an operator-set
// publish_interval_ms of 15 min or more (the clamps allow 1 h) flapped the
// node offline/online every cycle. The heartbeat now runs on its own cadence,
// min(publish_interval_ms, 5 min) — CLAUDE.md "Heartbeat every 5 min".

static const uint32_t kPiOfflineThresholdMs = 900000;

void test_heartbeat_interval_is_capped_at_five_minutes() {
    sp::PublishCadence c(60000);
    TEST_ASSERT_EQUAL_UINT32(60000, c.heartbeat_interval_ms());
    c.set_publish_interval(300000);
    TEST_ASSERT_EQUAL_UINT32(300000, c.heartbeat_interval_ms());
    c.set_publish_interval(sp::kMaxPublishIntervalMs);  // 1 h
    TEST_ASSERT_EQUAL_UINT32(300000, c.heartbeat_interval_ms());
    // Every publish interval the clamps allow keeps two missed heartbeats of
    // margin under the Pi's offline threshold.
    for (uint32_t ms = sp::kMinPublishIntervalMs;
         ms <= sp::kMaxPublishIntervalMs; ms += 5000) {
        c.set_publish_interval(ms);
        TEST_ASSERT_TRUE(c.heartbeat_interval_ms() <= ms);
        TEST_ASSERT_TRUE(3u * c.heartbeat_interval_ms() <= kPiOfflineThresholdMs);
    }
}

// Drive the cadence the way loop() does (1 s passes) and return the longest
// gap between heartbeats over `span_ms`, counting both publishes.
static uint32_t max_heartbeat_gap(sp::PublishCadence& c, uint32_t start,
                                  uint32_t span_ms, int* telemetry,
                                  int* heartbeats) {
    uint32_t last_hb = start, worst = 0;
    *telemetry = 0;
    *heartbeats = 0;
    for (uint32_t off = 1000; off <= span_ms; off += 1000) {
        sp::PublishCadence::Due d = c.update(start + off);
        if (d.telemetry) ++*telemetry;
        if (d.heartbeat) {
            uint32_t gap = (start + off) - last_hb;
            if (gap > worst) worst = gap;
            last_hb = start + off;
            ++*heartbeats;
        }
    }
    return worst;
}

void test_hour_publish_interval_still_heartbeats_every_five_minutes() {
    sp::PublishCadence c(sp::kMaxPublishIntervalMs);
    c.begin(0);
    int telemetry = 0, heartbeats = 0;
    uint32_t worst = max_heartbeat_gap(c, 0, 2UL * 3600UL * 1000UL, &telemetry,
                                       &heartbeats);
    TEST_ASSERT_EQUAL_INT(2, telemetry);    // telemetry keeps the operator's 1 h
    TEST_ASSERT_EQUAL_INT(24, heartbeats);  // heartbeat every 5 min
    TEST_ASSERT_EQUAL_UINT32(300000, worst);
    TEST_ASSERT_TRUE(worst < kPiOfflineThresholdMs);
}

void test_default_interval_heartbeats_with_telemetry() {
    // At the 60 s default both fire on the same pass — unchanged wire
    // behavior for every node that never touched publish_interval_ms.
    sp::PublishCadence c(60000);
    c.begin(0);
    int fired = 0;
    for (uint32_t t = 1000; t <= 600000; t += 1000) {
        sp::PublishCadence::Due d = c.update(t);
        TEST_ASSERT_EQUAL(d.telemetry, d.heartbeat);
        if (d.telemetry) {
            TEST_ASSERT_EQUAL_UINT32(0, t % 60000);
            ++fired;
        }
    }
    TEST_ASSERT_EQUAL_INT(10, fired);
}

void test_interval_change_takes_effect_and_is_wrap_safe() {
    uint32_t t0 = 0xFFFFFFFFu - 100000u;
    sp::PublishCadence c(60000);
    c.begin(t0);
    c.set_publish_interval(1800000);  // 30 min via cmd/config
    int telemetry = 0, heartbeats = 0;
    uint32_t worst = max_heartbeat_gap(c, t0, 3600000, &telemetry, &heartbeats);
    TEST_ASSERT_EQUAL_INT(2, telemetry);
    TEST_ASSERT_EQUAL_INT(12, heartbeats);
    TEST_ASSERT_EQUAL_UINT32(300000, worst);
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
    RUN_TEST(test_heartbeat_interval_is_capped_at_five_minutes);
    RUN_TEST(test_hour_publish_interval_still_heartbeats_every_five_minutes);
    RUN_TEST(test_default_interval_heartbeats_with_telemetry);
    RUN_TEST(test_interval_change_takes_effect_and_is_wrap_safe);
    return UNITY_END();
}
