#include "ota_manager.h"
#include "mqtt_manager.h"
#include <time.h>

// File-scope pointer so the stateless OTA callbacks can publish events.
// Only one OTAManager per node ever constructed; a static pointer is safe.
static MqttManager* _otaMqtt = nullptr;

static void _publishOta(const char* event, const char* extra_key = nullptr,
                        const char* extra_val = nullptr) {
    if (_otaMqtt == nullptr || !_otaMqtt->isConnected()) return;
    JsonDocument doc;
    doc["event"] = event;
    doc["ts"] = (long)time(nullptr);
    if (extra_key != nullptr) doc[extra_key] = extra_val;
    _otaMqtt->publish(_otaMqtt->buildTopic("ota").c_str(), doc);
}

OTAManager::OTAManager(ConfigStore& config, const char* hostname)
    : _config(config), _hostname(hostname) {}

void OTAManager::begin() {
    _otaMqtt = _mqtt;  // stash for the stateless callbacks

    String otaPass = _config.getString("ota_pass");

    // Refuse to enable OTA until the operator has set a real password.
    // The old default "sporeprint" let anyone on the LAN flash arbitrary
    // firmware via espota.py — a persistent backdoor on every node.
    if (otaPass.length() == 0 || otaPass == "sporeprint") {
        Serial.println("[OTA] DISABLED — ota_pass unset or default.");
        Serial.println("[OTA] Set a strong password via captive portal before OTA will work.");
        return;
    }

    // v3.4.9 L-6 — enforce a minimum password strength. Brute-force over
    // MD5-challenge auth on LAN is ~1k guesses/sec; 12 chars of mixed
    // entropy is the floor that keeps the search space >2^60.
    if (otaPass.length() < 12) {
        Serial.printf("[OTA] DISABLED — ota_pass too short (%u chars, need >=12).\n",
                      (unsigned)otaPass.length());
        return;
    }

    ArduinoOTA.setHostname(_hostname.c_str());
    ArduinoOTA.setPassword(otaPass.c_str());

    ArduinoOTA.onStart([]() {
        String type = (ArduinoOTA.getCommand() == U_FLASH) ? "firmware" : "filesystem";
        Serial.printf("[OTA] Start updating %s\n", type.c_str());
        _publishOta("start", "type", type.c_str());
    });

    ArduinoOTA.onEnd([]() {
        Serial.println("\n[OTA] Update complete!");
        _publishOta("success");
    });

    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("[OTA] Progress: %u%%\r", (progress / (total / 100)));
    });

    ArduinoOTA.onError([](ota_error_t error) {
        const char* reason = "unknown";
        if (error == OTA_AUTH_ERROR) reason = "auth_failed";
        else if (error == OTA_BEGIN_ERROR) reason = "begin_failed";
        else if (error == OTA_CONNECT_ERROR) reason = "connect_failed";
        else if (error == OTA_RECEIVE_ERROR) reason = "receive_failed";
        else if (error == OTA_END_ERROR) reason = "end_failed";
        Serial.printf("[OTA] Error[%u]: %s\n", error, reason);
        _publishOta("error", "reason", reason);
    });

    ArduinoOTA.begin();
    Serial.printf("[OTA] Ready. Hostname: %s\n", _hostname.c_str());
}

void OTAManager::loop() {
    ArduinoOTA.handle();
}
