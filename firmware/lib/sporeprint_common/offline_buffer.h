#pragma once

#include <Arduino.h>
#include "mqtt_manager.h"

#define BUFFER_MAX_ENTRIES 1000
#define BUFFER_FILE "/offline_buffer.json"

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
