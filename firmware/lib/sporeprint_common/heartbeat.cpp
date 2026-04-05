#include "heartbeat.h"
#include <WiFi.h>

Heartbeat::Heartbeat(MqttManager& mqtt, unsigned long intervalMs)
    : _mqtt(mqtt), _interval(intervalMs) {}

void Heartbeat::loop() {
    unsigned long now = millis();
    if (now - _lastBeat < _interval) return;
    _lastBeat = now;

    if (!_mqtt.isConnected()) return;

    JsonDocument doc;
    doc["uptime_sec"] = now / 1000;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["firmware_version"] = "0.1.0";
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["ip"] = WiFi.localIP().toString();

    String topic = _mqtt.buildTopic("status/heartbeat");
    _mqtt.publish(topic.c_str(), doc);
}
