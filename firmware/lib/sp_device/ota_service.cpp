#include "ota_service.h"

#include <esp_task_wdt.h>

#include <time.h>

namespace sp_device {

OtaService* OtaService::instance_ = nullptr;

void OtaService::publish_event(const char* event, const char* extra_key,
                               const char* extra_val) {
    if (!link_.connected()) return;
    JsonDocument doc;
    doc["event"] = event;
    doc["ts"] = (long)time(nullptr);
    if (extra_key != nullptr) doc[extra_key] = extra_val;
    link_.publish(link_.topic("ota").c_str(), doc);
}

bool OtaService::begin() {
    instance_ = this;

    if (pass_.length() == 0) {
        Serial.println("[OTA] DISABLED — no ota_pass provisioned (portal field).");
        return false;
    }
    // Brute-force over the MD5-challenge auth on LAN runs ~1k guesses/sec;
    // 12 mixed chars keeps the space >2^60.
    if (pass_.length() < 12) {
        Serial.printf("[OTA] DISABLED — ota_pass too short (%u chars, need >=12).\n",
                      (unsigned)pass_.length());
        return false;
    }

    ArduinoOTA.setHostname(hostname_.c_str());
    ArduinoOTA.setPassword(pass_.c_str());

    ArduinoOTA.onStart([]() {
        const char* type =
            (ArduinoOTA.getCommand() == U_FLASH) ? "firmware" : "filesystem";
        Serial.printf("[OTA] Start updating %s\n", type);
        if (instance_) instance_->publish_event("start", "type", type);
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("\n[OTA] Update complete.");
        if (instance_) instance_->publish_event("success");
    });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        // Flash writes legitimately exceed the loop WDT budget — this is
        // one of the two sanctioned pet sites outside loop().
        esp_task_wdt_reset();
        if (total >= 100) Serial.printf("[OTA] Progress: %u%%\r", progress / (total / 100));
    });
    ArduinoOTA.onError([](ota_error_t error) {
        const char* reason = "unknown";
        if (error == OTA_AUTH_ERROR) reason = "auth_failed";
        else if (error == OTA_BEGIN_ERROR) reason = "begin_failed";
        else if (error == OTA_CONNECT_ERROR) reason = "connect_failed";
        else if (error == OTA_RECEIVE_ERROR) reason = "receive_failed";
        else if (error == OTA_END_ERROR) reason = "end_failed";
        Serial.printf("[OTA] Error[%u]: %s\n", error, reason);
        if (instance_) instance_->publish_event("error", "reason", reason);
    });

    ArduinoOTA.begin();
    armed_ = true;
    Serial.printf("[OTA] Ready. Hostname: %s\n", hostname_.c_str());
    return true;
}

}  // namespace sp_device
