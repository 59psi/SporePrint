#pragma once
#include "health_reporter.h"

class CamHealthReporter : public HealthReporter {
public:
    CamHealthReporter(const char* nodeId, MqttManager& mqtt)
        : HealthReporter(nodeId, "camera", mqtt) {}

    uint32_t captureSuccess = 0;
    uint32_t captureFail = 0;
    unsigned long lastCapture = 0;
    float avgLatencyMs = 0;
    bool flashOk = true;

    void addComponentHealth(JsonObject& doc) override {
        JsonObject cam = doc["camera"].to<JsonObject>();
        cam["capture_success"] = captureSuccess;
        cam["capture_fail"] = captureFail;
        cam["last_capture_ms"] = lastCapture;
        cam["avg_latency_ms"] = avgLatencyMs;
        cam["flash_ok"] = flashOk;
        cam["psram_free"] = ESP.getFreePsram();
    }
};
