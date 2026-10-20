// test_core_link — the MQTT/WiFi-loss failsafe policy.
//
// CLAUDE.md §5c: "10min MQTT watchdog → safe mode". The node had no
// disconnected-duration tracking at all: a dead Pi/broker left the lighting
// bank lit indefinitely and relays running to their max-on, and a WiFi drop
// the Arduino core refuses to auto-retry (AUTH_FAIL et al.) left the node
// dark until power-cycled. LinkWatchdog is the pure policy; the composition
// root turns its actions into channel force_off()s and WiFi.begin().
//
// Also: the heartbeat cadence — PublishCadence keeps the status
// heartbeat inside the Pi's offline threshold whatever the telemetry interval.

#include <unity.h>

#include <ArduinoJson.h>

#include <stdint.h>
#include <stdio.h>

#include <string>

#include "chunked_writer.h"
#include "clamps.h"
#include "link_watchdog.h"
#include "log_ring.h"
#include "publish_cadence.h"
#include "wire_contract.h"

void setUp() {}
void tearDown() {}

// The spec's values as literals, not the policy's constants: every test
// below fails if safe mode stops coming at 10 min or the WiFi re-begin at
// 60 s.
static const uint32_t kSafe = 10UL * 60UL * 1000UL;
static const uint32_t kRetry = 60UL * 1000UL;

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

// ── heartbeat cadence ──────────────────────────────────────────
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

// ── forwarded logs (log_ring.h) ────────────────────────────────
// A quiet node's few lines used to sit in RAM until eight had queued (often
// never before the next restart), and a batch whose publish failed was
// thrown away without being counted as dropped.

struct BatchLog {
    bool ok = true;
    int calls = 0;
    std::string last;  // the last batch offered, serialized
    sp::LogRing* push_during = nullptr;  // emit() racing the publish
    int push_count = 0;
};

static bool capture_publish(JsonDocument& doc, void* ctx) {
    BatchLog* b = static_cast<BatchLog*>(ctx);
    ++b->calls;
    b->last.clear();
    serializeJson(doc, b->last);
    for (int i = 0; b->push_during != nullptr && i < b->push_count; ++i)
        b->push_during->push(100000, 1, "late");
    return b->ok;
}

static void push_n(sp::LogRing& r, int n, uint32_t ts, uint8_t level,
                   const char* tag) {
    char msg[32];
    for (int i = 0; i < n; ++i) {
        snprintf(msg, sizeof(msg), "%s %d", tag, i);
        r.push(ts, level, msg);
    }
}

void test_log_ring_sends_a_quiet_nodes_lines_within_seconds() {
    sp::LogRing r;
    BatchLog b;
    push_n(r, 2, 1000, 1, "info");  // e.g. "[CMD] peripherals saved"
    TEST_ASSERT_FALSE(r.flush(1000, false, capture_publish, &b));
    TEST_ASSERT_FALSE(r.flush(1000 + sp::LogRing::kMaxAgeMs - 1, false,
                              capture_publish, &b));
    TEST_ASSERT_EQUAL_INT(0, b.calls);
    TEST_ASSERT_TRUE(r.flush(1000 + sp::LogRing::kMaxAgeMs, false,
                             capture_publish, &b));
    TEST_ASSERT_EQUAL_size_t(0, r.size());
    JsonDocument doc;
    deserializeJson(doc, b.last);
    TEST_ASSERT_EQUAL_INT(2, (int)doc["entries"].size());
    TEST_ASSERT_EQUAL_STRING("info 0", doc["entries"][0]["msg"]);
    TEST_ASSERT_TRUE(doc["dropped"].isNull());

    // A warning or an error goes out on the next allowed pass, not after 5 s.
    push_n(r, 1, 20000, 1, "info");
    push_n(r, 1, 20001, 2, "warn");
    TEST_ASSERT_TRUE(r.flush(20002, false, capture_publish, &b));
    // Eight queued lines are due at once too.
    push_n(r, 8, 30000, 1, "burst");
    TEST_ASSERT_TRUE(r.flush(30000, false, capture_publish, &b));
}

void test_log_ring_keeps_a_batch_whose_publish_failed() {
    sp::LogRing r;
    BatchLog b;
    push_n(r, 9, 0, 1, "line");
    b.ok = false;  // the link dropped mid-publish
    TEST_ASSERT_FALSE(r.flush(10, false, capture_publish, &b));
    TEST_ASSERT_EQUAL_size_t(9, r.size());  // nothing lost...
    TEST_ASSERT_EQUAL_UINT32(0, r.dropped());  // ...and nothing to report
    // The interval still paces retries.
    b.ok = true;
    TEST_ASSERT_FALSE(r.flush(10 + sp::LogRing::kFlushIntervalMs - 1, false,
                              capture_publish, &b));
    TEST_ASSERT_TRUE(r.flush(10 + sp::LogRing::kFlushIntervalMs, false,
                             capture_publish, &b));
    JsonDocument doc;
    deserializeJson(doc, b.last);
    TEST_ASSERT_EQUAL_STRING("line 0", doc["entries"][0]["msg"]);  // in order
    const size_t sent = doc["entries"].size();
    TEST_ASSERT_TRUE(sent > 0);
    TEST_ASSERT_EQUAL_size_t(9 - sent, r.size());
}

void test_log_ring_reports_overflow_once() {
    sp::LogRing r;
    BatchLog b;
    push_n(r, (int)sp::LogRing::kCapacity + 8, 0, 1, "x");
    TEST_ASSERT_EQUAL_size_t(sp::LogRing::kCapacity, r.size());
    TEST_ASSERT_EQUAL_UINT32(8, r.dropped());
    TEST_ASSERT_TRUE(r.flush(0, false, capture_publish, &b));
    JsonDocument doc;
    deserializeJson(doc, b.last);
    TEST_ASSERT_EQUAL_INT(8, doc["dropped"].as<int>());
    TEST_ASSERT_EQUAL_STRING("x 8", doc["entries"][0]["msg"]);  // oldest kept
    TEST_ASSERT_EQUAL_UINT32(0, r.dropped());
    TEST_ASSERT_TRUE(r.flush(5000, true, capture_publish, &b));
    deserializeJson(doc, b.last);
    TEST_ASSERT_TRUE(doc["dropped"].isNull());
}

void test_log_ring_force_ignores_thresholds_and_interval() {
    sp::LogRing r;
    BatchLog b;
    push_n(r, 1, 0, 1, "restarting");
    TEST_ASSERT_TRUE(r.flush(1, true, capture_publish, &b));
    push_n(r, 1, 2, 1, "second");
    TEST_ASSERT_TRUE(r.flush(3, true, capture_publish, &b));  // 2 ms later
    TEST_ASSERT_EQUAL_size_t(0, r.size());
    TEST_ASSERT_FALSE(r.flush(4, true, capture_publish, &b));  // empty
    TEST_ASSERT_EQUAL_INT(2, b.calls);
}

void test_log_ring_retires_exactly_the_published_entries() {
    // Lines logged while a batch is being published (even enough to wrap
    // the ring) are never retired with it.
    sp::LogRing r;
    BatchLog b;
    push_n(r, 4, 0, 1, "early");
    b.push_during = &r;
    b.push_count = 3;
    TEST_ASSERT_TRUE(r.flush(0, true, capture_publish, &b));
    TEST_ASSERT_EQUAL_size_t(3, r.size());
    b.push_count = (int)sp::LogRing::kCapacity;  // overflow mid-publish
    push_n(r, 2, 0, 1, "more");
    TEST_ASSERT_TRUE(r.flush(0, true, capture_publish, &b));
    TEST_ASSERT_TRUE(r.size() <= sp::LogRing::kCapacity);
    TEST_ASSERT_TRUE(r.size() > 0);
    b.push_during = nullptr;
    JsonDocument doc;
    TEST_ASSERT_TRUE(r.flush(0, true, capture_publish, &b));
    deserializeJson(doc, b.last);
    TEST_ASSERT_EQUAL_STRING("late", doc["entries"][0]["msg"]);
}

// ── chunked publish (chunked_writer.h) ─────────────────────────
// ArduinoJson writes strings a character at a time; straight into
// PubSubClient each character was one transport write — one TLS record per
// byte on Secure MQTT, and up to 10 s per byte on a stalled plaintext socket.

struct CountingSink {
    size_t writes = 0;
    size_t accept_total = 0;  // bytes accepted so far
    size_t accept_limit = (size_t)-1;
    std::string data;
    size_t write(const uint8_t* d, size_t n) {
        ++writes;
        size_t k = n;
        if (accept_total + k > accept_limit)
            k = accept_limit > accept_total ? accept_limit - accept_total : 0;
        data.append(reinterpret_cast<const char*>(d), k);
        accept_total += k;
        return k;
    }
};

static void build_log_batch(JsonDocument& doc) {
    JsonArray entries = doc["entries"].to<JsonArray>();
    for (int i = 0; i < 7; ++i) {
        char msg[96];
        snprintf(msg, sizeof(msg),
                 "[SENSOR] read pass %d took 61 ms (budget 50) - check the bus", i);
        sp::build_log_entry(entries.add<JsonObject>(), 1000u * (uint32_t)i, 2, msg);
    }
    doc["dropped"] = 3;
}

void test_chunked_writer_sends_whole_chunks() {
    JsonDocument doc;
    build_log_batch(doc);
    const size_t len = measureJson(doc);
    TEST_ASSERT_TRUE(len > 512);
    CountingSink sink;
    sp::ChunkedWriter<CountingSink> w(sink);
    serializeJson(doc, w);
    TEST_ASSERT_TRUE(w.flush());
    TEST_ASSERT_FALSE(w.failed());
    TEST_ASSERT_EQUAL_size_t(len, w.written());
    TEST_ASSERT_EQUAL_size_t((len + 255) / 256, sink.writes);  // not ~len
    std::string direct;
    serializeJson(doc, direct);
    TEST_ASSERT_EQUAL_STRING(direct.c_str(), sink.data.c_str());
}

void test_chunked_writer_stops_at_the_first_short_write() {
    JsonDocument doc;
    build_log_batch(doc);
    const size_t len = measureJson(doc);
    CountingSink sink;
    sink.accept_limit = 300;  // the second chunk is cut short
    sp::ChunkedWriter<CountingSink> w(sink);
    serializeJson(doc, w);
    TEST_ASSERT_FALSE(w.flush());
    TEST_ASSERT_TRUE(w.failed());
    TEST_ASSERT_EQUAL_size_t(2, sink.writes);  // nothing after the short one
    TEST_ASSERT_EQUAL_size_t(300, w.written());
    TEST_ASSERT_TRUE(w.written() < len);
}

int main(int, char**) {
    UNITY_BEGIN();
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
    RUN_TEST(test_log_ring_sends_a_quiet_nodes_lines_within_seconds);
    RUN_TEST(test_log_ring_keeps_a_batch_whose_publish_failed);
    RUN_TEST(test_log_ring_reports_overflow_once);
    RUN_TEST(test_log_ring_force_ignores_thresholds_and_interval);
    RUN_TEST(test_log_ring_retires_exactly_the_published_entries);
    RUN_TEST(test_chunked_writer_sends_whole_chunks);
    RUN_TEST(test_chunked_writer_stops_at_the_first_short_write);
    return UNITY_END();
}
