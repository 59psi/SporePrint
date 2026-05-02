#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include "sporeprint_common.h"
#include "health.h"

// v3.4.9 — task watchdog parity with relay_node. A hung scene transition or
// LEDC driver glitch freezes the main task; WDT recovers to safe-state
// (all channels OFF, same as setup()).
static const uint32_t WDT_TIMEOUT_SEC = 10;

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
LightingHealthReporter* healthReporter = nullptr;

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
    // v3.4.9 C-1 — HMAC verify before applying scene.
    if (!sporeprint::verifyOrWarn(doc, config, topic)) return;

    if (doc.containsKey("scene")) {
        applyScene(doc["scene"].as<const char*>());
        reportLevels();
    }
}

void onChannelCommand(const char* topic, JsonDocument& doc) {
    // v3.4.9 C-1 — HMAC verify before actuating a channel.
    if (!sporeprint::verifyOrWarn(doc, config, topic)) return;

    String topicStr = String(topic);
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (topicStr.endsWith(String("/") + CHANNEL_NAMES[i])) {
            uint16_t level = doc.containsKey("level") ? doc["level"].as<uint16_t>() : 0;
            if (doc.containsKey("state") && String(doc["state"].as<const char*>()) == "off") {
                level = 0;
            }
            setChannel(i, level);
            SP_LOG(LOG_INFO, "[LIGHT] %s = %d", CHANNEL_NAMES[i], level);
            reportLevels();
            return;
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== SporePrint Lighting Node ===");
    SP_LOG(LOG_INFO, "[BOOT] lighting node starting, reset_reason=%d",
           (int)esp_reset_reason());

    pinMode(FACTORY_RESET_PIN, INPUT_PULLUP);

    // Arduino-ESP32 core 2.x LEDC API (see relay_node/main.cpp for context).
    // GPIO assignments unchanged — only the configure+attach API calls.
    // Safe-state (all channels off) runs BEFORE esp_task_wdt_add so a WDT
    // reset during WiFi connect still boots into a dark chamber.
    for (int i = 0; i < NUM_CHANNELS; i++) {
        ledcSetup(i, PWM_FREQ, PWM_RESOLUTION);
        ledcAttachPin(CHANNEL_PINS[i], i);
        ledcWrite(i, 0);
    }

    esp_task_wdt_init(WDT_TIMEOUT_SEC, true);
    esp_task_wdt_add(NULL);

    // v3.4.9 C-1 — optional build-flag NVS provisioning.
    sporeprint::bootstrapHmacKeyFromBuildFlag(config);

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
    ota->setMqtt(mqtt);
    ota->begin();

    heartbeat = new Heartbeat(*mqtt);
    healthReporter = new LightingHealthReporter(nodeId.c_str(), *mqtt);

    // v4 archaeology fixes #12 + #13 — wire log forwarder, drain prior panic dump.
    sporeprint::logfwd::LogForward::attachMqtt(mqtt);
    sporeprint::coredump::uploadIfPresent(*mqtt);

    // Start dark
    applyScene("colonization_dark");

    SP_LOG(LOG_INFO, "[SETUP] lighting node ready (channels=%d)", NUM_CHANNELS);
}

void loop() {
    esp_task_wdt_reset();

    mqtt->loop();
    ota->loop();
    heartbeat->loop();
    sporeprint::logfwd::LogForward::loop();
    if (healthReporter) healthReporter->update();

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
