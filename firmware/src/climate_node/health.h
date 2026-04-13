#pragma once
#include "health_reporter.h"

struct SensorHealth {
    bool ok = true;
    uint32_t reads = 0;
    uint32_t fails = 0;
    const char* lastError = nullptr;

    void recordRead(bool success, const char* error = nullptr) {
        reads++;
        if (!success) { fails++; lastError = error; ok = false; }
        else { ok = true; }
    }
};

class ClimateHealthReporter : public HealthReporter {
public:
    ClimateHealthReporter(const char* nodeId, MqttManager& mqtt)
        : HealthReporter(nodeId, "climate", mqtt) {}

    SensorHealth sht31;
    SensorHealth scd40;
    SensorHealth bh1750;

    void addComponentHealth(JsonObject& doc) override {
        JsonObject sensors = doc["sensors"].to<JsonObject>();
        auto addSensor = [](JsonObject& parent, const char* name, const SensorHealth& s) {
            JsonObject obj = parent[name].to<JsonObject>();
            obj["ok"] = s.ok; obj["reads"] = s.reads;
            obj["fails"] = s.fails; obj["last_error"] = s.lastError;
        };
        addSensor(sensors, "sht31", sht31);
        addSensor(sensors, "scd40", scd40);
        addSensor(sensors, "bh1750", bh1750);
    }
};
