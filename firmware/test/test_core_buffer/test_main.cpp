// test_core_buffer — byte-capped offline FIFO: eviction order, byte
// accounting, oversize rejection, and flush backpressure.

#include <unity.h>

#include <string.h>

#include <string>
#include <vector>

#include "telemetry_buffer.h"

void setUp() {}
void tearDown() {}

void test_fifo_order_and_flush() {
    sp::TelemetryBuffer buf(4096);
    buf.buffer("t/a", "{\"n\":1}");
    buf.buffer("t/b", "{\"n\":2}");
    buf.buffer("t/c", "{\"n\":3}");
    TEST_ASSERT_EQUAL_INT(3, (int)buf.count());

    std::vector<std::string> seen;
    size_t sent = buf.flush([&](const char* topic, const char* payload) {
        seen.push_back(std::string(topic) + " " + payload);
        return true;
    });
    TEST_ASSERT_EQUAL_INT(3, (int)sent);
    TEST_ASSERT_EQUAL_INT(0, (int)buf.count());
    TEST_ASSERT_EQUAL_STRING("t/a {\"n\":1}", seen[0].c_str());
    TEST_ASSERT_EQUAL_STRING("t/c {\"n\":3}", seen[2].c_str());
    TEST_ASSERT_EQUAL_INT(0, (int)buf.used_bytes());
}

void test_byte_cap_evicts_oldest() {
    // Cap fits exactly two entries of this size.
    const char* payload = "0123456789012345678901234567890123456789";  // 40 B
    size_t per = 3 + 40 + sp::TelemetryBuffer::kEntryOverhead;          // 75 B
    sp::TelemetryBuffer buf(per * 2);
    buf.buffer("t/1", payload);
    buf.buffer("t/2", payload);
    TEST_ASSERT_EQUAL_INT(2, (int)buf.count());
    TEST_ASSERT_EQUAL_INT(0, (int)buf.dropped());

    buf.buffer("t/3", payload);  // evicts t/1
    TEST_ASSERT_EQUAL_INT(2, (int)buf.count());
    TEST_ASSERT_EQUAL_INT(1, (int)buf.dropped());
    TEST_ASSERT_TRUE(buf.used_bytes() <= buf.cap_bytes());

    std::vector<std::string> topics;
    buf.flush([&](const char* topic, const char*) {
        topics.push_back(topic);
        return true;
    });
    TEST_ASSERT_EQUAL_INT(2, (int)topics.size());
    TEST_ASSERT_EQUAL_STRING("t/2", topics[0].c_str());
    TEST_ASSERT_EQUAL_STRING("t/3", topics[1].c_str());
}

void test_oversize_message_rejected() {
    sp::TelemetryBuffer buf(64);
    std::string big(200, 'x');
    buf.buffer("t", big.c_str());
    TEST_ASSERT_EQUAL_INT(0, (int)buf.count());
    TEST_ASSERT_EQUAL_INT(1, (int)buf.dropped());
}

void test_flush_backpressure_preserves_rest() {
    sp::TelemetryBuffer buf(4096);
    buf.buffer("t/1", "a");
    buf.buffer("t/2", "b");
    buf.buffer("t/3", "c");

    int calls = 0;
    size_t sent = buf.flush([&](const char*, const char*) {
        ++calls;
        return calls == 1;  // first succeeds, second fails (broker hiccup)
    });
    TEST_ASSERT_EQUAL_INT(1, (int)sent);
    // The failed entry was NOT discarded — old firmware lost the remainder.
    TEST_ASSERT_EQUAL_INT(2, (int)buf.count());

    std::vector<std::string> topics;
    buf.flush([&](const char* topic, const char*) {
        topics.push_back(topic);
        return true;
    });
    TEST_ASSERT_EQUAL_STRING("t/2", topics[0].c_str());
    TEST_ASSERT_EQUAL_STRING("t/3", topics[1].c_str());
}

void test_flush_respects_max_per_call() {
    sp::TelemetryBuffer buf(8192);
    for (int i = 0; i < 20; ++i) buf.buffer("t", "p");
    size_t sent = buf.flush([](const char*, const char*) { return true; }, 8);
    TEST_ASSERT_EQUAL_INT(8, (int)sent);
    TEST_ASSERT_EQUAL_INT(12, (int)buf.count());
}

void test_default_cap_bounds_memory() {
    // The defect this class exists to prevent: 1000 telemetry entries at
    // ~250 B each must not be storable inside the default cap.
    sp::TelemetryBuffer buf;  // 16 KB default
    std::string payload(220, 'x');
    for (int i = 0; i < 1000; ++i) buf.buffer("sporeprint/node-01/telemetry",
                                              payload.c_str());
    TEST_ASSERT_TRUE(buf.used_bytes() <= buf.cap_bytes());
    TEST_ASSERT_TRUE(buf.count() < 70);  // 16 KB / ~280 B
    TEST_ASSERT_TRUE(buf.dropped() > 900);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_fifo_order_and_flush);
    RUN_TEST(test_byte_cap_evicts_oldest);
    RUN_TEST(test_oversize_message_rejected);
    RUN_TEST(test_flush_backpressure_preserves_rest);
    RUN_TEST(test_flush_respects_max_per_call);
    RUN_TEST(test_default_cap_bounds_memory);
    return UNITY_END();
}
