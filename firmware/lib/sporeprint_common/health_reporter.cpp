#include "health_reporter.h"
#include <WiFi.h>

HealthReporter::HealthReporter(const char* nodeId, const char* nodeType, MqttManager& mqtt)
    : _nodeId(nodeId), _nodeType(nodeType), _mqtt(mqtt) {}

uint32_t HealthReporter::_uptimeSec() { return millis() / 1000; }
uint32_t HealthReporter::_freeHeap() { return ESP.getFreeHeap(); }
int8_t HealthReporter::_wifiRssi() { return WiFi.RSSI(); }

void HealthReporter::update() {
    if (millis() - _lastReport < REPORT_INTERVAL_MS) return;
    _lastReport = millis();

    JsonDocument doc;
    doc["node_id"] = _nodeId;
    doc["type"] = _nodeType;
    doc["uptime_sec"] = _uptimeSec();
    doc["free_heap"] = _freeHeap();
    doc["wifi_rssi"] = _wifiRssi();

    JsonObject root = doc.as<JsonObject>();
    addComponentHealth(root);

    char topic[64];
    snprintf(topic, sizeof(topic), "sporeprint/%s/health", _nodeId);
    char buffer[512];
    serializeJson(doc, buffer, sizeof(buffer));
    _mqtt.publish(topic, buffer);
}
