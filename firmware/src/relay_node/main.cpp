#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include "sporeprint_common.h"
#include "health.h"

// 10-second task watchdog. Relay loop() must check in at least this often;
// if it gets stuck (WiFi reconnect pathology, MQTT library hang, etc.) the
// ESP32 reboots. Safe state on reset is "all channels OFF" — which setup()
// already enforces with ledcWrite(i, 0) on every boot.
static const uint32_t WDT_TIMEOUT_SEC = 10;

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
RelayHealthReporter* healthReporter = nullptr;

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
    bool wasOn = channels[ch].on;
    channels[ch].on = on;
    channels[ch].pwm = on ? pwm : 0;
    ledcWrite(ch, channels[ch].pwm);

    if (on && channels[ch].onSince == 0) {
        channels[ch].onSince = millis();
        if (healthReporter) {
            healthReporter->channels[ch].cycleCount++;
        }
    }
    if (!on) {
        if (wasOn && channels[ch].onSince > 0 && healthReporter) {
            healthReporter->channels[ch].onTimeSec +=
                (millis() - channels[ch].onSince) / 1000;
        }
        channels[ch].onSince = 0;
        channels[ch].offAt = 0;
    }
    if (healthReporter) {
        healthReporter->channels[ch].state = on;
        healthReporter->channels[ch].pwm = channels[ch].pwm;
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
    if (doc.containsKey("duration_sec")) {
        // Accept as signed to catch negative payloads, then clamp to
        // [1, 3600] s. Without this, a huge or negative value can wrap
        // millis() arithmetic and latch a relay ON indefinitely — the
        // worst failure mode for a heater or humidifier.
        int requested = doc["duration_sec"].as<int>();
        if (requested > 0) {
            const int MAX_DURATION_SEC = 3600;
            int clamped = requested;
            if (clamped > MAX_DURATION_SEC) {
                Serial.printf("[RELAY] duration_sec %d > %d, clamping\n",
                              requested, MAX_DURATION_SEC);
                clamped = MAX_DURATION_SEC;
            }
            channels[ch].offAt = millis() + ((unsigned long)clamped * 1000UL);
        } else if (requested < 0) {
            Serial.printf("[RELAY] ignoring negative duration_sec %d\n", requested);
        }
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

    // Initialize all channels OFF BEFORE anything that could block. If the
    // WDT trips during WiFi provisioning on a subsequent boot, coming up in
    // the all-off state is the documented "safe" recovery.
    for (int i = 0; i < NUM_CHANNELS; i++) {
        ledcAttach(CHANNEL_PINS[i], PWM_FREQ, PWM_RESOLUTION);
        ledcWrite(i, 0);
    }

    // Arm the task watchdog. Panic=true reboots on timeout (not just logs).
    // Subscribe the Arduino main task (the one that runs setup()/loop()).
    esp_task_wdt_init(WDT_TIMEOUT_SEC, true);
    esp_task_wdt_add(NULL);

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
    // Pet the watchdog at the top of every loop iteration. If any of the
    // subsequent calls deadlocks for >WDT_TIMEOUT_SEC, the ESP32 reboots
    // and setup() re-initializes all channels to OFF.
    esp_task_wdt_reset();

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
