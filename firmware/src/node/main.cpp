// SporePrint unified node firmware (v2).
//
// One image replaces the v1 climate/relay/lighting trio: the personality
// (provisioned via the captive portal) selects the channel bank, and the
// I²C sensor set is autodetected at boot — plug in whichever supported
// sensors you bought. The MQTT contract is byte-compatible with v1 (the Pi
// server consumes both fleets identically); `type` in heartbeats reports
// the personality so cloud command routing keeps resolving.
//
// Boot order IS the safety design:
//   1. channel pins to safe-state (all off) — before anything can block
//   2. NVS load + v1-namespace migration
//   3. provisioning portal / WiFi connect — NO watchdog armed yet (v1
//      armed a 10 s panic WDT here and bricked first-boot provisioning)
//   4. autodetect, MQTT, services
//   5. enter_steady_state(): the ONLY esp_task_wdt_add site (30 s, panic)
//   6. loop(): single WDT pet at the top; every driver call ≤50 ms

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#include <math.h>
#include <time.h>

#if defined(SP_BOARD_ESP32S3)
#include "board_profile_esp32s3.h"
#else
#include "board_profile_esp32dev.h"
#endif

#include "arduino_hal.h"
#include "autodetect.h"
#include "bh1750.h"
#include "channel_runtime.h"
#include "clamps.h"
#include "cmd_router.h"
#include "coredump_uploader.h"
#include "hmac_verify.h"
#include "hx711.h"
#include "log_forward.h"
#include "mhz19.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "tls_transport.h"
#include "ota_service.h"
#include "personality.h"
#include "reed_switch.h"
#include "scd30.h"
#include "scd4x.h"
#include "scene_table.h"
#include "sha256.h"
#include "sht3x.h"
#include "sht4x.h"
#include "telemetry_buffer.h"
#include "wifi_provisioner.h"
#include "wrap_time.h"

#ifndef SPOREPRINT_FW_VERSION
#define SPOREPRINT_FW_VERSION "dev"
#endif

// ── globals (composition root owns lifetimes) ───────────────────

static const int kChannelPins[SP_CHANNEL_COUNT] = SP_CHANNEL_PINS;

static sp_device::NvsKvStore kv;
static sp_device::NodeConfig cfg;
static sp_device::WifiProvisioner provisioner(kv);
static WiFiClient wifi_client;
static WiFiClientSecure wifi_client_secure;
static sp_device::MqttLink* mqtt = nullptr;
static sp_device::OtaService* ota = nullptr;

static sp_device::ArduinoI2cBus i2c_bus(Wire);
static sp_device::ArduinoClock sys_clock;

static sp::DetectedSensors detected;
static sp::Sht3x* sht3x = nullptr;
static sp::Sht4x* sht4x = nullptr;
static sp::Scd4x* scd4x = nullptr;
static sp::Scd30* scd30 = nullptr;
static sp::Bh1750* bh1750 = nullptr;
static sp::Mhz19* mhz19 = nullptr;
static sp_device::ArduinoUart* co2_uart = nullptr;
static sp::Hx711* hx711 = nullptr;
static sp_device::ArduinoPin hx_dout(SP_PIN_HX711_DOUT);
static sp_device::ArduinoPin hx_sck(SP_PIN_HX711_SCK);
static sp::ReedSwitch* reed = nullptr;
static sp_device::ArduinoPin reed_pin(SP_PIN_REED);

static sp::Channel channels[SP_CHANNEL_COUNT];
static int channel_count = 0;
static sp::CmdRouter router;
static sp::TelemetryBuffer offline_buffer;  // 16 KB byte cap

// Latest readings.
static float temp_c = NAN, rh = NAN, lux = NAN;
static uint16_t co2_ppm = 0;
static bool have_temp_rh = false, have_co2 = false, have_lux = false;
static int32_t hx711_raw = 0;
static bool have_hx711 = false;

// Cadence (operator-tunable via cmd/config, clamped).
static uint32_t read_interval_ms = 30000;
static uint32_t publish_interval_ms = 60000;
static uint32_t last_read_ms = 0;
static uint32_t last_publish_ms = 0;
static uint32_t last_switch_report_ms = 0;
static uint32_t factory_hold_start_ms = 0;

// ── helpers ─────────────────────────────────────────────────────

static float c_to_f(float c) { return c * 9.0f / 5.0f + 32.0f; }

static float dew_point_c(float t_c, float rh_pct) {
    // Magnus formula — same constants as v1 so dashboards don't shift.
    const float a = 17.27f, b = 237.7f;
    float alpha = (a * t_c) / (b + t_c) + logf(rh_pct / 100.0f);
    return (b * alpha) / (a - alpha);
}

static void write_channel_duty(int idx) {
    ledcWrite(idx, channels[idx].duty10());
}

static void report_switch_channel(int idx, const char* trigger) {
    JsonDocument doc;
    doc["channel"] = channels[idx].config().name;
    doc["state"] = channels[idx].is_on() ? "on" : "off";
    doc["pwm"] = channels[idx].pwm8();
    doc["trigger"] = trigger;
    std::string t = mqtt->topic("telemetry/");
    t += channels[idx].config().name;
    mqtt->publish(t.c_str(), doc);
}

static void report_dim_levels() {
    JsonDocument doc;
    for (int i = 0; i < channel_count; ++i) {
        doc[channels[i].config().name] = channels[i].level10();
    }
    mqtt->publish(mqtt->topic("telemetry").c_str(), doc);
}

static void emit_alert(const char* type, float value, const char* message,
                       const char* sensor = nullptr) {
    if (!mqtt->connected()) return;
    JsonDocument doc;
    doc["type"] = type;
    doc["value"] = value;
    doc["message"] = message;
    if (sensor != nullptr) doc["sensor"] = sensor;
    mqtt->publish(mqtt->topic("alert").c_str(), doc);
}

// ── command handling ────────────────────────────────────────────

// Clock-gated HMAC policy: with a provisioned key, frames verify strictly
// (and only once NTP has a sane epoch). With NO key, accept + warn every
// time — the v1 migration posture, except v2 can actually provision the
// key (portal field), and an empty key really is empty (the build-flag
// stringify corruption that silently armed garbage keys is gone).
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
    // Verification runs on the exact wire bytes MqttLink hands through —
    // never on a re-serialized document (number/string lexeme fidelity is
    // what makes the canonicalizer byte-exact against Python).
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

static void handle_config_cmd(JsonDocument& doc) {
    if (doc["read_interval_ms"].is<uint32_t>()) {
        sp::ClampResult r =
            sp::clamp_read_interval_ms(doc["read_interval_ms"].as<uint32_t>());
        read_interval_ms = r.value;
        SP_LOG(LOG_INFO, "[CMD] read_interval_ms=%u%s", (unsigned)r.value,
               r.clamped ? " (clamped)" : "");
    }
    if (doc["publish_interval_ms"].is<uint32_t>()) {
        sp::ClampResult r = sp::clamp_publish_interval_ms(
            doc["publish_interval_ms"].as<uint32_t>());
        publish_interval_ms = r.value;
        SP_LOG(LOG_INFO, "[CMD] publish_interval_ms=%u%s", (unsigned)r.value,
               r.clamped ? " (clamped)" : "");
    }
    if (!doc["calibrate_co2"].isNull()) {
        if (doc["calibrate_co2"].is<bool>()) {
            // v1 semantics (true = enable ASC) were wrong for chambers —
            // refuse loudly instead of quietly doing the wrong thing.
            SP_LOG(LOG_WARN,
                   "[CMD] calibrate_co2:true is deprecated — send a target "
                   "ppm (e.g. {\"calibrate_co2\": 420}) with the chamber "
                   "open to fresh air");
        } else if (doc["calibrate_co2"].is<uint16_t>()) {
            // Dispatch to whichever CO₂ sensor this node actually has —
            // the SCD4x-only gate silently dropped the command on SCD30
            // and MH-Z19C nodes.
            uint16_t ppm = doc["calibrate_co2"].as<uint16_t>();
            if (scd4x != nullptr) {
                SP_LOG(LOG_INFO, "[CMD] SCD4x forced recalibration to %u ppm",
                       ppm);
                bool ok = scd4x->recalibrate(ppm);
                SP_LOG(ok ? LOG_INFO : LOG_ERROR, "[CMD] FRC %s",
                       ok ? "applied" : "FAILED (sensor needs >3 min runtime)");
            } else if (scd30 != nullptr) {
                SP_LOG(LOG_INFO, "[CMD] SCD30 forced recalibration to %u ppm",
                       ppm);
                bool ok = scd30->recalibrate(ppm);
                SP_LOG(ok ? LOG_INFO : LOG_ERROR, "[CMD] FRC %s",
                       ok ? "applied" : "FAILED (bus write rejected)");
            } else if (mhz19 != nullptr) {
                // Winsen has no calibrate-to-target: zero-point cal latches
                // the CURRENT reading as the 400 ppm baseline, so the ppm
                // argument is ignored — open the chamber to fresh air first.
                SP_LOG(LOG_INFO,
                       "[CMD] MH-Z19C zero-point calibration (targets 400 ppm "
                       "fresh air; %u ppm arg ignored)",
                       ppm);
                mhz19->calibrate_zero();
            } else {
                SP_LOG(LOG_WARN, "[CMD] calibrate_co2: no CO2 sensor present");
            }
        }
    }
    if (doc["tare"].is<bool>() && doc["tare"].as<bool>()) {
        if (hx711 != nullptr && have_hx711) {
            cfg.hx711_tare = hx711_raw;
            cfg.save(kv);
            SP_LOG(LOG_INFO, "[CMD] scale tared at %d counts",
                   (int)cfg.hx711_tare);
        } else {
            SP_LOG(LOG_WARN, "[CMD] tare: no HX711 sample yet%s",
                   hx711 == nullptr ? " (hx711 not enabled)" : "");
        }
    }
    if (doc["calibrate_scale"].is<float>()) {
        float known_g = doc["calibrate_scale"].as<float>();
        if (hx711 == nullptr || !have_hx711) {
            SP_LOG(LOG_WARN, "[CMD] calibrate_scale: no HX711 sample yet%s",
                   hx711 == nullptr ? " (hx711 not enabled)" : "");
        } else if (!(known_g > 0.0f)) {
            SP_LOG(LOG_WARN, "[CMD] calibrate_scale: known mass must be > 0 g");
        } else {
            float scale = (float)(hx711_raw - cfg.hx711_tare) / known_g;
            // Reject nonsense before persisting: a zero/negative delta means
            // the mass isn't on the platter (or the cell is wired backwards).
            if (!isfinite(scale) || scale <= 0.0f) {
                SP_LOG(LOG_WARN,
                       "[CMD] calibrate_scale: implausible %.3f counts/g — "
                       "tare empty, then place the known mass",
                       (double)scale);
            } else {
                cfg.hx711_scale = scale;
                cfg.save(kv);
                SP_LOG(LOG_INFO,
                       "[CMD] scale calibrated: %.3f counts/g (%.1f g at %d "
                       "counts, tare %d)",
                       (double)scale, (double)known_g, (int)hx711_raw,
                       (int)cfg.hx711_tare);
            }
        }
    }
}

static void handle_scene_cmd(JsonDocument& doc) {
    const char* name = doc["scene"].as<const char*>();
    const sp::Scene* scene = sp::find_scene(name);
    if (scene == nullptr) {
        SP_LOG(LOG_WARN, "[LIGHT] Unknown scene: %s", name ? name : "(null)");
        return;
    }
    SP_LOG(LOG_INFO, "[LIGHT] Applying scene: %s", name);
    uint32_t now = millis();
    for (int i = 0; i < channel_count && i < sp::kSceneChannels; ++i) {
        sp::ChannelCommand cmd;
        cmd.has_level = true;
        cmd.level = scene->levels[i];
        if (scene->levels[i] == 0) {
            cmd.has_state = true;
            cmd.state_on = false;
        }
        channels[i].apply(cmd, now);
        write_channel_duty(i);
    }
    report_dim_levels();
}

static void handle_channel_cmd(int idx, JsonDocument& doc) {
    sp::ChannelCommand cmd;
    if (doc["state"].is<const char*>()) {
        cmd.has_state = true;
        String s = doc["state"].as<const char*>();
        s.toLowerCase();
        cmd.state_on = (s == "on");
    }
    if (doc["pwm"].is<int>()) {
        cmd.has_pwm = true;
        cmd.pwm = doc["pwm"].as<int>();
    }
    if (doc["level"].is<int>()) {
        cmd.has_level = true;
        cmd.level = doc["level"].as<int>();
    }
    if (doc["duration_sec"].is<int>()) {
        cmd.has_duration = true;
        cmd.duration_sec = doc["duration_sec"].as<int>();
    }
    if (doc["ramp_sec"].is<int>()) {
        cmd.has_ramp = true;
        cmd.ramp_sec = doc["ramp_sec"].as<int>();
    }

    uint32_t now = millis();
    sp::ChannelEvent ev = channels[idx].apply(cmd, now);
    if (ev == sp::ChannelEvent::Rejected) {
        SP_LOG(LOG_WARN, "[CH] %s: %s", channels[idx].config().name,
               channels[idx].reason());
        return;
    }
    write_channel_duty(idx);
    SP_LOG(LOG_INFO, "[CH] %s: %s pwm=%u level=%u",
           channels[idx].config().name, channels[idx].is_on() ? "ON" : "OFF",
           channels[idx].pwm8(), channels[idx].level10());
    if (channels[idx].config().mode == sp::ChannelMode::Switch) {
        report_switch_channel(idx, "command");
    } else {
        report_dim_levels();
    }
}

static void on_command(const char* suffix, const char* raw, size_t raw_len,
                       JsonDocument& doc, void*) {
    if (!verify_command(raw, raw_len, suffix)) return;
    sp::CmdRoute route = router.route(suffix);
    switch (route.target) {
        case sp::CmdTarget::Config:
            handle_config_cmd(doc);
            break;
        case sp::CmdTarget::Scene:
            handle_scene_cmd(doc);
            break;
        case sp::CmdTarget::Channel:
            handle_channel_cmd(route.channel_index, doc);
            break;
        case sp::CmdTarget::None:
            SP_LOG(LOG_WARN, "[CMD] Unknown command endpoint: cmd/%s", suffix);
            break;
    }
}

// ── sensing + reporting ─────────────────────────────────────────

static void read_sensors() {
    uint32_t t0 = millis();
    have_temp_rh = false;
    if (sht3x != nullptr) {
        have_temp_rh = sht3x->measure(&temp_c, &rh);
        if (!have_temp_rh)
            SP_LOG(LOG_WARN, "[SENSOR] SHT3x read error");
    } else if (sht4x != nullptr) {
        have_temp_rh = sht4x->measure(&temp_c, &rh);
        if (!have_temp_rh)
            SP_LOG(LOG_WARN, "[SENSOR] SHT4x read error");
    }

    if (scd4x != nullptr && scd4x->data_ready()) {
        uint16_t ppm;
        float t, h;
        if (scd4x->read(&ppm, &t, &h)) {
            co2_ppm = ppm;
            have_co2 = true;
            if (!have_temp_rh) {  // coarse fallback, same as v1
                temp_c = t;
                rh = h;
                have_temp_rh = true;
            }
        }
    } else if (scd30 != nullptr && scd30->data_ready()) {
        float ppm, t, h;
        if (scd30->read(&ppm, &t, &h)) {
            co2_ppm = (uint16_t)ppm;
            have_co2 = true;
            if (!have_temp_rh) {
                temp_c = t;
                rh = h;
                have_temp_rh = true;
            }
        }
    }

    if (bh1750 != nullptr) {
        float l;
        if (bh1750->read(&l)) {
            lux = l;
            have_lux = true;
        }
    }

    if (mhz19 != nullptr && !mhz19->awaiting_reply()) {
        mhz19->request_read();  // completion handled in loop()
    }

    if (hx711 != nullptr && hx711->is_ready()) {
        noInterrupts();  // PD_SCK high >60 µs power-cycles the chip
        hx711_raw = hx711->read_raw();
        interrupts();
        have_hx711 = true;
    }

    uint32_t took = millis() - t0;
    if (took > 50) {
        SP_LOG(LOG_WARN, "[SENSOR] read pass took %u ms (budget 50)",
               (unsigned)took);
    }
}

static void check_alerts() {
    if (!mqtt->connected()) return;
    if (have_temp_rh) {
        float temp_f = c_to_f(temp_c);
        if (temp_f > 90.0f || temp_f < 40.0f) {
            emit_alert("temperature", temp_f,
                       temp_f > 90.0f ? "Temperature critically high!"
                                      : "Temperature critically low!");
        }
        if (rh > 99.0f || rh < 30.0f) {
            emit_alert("humidity", rh,
                       rh > 99.0f ? "Humidity saturated!"
                                  : "Humidity critically low!");
        }
    } else if (sht3x != nullptr || sht4x != nullptr) {
        emit_alert("sensor_failure", 0.0f, "Temp/RH sensor read failed",
                   sht3x ? "SHT3x" : "SHT4x");
    }
    if (have_co2 && co2_ppm > 4000) {
        emit_alert("co2", (float)co2_ppm, "CO2 dangerously high!");
    }
}

static void publish_telemetry() {
    JsonDocument doc;
    doc["ts"] = millis() / 1000;  // uptime — the server stamps real time
    if (have_temp_rh) {
        float tf = c_to_f(temp_c);
        doc["temp_f"] = roundf(tf * 10.0f) / 10.0f;
        doc["temp_c"] = roundf(temp_c * 10.0f) / 10.0f;
        doc["humidity"] = roundf(rh * 10.0f) / 10.0f;
        doc["dew_point_f"] = roundf(c_to_f(dew_point_c(temp_c, rh)) * 10.0f) / 10.0f;
    }
    if (have_co2) doc["co2_ppm"] = co2_ppm;
    if (have_lux) doc["lux"] = roundf(lux * 10.0f) / 10.0f;
    if (have_hx711) {
        float grams;
        if (sp::Hx711::to_grams(hx711_raw, cfg.hx711_tare, cfg.hx711_scale,
                                &grams)) {
            doc["weight_g"] = roundf(grams * 10.0f) / 10.0f;
        } else {
            // Uncalibrated (scale == 0) — publish raw counts so the
            // operator can watch the tare/calibrate flow move the needle.
            doc["scale_raw"] = hx711_raw;  // tolerated-not-stored
        }
    }
    if (reed != nullptr) doc["door_open"] = !reed->is_closed();

    std::string topic = mqtt->topic("telemetry");
    if (mqtt->connected()) {
        mqtt->publish(topic.c_str(), doc);
        offline_buffer.flush([](const char* t, const char* p) {
            return mqtt->publish_raw(t, p);
        });
    } else {
        char buf[384];
        serializeJson(doc, buf, sizeof(buf));
        offline_buffer.buffer(topic.c_str(), buf);
    }
}

static void publish_heartbeat() {
    JsonDocument doc;
    doc["uptime_sec"] = millis() / 1000;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["firmware_version"] = SPOREPRINT_FW_VERSION;
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["ip"] = WiFi.localIP().toString();
    doc["reset_reason"] = (int)esp_reset_reason();
    doc["wifi_reconnects"] = 0;  // core auto-reconnect owns WiFi recovery
    doc["mqtt_reconnects"] = mqtt->reconnect_count();
    // v2 additive fields — the Pi upsert + cloud routing consume `type`;
    // `roles` carries the full capability set for the patched resolver.
    doc["type"] = sp::node_type_str(cfg.personality);
    JsonArray roles = doc["roles"].to<JsonArray>();
    if (sht3x || sht4x || scd4x || scd30 || bh1750 || mhz19)
        roles.add("climate");
    if (cfg.personality == sp::Personality::RelayBank) roles.add("relay");
    if (cfg.personality == sp::Personality::LightingBank) roles.add("lighting");
    doc["fw_image"] = "node";
    if (!cfg.migrated_from.empty())
        doc["migrated_from"] = cfg.migrated_from.c_str();
    mqtt->publish(mqtt->topic("status/heartbeat").c_str(), doc);
}

static void publish_health() {
    JsonDocument doc;
    doc["node_id"] = cfg.node_id.c_str();
    doc["type"] = sp::node_type_str(cfg.personality);
    doc["uptime_sec"] = millis() / 1000;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["wifi_rssi"] = WiFi.RSSI();

    JsonObject sensors = doc["sensors"].to<JsonObject>();
    auto add_sensor = [&](const char* name, const sp::DriverHealth& h) {
        JsonObject o = sensors[name].to<JsonObject>();
        o["ok"] = h.last_error == nullptr;
        o["reads"] = h.reads;
        o["fails"] = h.fails;
        o["last_error"] = h.last_error;
    };
    if (sht3x) add_sensor("sht3x", sht3x->health());
    if (sht4x) add_sensor("sht4x", sht4x->health());
    if (scd4x) add_sensor("scd4x", scd4x->health());
    if (scd30) add_sensor("scd30", scd30->health());
    if (bh1750) add_sensor("bh1750", bh1750->health());
    if (mhz19) add_sensor("mhz19", mhz19->health());
    if (hx711) add_sensor("hx711", hx711->health());
    if (reed) add_sensor("reed", reed->health());

    if (channel_count > 0) {
        JsonObject chans = doc["channels"].to<JsonObject>();
        uint32_t now = millis();
        for (int i = 0; i < channel_count; ++i) {
            const sp::Channel& ch = channels[i];
            JsonObject o = chans[ch.config().name].to<JsonObject>();
            o["state"] = ch.is_on();
            o["pwm"] = ch.config().mode == sp::ChannelMode::Switch
                           ? (uint16_t)ch.pwm8()
                           : ch.level10();
            o["on_time_sec"] = ch.on_time_sec_live(now);
            o["cycle_count"] = ch.health().cycle_count;
            o["safety_cutoffs"] = ch.health().safety_cutoffs;
        }
    }

    // Declared-but-missing sensors are an alert, not silence.
    JsonArray missing = doc["expected_missing"].to<JsonArray>();
    bool expects_climate = true;  // every personality benefits from sensors
    if (expects_climate && !sht3x && !sht4x) missing.add("temp_rh");
    if (cfg.mhz19_enabled && mhz19 == nullptr) missing.add("mhz19");
    if (cfg.hx711_enabled && hx711 == nullptr) missing.add("hx711");
    if (cfg.reed_enabled && reed == nullptr) missing.add("reed");

    mqtt->publish(mqtt->topic("health").c_str(), doc);
}

// ── boot ────────────────────────────────────────────────────────

static void enter_steady_state() {
    // The ONLY esp_task_wdt_add site in the image. Everything before this
    // point is protected by explicit deadlines, not the WDT.
    esp_task_wdt_init(30, true);
    esp_task_wdt_add(NULL);
    SP_LOG(LOG_INFO, "[BOOT] steady state — WDT armed (30 s)");
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.printf("\n=== SporePrint Node v2 (%s) ===\n", SP_BOARD_NAME);

    // 1. Safe-state FIRST: all channel outputs off before anything blocks.
    for (int i = 0; i < SP_CHANNEL_COUNT; ++i) {
        ledcSetup(i, SP_LEDC_FREQ_HZ, SP_LEDC_RES_BITS);
        ledcAttachPin(kChannelPins[i], i);
        ledcWrite(i, 0);
    }
    pinMode(SP_PIN_FACTORY_RESET, INPUT_PULLUP);

    // 2. Config + v1 migration.
    std::string migrated = sp_device::migrate_legacy(kv);
    cfg = sp_device::NodeConfig::load(kv);
    if (!migrated.empty())
        Serial.printf("[CONFIG] Migrated v1 namespace '%s'\n", migrated.c_str());

    // 3. Provisioning / WiFi — pre-WDT, deadline-bounded.
    if (!cfg.provisioned()) {
        provisioner.run_portal(cfg);  // never returns
    }
    if (!provisioner.connect(cfg)) {
        // Stored creds failed — give the operator the portal (10-min
        // ceiling inside), which reboots back into another attempt.
        provisioner.run_portal(cfg);  // never returns
    }
    provisioner.start_ntp(cfg);

    // 4. Channel bank from personality.
    sp::ChannelConfig channel_cfgs[4];
    channel_count = sp::personality_channels(cfg.personality, channel_cfgs);
    router.reset();
    router.enable_scene(cfg.personality == sp::Personality::LightingBank);
    for (int i = 0; i < channel_count; ++i) {
        channels[i].configure(channel_cfgs[i]);
        router.add_channel(channels[i].config().name, i);
    }

    // 5. Sensors.
    Wire.begin(SP_PIN_I2C_SDA, SP_PIN_I2C_SCL);
    detected = sp::autodetect_i2c(i2c_bus, sys_clock);
    Serial.printf("[SENSOR] autodetect: temp_rh=%s@0x%02x co2=%s bh1750=%d\n",
                  sp::temp_rh_kind_str(detected.temp_rh), detected.temp_rh_addr,
                  sp::co2_kind_str(detected.co2), detected.bh1750);
    if (detected.temp_rh == sp::TempRhKind::Sht3x)
        sht3x = new sp::Sht3x(i2c_bus, sys_clock, detected.temp_rh_addr);
    if (detected.temp_rh == sp::TempRhKind::Sht4x)
        sht4x = new sp::Sht4x(i2c_bus, sys_clock, detected.temp_rh_addr);
    if (detected.co2 == sp::Co2Kind::Scd4x) {
        scd4x = new sp::Scd4x(i2c_bus, sys_clock);
        scd4x->begin();  // ASC off + periodic start
    }
    if (detected.co2 == sp::Co2Kind::Scd30) {
        scd30 = new sp::Scd30(i2c_bus, sys_clock);
        scd30->begin();
    }
    if (detected.bh1750) {
        bh1750 = new sp::Bh1750(i2c_bus, detected.bh1750_addr);
        bh1750->begin();
    }
    if (cfg.mhz19_enabled) {
        co2_uart = new sp_device::ArduinoUart(Serial2);
        Serial2.begin(9600, SERIAL_8N1, SP_UART_CO2_RX, SP_UART_CO2_TX);
        mhz19 = new sp::Mhz19(*co2_uart, sys_clock);
        mhz19->begin(false);  // ABC off — chamber air is never 400 ppm
    }
    if (cfg.hx711_enabled) {
        hx711 = new sp::Hx711(hx_dout, hx_sck, sp_device::hx711_delay_us);
        hx711->begin();
    }
    if (cfg.reed_enabled) {
        reed = new sp::ReedSwitch(reed_pin);
        reed->begin(millis());
    }

    // 6. MQTT + services.
    sp_device::MqttTransport xport =
        sp_device::select_mqtt_transport(cfg, kv, wifi_client,
                                         wifi_client_secure);
    mqtt = new sp_device::MqttLink(*xport.client, cfg.node_id.c_str(),
                                   sp::node_type_str(cfg.personality),
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

    SP_LOG(LOG_INFO, "[BOOT] node ready: id=%s type=%s channels=%d reset=%d",
           cfg.node_id.c_str(), sp::node_type_str(cfg.personality),
           channel_count, (int)esp_reset_reason());

    // 7. Arm the watchdog LAST.
    enter_steady_state();
}

// ── loop ────────────────────────────────────────────────────────

void loop() {
    esp_task_wdt_reset();  // the single pet site
    uint32_t now = millis();

    mqtt->loop(now);
    ota->loop();
    sp_device::logfwd::loop(now);

    // Channel safety ticks (duration / max-on / ramps).
    for (int i = 0; i < channel_count; ++i) {
        if (channels[i].tick(now) == sp::ChannelEvent::Changed) {
            write_channel_duty(i);
            if (channels[i].config().mode == sp::ChannelMode::Switch) {
                report_switch_channel(i, channels[i].last_change_was_cutoff()
                                             ? "safety_cutoff"
                                             : "report");
                if (channels[i].last_change_was_cutoff())
                    SP_LOG(LOG_ERROR, "[SAFETY] %s %s",
                           channels[i].config().name, channels[i].reason());
            } else {
                report_dim_levels();
            }
        }
    }

    // MH-Z19C reply pump.
    if (mhz19 != nullptr) {
        uint16_t ppm;
        if (mhz19->update(now, &ppm)) {
            co2_ppm = ppm;
            have_co2 = true;
        }
    }

    // Reed edges.
    if (reed != nullptr) {
        sp::ReedSwitch::Event ev = reed->update(now);
        if (ev == sp::ReedSwitch::Event::Opened)
            emit_alert("door", 1.0f, "Chamber door opened", "reed");
        else if (ev == sp::ReedSwitch::Event::Closed)
            emit_alert("door", 0.0f, "Chamber door closed", "reed");
    }

    // Cadenced work.
    if (sp::elapsed_ms(now, last_read_ms) >= read_interval_ms) {
        last_read_ms = now;
        read_sensors();
        check_alerts();
    }
    if (sp::elapsed_ms(now, last_publish_ms) >= publish_interval_ms) {
        last_publish_ms = now;
        publish_telemetry();
        publish_heartbeat();
        publish_health();
    }
    // Switch banks also report state every 60 s (v1 contract).
    if (channel_count > 0 &&
        channels[0].config().mode == sp::ChannelMode::Switch &&
        sp::elapsed_ms(now, last_switch_report_ms) >= 60000) {
        last_switch_report_ms = now;
        for (int i = 0; i < channel_count; ++i)
            report_switch_channel(i, "report");
    }

    // Factory reset (hold 10 s).
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
