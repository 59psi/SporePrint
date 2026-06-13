#pragma once
//
// ota_service — ArduinoOTA with the v1 password policy (no default, min 12
// chars) and MQTT lifecycle events. v2 provisions ota_pass via the captive
// portal, which v1 never could — its "set a strong password via captive
// portal" message referred to a field that didn't exist, so OTA was
// permanently disabled in practice.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>

#include "mqtt_link.h"

namespace sp_device {

class OtaService {
public:
    OtaService(MqttLink& link, const char* hostname, const char* ota_pass)
        : link_(link), hostname_(hostname), pass_(ota_pass) {}

    // Returns true when OTA is armed (password present + strong enough).
    bool begin();
    void loop() { if (armed_) ArduinoOTA.handle(); }
    bool armed() const { return armed_; }

private:
    void publish_event(const char* event, const char* extra_key = nullptr,
                       const char* extra_val = nullptr);

    MqttLink& link_;
    String hostname_;
    String pass_;
    bool armed_ = false;

    static OtaService* instance_;
};

}  // namespace sp_device
