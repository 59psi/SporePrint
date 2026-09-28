// SporePrint camera firmware (v2) — AI-Thinker ESP32-CAM with an OV2640,
// OV3660 or OV5640 sensor (same 24-pin module connector and pin map; the
// sensor is detected at init by PID — see cam_policy.h for per-sensor
// tuning).
//
// Captures every 15 minutes (plus on-demand via cmd/capture) and POSTs the
// JPEG to the Pi's /api/vision/frame. Same boot-order safety design as the
// node image: provisioning runs pre-WDT; the watchdog arms last at 90 s
// (a JPEG POST on a slow link legitimately holds the loop 10-15 s).
//
// Capture: the flash stays ON through the exposure, and the frame the
// driver has been holding since the previous capture is drained first —
// with one frame buffer the driver fills it right after the last return
// and then holds it, so a plain fb_get 15 min later returns a 15-min-old,
// flash-less frame.
//
// Upload URL: an explicitly set server_url wins; otherwise the Pi address
// entered in the setup portal (cfg.broker_host) on :8000. X-Timestamp is
// sent only when the clock is NTP-synced (the Pi stamps arrival time
// otherwise). X-Camera-Sensor names the detected sensor.
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
#include "cam_policy.h"

#include "coredump_uploader.h"
#include "log_forward.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "tls_transport.h"
#include "ota_service.h"
#include "server_url_allow.h"
#include "sha256.h"
#include "hmac_verify.h"
#include "wifi_provisioner.h"
#include "wire_contract.h"
#include "wrap_time.h"

#ifndef SPOREPRINT_FW_VERSION
#define SPOREPRINT_FW_VERSION "dev"
#endif

static constexpr uint32_t kCaptureIntervalMs = 15UL * 60UL * 1000UL;

// Flash-on settle before the kept exposure: the sensor free-runs while the
// driver holds its one buffer, so AE/AWB converge on the flash-lit scene
// during this wait (hardware timing — a dark-phase chamber goes from
// black to LED-lit). Then kDiscardFrames frames are dropped: the first is
// the stale frame held since the previous capture, the second is margin
// for exposure still converging.
static constexpr uint32_t kFlashSettleMs = 500;
static constexpr int kDiscardFrames = 2;

static_assert(sp_cam::kPidOv2640 == OV2640_PID, "cam_policy PID drift");
static_assert(sp_cam::kPidOv3660 == OV3660_PID, "cam_policy PID drift");
static_assert(sp_cam::kPidOv5640 == OV5640_PID, "cam_policy PID drift");

static sp_device::NvsKvStore kv;
static sp_device::NodeConfig cfg;
static sp_device::WifiProvisioner provisioner(kv);
static WiFiClient wifi_client;
static WiFiClientSecure wifi_client_secure;
static sp_device::MqttLink* mqtt = nullptr;
static sp_device::OtaService* ota = nullptr;

static std::string server_url;
static uint32_t last_capture_ms = 0;
static uint32_t factory_hold_start_ms = 0;
static uint32_t capture_success = 0, capture_fail = 0;
static float avg_latency_ms = 0;
static uint32_t last_health_ms = 0;

static bool camera_ok = false;
static sp_cam::SensorProfile sensor = sp_cam::sensor_profile_none();
static uint16_t sensor_pid = 0;
static uint8_t jpeg_quality = 0;  // current quality number (0-63, lower = better)

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
    c.xclk_freq_hz = 20000000;  // valid for OV2640, OV3660 and OV5640
    c.pixel_format = PIXFORMAT_JPEG;
    // UXGA on every supported sensor (why: cam_policy.h SensorProfile).
    c.frame_size = FRAMESIZE_UXGA;  // 1600x1200
    c.jpeg_quality = 10;
    // One buffer, filled only when empty — capture_and_post() drains the
    // held (stale) frame itself. GRAB_LATEST is a no-op with fb_count 1
    // (esp_camera.h), so name the behavior the driver actually has.
    c.fb_count = 1;
    c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    c.fb_location = CAMERA_FB_IN_PSRAM;
    const bool psram = psramFound();
    if (!psram) {
        // Degrade, don't die: a VGA JPEG buffer (~61 KB) fits internal
        // DRAM — but only if it is REQUESTED there. Left at the PSRAM
        // default, init fails on exactly the boards this branch is for.
        c.frame_size = FRAMESIZE_VGA;
        c.jpeg_quality = 12;
        c.fb_location = CAMERA_FB_IN_DRAM;
    }
    esp_err_t err = esp_camera_init(&c);
    if (err != ESP_OK) {
        Serial.printf("[CAM] Init failed: 0x%x\n", err);
        return false;
    }
    jpeg_quality = (uint8_t)c.jpeg_quality;

    // Identify the sensor and apply its tuning (OV2640: nothing — the
    // pre-OV3660 behavior; OV3660: Espressif's flip/colour correction).
    sensor_t* s = esp_camera_sensor_get();
    if (s != nullptr) {
        sensor_pid = s->id.PID;
        sensor = sp_cam::sensor_profile(sensor_pid);
        if (sensor.apply_color_tuning) {
            s->set_vflip(s, sensor.vflip);
            s->set_brightness(s, sensor.brightness);
            s->set_saturation(s, sensor.saturation);
        }
        const uint8_t q =
            psram ? sensor.jpeg_quality_psram : sensor.jpeg_quality_dram;
        if (q != jpeg_quality && s->set_quality(s, q) == 0) jpeg_quality = q;
    } else {
        sensor = sp_cam::sensor_profile(0);  // initialized but unidentifiable
    }
    Serial.printf("[CAM] Camera initialized: %s (PID 0x%04x) %s q=%u\n",
                  sensor.name, (unsigned)sensor_pid,
                  psram ? "UXGA/PSRAM" : "VGA/DRAM", (unsigned)jpeg_quality);
    return true;
}

// Returns a frame exposed NOW (flash on, when requested) — never the one
// the driver has been holding since the previous capture.
static camera_fb_t* grab_fresh_frame(bool use_flash) {
    if (use_flash) {
        digitalWrite(SP_PIN_FLASH, HIGH);
        delay(kFlashSettleMs);  // hardware timing: AE/AWB settle under the LED
    }
    for (int i = 0; i < kDiscardFrames; ++i) {
        camera_fb_t* stale = esp_camera_fb_get();
        if (stale != nullptr) esp_camera_fb_return(stale);
    }
    camera_fb_t* fb = esp_camera_fb_get();
    if (use_flash) digitalWrite(SP_PIN_FLASH, LOW);  // after the exposure
    return fb;
}

static bool capture_and_post(bool use_flash) {
    if (!camera_ok) {
        // No sensor: don't pulse the flash for nothing. Counted as before.
        SP_LOG(LOG_ERROR, "[CAM] Capture skipped — camera not initialized");
        ++capture_fail;
        return false;
    }
    uint32_t start = millis();

    camera_fb_t* fb = grab_fresh_frame(use_flash);
    if (fb == nullptr) {
        SP_LOG(LOG_ERROR, "[CAM] Capture failed (frame buffer null)");
        ++capture_fail;
        // Most likely a JPEG that overflowed the fixed frame buffer (a
        // busy scene on a higher-resolution sensor): shrink future frames.
        const uint8_t next = sp_cam::backoff_jpeg_quality(jpeg_quality);
        sensor_t* s = esp_camera_sensor_get();
        if (next != jpeg_quality && s != nullptr && s->set_quality(s, next) == 0) {
            SP_LOG(LOG_WARN, "[CAM] JPEG quality %u -> %u after dropped frame",
                   (unsigned)jpeg_quality, (unsigned)next);
            jpeg_quality = next;
        }
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

    // HTTPS only against the pinned Pi CA — HTTPClient::begin(url) on an
    // https URL would otherwise run TLS with setInsecure(). The CA string
    // must outlive `http` (HTTPClient keeps the pointer), so it is declared
    // first.
    std::string upload_ca;
    if (sp_cam::is_https(server_url)) upload_ca = kv.get_string("broker_ca", "");
    const sp_cam::UploadTransport transport =
        sp_cam::upload_transport(server_url, !upload_ca.empty());
    if (transport == sp_cam::UploadTransport::Refuse) {
        SP_LOG(LOG_ERROR,
               "[CAM] https server_url but no pinned Pi CA — refusing an "
               "unverified TLS upload (use http://, or enable Secure MQTT)");
        ++capture_fail;
        esp_camera_fb_return(fb);
        return false;
    }

    HTTPClient http;
    std::string url = server_url + "/api/vision/frame";
    http.setConnectTimeout(10000);
    http.setTimeout(10000);
    if (transport == sp_cam::UploadTransport::TlsPinned)
        http.begin(url.c_str(), upload_ca.c_str());
    else
        http.begin(url.c_str());
    http.addHeader("Content-Type", "image/jpeg");
    http.addHeader("X-Node-Id", cfg.node_id.c_str());
    // Epoch seconds only when NTP has synced; omitted otherwise so the Pi
    // stamps arrival time (uptime here became 1970 dates + filename
    // collisions server-side).
    char ts[24];
    if (sp_cam::frame_timestamp((int64_t)time(nullptr), ts, sizeof(ts)))
        http.addHeader("X-Timestamp", ts);
    char res[16];
    snprintf(res, sizeof(res), "%dx%d", fb->width, fb->height);
    http.addHeader("X-Resolution", res);
    http.addHeader("X-Flash-Used", use_flash ? "1" : "0");
    http.addHeader("X-Camera-Sensor", sensor.name);

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
    // Additive keys: which sensor this cam actually has (the BOM 2-pack
    // moved from OV2640 to OV3660) and the live JPEG quality (the
    // dropped-frame backoff can raise it).
    cam["sensor"] = sensor.name;  // "ov2640" | "ov3660" | "ov5640" | "unknown" | "none"
    cam["sensor_pid"] = sensor_pid;
    cam["jpeg_quality"] = jpeg_quality;
    mqtt->publish(mqtt->topic("health").c_str(), doc);
}

static void publish_heartbeat() {
    if (!mqtt->connected()) return;
    // Keep the IP String alive until publish — build_heartbeat borrows it.
    String ip = WiFi.localIP().toString();
    const char* roles[1] = {"camera"};

    sp::HeartbeatInputs in;
    in.uptime_sec = millis() / 1000;
    in.free_heap = ESP.getFreeHeap();
    in.firmware_version = SPOREPRINT_FW_VERSION;
    in.wifi_rssi = WiFi.RSSI();
    in.ip = ip.c_str();
    in.reset_reason = (int)esp_reset_reason();
    in.emit_wifi_reconnects = false;  // cam heartbeat omits wifi_reconnects
    in.mqtt_reconnects = mqtt->reconnect_count();
    in.type = "camera";
    in.roles = roles;
    in.n_roles = 1;
    in.fw_image = "cam";
    in.migrated_from = cfg.migrated_from.c_str();

    JsonDocument doc;
    sp::build_heartbeat(in, doc);
    // Optional, cam-only key on top of the shared contract (the Pi ignores
    // keys it doesn't know): the detected image sensor.
    doc["camera_sensor"] = sensor.name;
    mqtt->publish(mqtt->topic("status/heartbeat").c_str(), doc);
}

static bool verify_command(const char* raw, size_t raw_len,
                           const char* suffix) {
    // Shared, host-tested policy — identical to the node image (test_core_hmac).
    sp::CmdAuthResult r = sp::command_auth_decision(
        raw, raw_len, cfg.hmac_key.c_str(), cfg.hmac_key.size(),
        (uint64_t)time(nullptr), sp::hmac_sha256_host);
    switch (r.decision) {
        case sp::CmdAuthDecision::AcceptUnsigned:
            SP_LOG(LOG_WARN,
                   "[SEC] hmac_key not provisioned — accepting unsigned cmd/%s",
                   suffix);
            return true;
        case sp::CmdAuthDecision::RejectClockUnsynced:
            SP_LOG(LOG_WARN, "[SEC] Rejecting cmd/%s: clock not synced", suffix);
            return false;
        case sp::CmdAuthDecision::Reject:
            SP_LOG(LOG_WARN, "[SEC] Rejecting cmd/%s: %s", suffix,
                   sp::verify_status_str(r.status));
            return false;
        case sp::CmdAuthDecision::Accept:
            return true;
    }
    return false;
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
            // The portal's Pi address is trusted like paired_pi_host — both
            // are set by the operator at provisioning, never over MQTT.
            if (sp_cam::server_url_cmd_allowed(lowered, cfg.paired_pi_host,
                                               cfg.broker_host)) {
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
    camera_ok = init_camera();
    if (!camera_ok) Serial.println("[CAM] Continuing WITHOUT camera — check module");

    if (!cfg.provisioned()) provisioner.run_portal(cfg);
    if (!provisioner.connect(cfg)) provisioner.run_portal(cfg);
    provisioner.start_ntp(cfg);

    // Stored server_url (MQTT cmd / v1 migration) wins; otherwise the Pi
    // address typed into the portal — the old hardcoded sporeprint.local
    // broke every LAN without mDNS even though MQTT (same host) worked.
    server_url = sp_cam::resolve_server_url(kv.get_string("server_url", ""),
                                            cfg.broker_host);
    Serial.printf("[CAM] Frame upload URL: %s\n", server_url.c_str());

    sp_device::MqttTransport xport =
        sp_device::select_mqtt_transport(cfg, kv, wifi_client,
                                         wifi_client_secure);
    mqtt = new sp_device::MqttLink(*xport.client, cfg.node_id.c_str(), "camera",
                                   SPOREPRINT_FW_VERSION);
    mqtt->on_command(on_command, nullptr);
    mqtt->begin(cfg.broker_host.c_str(), xport.port,
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
    SP_LOG(LOG_INFO, "[BOOT] cam ready: id=%s camera=%d sensor=%s reset=%d",
           cfg.node_id.c_str(), camera_ok, sensor.name, (int)esp_reset_reason());

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
