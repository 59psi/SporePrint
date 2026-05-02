#include "log_forward.h"

#include <ArduinoJson.h>

namespace sporeprint {
namespace logfwd {

MqttManager* LogForward::_mqtt = nullptr;
LogEntry      LogForward::_ring[LOG_RING_CAPACITY];
size_t        LogForward::_head = 0;
size_t        LogForward::_tail = 0;
size_t        LogForward::_count = 0;
size_t        LogForward::_dropped = 0;
unsigned long LogForward::_lastFlush = 0;

void LogForward::attachMqtt(MqttManager* mqtt) {
    _mqtt = mqtt;
}

void LogForward::emit(uint8_t level, const char* fmt, ...) {
    char buf[LOG_ENTRY_MSG_LEN];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n < 0) {
        strncpy(buf, "(log format error)", sizeof(buf) - 1);
        buf[sizeof(buf) - 1] = '\0';
    }

    Serial.println(buf);

    LogEntry& slot = _ring[_head];
    slot.ts_ms = millis();
    slot.level = level;
    strncpy(slot.msg, buf, sizeof(slot.msg) - 1);
    slot.msg[sizeof(slot.msg) - 1] = '\0';

    _head = (_head + 1) % LOG_RING_CAPACITY;
    // Drop OLDEST on overrun — fresh logs are usually more diagnostic.
    if (_count == LOG_RING_CAPACITY) {
        _tail = (_tail + 1) % LOG_RING_CAPACITY;
        _dropped++;
    } else {
        _count++;
    }
}

void LogForward::loop() {
    if (!_mqtt || !_mqtt->isConnected()) return;
    if (_count < LOG_FLUSH_THRESHOLD) return;

    // Throttle to 1 flush / 2 s so a chatty boot doesn't saturate the broker.
    unsigned long now = millis();
    if (now - _lastFlush < 2000) return;
    _lastFlush = now;

    JsonDocument doc;
    JsonArray entries = doc["entries"].to<JsonArray>();
    if (_dropped > 0) {
        doc["dropped"] = _dropped;
    }

    // Stop adding entries before we blow the PubSubClient 1024-byte buffer.
    // Headroom of 124 bytes covers envelope + topic + JSON overhead.
    size_t remainingBudget = 900;
    size_t drained = 0;
    while (_count > 0) {
        LogEntry& e = _ring[_tail];
        size_t entryCost = strlen(e.msg) + 32;
        if (entryCost > remainingBudget) break;
        remainingBudget -= entryCost;

        JsonObject obj = entries.add<JsonObject>();
        obj["ts_ms"] = e.ts_ms;
        obj["level"] = e.level;
        obj["msg"] = e.msg;

        _tail = (_tail + 1) % LOG_RING_CAPACITY;
        _count--;
        drained++;
    }

    if (drained == 0) return;

    String topic = _mqtt->buildTopic("logs");
    _mqtt->publish(topic.c_str(), doc);

    // Only clear the counter after a successful publish.
    _dropped = 0;
}

size_t LogForward::queueDepth() { return _count; }
size_t LogForward::droppedCount() { return _dropped; }

}  // namespace logfwd
}  // namespace sporeprint
