#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_task_wdt.h>
#include "esp_camera.h"
#include "sporeprint_common.h"
#include "health.h"

// v3.4.9 — task watchdog parity with relay_node. Longer timeout than the
// others because an outbound JPEG POST on a slow upload can legitimately
// hold the main task for 10-15 seconds. 60s leaves plenty of margin.
static const uint32_t WDT_TIMEOUT_SEC = 60;

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
CamHealthReporter* healthReporter = nullptr;

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
    unsigned long startMs = millis();
    flashPulse();
    delay(100);

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("[CAM] Capture failed (frame buffer null)");
        if (healthReporter) healthReporter->captureFail++;
        return false;
    }

    Serial.printf("[CAM] Captured %dx%d (%u bytes)\n", fb->width, fb->height, fb->len);

    if (serverUrl.length() == 0) {
        Serial.println("[CAM] server_url unset — frame captured but cannot post");
        if (healthReporter) healthReporter->captureFail++;
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

    bool ok = (httpCode == 200);
    if (healthReporter) {
        if (ok) {
            healthReporter->captureSuccess++;
            healthReporter->lastCapture = millis();
            unsigned long latency = millis() - startMs;
            // EMA with alpha=0.2 — smooths spikes, reacts to trends.
            healthReporter->avgLatencyMs =
                healthReporter->avgLatencyMs * 0.8f + (float)latency * 0.2f;
        } else {
            healthReporter->captureFail++;
        }
    }
    return ok;
}

// v3.4.9 H-1: validate server_url before accepting + persisting. Prior
// behavior wrote whatever arrived over MQTT straight to NVS — a LAN actor
// with broker creds could redirect every captured frame to an attacker
// server indefinitely. Allow only:
//   - http:// or https:// scheme
//   - hostname of the paired Pi (stored during provisioning) OR
//     sporeprint.local (mDNS) OR sporeprint.ai (cloud fallback)
//   - no userinfo, no query string, no fragment
//   - total length <= 128 chars (prevents flash-filling DoS)
static bool isServerUrlAllowed(const String& url) {
    if (url.length() == 0 || url.length() > 128) return false;

    // Scheme check
    String lower = url;
    lower.toLowerCase();
    bool https = lower.startsWith("https://");
    bool http = lower.startsWith("http://");
    if (!https && !http) return false;

    // No userinfo (prohibits http://attacker@pi/)
    int schemeEnd = lower.indexOf("://") + 3;
    int hostEnd = lower.indexOf('/', schemeEnd);
    if (hostEnd < 0) hostEnd = lower.length();
    String hostPart = lower.substring(schemeEnd, hostEnd);
    if (hostPart.indexOf('@') >= 0) return false;

    // Strip port
    int colon = hostPart.indexOf(':');
    String host = (colon >= 0) ? hostPart.substring(0, colon) : hostPart;

    // No query / fragment anywhere in the URL (keep it to the Pi ingest path).
    if (lower.indexOf('?') >= 0 || lower.indexOf('#') >= 0) return false;

    // Allow-list of acceptable hosts. The pairedPiHost is set at
    // provisioning time via `paired_pi_host` in NVS; falls back to the
    // mDNS / cloud hostnames if unset.
    String pairedPi = config.getString("paired_pi_host");
    pairedPi.toLowerCase();
    if (host == "sporeprint.local") return true;
    if (host == "sporeprint.ai") return true;
    if (pairedPi.length() > 0 && host == pairedPi) return true;

    // RFC1918 ranges — acceptable for LAN Pi that isn't using mDNS.
    // Cheap check: must start with 10., 172.16-31., or 192.168.
    if (host.startsWith("10.")) return true;
    if (host.startsWith("192.168.")) return true;
    if (host.startsWith("172.")) {
        int secondDot = host.indexOf('.', 4);
        if (secondDot > 0) {
            int secondOctet = host.substring(4, secondDot).toInt();
            if (secondOctet >= 16 && secondOctet <= 31) return true;
        }
    }
    return false;
}

void onCommand(const char* topic, JsonDocument& doc) {
    // v3.4.9 C-1 — HMAC verify before any action (capture or config).
    // H-1 server_url validation kicks in on top for belt-and-suspenders.
    if (!sporeprint::verifyOrWarn(doc, config, topic)) {
        return;
    }

    if (doc.containsKey("capture") && doc["capture"].as<bool>()) {
        Serial.println("[CMD] On-demand capture requested");
        captureAndPost();
    }
    if (doc.containsKey("server_url")) {
        String candidate = doc["server_url"].as<String>();
        if (!isServerUrlAllowed(candidate)) {
            Serial.printf("[CMD] REJECTED server_url=%s (not in allow-list)\n",
                          candidate.c_str());
            return;
        }
        serverUrl = candidate;
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

    // Arm WDT before camera/wifi init — either can block on PSRAM / sensor
    // handshake. Reset-state for cam_node is simply "try again from boot".
    esp_task_wdt_init(WDT_TIMEOUT_SEC, true);
    esp_task_wdt_add(NULL);

    // v3.4.9 C-1 — optional build-flag NVS provisioning.
    sporeprint::bootstrapHmacKeyFromBuildFlag(config);

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
    ota->setMqtt(mqtt);
    ota->begin();

    heartbeat = new Heartbeat(*mqtt);
    healthReporter = new CamHealthReporter(nodeId.c_str(), *mqtt);

    Serial.println("[SETUP] Camera node ready!");
}

void loop() {
    esp_task_wdt_reset();

    mqtt->loop();
    ota->loop();
    heartbeat->loop();
    if (healthReporter) healthReporter->update();

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
