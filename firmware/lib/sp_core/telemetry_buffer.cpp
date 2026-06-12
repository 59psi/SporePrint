#include "telemetry_buffer.h"

namespace sp {

void TelemetryBuffer::buffer(const char* topic, const char* payload) {
    Entry e;
    e.topic = topic;
    e.payload = payload;
    size_t cost = entry_cost(e);
    if (cost > cap_bytes_) {
        // Single message larger than the whole budget — refuse, count it.
        ++dropped_;
        return;
    }
    while (used_bytes_ + cost > cap_bytes_ && !entries_.empty()) {
        used_bytes_ -= entry_cost(entries_.front());
        entries_.pop_front();
        ++dropped_;
    }
    used_bytes_ += cost;
    entries_.push_back(static_cast<Entry&&>(e));
}

}  // namespace sp
