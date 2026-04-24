#pragma once

#include <Arduino.h>
#include "mqtt_manager.h"

// v3.4.9: this buffer is in-RAM only. An earlier draft had a
// `BUFFER_FILE` constant suggesting LittleFS persistence, but no read or
// write code ever called it. Removed the constant rather than
// implementing LittleFS now, because the use-case doesn't justify the
// flash-wear trade-off: telemetry is 60-second-cadence and restarts are
// rare on a healthy node. If persistence becomes necessary, add it as an
// explicit feature with retention limits, not a half-wired constant.
#define BUFFER_MAX_ENTRIES 1000

class OfflineBuffer {
public:
    OfflineBuffer(MqttManager& mqtt);

    void begin();
    void buffer(const String& topic, const String& payload);
    void flush();
    int getCount();

private:
    MqttManager& _mqtt;
    int _count = 0;
    int _head = 0;  // next write position

    struct Entry {
        String topic;
        String payload;
    };
    Entry _entries[BUFFER_MAX_ENTRIES];
};
