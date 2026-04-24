#include "heartbeat.h"
#include <WiFi.h>
#include <esp_system.h>

// v3.4.9 — firmware_version comes from the SPOREPRINT_FW_VERSION build
// flag, kept in sync with the parent repo via firmware/VERSION.txt and
// scripts/bump.sh. Previously this was hardcoded "0.1.0" in every
// build, making OTA version drift invisible from the cloud.
#ifndef SPOREPRINT_FW_VERSION
#define SPOREPRINT_FW_VERSION "unset"
#endif

// Persistent-across-loop counters. `millis()` is not stable across a
// reboot; we report them alongside esp_reset_reason() so the operator
// can see "last reboot was because of WDT trip" vs "normal power-on".
static uint32_t _wifi_reconnect_count = 0;
static uint32_t _mqtt_reconnect_count = 0;
static bool _last_wifi_connected = false;
static bool _last_mqtt_connected = false;

void heartbeat_on_wifi_reconnect() { _wifi_reconnect_count++; }
void heartbeat_on_mqtt_reconnect() { _mqtt_reconnect_count++; }

Heartbeat::Heartbeat(MqttManager& mqtt, unsigned long intervalMs)
    : _mqtt(mqtt), _interval(intervalMs) {}

void Heartbeat::loop() {
    unsigned long now = millis();

    // Track reconnects cheaply — every call, compare to last-seen state.
    bool wifiNow = WiFi.status() == WL_CONNECTED;
    if (wifiNow && !_last_wifi_connected) _wifi_reconnect_count++;
    _last_wifi_connected = wifiNow;

    bool mqttNow = _mqtt.isConnected();
    if (mqttNow && !_last_mqtt_connected) _mqtt_reconnect_count++;
    _last_mqtt_connected = mqttNow;

    if (now - _lastBeat < _interval) return;
    _lastBeat = now;

    if (!mqttNow) return;

    JsonDocument doc;
    doc["uptime_sec"] = now / 1000;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["firmware_version"] = SPOREPRINT_FW_VERSION;
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["ip"] = WiFi.localIP().toString();
    // v3.4.9 — reset reason + reconnect counters. Helps discriminate
    // "node cycling every 10 min" (wdt_reset_count climbs) from
    // "node up 3 weeks" (all zero).
    doc["reset_reason"] = (int)esp_reset_reason();
    doc["wifi_reconnects"] = _wifi_reconnect_count;
    doc["mqtt_reconnects"] = _mqtt_reconnect_count;

    String topic = _mqtt.buildTopic("status/heartbeat");
    _mqtt.publish(topic.c_str(), doc);
}
