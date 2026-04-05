#include <Arduino.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include "sporeprint_common.h"

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
void onCommand(const char* topic, JsonDocument& doc) {
    if (doc.containsKey("read_interval_ms")) {
        readInterval = doc["read_interval_ms"].as<unsigned long>();
        Serial.printf("[CMD] Read interval set to %lu ms\n", readInterval);
    }
    if (doc.containsKey("publish_interval_ms")) {
        publishInterval = doc["publish_interval_ms"].as<unsigned long>();
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
    } else {
        sht31Ok = false;
        Serial.println("[SENSOR] SHT31 read error!");
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
    } else {
        scd40Ok = false;
    }

    // BH1750 — Light
    float luxReading = lightMeter.readLightLevel();
    if (luxReading >= 0) {
        lux = luxReading;
        bh1750Ok = true;
    } else {
        bh1750Ok = false;
    }
}

// ─── Alert Check ────────────────────────────────────────────────
void checkAlerts() {
    JsonDocument alert;
    bool shouldAlert = false;

    if (sht31Ok && (tempF > 90.0 || tempF < 40.0)) {
        alert["type"] = "temperature";
        alert["value"] = tempF;
        alert["message"] = tempF > 90.0 ? "Temperature critically high!" : "Temperature critically low!";
        shouldAlert = true;
    }
    if (sht31Ok && (humidity > 99.0 || humidity < 30.0)) {
        alert["type"] = "humidity";
        alert["value"] = humidity;
        alert["message"] = humidity > 99.0 ? "Humidity saturated!" : "Humidity critically low!";
        shouldAlert = true;
    }
    if (scd40Ok && co2Ppm > 4000) {
        alert["type"] = "co2";
        alert["value"] = co2Ppm;
        alert["message"] = "CO2 dangerously high!";
        shouldAlert = true;
    }
    if (!sht31Ok) {
        alert["type"] = "sensor_failure";
        alert["sensor"] = "SHT31";
        alert["message"] = "SHT31 sensor read failed";
        shouldAlert = true;
    }

    if (shouldAlert && mqtt->isConnected()) {
        mqtt->publish(mqtt->buildTopic("alert").c_str(), alert);
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

    // Factory reset button
    pinMode(FACTORY_RESET_PIN, INPUT_PULLUP);

    // WiFi
    wifi.begin();

    // Node ID
    String nodeId = config.getString("node_id");
    if (nodeId.length() == 0) nodeId = DEFAULT_NODE_ID;

    // MQTT
    mqtt = new MqttManager(config, NODE_TYPE, nodeId.c_str());
    mqtt->begin();
    mqtt->subscribe(mqtt->buildTopic("cmd/config").c_str(), onCommand);

    // OTA
    String hostname = "sporeprint-" + nodeId;
    ota = new OTAManager(config, hostname.c_str());
    ota->begin();

    // Heartbeat
    heartbeat = new Heartbeat(*mqtt);

    // Offline buffer
    offlineBuffer = new OfflineBuffer(*mqtt);
    offlineBuffer->begin();

    // I2C Sensors
    Wire.begin();

    // SHT31
    sht31.begin(0x44);
    SHT31D check = sht31.readSerialNumber();
    if (check.error == SHT3XD_NO_ERROR) {
        Serial.printf("[SENSOR] SHT31 found (SN: %u)\n", check.sn);
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

    Serial.println("[SETUP] Climate node ready!");
}

// ─── Loop ───────────────────────────────────────────────────────
void loop() {
    mqtt->loop();
    ota->loop();
    heartbeat->loop();

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
