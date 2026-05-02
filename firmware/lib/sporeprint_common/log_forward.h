#pragma once
//
// v4 archaeology fix #13 — MQTT log forwarding.
//
//   SP_LOG(LOG_INFO, "[BOOT] free heap=%u", ESP.getFreeHeap());
//
// Always mirrors to Serial AND enqueues into a fixed-size ring. When
// MQTT is connected and the queue crosses LOG_FLUSH_THRESHOLD, the next
// LogForward::loop() drains it to sporeprint/<node_id>/logs as
// { "entries": [ {ts_ms, level, msg}, ... ] }.
//
// Build flag -DSP_LOG_MIN_LEVEL=LOG_INFO drops DEBUG at preprocess time
// (zero RAM, zero cycles).
// Memory budget: 32 × 200 bytes = 6.4 KB ring + metadata.

#include <Arduino.h>
#include <stdarg.h>
#include <stdint.h>
#include "mqtt_manager.h"

// Ordered low-to-high so SP_LOG_MIN_LEVEL can numerically compare.
// Don't reorder without sweeping SP_LOG sites.
#define LOG_DEBUG  0
#define LOG_INFO   1
#define LOG_WARN   2
#define LOG_ERROR  3

#ifndef SP_LOG_MIN_LEVEL
#define SP_LOG_MIN_LEVEL LOG_INFO
#endif

#ifndef LOG_RING_CAPACITY
#define LOG_RING_CAPACITY 32
#endif
#ifndef LOG_ENTRY_MSG_LEN
#define LOG_ENTRY_MSG_LEN 200
#endif
#ifndef LOG_FLUSH_THRESHOLD
#define LOG_FLUSH_THRESHOLD 8
#endif

namespace sporeprint {
namespace logfwd {

struct LogEntry {
    uint32_t ts_ms;
    uint8_t level;
    char msg[LOG_ENTRY_MSG_LEN];
};

class LogForward {
public:
    static void attachMqtt(MqttManager* mqtt);

    static void emit(uint8_t level, const char* fmt, ...)
        __attribute__((format(printf, 2, 3)));

    static void loop();

    static size_t queueDepth();
    static size_t droppedCount();

private:
    static MqttManager* _mqtt;
    static LogEntry _ring[LOG_RING_CAPACITY];
    static size_t _head;
    static size_t _tail;
    static size_t _count;
    static size_t _dropped;
    static unsigned long _lastFlush;
};

}  // namespace logfwd
}  // namespace sporeprint

// Compile-time filter — args below SP_LOG_MIN_LEVEL evaporate before vsnprintf.
#define SP_LOG(level, fmt, ...)                                          \
    do {                                                                  \
        if ((level) >= SP_LOG_MIN_LEVEL) {                                \
            ::sporeprint::logfwd::LogForward::emit((level), fmt, ##__VA_ARGS__); \
        }                                                                 \
    } while (0)
