#include <Arduino.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include "sporeprint_common.h"
#include "health.h"

// v3.4.9 — task watchdog parity with relay_node. Climate's I2C reads can
// block the main task on a sensor hang; WDT recovers the board to a known
// boot state. 30s is generous — SHT31 + SCD40 + BH1750 full cycle is <1s.
static const uint32_t WDT_TIMEOUT_SEC = 30;

// Sensor libraries
#include <ClosedCube_SHT31D.h>
#include <SparkFun_SCD4x_Arduino_Library.h>
#include <BH1750.h>

// ─── Configuration ──────────────────────────────────────────────
#define NODE_TYPE "climate"
#define DEFAULT_NODE_ID "climate-01"
#define DEFAULT_READ_INTERVAL_MS 30000
#define DEFAULT_PUBLISH_INTERVAL_MS 60000
#define FACTORY_RESET_PIN 0
#define FACTORY_RESET_HOLD_MS 10000

// ─── Globals ────────────────────────────────────────────────────
ConfigStore config("climate");
WiFiManager wifi(config);
MqttManager* mqtt = nullptr;
OTAManager* ota = nullptr;
Heartbeat* heartbeat = nullptr;
OfflineBuffer* offlineBuffer = nullptr;
ClimateHealthReporter* healthReporter = nullptr;

ClosedCube_SHT31D sht31;
SCD4x scd40;
BH1750 lightMeter;

unsigned long lastRead = 0;
unsigned long lastPublish = 0;
unsigned long readInterval = DEFAULT_READ_INTERVAL_MS;
unsigned long publishInterval = DEFAULT_PUBLISH_INTERVAL_MS;
unsigned long factoryResetStart = 0;

// Latest readings
float tempC = 0, tempF = 0, humidity = 0, dewPointF = 0;
uint16_t co2Ppm = 0;
float lux = 0;
bool sht31Ok = false, scd40Ok = false, bh1750Ok = false;

// ─── Dew Point (Magnus formula) ─────────────────────────────────
float calcDewPointC(float tempC, float rh) {
    float a = 17.27;
    float b = 237.7;
    float alpha = (a * tempC) / (b + tempC) + log(rh / 100.0);
    return (b * alpha) / (a - alpha);
}

float cToF(float c) { return c * 9.0 / 5.0 + 32.0; }

// ─── MQTT Command Handler ───────────────────────────────────────
// Interval clamps protect against pathological MQTT payloads. Without them:
//   - read_interval_ms = 0 busy-loops readSensors() and starves the MQTT /
//     OTA tasks (WDT trip a few seconds later).
//   - A gigantic value silently stalls sensor reads for days.
// Clamp + log on out-of-range input rather than silently apply.
static const unsigned long MIN_READ_INTERVAL_MS = 1000UL;       // 1 s
static const unsigned long MAX_READ_INTERVAL_MS = 600000UL;     // 10 min
static const unsigned long MIN_PUBLISH_INTERVAL_MS = 5000UL;    // 5 s
static const unsigned long MAX_PUBLISH_INTERVAL_MS = 3600000UL; // 1 h

static unsigned long clampULong(unsigned long v, unsigned long lo, unsigned long hi, const char* label) {
    if (v < lo) {
        Serial.printf("[CMD] %s=%lu below min %lu — clamping\n", label, v, lo);
        return lo;
    }
    if (v > hi) {
        Serial.printf("[CMD] %s=%lu above max %lu — clamping\n", label, v, hi);
        return hi;
    }
    return v;
}

void onCommand(const char* topic, JsonDocument& doc) {
    // v3.4.9 C-1 — HMAC verify before applying config changes.
    if (!sporeprint::verifyOrWarn(doc, config, topic)) {
        return;
    }

    if (doc.containsKey("read_interval_ms")) {
        unsigned long requested = doc["read_interval_ms"].as<unsigned long>();
        readInterval = clampULong(requested,
                                  MIN_READ_INTERVAL_MS, MAX_READ_INTERVAL_MS,
                                  "read_interval_ms");
        Serial.printf("[CMD] Read interval set to %lu ms\n", readInterval);
    }
    if (doc.containsKey("publish_interval_ms")) {
        unsigned long requested = doc["publish_interval_ms"].as<unsigned long>();
        publishInterval = clampULong(requested,
                                     MIN_PUBLISH_INTERVAL_MS, MAX_PUBLISH_INTERVAL_MS,
                                     "publish_interval_ms");
        Serial.printf("[CMD] Publish interval set to %lu ms\n", publishInterval);
    }
    if (doc.containsKey("calibrate_co2") && doc["calibrate_co2"].as<bool>()) {
        Serial.println("[CMD] Forcing CO2 recalibration...");
        scd40.setAutomaticSelfCalibrationEnabled(true);
    }
}

// ─── Sensor Reading ─────────────────────────────────────────────
void readSensors() {
    // SHT31 — Temperature & Humidity
    SHT31D result = sht31.readTempAndHumidity(SHT3XD_REPEATABILITY_HIGH,
                                                SHT3XD_MODE_POLLING, 50);
    if (result.error == SHT3XD_NO_ERROR) {
        tempC = result.t;
        tempF = cToF(tempC);
        humidity = result.rh;
        dewPointF = cToF(calcDewPointC(tempC, humidity));
        sht31Ok = true;
        if (healthReporter) healthReporter->sht31.recordRead(true);
    } else {
        sht31Ok = false;
        SP_LOG(LOG_WARN, "[SENSOR] SHT31 read error (err=%d)", (int)result.error);
        if (healthReporter) healthReporter->sht31.recordRead(false, "read error");
    }

    // SCD40 — CO2
    if (scd40.readMeasurement()) {
        co2Ppm = scd40.getCO2();
        // Use SCD40 temp/humidity as fallback if SHT31 failed
        if (!sht31Ok) {
            tempC = scd40.getTemperature();
            tempF = cToF(tempC);
            humidity = scd40.getHumidity();
            dewPointF = cToF(calcDewPointC(tempC, humidity));
        }
        scd40Ok = true;
        if (healthReporter) healthReporter->scd40.recordRead(true);
    } else {
        scd40Ok = false;
        if (healthReporter) healthReporter->scd40.recordRead(false, "no measurement");
    }

    // BH1750 — Light
    float luxReading = lightMeter.readLightLevel();
    if (luxReading >= 0) {
        lux = luxReading;
        bh1750Ok = true;
        if (healthReporter) healthReporter->bh1750.recordRead(true);
    } else {
        bh1750Ok = false;
        if (healthReporter) healthReporter->bh1750.recordRead(false, "read error");
    }
}

// ─── Alert Check ────────────────────────────────────────────────
// v3.4.9: emit each tripped condition as a separate alert instead of
// overwriting a single JsonDocument. Previously multiple simultaneous
// conditions (temp + humidity both out of range) collapsed to the last
// one, hiding the "door left open" signature from the grower. The Pi's
// notification service already dedups by type+value, so per-event
// publishes don't multiply operator noise.
void checkAlerts() {
    if (!mqtt->isConnected()) return;

    auto emit = [](const char* type, float value, const char* message,
                   const char* sensor = nullptr) {
        JsonDocument alert;
        alert["type"] = type;
        alert["value"] = value;
        alert["message"] = message;
        if (sensor != nullptr) alert["sensor"] = sensor;
        mqtt->publish(mqtt->buildTopic("alert").c_str(), alert);
    };

    if (sht31Ok && (tempF > 90.0 || tempF < 40.0)) {
        emit("temperature", tempF,
             tempF > 90.0 ? "Temperature critically high!" : "Temperature critically low!");
    }
    if (sht31Ok && (humidity > 99.0 || humidity < 30.0)) {
        emit("humidity", humidity,
             humidity > 99.0 ? "Humidity saturated!" : "Humidity critically low!");
    }
    if (scd40Ok && co2Ppm > 4000) {
        emit("co2", (float)co2Ppm, "CO2 dangerously high!");
    }
    if (!sht31Ok) {
        emit("sensor_failure", 0.0f, "SHT31 sensor read failed", "SHT31");
    }
}

// ─── Publish Telemetry ──────────────────────────────────────────
void publishTelemetry() {
    JsonDocument doc;
    doc["ts"] = millis() / 1000;  // Uptime-based, server adds real timestamp
    doc["temp_f"] = round(tempF * 10.0) / 10.0;
    doc["temp_c"] = round(tempC * 10.0) / 10.0;
    doc["humidity"] = round(humidity * 10.0) / 10.0;
    doc["co2_ppm"] = co2Ppm;
    doc["lux"] = round(lux * 10.0) / 10.0;
    doc["dew_point_f"] = round(dewPointF * 10.0) / 10.0;

    String topic = mqtt->buildTopic("telemetry");

    if (mqtt->isConnected()) {
        mqtt->publish(topic.c_str(), doc);
        // Flush any buffered messages
        if (offlineBuffer->getCount() > 0) {
            offlineBuffer->flush();
        }
    } else {
        char buffer[256];
        serializeJson(doc, buffer);
        offlineBuffer->buffer(topic, buffer);
    }
}

// ─── Setup ──────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== SporePrint Climate Node ===");
    SP_LOG(LOG_INFO, "[BOOT] climate node starting, reset_reason=%d",
           (int)esp_reset_reason());

    // Factory reset button
    pinMode(FACTORY_RESET_PIN, INPUT_PULLUP);

    // Arm the task watchdog before any potentially-blocking init (Wire.begin,
    // sensor begin, WiFi connect). Panic=true triggers reboot on timeout.
    esp_task_wdt_init(WDT_TIMEOUT_SEC, true);
    esp_task_wdt_add(NULL);

    // v3.4.9 C-1 — optional build-flag NVS provisioning.
    sporeprint::bootstrapHmacKeyFromBuildFlag(config);

    // WiFi
    wifi.begin();

    // Node ID
    String nodeId = config.getString("node_id");
    if (nodeId.length() == 0) nodeId = DEFAULT_NODE_ID;

    // MQTT
    mqtt = new MqttManager(config, NODE_TYPE, nodeId.c_str());
    mqtt->begin();
    mqtt->subscribe(mqtt->buildTopic("cmd/config").c_str(), onCommand);

    // v4 archaeology fixes #12 + #13 — wire log forwarder, drain prior panic dump.
    sporeprint::logfwd::LogForward::attachMqtt(mqtt);
    sporeprint::coredump::uploadIfPresent(*mqtt);

    // OTA
    String hostname = "sporeprint-" + nodeId;
    ota = new OTAManager(config, hostname.c_str());
    ota->setMqtt(mqtt);
    ota->begin();

    // Heartbeat
    heartbeat = new Heartbeat(*mqtt);

    // Offline buffer
    offlineBuffer = new OfflineBuffer(*mqtt);
    offlineBuffer->begin();

    // Health reporter
    healthReporter = new ClimateHealthReporter(nodeId.c_str(), *mqtt);

    // I2C Sensors
    Wire.begin();

    // SHT31 — ClosedCube SHT31D 1.5.x returns the serial number directly as
    // uint32_t rather than a struct. Zero is treated as "not responding" per
    // the library's convention for failed reads.
    sht31.begin(0x44);
    uint32_t sht31Serial = sht31.readSerialNumber();
    if (sht31Serial != 0) {
        Serial.printf("[SENSOR] SHT31 found (SN: %u)\n", sht31Serial);
        sht31Ok = true;
    } else {
        Serial.println("[SENSOR] SHT31 not found!");
    }

    // SCD40
    if (scd40.begin()) {
        Serial.println("[SENSOR] SCD40 found");
        scd40.startPeriodicMeasurement();
        scd40Ok = true;
    } else {
        Serial.println("[SENSOR] SCD40 not found!");
    }

    // BH1750
    if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
        Serial.println("[SENSOR] BH1750 found");
        bh1750Ok = true;
    } else {
        Serial.println("[SENSOR] BH1750 not found!");
    }

    SP_LOG(LOG_INFO, "[SETUP] climate node ready (sht31=%d scd40=%d bh1750=%d)",
           sht31Ok, scd40Ok, bh1750Ok);
}

// ─── Loop ───────────────────────────────────────────────────────
void loop() {
    // Pet the task watchdog at the top of every iteration. If any of the
    // below deadlocks for >WDT_TIMEOUT_SEC, the ESP32 reboots and setup()
    // re-initializes the sensors in a known state.
    esp_task_wdt_reset();

    mqtt->loop();
    ota->loop();
    heartbeat->loop();
    sporeprint::logfwd::LogForward::loop();
    if (healthReporter) healthReporter->update();

    unsigned long now = millis();

    // Factory reset check
    if (digitalRead(FACTORY_RESET_PIN) == LOW) {
        if (factoryResetStart == 0) factoryResetStart = now;
        if (now - factoryResetStart > FACTORY_RESET_HOLD_MS) {
            Serial.println("[SYSTEM] Factory reset triggered!");
            config.factoryReset();
        }
    } else {
        factoryResetStart = 0;
    }

    // Read sensors
    if (now - lastRead >= readInterval) {
        lastRead = now;
        readSensors();
        checkAlerts();
    }

    // Publish telemetry
    if (now - lastPublish >= publishInterval) {
        lastPublish = now;
        publishTelemetry();
    }
}
