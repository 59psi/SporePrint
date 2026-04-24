#pragma once

#include <Arduino.h>
#include <ArduinoOTA.h>
#include "config_store.h"

class MqttManager;  // forward decl — optional publishing of OTA events.

class OTAManager {
public:
    OTAManager(ConfigStore& config, const char* hostname);
    void begin();
    void loop();

    // v3.4.9 — wire an MQTT client so OTA lifecycle events publish to
    // sporeprint/<node>/ota. Unblocks "did the OTA actually apply?" remote
    // diagnosis. Call before begin(). Optional — nullptr = Serial-only.
    void setMqtt(MqttManager* mqtt) { _mqtt = mqtt; }

private:
    ConfigStore& _config;
    String _hostname;
    MqttManager* _mqtt = nullptr;
};
