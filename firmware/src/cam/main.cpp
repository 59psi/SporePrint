// SporePrint camera firmware (v2) — AI-Thinker ESP32-CAM with an OV2640,
// OV3660 or OV5640 sensor (same 24-pin module connector and pin map; the
// sensor is detected at init by PID — see cam_policy.h for per-sensor
// tuning). The same image also builds for the ESP32-S3 camera boards earlier
// BOMs listed (boards/board_profile_esp32s3cam.h: Freenove ESP32-S3-WROOM
// CAM, Seeed XIAO ESP32S3 Sense, Waveshare ESP32-S3-CAM-OVxxxx), which have
// no flash LED and use their BOOT button (GPIO 0) as the reset button.
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
// Boot / link policy — the same host-tested sp_core policy as the node:
//   * setup portal (an OPEN AP) only when unprovisioned, on request (reset
//     button — GPIO 13 on the AI-Thinker, BOOT / GPIO 0 on the S3 boards —
//     held 3-10 s, then released), or when freshly-typed
//     credentials never connected; a cam whose WiFi has worked before boots
//     offline and re-begins the STA link every 60 s (boot_policy.h,
//     link_watchdog.h)
//   * reset button held > 10 s → factory reset, timed only over densely
//     sampled passes (a 10-15 s capture/POST used to stretch a short press
//     into a reset); no capture or MQTT connect starts while it is held
//   * OTA probation + rollback (image_rollback.h)
//   * signed commands bound to their arrival topic + replay guard
//     (hmac_verify.h)
//   * status heartbeat + health every 5 min on their own clock
//     (publish_cadence.h); Secure MQTT with no pinned CA is a loud fallback
//     or fails closed (tls_policy.h)
//
// v2 fixes over the v1 cam:
//   * factory reset moves GPIO 0 → 13 (v1 shared GPIO 0 with the camera
//     XCLK — the reset pullup fought the pixel clock)
//   * server_url validation requires a genuine dotted-quad before any
//     RFC1918 allowance ("10.attacker.com" passed v1's startsWith check)
//   * the flash is per-capture optional ({"capture":true,"flash":false}) —
//     v1 hardcoded X-Flash-Used: 1 with no way to turn the LED off
//   * every wait of a capture + upload is bounded (cam_policy.h budget):
//     the upload runs on the cam's own clients with the capped DNS lookup,
//     a 10 s connect, a 10 s TLS handshake and 10 s socket waits, so a
//     wedged server or a stalled handshake can't hold the loop past the WDT
//   * an on-demand capture (cmd {"capture":true}) only records the request;
//     loop() takes it like a scheduled one, never inside the MQTT callback
//     (deep under PubSubClient's stack, with the keepalive starved), and the
//     keepalive covers the longest loop pass

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <esp_camera.h>

#include <time.h>

#if defined(SP_BOARD_ESP32S3_CAM)
#include "board_profile_esp32s3cam.h"
#else
#include "board_profile_esp32cam.h"
#endif
#include "cam_policy.h"

#if defined(SP_CAM_HAS_WS_EXIO)
#include "idf_i2c_bus.h"
#include "ws_cam_exio.h"
#endif

#include "alert_latch.h"
#include "boot_policy.h"
#include "bounded_dns.h"
#include "command_auth.h"
#include "coredump_uploader.h"
#include "deferred_restart.h"
#include "image_rollback.h"
#include "link_watchdog.h"
#include "log_forward.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "ota_build.h"
#include "ota_gate.h"
#include "tls_transport.h"
#include "ota_service.h"
#include "provisioning.h"
#include "publish_cadence.h"
#include "server_url_allow.h"
#include "hmac_verify.h"
#include "task_wdt.h"
#include "tls_policy.h"
#include "wifi_provisioner.h"
#include "wire_contract.h"
#include "wrap_time.h"

#ifndef SPOREPRINT_FW_VERSION
#define SPOREPRINT_FW_VERSION "dev"
#endif

static constexpr uint32_t kCaptureIntervalMs = 15UL * 60UL * 1000UL;
// Health + heartbeat cadence: the cam has no operator-tunable publish
// interval, so both run at the 5-min heartbeat ceiling.
static constexpr uint32_t kStatusIntervalMs =
    sp::PublishCadence::kMaxHeartbeatIntervalMs;

// Flash-on settle before the kept exposure: the sensor free-runs while the
// driver holds its one buffer, so AE/AWB converge on the flash-lit scene
// during this wait (hardware timing — a dark-phase chamber goes from
// black to LED-lit). Then kDiscardFrames frames are dropped: the first is
// the stale frame held since the previous capture, the second is margin
// for exposure still converging.
static constexpr uint32_t kFlashSettleMs = 500;
static constexpr int kDiscardFrames = 2;

// Board facts from the profile (the AI-Thinker profile predates the S3
// boards and sets none of these: its defaults).
#ifndef SP_CAM_BOARD_KIND
#define SP_CAM_BOARD_KIND AiThinker
#endif
#ifndef SP_CAM_XCLK_HZ
#define SP_CAM_XCLK_HZ 20000000  // valid for OV2640, OV3660 and OV5640
#endif
static constexpr sp_cam::Board kBoard = sp_cam::Board::SP_CAM_BOARD_KIND;
static constexpr bool kHasFlash = SP_PIN_FLASH >= 0;

static_assert(sp_cam::kPidOv2640 == OV2640_PID, "cam_policy PID drift");
static_assert(sp_cam::kPidOv3660 == OV3660_PID, "cam_policy PID drift");
static_assert(sp_cam::kPidOv5640 == OV5640_PID, "cam_policy PID drift");

static sp_device::NvsKvStore kv;
static sp_device::NodeConfig cfg;
// No peripheral fieldset and no personality select: the camera builds
// neither the Tier-3 drivers nor a channel bank.
static sp_device::WifiProvisioner provisioner(kv, /*peripheral_opts=*/false,
                                               /*personality_opt=*/false);
// Bounded DNS (sp_device/bounded_dns.h): a broker lookup can't outlast its
// slot in the loop-WDT budget (sp_core/link_budget.h).
static sp_device::BoundedDnsClient wifi_client;
static sp_device::BoundedDnsSecureClient wifi_client_secure;
static sp_device::TlsSupervisor tls_link(cfg, kv, wifi_client,
                                         wifi_client_secure);
static sp_device::MqttLink* mqtt = nullptr;
static sp_device::OtaService* ota = nullptr;

static std::string server_url;
static uint32_t last_capture_ms = 0;
static uint32_t capture_success = 0, capture_fail = 0;
static float avg_latency_ms = 0;
static sp::PublishCadence status_cadence(kStatusIntervalMs);
// cmd {"capture": true}: taken by loop() on its next free pass.
static bool capture_requested = false;
static bool capture_requested_flash = true;

// Reset button (SP_PIN_FACTORY_RESET: GPIO 13 on the AI-Thinker, BOOT /
// GPIO 0 on the S3 boards): 3-10 s hold + release → setup portal, >10 s →
// factory reset — densely-sampled holds only (boot_policy.h).
static sp::ButtonHold reset_button;
// Signed commands: each accepted (topic, MAC) once per replay window.
static sp::ReplayGuard cmd_replay_guard;
// OTA probation + deliberate, deferred restarts.
static sp::ImageConfirm image_confirm;
static sp_device::DeferredRestart restart;
// WiFi re-begin after an offline boot / a disconnect the core won't retry
// (the cam has no channels, so the watchdog's safe-mode actions are unused).
static sp::LinkWatchdog link_wd;
static uint32_t wifi_reconnects = 0;
static sp::TlsDowngradeLatch tls_downgrade_alert;  // tls_policy.h

static bool camera_ok = false;
static sp_cam::SensorProfile sensor = sp_cam::sensor_profile_none();
static uint16_t sensor_pid = 0;
static uint8_t jpeg_quality = 0;  // current quality number (0-63, lower = better)

static bool init_camera() {
#if defined(SP_CAM_HAS_WS_EXIO)
    // Waveshare ESP32-S3-CAM: the sensor's SCCB shares the board I²C bus
    // with the I/O expander that holds its PWDN. This opens the bus (I²C
    // port SP_CAM_SCCB_I2C_PORT), the expander powers the sensor, and the
    // camera driver reuses the same bus below instead of opening its own on
    // the same pins. The bus outlives this function (the driver keeps it).
    static sp_cam::IdfI2cBus board_i2c;
    if (!board_i2c.begin(SP_CAM_SCCB_I2C_PORT, SP_CAM_SIOD, SP_CAM_SIOC)) {
        Serial.println("[CAM] board I2C bus unavailable");
        return false;
    }
    if (!sp::WsCamExio(board_i2c).camera_power_on())
        Serial.println("[CAM] I/O expander @0x24 not answering - relying on "
                       "the PWDN pull-down");
    delay(10);  // hardware timing: sensor power-up before the first SCCB access
#endif
    camera_config_t c = {};
    // XCLK on LEDC timer 0 / channel 0, set up by the driver through ESP-IDF
    // — invisible to the Arduino LEDC allocator, so this image never calls
    // ledcAttach / analogWrite (board_profile_esp32cam.h, image_guard.py).
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
#if defined(SP_CAM_SCCB_I2C_PORT)
    c.pin_sccb_sda = -1;  // reuse the bus opened above
    c.pin_sccb_scl = -1;
    c.sccb_i2c_port = SP_CAM_SCCB_I2C_PORT;
#else
    c.pin_sccb_sda = SP_CAM_SIOD;
    c.pin_sccb_scl = SP_CAM_SIOC;
#endif
    c.pin_pwdn = SP_CAM_PWDN;
    c.pin_reset = SP_CAM_RESET;
    c.xclk_freq_hz = SP_CAM_XCLK_HZ;
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
        // How the sensor sits on this board (Freenove S3 only; cam_policy.h).
        const sp_cam::Orientation o = sp_cam::board_orientation(kBoard, sensor_pid);
        if (o.apply) {
            s->set_hmirror(s, o.hmirror);
            s->set_vflip(s, o.vflip);
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
// the driver has been holding since the previous capture. `use_flash` is
// already false on a board without a flash LED (flash_for_capture).
static camera_fb_t* grab_fresh_frame(bool use_flash) {
#if SP_PIN_FLASH >= 0
    if (use_flash) {
        digitalWrite(SP_PIN_FLASH, HIGH);
        delay(kFlashSettleMs);  // hardware timing: AE/AWB settle under the LED
    }
#endif
    for (int i = 0; i < kDiscardFrames; ++i) {
        camera_fb_t* stale = esp_camera_fb_get();
        if (stale != nullptr) esp_camera_fb_return(stale);
    }
    camera_fb_t* fb = esp_camera_fb_get();
#if SP_PIN_FLASH >= 0
    if (use_flash) digitalWrite(SP_PIN_FLASH, LOW);  // after the exposure
#endif
    return fb;
}

static bool capture_and_post(bool want_flash) {
    const bool use_flash = sp_cam::flash_for_capture(want_flash, kHasFlash);
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
    // https URL would otherwise run TLS with setInsecure().
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

    // The upload runs on the cam's own clients, never HTTPClient's built-in
    // ones (an unbounded DNS lookup, a 120 s TLS handshake): the capped
    // lookup (bounded_dns.h), and the connect, handshake and socket-wait
    // bounds of the cam_policy.h budget. Declaration order is lifetime order:
    // the CA string outlives the TLS client (it keeps the pointer), and both
    // clients outlive `http`, whose destructor still touches its client.
    sp_device::BoundedDnsClient plain_client;
    sp_device::BoundedDnsSecureClient tls_client;
    plain_client.setConnectionTimeout(sp_cam::kUploadConnectTimeoutS * 1000UL);
    tls_client.setConnectionTimeout(sp_cam::kUploadConnectTimeoutS * 1000UL);
    tls_client.setHandshakeTimeout(sp_cam::kUploadHandshakeTimeoutS);
    NetworkClient* client = &plain_client;
    if (transport == sp_cam::UploadTransport::TlsPinned) {
        tls_client.setCACert(upload_ca.c_str());
        client = &tls_client;
    }

    HTTPClient http;
    std::string url = server_url + "/api/vision/frame";
    http.setConnectTimeout(sp_cam::kUploadConnectTimeoutS * 1000UL);
    http.setTimeout((uint16_t)(sp_cam::kUploadIoTimeoutS * 1000UL));
    http.setReuse(false);  // one frame per connection: end() closes it
    if (!http.begin(*client, url.c_str())) {
        SP_LOG(LOG_ERROR, "[CAM] bad upload URL %s", url.c_str());
        ++capture_fail;
        esp_camera_fb_return(fb);
        return false;
    }
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

// The camera health document — key set and literals in the shared,
// host-tested builder (wire_contract.h build_camera_health).
static void publish_health() {
    if (!mqtt->connected()) return;
    sp::CameraHealthInputs in;
    in.node_id = cfg.node_id.c_str();
    in.uptime_sec = millis() / 1000;
    in.free_heap = ESP.getFreeHeap();
    in.wifi_rssi = WiFi.RSSI();
    in.capture_success = capture_success;
    in.capture_fail = capture_fail;
    in.avg_latency_ms = avg_latency_ms;
    in.psram_free = ESP.getFreePsram();
    // Which sensor this cam actually has (the BOM 2-pack moved from OV2640
    // to OV3660) and the live JPEG quality (the dropped-frame backoff can
    // raise it).
    in.sensor = sensor.name;
    in.sensor_pid = sensor_pid;
    in.jpeg_quality = jpeg_quality;
    JsonDocument doc;
    sp::build_camera_health(in, doc);
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
    in.emit_tls = true;  // additive: the MQTT transport in use
    in.tls = tls_link.tls();
    in.tls_fallback = tls_link.fallback();
    in.ca_fp = tls_link.ca_fp();  // additive: which CA the TLS link trusts
    in.board = SP_BOARD_NAME;

    JsonDocument doc;
    sp::build_heartbeat(in, doc);
    // Optional, cam-only key on top of the shared contract (the Pi ignores
    // keys it doesn't know): the detected image sensor.
    doc["camera_sensor"] = sensor.name;
    mqtt->publish(mqtt->topic("status/heartbeat").c_str(), doc);
}

// Returns true only when the alert was actually published (the latch counts
// an alert as delivered only then).
static bool emit_alert(const char* type, float value, const char* message) {
    if (!mqtt->connected()) return false;
    JsonDocument doc;
    sp::build_alert(type, value, message, nullptr, doc);
    return mqtt->publish(mqtt->topic("alert").c_str(), doc);
}

// ── OTA image confirmation ──────────────────────────────────────
// Without this hook the Arduino core marks a freshly-OTA'd image valid before
// setup(), so a bad cam OTA crash-looped on the new slot forever
// (sp_device/image_rollback.h).
extern "C" bool verifyRollbackLater() { return true; }

// Operator-requested reboot (portal gesture): confirm a probation image only
// if it reached MQTT this boot, then restart after a short flush delay
// (sp_device/deferred_restart.h).
static void request_restart(const char* why) {
    restart.request(why, image_confirm, mqtt, ota);
}

static void on_command(const char* suffix, const char* raw, size_t raw_len,
                       JsonDocument& doc, void*) {
    // Signature + replay check (with the previous key during a key rotation)
    // and the reserved suffixes (coredump_ack, ota_manifest), shared with the
    // node image (sp_device/command_auth.h) — a coredump ack is never a
    // capture / server_url frame.
    if (sp_device::command_prologue(*mqtt, cfg, kv, cmd_replay_guard, ota,
                                    suffix, raw, raw_len, doc) !=
        sp_device::CmdPrologue::Route)
        return;

    if (doc["capture"].is<bool>() && doc["capture"].as<bool>()) {
        // Recorded only: loop() takes the frame on its next free pass, as
        // it does a scheduled one. Capturing here ran a 10-30 s POST (and
        // with https a TLS handshake) inside PubSubClient's callback, deep
        // on the loop stack and with MQTT unpumped meanwhile.
        capture_requested = true;
        capture_requested_flash =
            doc["flash"].is<bool>() ? doc["flash"].as<bool>() : true;
        SP_LOG(LOG_INFO, "[CMD] On-demand capture requested (flash=%d)",
               (int)capture_requested_flash);
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
            switch (sp_cam::server_url_cmd(lowered, cfg.paired_pi_host,
                                           cfg.broker_host)) {
                case sp_cam::ServerUrlCmd::Set:
                    server_url = lowered;
                    kv.set_string(sp::kServerUrlKey, server_url);
                    SP_LOG(LOG_INFO, "[CMD] server_url set to %s",
                           server_url.c_str());
                    break;
                case sp_cam::ServerUrlCmd::Reset:
                    kv.set_string(sp::kServerUrlKey, "");
                    server_url = sp_cam::default_server_url(cfg.broker_host);
                    SP_LOG(LOG_INFO,
                           "[CMD] server_url cleared - uploads go to the Pi "
                           "address: %s",
                           server_url.c_str());
                    break;
                case sp_cam::ServerUrlCmd::Reject:
                    SP_LOG(LOG_WARN, "[CMD] REJECTED server_url=%s (allowlist)",
                           candidate);
                    break;
            }
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.printf("\n=== SporePrint Cam v2 (%s) ===\n", SP_BOARD_NAME);

#if SP_PIN_FLASH >= 0
    pinMode(SP_PIN_FLASH, OUTPUT);
    digitalWrite(SP_PIN_FLASH, LOW);
#endif
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

    // Provisioning / WiFi — pre-WDT (boot_policy.h), the same
    // step as the node image (WifiProvisioner::bring_up): a working cam
    // never falls into the open setup AP on its own.
    char portal_hint[96];
    snprintf(portal_hint, sizeof(portal_hint),
             "Hold the reset button (GPIO %d) 3-10 s, then release, to open "
             "the setup portal.",
             SP_PIN_FACTORY_RESET);
    provisioner.bring_up(cfg, portal_hint);

    // Stored server_url (MQTT cmd / v1 migration) wins; otherwise the Pi
    // address typed into the portal — the old hardcoded sporeprint.local
    // broke every LAN without mDNS even though MQTT (same host) worked. A
    // portal save with a new Pi address drops a stored URL.
    server_url = sp_cam::resolve_server_url(kv.get_string(sp::kServerUrlKey, ""),
                                            cfg.broker_host);
    Serial.printf("[CAM] Frame upload URL: %s\n", server_url.c_str());

    sp_device::MqttTransport xport = tls_link.select();
    mqtt = new sp_device::MqttLink(*xport.client, cfg.node_id.c_str(), "camera",
                                   SPOREPRINT_FW_VERSION);
    mqtt->on_command(on_command, nullptr);
    // A capture + upload pass holds the loop (no MQTT pumping) for up to the
    // WDT: the broker must not declare the cam dead meanwhile (cam_policy.h).
    mqtt->set_keepalive(sp_cam::kCamMqttKeepaliveS);
    mqtt->begin(cfg.broker_host.c_str(), xport.port,
                cfg.mqtt_user.c_str(), cfg.mqtt_pass.c_str(),
                /*connect_now=*/sp::tls_mode_allows_mqtt(xport.mode));

    sp_device::logfwd::attach(mqtt);
    // Find + hash a panic dump; loop() uploads it and the Pi's ack erases it.
    sp_device::coredump::begin(*mqtt, kv);

    std::string hostname = "sporeprint-" + cfg.node_id;
    ota = new sp_device::OtaService(*mqtt, hostname.c_str(),
                                    cfg.ota_pass.c_str());
    // A push while this image is on probation would overwrite the confirmed
    // image in the other slot: confirm this one first if it reached MQTT,
    // else refuse the push (sp_device/image_rollback.h).
    ota->before_flash(
        [](void*) {
            return sp_device::clear_probation_for_ota(image_confirm, mqtt, ota);
        },
        nullptr);
    ota->configure_manifests(
        sp_device::ota_manifest_build_config(&kv, SPOREPRINT_FW_VERSION));
    ota->begin();

    if (!camera_ok) {
        SP_LOG(LOG_ERROR, "[CAM] camera init FAILED — captures disabled");
        ++capture_fail;
    }
    SP_LOG(LOG_INFO,
           "[BOOT] cam ready: id=%s camera=%d sensor=%s mqtt=%s reset=%d",
           cfg.node_id.c_str(), camera_ok, sensor.name,
           sp::tls_mode_str(xport.mode), (int)esp_reset_reason());
    sp_device::note_probation_at_boot(image_confirm);
    link_wd.begin(millis());

    // Arm last: 90 s — a capture + upload pass is bounded to fit inside it
    // (cam_policy.h kCaptureUploadWorstCaseS).
    const esp_err_t wdt =
        sp_device::arm_loop_task_wdt(sp_cam::kCamLoopWdtTimeoutS);
    if (wdt != ESP_OK)
        SP_LOG(LOG_ERROR, "[BOOT] task WDT arm FAILED (%s) - loop unguarded",
               esp_err_to_name(wdt));
}

void loop() {
    esp_task_wdt_reset();
    uint32_t now = millis();

    // Reset button, read first with this pass's fresh `now`: held > 10 s →
    // factory reset; released after 3-10 s → reboot into the setup portal
    // (the only way a working, provisioned cam opens it). ButtonHold times
    // only densely-sampled stretches — the old timer, stamped before a
    // 10-15 s capture/POST or MQTT connect, could turn a short press into a
    // factory reset — and nothing blocking starts while the button is down.
    const bool reset_down = digitalRead(SP_PIN_FACTORY_RESET) == LOW;
    switch (reset_button.update(now, reset_down)) {
        case sp::ButtonHold::Action::FactoryReset:
            SP_LOG(LOG_ERROR, "[SYSTEM] Factory reset triggered");
            sp_device::confirm_before_deliberate_restart(image_confirm, mqtt,
                                                         ota, "factory reset");
            sp_device::logfwd::flush_now();  // the lines saying why
            sp_device::factory_reset_all();  // restarts
            break;
        case sp::ButtonHold::Action::OpenPortal:
            if (!restart.pending()) {
                provisioner.request_portal_at_next_boot();
                request_restart("setup portal requested (reset held 3-10 s)");
            }
            break;
        default:
            break;
    }

    // Secure MQTT with no verified CA: judge a running trial, or at most one
    // bounded CA fetch / probe per pass; no MQTT connect attempt in such a
    // pass (tls_policy.h).
    const bool tls_blocked = tls_link.loop(now, reset_down, *mqtt);
    const uint32_t attempts_before = mqtt->connect_attempts();
    mqtt->loop(now, sp::mqtt_may_connect(tls_link.mode(), tls_blocked, reset_down));
    // A pass that already blocked on the network (a CA fetch or probe, an
    // MQTT connect attempt) starts no capture: the capture + upload budget
    // (cam_policy.h) assumes the pass to itself.
    const bool pass_blocked =
        tls_blocked || mqtt->connect_attempts() != attempts_before;
    ota->loop();
    sp_device::logfwd::loop(now);
    sp_device::coredump::loop(now, sp_device::coredump_ack_verifiable(cfg));

    // OTA probation: a new image proves itself with 60 s of continuous MQTT.
    // A failed confirm re-arms and is retried; a confirm also raises the
    // anti-rollback floor a manifest-verified push left pending.
    if (image_confirm.update(now, mqtt->connected()))
        sp_device::confirm_running_image(image_confirm, ota,
                                         "60 s of MQTT after boot");

    restart.loop();  // a requested restart, once its flush delay has passed

    // WiFi recovery (offline boot, or a disconnect reason the core's
    // auto-reconnect gives up on): re-begin the STA link every 60 s.
    if (link_wd.update(now, WiFi.status() == WL_CONNECTED, mqtt->connected())
            .wifi_retry) {
        ++wifi_reconnects;
        SP_LOG(LOG_WARN, "[WIFI] link down - re-begin STA (retry %u)",
               (unsigned)wifi_reconnects);
        WiFi.disconnect();
        WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
    }

    if (!reset_down && !restart.pending() && !pass_blocked) {
        if (capture_requested) {
            capture_requested = false;
            SP_LOG(LOG_INFO, "[CAM] On-demand capture (flash=%d)",
                   (int)capture_requested_flash);
            capture_and_post(capture_requested_flash);
        } else if (sp::elapsed_ms(now, last_capture_ms) >= kCaptureIntervalMs) {
            last_capture_ms = now;
            capture_and_post(true);
        }
    }

    // Health + heartbeat every 5 min on their own clock (no coupling to the
    // capture schedule).
    const sp::PublishCadence::Due due = status_cadence.update(now);
    if (due.telemetry) publish_health();
    if (due.heartbeat) publish_heartbeat();

    // Secure MQTT asked for, plaintext in use: entry + hourly,
    // and at once when the reason changes (no CA yet, cert name mismatch,
    // 8883 unreachable, ...), until a fetched CA verifies and is pinned.
    const sp::TlsFailReason tls_down = tls_link.downgrade();
    if (mqtt->connected() && tls_downgrade_alert.due(tls_down, now) &&
        emit_alert(sp::kAlertTlsDowngrade, (float)cfg.broker_port,
                   sp::tls_downgrade_message(tls_down)))
        tls_downgrade_alert.emitted(now);
}
