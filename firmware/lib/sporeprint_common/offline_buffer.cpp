#include "offline_buffer.h"

OfflineBuffer::OfflineBuffer(MqttManager& mqtt) : _mqtt(mqtt) {}

void OfflineBuffer::begin() {
    _count = 0;
    _head = 0;
    Serial.println("[BUFFER] Offline buffer ready (RAM-based, max 1000 entries)");
}

void OfflineBuffer::buffer(const String& topic, const String& payload) {
    _entries[_head].topic = topic;
    _entries[_head].payload = payload;
    _head = (_head + 1) % BUFFER_MAX_ENTRIES;
    if (_count < BUFFER_MAX_ENTRIES) _count++;

    Serial.printf("[BUFFER] Buffered message (%d stored)\n", _count);
}

void OfflineBuffer::flush() {
    if (_count == 0) return;

    Serial.printf("[BUFFER] Flushing %d buffered messages...\n", _count);

    int start = (_head - _count + BUFFER_MAX_ENTRIES) % BUFFER_MAX_ENTRIES;
    int flushed = 0;

    for (int i = 0; i < _count; i++) {
        int idx = (start + i) % BUFFER_MAX_ENTRIES;
        _mqtt.publish(_entries[idx].topic.c_str(), _entries[idx].payload.c_str());
        _entries[idx].topic = "";
        _entries[idx].payload = "";
        flushed++;
        yield();  // Let other tasks run without blocking for 10ms per message
    }

    _count = 0;
    _head = 0;
    Serial.printf("[BUFFER] Flushed %d messages\n", flushed);
}

int OfflineBuffer::getCount() {
    return _count;
}
