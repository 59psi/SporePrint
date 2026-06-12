#pragma once
//
// log_forward — SP_LOG() mirrors to Serial AND a fixed ring; when MQTT is
// up and the ring crosses the flush threshold, loop() drains a batch to
// sporeprint/<id>/logs as {"entries":[{ts_ms,level,msg},...]}.
//
// v2 publishes through MqttLink's STREAMED path, so the batch actually
// arrives parseable — v1 built batches budgeted for the 1024-byte client
// buffer and then pushed them through a 512-byte serialize buffer; every
// first post-boot flush reached the Pi as truncated garbage.
//
// Memory budget: 32 × 200 B ring ≈ 6.4 KB.

#include <Arduino.h>
#include <stdarg.h>

#include "mqtt_link.h"

#define LOG_DEBUG 0
#define LOG_INFO 1
#define LOG_WARN 2
#define LOG_ERROR 3

#ifndef SP_LOG_MIN_LEVEL
#define SP_LOG_MIN_LEVEL LOG_INFO
#endif

namespace sp_device {
namespace logfwd {

constexpr size_t kRingCapacity = 32;
constexpr size_t kEntryMsgLen = 200;
constexpr size_t kFlushThreshold = 8;
constexpr uint32_t kFlushIntervalMs = 2000;

struct LogEntry {
    uint32_t ts_ms;
    uint8_t level;
    char msg[kEntryMsgLen];
};

void attach(MqttLink* link);
void emit(uint8_t level, const char* fmt, ...)
    __attribute__((format(printf, 2, 3)));
void loop(uint32_t now_ms);
size_t queue_depth();
uint32_t dropped_count();

}  // namespace logfwd
}  // namespace sp_device

#define SP_LOG(level, fmt, ...)                                       \
    do {                                                              \
        if ((level) >= SP_LOG_MIN_LEVEL) {                            \
            ::sp_device::logfwd::emit((level), fmt, ##__VA_ARGS__);   \
        }                                                             \
    } while (0)
