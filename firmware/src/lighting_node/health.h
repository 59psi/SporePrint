#pragma once
#include "health_reporter.h"

struct LightChannelHealth {
    uint16_t pwm = 0;
    float onHours = 0;
    bool scheduleSynced = false;
};

class LightingHealthReporter : public HealthReporter {
public:
    LightingHealthReporter(const char* nodeId, MqttManager& mqtt)
        : HealthReporter(nodeId, "lighting", mqtt) {}

    static const int NUM_CHANNELS = 4;
    LightChannelHealth channels[NUM_CHANNELS];

    void addComponentHealth(JsonObject& doc) override {
        JsonObject chans = doc["channels"].to<JsonObject>();
        const char* names[] = {"white_6500k", "blue_450nm", "red_660nm", "far_red_730nm"};
        for (int i = 0; i < NUM_CHANNELS; i++) {
            JsonObject ch = chans[names[i]].to<JsonObject>();
            ch["pwm"] = channels[i].pwm;
            ch["on_hours"] = channels[i].onHours;
            ch["schedule_synced"] = channels[i].scheduleSynced;
        }
    }
};
