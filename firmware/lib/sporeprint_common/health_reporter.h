#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "mqtt_manager.h"

class HealthReporter {
public:
    HealthReporter(const char* nodeId, const char* nodeType, MqttManager& mqtt);
    void update();
    virtual void addComponentHealth(JsonObject& doc) = 0;

protected:
    const char* _nodeId;
    const char* _nodeType;
    MqttManager& _mqtt;
    unsigned long _lastReport = 0;
    static const unsigned long REPORT_INTERVAL_MS = 300000;

    uint32_t _uptimeSec();
    uint32_t _freeHeap();
    int8_t _wifiRssi();
};
