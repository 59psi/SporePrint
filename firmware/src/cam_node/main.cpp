#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "esp_camera.h"
#include "sporeprint_common.h"

#define NODE_TYPE "camera"
#define DEFAULT_NODE_ID "cam-01"
#define FLASH_PIN 4
#define CAPTURE_INTERVAL_MS 900000  // 15 minutes
#define FACTORY_RESET_PIN 0
#define FACTORY_RESET_HOLD_MS 10000

// AI-Thinker ESP32-CAM pin definitions
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

ConfigStore config("camera");
WiFiManager wifi(config);
MqttManager* mqtt = nullptr;
OTAManager* ota = nullptr;
Heartbeat* heartbeat = nullptr;

unsigned long lastCapture = 0;
unsigned long factoryResetStart = 0;
String serverUrl = "";

bool initCamera() {
    camera_config_t cfg;
    cfg.ledc_channel = LEDC_CHANNEL_0;
    cfg.ledc_timer = LEDC_TIMER_0;
    cfg.pin_d0 = Y2_GPIO_NUM;
    cfg.pin_d1 = Y3_GPIO_NUM;
    cfg.pin_d2 = Y4_GPIO_NUM;
    cfg.pin_d3 = Y5_GPIO_NUM;
    cfg.pin_d4 = Y6_GPIO_NUM;
    cfg.pin_d5 = Y7_GPIO_NUM;
    cfg.pin_d6 = Y8_GPIO_NUM;
    cfg.pin_d7 = Y9_GPIO_NUM;
    cfg.pin_xclk = XCLK_GPIO_NUM;
    cfg.pin_pclk = PCLK_GPIO_NUM;
    cfg.pin_vsync = VSYNC_GPIO_NUM;
    cfg.pin_href = HREF_GPIO_NUM;
    cfg.pin_sccb_sda = SIOD_GPIO_NUM;
    cfg.pin_sccb_scl = SIOC_GPIO_NUM;
    cfg.pin_pwdn = PWDN_GPIO_NUM;
    cfg.pin_reset = RESET_GPIO_NUM;
    cfg.xclk_freq_hz = 20000000;
    cfg.pixel_format = PIXFORMAT_JPEG;
    cfg.frame_size = FRAMESIZE_UXGA;  // 1600x1200
    cfg.jpeg_quality = 10;
    cfg.fb_count = 1;
    cfg.grab_mode = CAMERA_GRAB_LATEST;

    // Lower quality if PSRAM not available
    if (!psramFound()) {
        cfg.frame_size = FRAMESIZE_VGA;
        cfg.jpeg_quality = 12;
        cfg.fb_count = 1;
    }

    esp_err_t err = esp_camera_init(&cfg);
    if (err != ESP_OK) {
        Serial.printf("[CAM] Init failed: 0x%x\n", err);
        return false;
    }
    Serial.println("[CAM] Camera initialized");
    return true;
}

void flashPulse() {
    digitalWrite(FLASH_PIN, HIGH);
    delay(200);
    digitalWrite(FLASH_PIN, LOW);
}

bool captureAndPost() {
    flashPulse();
    delay(100);

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("[CAM] Capture failed");
        return false;
    }

    Serial.printf("[CAM] Captured %dx%d (%u bytes)\n", fb->width, fb->height, fb->len);

    if (serverUrl.length() == 0) {
        esp_camera_fb_return(fb);
        return false;
    }

    HTTPClient http;
    String url = serverUrl + "/api/vision/frame";
    http.begin(url);
    http.addHeader("Content-Type", "image/jpeg");
    http.addHeader("X-Node-Id", mqtt->getNodeId());
    http.addHeader("X-Timestamp", String(millis() / 1000));
    http.addHeader("X-Resolution", String(fb->width) + "x" + String(fb->height));
    http.addHeader("X-Flash-Used", "1");

    int httpCode = http.POST(fb->buf, fb->len);
    Serial.printf("[CAM] POST %s → %d\n", url.c_str(), httpCode);

    http.end();
    esp_camera_fb_return(fb);
    return httpCode == 200;
}

void onCommand(const char* topic, JsonDocument& doc) {
    if (doc.containsKey("capture") && doc["capture"].as<bool>()) {
        Serial.println("[CMD] On-demand capture requested");
        captureAndPost();
    }
    if (doc.containsKey("server_url")) {
        serverUrl = doc["server_url"].as<String>();
        config.setString("server_url", serverUrl);
        Serial.printf("[CMD] Server URL set to %s\n", serverUrl.c_str());
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== SporePrint Camera Node ===");

    pinMode(FLASH_PIN, OUTPUT);
    digitalWrite(FLASH_PIN, LOW);
    pinMode(FACTORY_RESET_PIN, INPUT_PULLUP);

    if (!initCamera()) {
        Serial.println("[CAM] Camera init failed! Restarting...");
        delay(3000);
        ESP.restart();
    }

    wifi.begin();

    String nodeId = config.getString("node_id");
    if (nodeId.length() == 0) nodeId = DEFAULT_NODE_ID;

    serverUrl = config.getString("server_url");
    if (serverUrl.length() == 0) serverUrl = "http://sporeprint.local:8000";

    mqtt = new MqttManager(config, NODE_TYPE, nodeId.c_str());
    mqtt->begin();
    mqtt->subscribe(mqtt->buildTopic("cmd/#").c_str(), onCommand);

    String hostname = "sporeprint-" + nodeId;
    ota = new OTAManager(config, hostname.c_str());
    ota->begin();

    heartbeat = new Heartbeat(*mqtt);

    Serial.println("[SETUP] Camera node ready!");
}

void loop() {
    mqtt->loop();
    ota->loop();
    heartbeat->loop();

    unsigned long now = millis();

    // Scheduled capture
    if (now - lastCapture >= CAPTURE_INTERVAL_MS) {
        lastCapture = now;
        captureAndPost();
    }

    // Factory reset
    if (digitalRead(FACTORY_RESET_PIN) == LOW) {
        if (factoryResetStart == 0) factoryResetStart = now;
        if (now - factoryResetStart > FACTORY_RESET_HOLD_MS) config.factoryReset();
    } else {
        factoryResetStart = 0;
    }
}
