#pragma once
//
// log_forward — SP_LOG() mirrors to Serial AND a fixed ring (sp_core/
// log_ring.h); while MQTT is up, loop() publishes a batch to
// sporeprint/<id>/logs as {"entries":[{ts_ms,level,msg},...]} once one is
// due: eight lines queued, the oldest 5 s old, or a warning / error queued.
// A batch leaves the ring only once it was published. flush_now() sends
// what is queued before a deliberate restart.
//
// v2 publishes through MqttLink's STREAMED path, so the batch actually
// arrives parseable — v1 built batches budgeted for the 1024-byte client
// buffer and then pushed them through a 512-byte serialize buffer; every
// first post-boot flush reached the Pi as truncated garbage.
//
// Memory budget: 32 × 200 B ring ≈ 6.6 KB.

#include <Arduino.h>
#include <stdarg.h>

#include "log_ring.h"
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

constexpr size_t kEntryMsgLen = sp::LogRing::kMsgLen;
static_assert(LOG_WARN == sp::LogRing::kUrgentLevel,
              "a queued warning makes a batch due");

void attach(MqttLink* link);
void emit(uint8_t level, const char* fmt, ...)
    __attribute__((format(printf, 2, 3)));
void loop(uint32_t now_ms);
// Publish everything queued now (a few batches at most), ignoring the
// thresholds and the flush interval: call before a deliberate restart so the
// lines explaining it reach the Pi. No-op while MQTT is down.
void flush_now();
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
