#pragma once
//
// log_ring — the forwarded-log queue behind SP_LOG and its flush policy,
// pure so both are host-tested (test_core_link). sp_device/log_forward.cpp
// owns the one instance, fills it from SP_LOG and publishes its batches to
// sporeprint/<id>/logs as {"entries":[{ts_ms,level,msg},...],"dropped"?}.
//
// When a batch goes out (at most one per kFlushIntervalMs):
//   * kFlushThreshold entries are queued, or
//   * the oldest queued entry is kMaxAgeMs old, or
//   * a LOG_WARN-or-worse entry is queued, or
//   * the caller forces it (a deliberate restart flushes first).
// A quiet node's few lines (often the ones saying why it reboots) used to
// wait in RAM until eight had queued, and died with the next restart.
//
// A batch leaves the ring only once it was published. A failed publish (the
// link dropped mid-stream) keeps its entries for the next try; only overflow
// drops entries (oldest first), and every drop is counted in `dropped`,
// which the next published batch reports.
//
// Native-safe: no Arduino headers (ArduinoJson is header-only).

#include <ArduinoJson.h>

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "wire_contract.h"  // build_log_entry
#include "wrap_time.h"

namespace sp {

class LogRing {
public:
    static constexpr size_t kCapacity = 32;  // 32 × ~208 B ≈ 6.6 KB
    static constexpr size_t kMsgLen = 200;
    static constexpr size_t kFlushThreshold = 8;
    static constexpr uint32_t kMaxAgeMs = 5000;
    static constexpr uint8_t kUrgentLevel = 2;  // LOG_WARN (log_forward.h)
    static constexpr uint32_t kFlushIntervalMs = 2000;
    // Bytes of entries per publish: a courtesy cap, not a corruption limit
    // (the publish is chunked).
    static constexpr size_t kBatchBudget = 900;

    // Publishes one batch document; true when it went out.
    using PublishFn = bool (*)(JsonDocument& doc, void* ctx);

    void push(uint32_t ts_ms, uint8_t level, const char* msg) {
        Entry& slot = ring_[head_];
        slot.ts_ms = ts_ms;
        slot.level = level;
        strncpy(slot.msg, msg != nullptr ? msg : "", kMsgLen - 1);
        slot.msg[kMsgLen - 1] = '\0';
        head_ = (head_ + 1) % kCapacity;
        if (count_ == kCapacity) {
            pop();  // the new entry overwrote the oldest
            ++count_;
            ++dropped_;
        } else {
            ++count_;
        }
    }

    // Publish one batch when one is due (or `force`). True when a batch was
    // published and its entries left the ring.
    bool flush(uint32_t now_ms, bool force, PublishFn publish, void* ctx) {
        if (count_ == 0 || publish == nullptr) return false;
        if (!force && !due(now_ms)) return false;
        last_flush_ms_ = now_ms;  // a failed attempt waits the interval too
        flushed_once_ = true;

        JsonDocument doc;
        JsonArray entries = doc["entries"].to<JsonArray>();
        const uint32_t dropped = dropped_;
        if (dropped > 0) doc["dropped"] = dropped;
        const uint32_t first = tail_seq_;
        size_t budget = kBatchBudget;
        size_t n = 0;
        for (; n < count_; ++n) {
            const Entry& e = ring_[(tail_ + n) % kCapacity];
            const size_t cost = strlen(e.msg) + 32;
            if (cost > budget) break;
            budget -= cost;
            build_log_entry(entries.add<JsonObject>(), e.ts_ms, e.level, e.msg);
        }
        if (n == 0) return false;
        if (!publish(doc, ctx)) return false;  // entries stay queued
        // Retire exactly the published entries (by sequence: an overflow
        // during the publish may already have pushed some of them out).
        while (count_ > 0 && (int32_t)(tail_seq_ - (first + (uint32_t)n)) < 0)
            pop();
        dropped_ -= dropped;  // reported; drops since then still count
        return true;
    }

    size_t size() const { return count_; }
    uint32_t dropped() const { return dropped_; }

private:
    struct Entry {
        uint32_t ts_ms;
        uint8_t level;
        char msg[kMsgLen];
    };

    bool due(uint32_t now_ms) const {
        if (flushed_once_ &&
            elapsed_since(now_ms, last_flush_ms_) < kFlushIntervalMs)
            return false;
        if (count_ >= kFlushThreshold) return true;
        if (elapsed_since(now_ms, ring_[tail_].ts_ms) >= kMaxAgeMs) return true;
        for (size_t i = 0; i < count_; ++i)
            if (ring_[(tail_ + i) % kCapacity].level >= kUrgentLevel)
                return true;
        return false;
    }

    void pop() {
        tail_ = (tail_ + 1) % kCapacity;
        ++tail_seq_;
        --count_;
    }

    Entry ring_[kCapacity] = {};
    size_t head_ = 0;
    size_t tail_ = 0;
    size_t count_ = 0;
    uint32_t tail_seq_ = 0;  // sequence number of the entry at tail_
    uint32_t dropped_ = 0;
    bool flushed_once_ = false;
    uint32_t last_flush_ms_ = 0;
};

}  // namespace sp
