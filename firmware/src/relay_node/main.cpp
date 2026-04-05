#include <Arduino.h>
#include <ArduinoJson.h>
#include "sporeprint_common.h"

#define NODE_TYPE "relay"
#define DEFAULT_NODE_ID "relay-01"
#define NUM_CHANNELS 4
#define PWM_FREQ 25000
#define PWM_RESOLUTION 8  // 0-255
#define FACTORY_RESET_PIN 0
#define FACTORY_RESET_HOLD_MS 10000

// Channel GPIO pins
const int CHANNEL_PINS[NUM_CHANNELS] = {25, 26, 27, 14};
const char* CHANNEL_NAMES[NUM_CHANNELS] = {"fae", "exhaust", "circulation", "aux"};

ConfigStore config("relay");
WiFiManager wifi(config);
MqttManager* mqtt = nullptr;
OTAManager* ota = nullptr;
Heartbeat* heartbeat = nullptr;

// Channel state
struct ChannelState {
    bool on = false;
    uint8_t pwm = 0;
    unsigned long offAt = 0;     // millis() when auto-off triggers (0 = no timer)
    unsigned long maxOnMs = 1800000;  // 30 min default safety cutoff
    unsigned long onSince = 0;
};
ChannelState channels[NUM_CHANNELS];
unsigned long factoryResetStart = 0;
unsigned long lastReport = 0;

void setChannel(int ch, bool on, uint8_t pwm) {
    channels[ch].on = on;
    channels[ch].pwm = on ? pwm : 0;
    ledcWrite(ch, channels[ch].pwm);

    if (on && channels[ch].onSince == 0) {
        channels[ch].onSince = millis();
    }
    if (!on) {
        channels[ch].onSince = 0;
        channels[ch].offAt = 0;
    }
}

void reportChannel(int ch) {
    JsonDocument doc;
    doc["channel"] = CHANNEL_NAMES[ch];
    doc["state"] = channels[ch].on ? "on" : "off";
    doc["pwm"] = channels[ch].pwm;
    doc["trigger"] = "report";

    String topic = mqtt->buildTopic(("telemetry/" + String(CHANNEL_NAMES[ch])).c_str());
    mqtt->publish(topic.c_str(), doc);
}

void onChannelCommand(const char* topic, JsonDocument& doc) {
    String topicStr = String(topic);

    // Find which channel
    int ch = -1;
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (topicStr.endsWith(String("/") + CHANNEL_NAMES[i])) {
            ch = i;
            break;
        }
    }
    if (ch < 0) return;

    bool on = true;
    uint8_t pwm = 255;

    if (doc.containsKey("state")) {
        on = String(doc["state"].as<const char*>()) == "on";
    }
    if (doc.containsKey("pwm")) {
        pwm = doc["pwm"].as<uint8_t>();
        on = pwm > 0;
    }
    if (doc.containsKey("duration_sec") && doc["duration_sec"].as<int>() > 0) {
        channels[ch].offAt = millis() + (doc["duration_sec"].as<unsigned long>() * 1000);
    }

    Serial.printf("[RELAY] Ch%d (%s): %s PWM=%d\n", ch, CHANNEL_NAMES[ch], on ? "ON" : "OFF", pwm);
    setChannel(ch, on, pwm);
    reportChannel(ch);
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== SporePrint Relay Node ===");

    pinMode(FACTORY_RESET_PIN, INPUT_PULLUP);

    // Initialize all channels OFF
    for (int i = 0; i < NUM_CHANNELS; i++) {
        ledcAttach(CHANNEL_PINS[i], PWM_FREQ, PWM_RESOLUTION);
        ledcWrite(i, 0);
    }

    wifi.begin();

    String nodeId = config.getString("node_id");
    if (nodeId.length() == 0) nodeId = DEFAULT_NODE_ID;

    mqtt = new MqttManager(config, NODE_TYPE, nodeId.c_str());
    mqtt->begin();

    // Subscribe to per-channel commands
    for (int i = 0; i < NUM_CHANNELS; i++) {
        String cmdTopic = mqtt->buildTopic(("cmd/" + String(CHANNEL_NAMES[i])).c_str());
        mqtt->subscribe(cmdTopic.c_str(), onChannelCommand);
    }

    String hostname = "sporeprint-" + nodeId;
    ota = new OTAManager(config, hostname.c_str());
    ota->begin();

    heartbeat = new Heartbeat(*mqtt);

    Serial.println("[SETUP] Relay node ready!");
}

void loop() {
    mqtt->loop();
    ota->loop();
    heartbeat->loop();

    unsigned long now = millis();

    // Safety checks
    for (int i = 0; i < NUM_CHANNELS; i++) {
        // Timed off
        if (channels[i].offAt > 0 && now >= channels[i].offAt) {
            Serial.printf("[SAFETY] Ch%d auto-off (timer expired)\n", i);
            setChannel(i, false, 0);
            reportChannel(i);
        }
        // Max-on safety cutoff
        if (channels[i].on && channels[i].onSince > 0 &&
            (now - channels[i].onSince) > channels[i].maxOnMs) {
            Serial.printf("[SAFETY] Ch%d auto-off (max-on exceeded)\n", i);
            setChannel(i, false, 0);
            reportChannel(i);
        }
    }

    // Periodic state report
    if (now - lastReport > 60000) {
        lastReport = now;
        for (int i = 0; i < NUM_CHANNELS; i++) {
            reportChannel(i);
        }
    }

    // Factory reset
    if (digitalRead(FACTORY_RESET_PIN) == LOW) {
        if (factoryResetStart == 0) factoryResetStart = now;
        if (now - factoryResetStart > FACTORY_RESET_HOLD_MS) config.factoryReset();
    } else {
        factoryResetStart = 0;
    }
}
