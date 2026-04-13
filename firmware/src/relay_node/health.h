#pragma once
#include "health_reporter.h"

struct ChannelHealth {
    bool state = false;
    uint8_t pwm = 0;
    uint32_t onTimeSec = 0;
    uint32_t cycleCount = 0;
    uint32_t safetyCutoffs = 0;
};

class RelayHealthReporter : public HealthReporter {
public:
    RelayHealthReporter(const char* nodeId, MqttManager& mqtt)
        : HealthReporter(nodeId, "relay", mqtt) {}

    static const int NUM_CHANNELS = 4;
    ChannelHealth channels[NUM_CHANNELS];

    void addComponentHealth(JsonObject& doc) override {
        JsonObject chans = doc["channels"].to<JsonObject>();
        for (int i = 0; i < NUM_CHANNELS; i++) {
            char key[8]; snprintf(key, sizeof(key), "ch%d", i);
            JsonObject ch = chans[key].to<JsonObject>();
            ch["state"] = channels[i].state;
            ch["pwm"] = channels[i].pwm;
            ch["on_time_sec"] = channels[i].onTimeSec;
            ch["cycle_count"] = channels[i].cycleCount;
            ch["safety_cutoffs"] = channels[i].safetyCutoffs;
        }
    }
};
