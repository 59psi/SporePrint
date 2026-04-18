#include "ota_manager.h"

OTAManager::OTAManager(ConfigStore& config, const char* hostname)
    : _config(config), _hostname(hostname) {}

void OTAManager::begin() {
    String otaPass = _config.getString("ota_pass");

    // Refuse to enable OTA until the operator has set a real password.
    // The old default "sporeprint" let anyone on the LAN flash arbitrary
    // firmware via espota.py — a persistent backdoor on every node.
    if (otaPass.length() == 0 || otaPass == "sporeprint") {
        Serial.println("[OTA] DISABLED — ota_pass unset or default.");
        Serial.println("[OTA] Set a strong password via captive portal before OTA will work.");
        return;
    }

    ArduinoOTA.setHostname(_hostname.c_str());
    ArduinoOTA.setPassword(otaPass.c_str());

    ArduinoOTA.onStart([]() {
        String type = (ArduinoOTA.getCommand() == U_FLASH) ? "firmware" : "filesystem";
        Serial.printf("[OTA] Start updating %s\n", type.c_str());
    });

    ArduinoOTA.onEnd([]() {
        Serial.println("\n[OTA] Update complete!");
    });

    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("[OTA] Progress: %u%%\r", (progress / (total / 100)));
    });

    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("[OTA] Error[%u]: ", error);
        if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
        else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
        else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
        else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
        else if (error == OTA_END_ERROR) Serial.println("End Failed");
    });

    ArduinoOTA.begin();
    Serial.printf("[OTA] Ready. Hostname: %s\n", _hostname.c_str());
}

void OTAManager::loop() {
    ArduinoOTA.handle();
}
