#include "log_forward.h"

#include <ArduinoJson.h>

#include "wrap_time.h"

namespace sp_device {
namespace logfwd {

namespace {
MqttLink* g_link = nullptr;
LogEntry g_ring[kRingCapacity];
size_t g_head = 0;
size_t g_tail = 0;
size_t g_count = 0;
uint32_t g_dropped = 0;
uint32_t g_last_flush_ms = 0;
}  // namespace

void attach(MqttLink* link) { g_link = link; }

void emit(uint8_t level, const char* fmt, ...) {
    char buf[kEntryMsgLen];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n < 0) {
        strncpy(buf, "(log format error)", sizeof(buf) - 1);
        buf[sizeof(buf) - 1] = '\0';
    }

    Serial.println(buf);

    LogEntry& slot = g_ring[g_head];
    slot.ts_ms = millis();
    slot.level = level;
    strncpy(slot.msg, buf, sizeof(slot.msg) - 1);
    slot.msg[sizeof(slot.msg) - 1] = '\0';

    g_head = (g_head + 1) % kRingCapacity;
    if (g_count == kRingCapacity) {
        g_tail = (g_tail + 1) % kRingCapacity;  // drop OLDEST
        ++g_dropped;
    } else {
        ++g_count;
    }
}

void loop(uint32_t now_ms) {
    if (g_link == nullptr || !g_link->connected()) return;
    if (g_count < kFlushThreshold) return;
    if (sp::elapsed_ms(now_ms, g_last_flush_ms) < kFlushIntervalMs) return;
    g_last_flush_ms = now_ms;

    JsonDocument doc;
    JsonArray entries = doc["entries"].to<JsonArray>();
    if (g_dropped > 0) doc["dropped"] = g_dropped;

    // Bound the batch so one publish stays comfortably under the broker's
    // patience; the streamed path means size is no longer a corruption
    // risk, just a courtesy cap.
    size_t budget = 900;
    size_t drained = 0;
    while (g_count > 0) {
        LogEntry& e = g_ring[g_tail];
        size_t cost = strlen(e.msg) + 32;
        if (cost > budget) break;
        budget -= cost;
        JsonObject obj = entries.add<JsonObject>();
        obj["ts_ms"] = e.ts_ms;
        obj["level"] = e.level;
        obj["msg"] = e.msg;
        g_tail = (g_tail + 1) % kRingCapacity;
        --g_count;
        ++drained;
    }
    if (drained == 0) return;

    if (g_link->publish(g_link->topic("logs").c_str(), doc)) {
        g_dropped = 0;  // counter reported; reset after a successful send
    }
}

size_t queue_depth() { return g_count; }
uint32_t dropped_count() { return g_dropped; }

}  // namespace logfwd
}  // namespace sp_device
