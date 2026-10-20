#include "log_forward.h"

#include <ArduinoJson.h>

namespace sp_device {
namespace logfwd {

namespace {
MqttLink* g_link = nullptr;
sp::LogRing g_ring;

bool publish_batch(JsonDocument& doc, void*) {
    return g_link->publish(g_link->topic("logs").c_str(), doc);
}
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
    g_ring.push(millis(), level, buf);  // oldest dropped (and counted) when full
}

void loop(uint32_t now_ms) {
    if (g_link == nullptr || !g_link->connected()) return;
    g_ring.flush(now_ms, /*force=*/false, publish_batch, nullptr);
}

void flush_now() {
    if (g_link == nullptr || !g_link->connected()) return;
    // The ring holds 32 entries and a batch several, so a few passes empty
    // it; stop at the first failed publish (its entries stay queued).
    for (int i = 0; i < 8 && g_ring.size() > 0; ++i) {
        if (!g_ring.flush(millis(), /*force=*/true, publish_batch, nullptr))
            break;
    }
}

size_t queue_depth() { return g_ring.size(); }
uint32_t dropped_count() { return g_ring.dropped(); }

}  // namespace logfwd
}  // namespace sp_device
