// SporePrint camera firmware (v2) — AI-Thinker ESP32-CAM (OV2640).
//
// Captures every 15 minutes (plus on-demand via cmd/capture) and POSTs the
// JPEG to the Pi's /api/vision/frame. Same boot-order safety design as the
// node image: provisioning runs pre-WDT; the watchdog arms last at 90 s
// (a JPEG POST on a slow link legitimately holds the loop 10-15 s).
//
// v2 fixes over the v1 cam:
//   * factory reset moves GPIO 0 → 13 (v1 shared GPIO 0 with the camera
//     XCLK — the reset pullup fought the pixel clock)
//   * server_url validation requires a genuine dotted-quad before any
//     RFC1918 allowance ("10.attacker.com" passed v1's startsWith check)
//   * the flash is per-capture optional ({"capture":true,"flash":false}) —
//     v1 hardcoded X-Flash-Used: 1 with no way to turn the LED off
//   * HTTP timeouts are explicit (10 s connect / 10 s read) so a wedged
//     server can't hold the loop past the WDT budget

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_task_wdt.h>

#include <time.h>

#include "board_profile_esp32cam.h"

#include "coredump_uploader.h"
#include "log_forward.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "ota_service.h"
#include "server_url_allow.h"
#include "sha256.h"
#include "hmac_verify.h"
#include "wifi_provisioner.h"
#include "wrap_time.h"

#ifndef SPOREPRINT_FW_VERSION
#define SPOREPRINT_FW_VERSION "dev"
#endif

static constexpr uint32_t kCaptureIntervalMs = 15UL * 60UL * 1000UL;

static sp_device::NvsKvStore kv;
static sp_device::NodeConfig cfg;
static sp_device::WifiProvisioner provisioner(kv);
static WiFiClient wifi_client;
static sp_device::MqttLink* mqtt = nullptr;
static sp_device::OtaService* ota = nullptr;

static std::string server_url;
static uint32_t last_capture_ms = 0;
static uint32_t factory_hold_start_ms = 0;
static uint32_t capture_success = 0, capture_fail = 0;
static float avg_latency_ms = 0;
static uint32_t last_health_ms = 0;

static bool init_camera() {
    camera_config_t c = {};
    c.ledc_channel = LEDC_CHANNEL_0;
    c.ledc_timer = LEDC_TIMER_0;
    c.pin_d0 = SP_CAM_Y2;
    c.pin_d1 = SP_CAM_Y3;
    c.pin_d2 = SP_CAM_Y4;
    c.pin_d3 = SP_CAM_Y5;
    c.pin_d4 = SP_CAM_Y6;
    c.pin_d5 = SP_CAM_Y7;
    c.pin_d6 = SP_CAM_Y8;
    c.pin_d7 = SP_CAM_Y9;
    c.pin_xclk = SP_CAM_XCLK;
    c.pin_pclk = SP_CAM_PCLK;
    c.pin_vsync = SP_CAM_VSYNC;
    c.pin_href = SP_CAM_HREF;
    c.pin_sccb_sda = SP_CAM_SIOD;
    c.pin_sccb_scl = SP_CAM_SIOC;
    c.pin_pwdn = SP_CAM_PWDN;
    c.pin_reset = SP_CAM_RESET;
    c.xclk_freq_hz = 20000000;
    c.pixel_format = PIXFORMAT_JPEG;
    c.frame_size = FRAMESIZE_UXGA;  // 1600x1200
    c.jpeg_quality = 10;
    c.fb_count = 1;
    c.grab_mode = CAMERA_GRAB_LATEST;
    if (!psramFound()) {
        c.frame_size = FRAMESIZE_VGA;
        c.jpeg_quality = 12;
    }
    esp_err_t err = esp_camera_init(&c);
    if (err != ESP_OK) {
        Serial.printf("[CAM] Init failed: 0x%x\n", err);
        return false;
    }
    Serial.println("[CAM] Camera initialized");
    return true;
}

static bool capture_and_post(bool use_flash) {
    uint32_t start = millis();
    if (use_flash) {
        digitalWrite(SP_PIN_FLASH, HIGH);
        delay(200);
        digitalWrite(SP_PIN_FLASH, LOW);
        delay(100);
    }

    camera_fb_t* fb = esp_camera_fb_get();
    if (fb == nullptr) {
        SP_LOG(LOG_ERROR, "[CAM] Capture failed (frame buffer null)");
        ++capture_fail;
        return false;
    }
    SP_LOG(LOG_INFO, "[CAM] Captured %dx%d (%u bytes)", fb->width, fb->height,
           (unsigned)fb->len);

    if (server_url.empty()) {
        SP_LOG(LOG_WARN, "[CAM] server_url unset — frame dropped");
        ++capture_fail;
        esp_camera_fb_return(fb);
        return false;
    }

    HTTPClient http;
    std::string url = server_url + "/api/vision/frame";
    http.setConnectTimeout(10000);
    http.setTimeout(10000);
    http.begin(url.c_str());
    http.addHeader("Content-Type", "image/jpeg");
    http.addHeader("X-Node-Id", cfg.node_id.c_str());
    // Epoch when NTP has synced; uptime otherwise (server treats as opaque).
    time_t now = time(nullptr);
    char ts[16];
    snprintf(ts, sizeof(ts), "%lu",
             (unsigned long)(now > 1577836800 ? (unsigned long)now
                                              : millis() / 1000));
    http.addHeader("X-Timestamp", ts);
    char res[16];
    snprintf(res, sizeof(res), "%dx%d", fb->width, fb->height);
    http.addHeader("X-Resolution", res);
    http.addHeader("X-Flash-Used", use_flash ? "1" : "0");

    int code = http.POST(fb->buf, fb->len);
    SP_LOG(code == 200 ? LOG_INFO : LOG_WARN, "[CAM] POST %s -> %d",
           url.c_str(), code);
    http.end();
    esp_camera_fb_return(fb);

    if (code == 200) {
        ++capture_success;
        uint32_t latency = sp::elapsed_ms(millis(), start);
        avg_latency_ms = avg_latency_ms * 0.8f + (float)latency * 0.2f;
        return true;
    }
    ++capture_fail;
    return false;
}

static void publish_health() {
    if (!mqtt->connected()) return;
    JsonDocument doc;
    doc["node_id"] = cfg.node_id.c_str();
    doc["type"] = "camera";
    doc["uptime_sec"] = millis() / 1000;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["wifi_rssi"] = WiFi.RSSI();
    JsonObject cam = doc["camera"].to<JsonObject>();
    cam["capture_success"] = capture_success;
    cam["capture_fail"] = capture_fail;
    cam["avg_latency_ms"] = avg_latency_ms;
    cam["psram_free"] = ESP.getFreePsram();
    mqtt->publish(mqtt->topic("health").c_str(), doc);
}

static void publish_heartbeat() {
    if (!mqtt->connected()) return;
    JsonDocument doc;
    doc["uptime_sec"] = millis() / 1000;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["firmware_version"] = SPOREPRINT_FW_VERSION;
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["ip"] = WiFi.localIP().toString();
    doc["reset_reason"] = (int)esp_reset_reason();
    doc["mqtt_reconnects"] = mqtt->reconnect_count();
    doc["type"] = "camera";
    JsonArray roles = doc["roles"].to<JsonArray>();
    roles.add("camera");
    doc["fw_image"] = "cam";
    if (!cfg.migrated_from.empty())
        doc["migrated_from"] = cfg.migrated_from.c_str();
    mqtt->publish(mqtt->topic("status/heartbeat").c_str(), doc);
}

static bool verify_command(const char* raw, size_t raw_len,
                           const char* suffix) {
    if (cfg.hmac_key.empty()) {
        SP_LOG(LOG_WARN,
               "[SEC] hmac_key not provisioned — accepting unsigned cmd/%s",
               suffix);
        return true;
    }
    time_t now = time(nullptr);
    if (now < 1577836800) {
        SP_LOG(LOG_WARN, "[SEC] Rejecting cmd/%s: clock not synced", suffix);
        return false;
    }
    sp::VerifyStatus st =
        sp::verify_frame(raw, raw_len, cfg.hmac_key.c_str(),
                         cfg.hmac_key.size(), (uint64_t)now,
                         sp::hmac_sha256_host);
    if (st != sp::VerifyStatus::Ok) {
        SP_LOG(LOG_WARN, "[SEC] Rejecting cmd/%s: %s", suffix,
               sp::verify_status_str(st));
        return false;
    }
    return true;
}

static void on_command(const char* suffix, const char* raw, size_t raw_len,
                       JsonDocument& doc, void*) {
    if (!verify_command(raw, raw_len, suffix)) return;

    if (doc["capture"].is<bool>() && doc["capture"].as<bool>()) {
        bool flash = doc["flash"].is<bool>() ? doc["flash"].as<bool>() : true;
        SP_LOG(LOG_INFO, "[CMD] On-demand capture (flash=%d)", flash);
        capture_and_post(flash);
    }
    if (doc["server_url"].is<const char*>()) {
        const char* candidate = doc["server_url"].as<const char*>();
        // Lowercase before validation (allowlist compares lowercased).
        char lowered[136];
        size_t n = strlen(candidate);
        if (n < sizeof(lowered)) {
            for (size_t i = 0; i <= n; ++i)
                lowered[i] = (char)tolower((unsigned char)candidate[i]);
            if (sp::server_url_allowed(lowered, cfg.paired_pi_host.c_str())) {
                server_url = lowered;
                kv.set_string("server_url", server_url);
                SP_LOG(LOG_INFO, "[CMD] server_url set to %s",
                       server_url.c_str());
            } else {
                SP_LOG(LOG_WARN, "[CMD] REJECTED server_url=%s (allowlist)",
                       candidate);
            }
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.printf("\n=== SporePrint Cam v2 (%s) ===\n", SP_BOARD_NAME);

    pinMode(SP_PIN_FLASH, OUTPUT);
    digitalWrite(SP_PIN_FLASH, LOW);
    pinMode(SP_PIN_FACTORY_RESET, INPUT_PULLUP);

    std::string migrated = sp_device::migrate_legacy(kv);
    cfg = sp_device::NodeConfig::load(kv);
    if (!migrated.empty())
        Serial.printf("[CONFIG] Migrated v1 namespace '%s'\n", migrated.c_str());

    // Camera before WiFi — a dead sensor module should be loudly visible
    // but must NOT brick provisioning (v1 restart-looped before the portal
    // could ever appear). Boot degraded instead: MQTT health reports the
    // failure while the operator can still reach the node.
    bool camera_ok = init_camera();
    if (!camera_ok) Serial.println("[CAM] Continuing WITHOUT camera — check module");

    if (!cfg.provisioned()) provisioner.run_portal(cfg);
    if (!provisioner.connect(cfg)) provisioner.run_portal(cfg);
    provisioner.start_ntp(cfg);

    server_url = kv.get_string("server_url", "http://sporeprint.local:8000");

    mqtt = new sp_device::MqttLink(wifi_client, cfg.node_id.c_str(), "camera",
                                   SPOREPRINT_FW_VERSION);
    mqtt->on_command(on_command, nullptr);
    mqtt->begin(cfg.broker_host.c_str(), (uint16_t)cfg.broker_port,
                cfg.mqtt_user.c_str(), cfg.mqtt_pass.c_str());

    sp_device::logfwd::attach(mqtt);
    sp_device::coredump::upload_if_present(*mqtt);

    std::string hostname = "sporeprint-" + cfg.node_id;
    ota = new sp_device::OtaService(*mqtt, hostname.c_str(),
                                    cfg.ota_pass.c_str());
    ota->begin();

    if (!camera_ok) {
        SP_LOG(LOG_ERROR, "[CAM] camera init FAILED — captures disabled");
        ++capture_fail;
    }
    SP_LOG(LOG_INFO, "[BOOT] cam ready: id=%s camera=%d reset=%d",
           cfg.node_id.c_str(), camera_ok, (int)esp_reset_reason());

    // Arm last: 90 s — an on-demand capture's POST can hold 10-15 s and
    // retries are legitimate.
    esp_task_wdt_init(90, true);
    esp_task_wdt_add(NULL);
}

void loop() {
    esp_task_wdt_reset();
    uint32_t now = millis();

    mqtt->loop(now);
    ota->loop();
    sp_device::logfwd::loop(now);

    if (sp::elapsed_ms(now, last_capture_ms) >= kCaptureIntervalMs) {
        last_capture_ms = now;
        capture_and_post(true);
    }
    if (sp::elapsed_ms(now, last_health_ms) >= 300000) {
        last_health_ms = now;
        publish_health();
        publish_heartbeat();
    }

    if (digitalRead(SP_PIN_FACTORY_RESET) == LOW) {
        if (factory_hold_start_ms == 0) factory_hold_start_ms = now;
        if (sp::elapsed_ms(now, factory_hold_start_ms) > 10000) {
            SP_LOG(LOG_ERROR, "[SYSTEM] Factory reset triggered");
            sp_device::factory_reset_all();
        }
    } else {
        factory_hold_start_ms = 0;
    }
}
