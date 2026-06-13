#pragma once
//
// telemetry_buffer — byte-capped offline FIFO for telemetry published while
// the broker is unreachable.
//
// The v4.1.x buffer was capped by ENTRY COUNT (1000) — at ~250 bytes per
// buffered message that is ~250 KB of heap, more than an ESP32 has free, so
// a long broker outage OOM'd the node before the ring ever wrapped. This
// buffer accounts BYTES (topic + payload + small fixed overhead per entry)
// against a hard cap and evicts oldest-first, counting what it dropped.
//
// Flush is incremental and respects backpressure: it stops on the first
// publish failure (entries are only discarded after a successful publish)
// and drains at most `max_per_flush` entries per call so a fat backlog
// cannot stall the loop past the watchdog budget.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include <deque>
#include <string>

namespace sp {

class TelemetryBuffer {
public:
    // Per-entry bookkeeping overhead charged against the cap (deque node +
    // two string headers, approximated conservatively).
    static constexpr size_t kEntryOverhead = 32;

    explicit TelemetryBuffer(size_t cap_bytes = 16 * 1024)
        : cap_bytes_(cap_bytes) {}

    // Buffer a message. Evicts oldest entries until it fits. A message
    // larger than the whole cap is rejected outright (counted as dropped).
    void buffer(const char* topic, const char* payload);

    // Attempt to publish up to `max_per_flush` buffered entries through
    // `publish`. Stops early when publish returns false. Returns how many
    // entries were successfully published.
    template <typename PublishFn>
    size_t flush(PublishFn publish, size_t max_per_flush = 8) {
        size_t sent = 0;
        while (!entries_.empty() && sent < max_per_flush) {
            const Entry& e = entries_.front();
            if (!publish(e.topic.c_str(), e.payload.c_str())) break;
            used_bytes_ -= entry_cost(e);
            entries_.pop_front();
            ++sent;
        }
        return sent;
    }

    size_t count() const { return entries_.size(); }
    size_t used_bytes() const { return used_bytes_; }
    size_t cap_bytes() const { return cap_bytes_; }
    // Entries evicted (cap pressure) or rejected (oversize) since boot.
    uint32_t dropped() const { return dropped_; }

private:
    struct Entry {
        std::string topic;
        std::string payload;
    };

    static size_t entry_cost(const Entry& e) {
        return e.topic.size() + e.payload.size() + kEntryOverhead;
    }

    std::deque<Entry> entries_;
    size_t cap_bytes_;
    size_t used_bytes_ = 0;
    uint32_t dropped_ = 0;
};

}  // namespace sp
