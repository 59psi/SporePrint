#include <Arduino.h>
#include <ArduinoJson.h>
#include "sporeprint_common.h"

#define NODE_TYPE "lighting"
#define DEFAULT_NODE_ID "light-01"
#define NUM_CHANNELS 4
#define PWM_FREQ 25000
#define PWM_RESOLUTION 10  // 0-1023 for smooth dimming
#define FACTORY_RESET_PIN 0
#define FACTORY_RESET_HOLD_MS 10000

const int CHANNEL_PINS[NUM_CHANNELS] = {25, 26, 27, 14};
const char* CHANNEL_NAMES[NUM_CHANNELS] = {"white", "blue", "red", "far_red"};

ConfigStore config("lighting");
WiFiManager wifi(config);
MqttManager* mqtt = nullptr;
OTAManager* ota = nullptr;
Heartbeat* heartbeat = nullptr;

uint16_t channelLevels[NUM_CHANNELS] = {0, 0, 0, 0};
unsigned long factoryResetStart = 0;
unsigned long lastReport = 0;

// ─── Scene Presets ──────────────────────────────────────────────
struct Scene {
    const char* name;
    uint16_t levels[NUM_CHANNELS];  // white, blue, red, far_red
};

const Scene SCENES[] = {
    {"colonization_dark",   {0,    0,   0,   0}},
    {"pinning_daylight",    {700,  200, 0,   0}},
    {"fruiting_standard",   {800,  150, 100, 50}},
    {"cordyceps_blue",      {0,    900, 0,   0}},
    {"lions_mane_gentle",   {400,  100, 0,   0}},
};
const int NUM_SCENES = sizeof(SCENES) / sizeof(Scene);

void setChannel(int ch, uint16_t level) {
    channelLevels[ch] = min(level, (uint16_t)1023);
    ledcWrite(ch, channelLevels[ch]);
}

void applyScene(const char* sceneName) {
    for (int s = 0; s < NUM_SCENES; s++) {
        if (strcmp(SCENES[s].name, sceneName) == 0) {
            Serial.printf("[LIGHT] Applying scene: %s\n", sceneName);
            for (int ch = 0; ch < NUM_CHANNELS; ch++) {
                setChannel(ch, SCENES[s].levels[ch]);
            }
            return;
        }
    }
    Serial.printf("[LIGHT] Unknown scene: %s\n", sceneName);
}

void reportLevels() {
    JsonDocument doc;
    for (int i = 0; i < NUM_CHANNELS; i++) {
        doc[CHANNEL_NAMES[i]] = channelLevels[i];
    }
    mqtt->publish(mqtt->buildTopic("telemetry").c_str(), doc);
}

void onSceneCommand(const char* topic, JsonDocument& doc) {
    if (doc.containsKey("scene")) {
        applyScene(doc["scene"].as<const char*>());
        reportLevels();
    }
}

void onChannelCommand(const char* topic, JsonDocument& doc) {
    String topicStr = String(topic);
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (topicStr.endsWith(String("/") + CHANNEL_NAMES[i])) {
            uint16_t level = doc.containsKey("level") ? doc["level"].as<uint16_t>() : 0;
            if (doc.containsKey("state") && String(doc["state"].as<const char*>()) == "off") {
                level = 0;
            }
            setChannel(i, level);
            Serial.printf("[LIGHT] %s = %d\n", CHANNEL_NAMES[i], level);
            reportLevels();
            return;
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== SporePrint Lighting Node ===");

    pinMode(FACTORY_RESET_PIN, INPUT_PULLUP);

    for (int i = 0; i < NUM_CHANNELS; i++) {
        ledcAttach(CHANNEL_PINS[i], PWM_FREQ, PWM_RESOLUTION);
        ledcWrite(i, 0);
    }

    wifi.begin();

    String nodeId = config.getString("node_id");
    if (nodeId.length() == 0) nodeId = DEFAULT_NODE_ID;

    mqtt = new MqttManager(config, NODE_TYPE, nodeId.c_str());
    mqtt->begin();

    mqtt->subscribe(mqtt->buildTopic("cmd/scene").c_str(), onSceneCommand);
    String cmdWild = mqtt->buildTopic("cmd/#");
    mqtt->subscribe(cmdWild.c_str(), onChannelCommand);

    String hostname = "sporeprint-" + nodeId;
    ota = new OTAManager(config, hostname.c_str());
    ota->begin();

    heartbeat = new Heartbeat(*mqtt);

    // Start dark
    applyScene("colonization_dark");

    Serial.println("[SETUP] Lighting node ready!");
}

void loop() {
    mqtt->loop();
    ota->loop();
    heartbeat->loop();

    unsigned long now = millis();

    if (now - lastReport > 60000) {
        lastReport = now;
        reportLevels();
    }

    if (digitalRead(FACTORY_RESET_PIN) == LOW) {
        if (factoryResetStart == 0) factoryResetStart = now;
        if (now - factoryResetStart > FACTORY_RESET_HOLD_MS) config.factoryReset();
    } else {
        factoryResetStart = 0;
    }
}
