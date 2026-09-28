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
//   1. channel pins to safe-state (all off) — the very first thing setup()
//      does, before Serial / any delay / anything that can block
//   2. NVS load + v1-namespace migration
//   3. provisioning portal / WiFi connect — NO watchdog armed yet (v1
//      armed a 10 s panic WDT here and bricked first-boot provisioning).
//      The open setup AP only comes up for an unprovisioned node, on
//      operator request (BOOT held 3-10 s), or when freshly-typed
//      credentials fail; a node whose WiFi has worked before boots offline
//      instead and keeps retrying (boot_policy.h)
//   4. autodetect, MQTT, services
//   5. enter_steady_state(): the ONLY esp_task_wdt_add site (30 s, panic)
//   6. loop(): single WDT pet at the top; every driver call ≤50 ms; one
//      MQTT connect attempt fits the WDT (link_budget.h)
//
// Runtime failsafes (host-tested policy in sp_core):
//   * link watchdog — MQTT down 10 min → every channel off (safe mode);
//     WiFi down → STA re-begin every 60 s (link_watchdog.h)
//   * OTA probation — a new image is confirmed only after 60 s of MQTT;
//     a crash / WDT / power loss before that boots the previous image, and
//     so does an operator restart before the image ever reached MQTT
//     (boot_policy.h ImageConfirm + verifyRollbackLater below)
//   * OTA start → every channel off before the synchronous flash
//   * a sensor with no fresh sample inside the staleness window stops being
//     published and raises one sensor_failure alert (freshness.h)
//   * alerts fire on entry + hourly reminders, with hysteresis
//     (alert_latch.h)
//   * status heartbeat on its own clock, min(publish_interval, 5 min), so
//     a long telemetry interval never trips the Pi's 900 s offline sweep
//     (publish_cadence.h)
//   * Secure MQTT with no pinned Pi CA never downgrades silently: loud
//     fallback + CA-fetch retries, or fail closed with "Require TLS"
//     (tls_policy.h)

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#if defined(SP_BOARD_ESP32S3)
#include "board_profile_esp32s3.h"
#else
#include "board_profile_esp32dev.h"
#endif

#include "alert_latch.h"
#include "arduino_hal.h"
#include "autodetect.h"
#include "bh1750.h"
#include "boot_policy.h"
#include "channel_runtime.h"
#include "clamps.h"
#include "cmd_router.h"
#include "coredump_uploader.h"
#include "freshness.h"
#include "hmac_verify.h"
#include "hx711.h"
#include "image_rollback.h"
#include "link_budget.h"
#include "link_watchdog.h"
#include "log_forward.h"
#include "mhz19.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "tls_transport.h"
#include "ota_service.h"
#include "personality.h"
#include "provisioning.h"
#include "publish_cadence.h"
#include "reed_switch.h"
#include "scale_calibrator.h"
#include "scd30.h"
#include "scd4x.h"
#include "scene_table.h"
#include "sha256.h"
#include "sht3x.h"
#include "sht4x.h"
#include "telemetry_buffer.h"
#include "tls_policy.h"
#include "wifi_provisioner.h"
#include "wire_contract.h"
#include "wrap_time.h"

#ifndef SPOREPRINT_FW_VERSION
#define SPOREPRINT_FW_VERSION "dev"
#endif

// ── globals (composition root owns lifetimes) ───────────────────

static const int kChannelPins[SP_CHANNEL_COUNT] = SP_CHANNEL_PINS;

static sp_device::NvsKvStore kv;
static sp_device::NodeConfig cfg;
// The node image offers the Tier-3 peripheral checkboxes (MH-Z19C, HX711,
// reed) — the only builds that construct those drivers.
static sp_device::WifiProvisioner provisioner(kv, /*peripheral_opts=*/true);
static WiFiClient wifi_client;
static WiFiClientSecure wifi_client_secure;
// Transport selection + runtime CA-fetch retry (fw-node#2).
static sp_device::TlsSupervisor tls_link(cfg, kv, wifi_client,
                                         wifi_client_secure);
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

// Per-source reading freshness: a sensor that stops delivering (loose
// cable, dead part, unwired Tier-3 peripheral) must stop being published as
// if it were fresh — a frozen CO2 value silences the Pi's FAE / emergency
// exhaust rules.
static sp::ReadingFreshness scd_fresh;  // SCD4x / SCD30
static sp::ReadingFreshness mhz_fresh;  // MH-Z19C (armed after warm-up)
static sp::ReadingFreshness lux_fresh;
static sp::ReadingFreshness hx_fresh;
static bool mhz_warm = false;
static uint32_t boot_ms = 0;
// The MH-Z19C answers unreliably during its preheat; don't call it missing
// before this much uptime.
static constexpr uint32_t kMhz19WarmupMs = 3UL * 60UL * 1000UL;

// Alert latches: entry + hourly reminder, with hysteresis — not one alert
// per read pass (2,880/day per condition at the 30 s default).
static sp::ThresholdAlert temp_hi_alert(sp::ThresholdAlert::Dir::Above, 90.0f, 1.0f);
static sp::ThresholdAlert temp_lo_alert(sp::ThresholdAlert::Dir::Below, 40.0f, 1.0f);
static sp::ThresholdAlert rh_hi_alert(sp::ThresholdAlert::Dir::Above, 99.0f, 2.0f);
static sp::ThresholdAlert rh_lo_alert(sp::ThresholdAlert::Dir::Below, 30.0f, 2.0f);
static sp::ThresholdAlert co2_hi_alert(sp::ThresholdAlert::Dir::Above, 4000.0f, 200.0f);
static sp::AlertLatch temp_rh_fail_alert;
static sp::AlertLatch scd_stale_alert, mhz_stale_alert, lux_stale_alert,
    hx_stale_alert;
static sp::AlertLatch tls_downgrade_alert;  // Secure MQTT on plaintext fallback

// HX711 tare / calibrate: averaged fresh samples, never the cached one.
static sp::ScaleCalibrator scale_cal;

// MQTT/WiFi-loss failsafe.
static sp::LinkWatchdog link_wd;
static uint32_t wifi_reconnects = 0;
static uint32_t safe_mode_cut_mask = 0;  // channels safe mode turned off

// Cadence (operator-tunable via cmd/config, clamped). Telemetry + health
// follow publish_interval_ms; the heartbeat keeps its own <= 5 min clock.
static uint32_t read_interval_ms = 30000;
static sp::PublishCadence cadence(60000);  // publish_interval_ms
static uint32_t last_read_ms = 0;
static uint32_t last_switch_report_ms = 0;

// BOOT button: 3-10 s hold + release → setup portal, >10 s → factory reset.
static sp::ButtonHold boot_button;

// Signed commands: each accepted (topic, MAC) once per replay window.
static sp::ReplayGuard cmd_replay_guard;

// OTA probation (fw-node#12) + deliberate, deferred restarts.
static sp::ImageConfirm image_confirm;
static bool restart_pending = false;
static uint32_t restart_requested_ms = 0;
static constexpr uint32_t kRestartDelayMs = 1500;  // let logs/MQTT flush

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
    sp::build_switch_report(channels[idx].config().name, channels[idx].is_on(),
                            channels[idx].pwm8(), trigger, doc);
    std::string t = mqtt->topic("telemetry/");
    t += channels[idx].config().name;
    mqtt->publish(t.c_str(), doc);
}

static void report_dim_levels() {
    JsonDocument doc;
    sp::DimLevel levels[SP_CHANNEL_COUNT];
    for (int i = 0; i < channel_count; ++i) {
        levels[i].name = channels[i].config().name;
        levels[i].level = channels[i].level10();
    }
    sp::build_dim_levels(levels, channel_count, doc);
    mqtt->publish(mqtt->topic("telemetry").c_str(), doc);
}

// Returns true only when the alert was actually published — alert latches
// count an alert as delivered only then.
static bool emit_alert(const char* type, float value, const char* message,
                       const char* sensor = nullptr) {
    if (!mqtt->connected()) return false;
    JsonDocument doc;
    sp::build_alert(type, value, message, sensor, doc);
    return mqtt->publish(mqtt->topic("alert").c_str(), doc);
}

// Firmware-imposed all-off (link-loss safe mode, OTA start). Returns a
// bitmask of the channels that were on. With `report`, publishes the new
// states right away (switch banks as safety_cutoff, dim banks as levels).
static uint32_t force_all_off(const char* reason, bool report) {
    uint32_t now = millis();
    uint32_t cut = 0;
    for (int i = 0; i < channel_count; ++i) {
        if (channels[i].force_off(now, reason) != sp::ChannelEvent::Changed)
            continue;
        write_channel_duty(i);
        cut |= (1u << i);
        SP_LOG(LOG_ERROR, "[SAFETY] %s forced off: %s",
               channels[i].config().name, reason);
        if (report && channels[i].config().mode == sp::ChannelMode::Switch)
            report_switch_channel(i, "safety_cutoff");
    }
    if (report && cut != 0 && channel_count > 0 &&
        channels[0].config().mode == sp::ChannelMode::Dim)
        report_dim_levels();
    return cut;
}

// ── OTA image confirmation ──────────────────────────────────────
//
// The prebuilt SDK has CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE, but the
// Arduino core marks a freshly-OTA'd image valid in initArduino() — before
// setup() — unless this weak hook returns true. It used to be absent, so a
// bad OTA (panic after WiFi, never reaching MQTT, WDT loop) crash-looped on
// the new slot forever. Now the image stays ESP_OTA_IMG_PENDING_VERIFY
// until confirm_running_image(); any reset before that makes the
// bootloader boot the previous image (sp_device/image_rollback.h).
extern "C" bool verifyRollbackLater() { return true; }

static void confirm_running_image(const char* why) {
    sp_device::confirm_running_image(image_confirm, why);
}

// Before an operator-requested reboot (peripheral change, portal request,
// factory reset): an image that never reached MQTT stays unconfirmed, so the
// BOOT gesture an operator reaches for when a fresh OTA can't connect does
// not lock that image in.
static void confirm_before_deliberate_restart(const char* why) {
    sp_device::confirm_before_deliberate_restart(image_confirm, mqtt, why);
}

// Operator-requested reboot. Deferred a moment so the log line reaches MQTT;
// loop() measures the delay with a fresh millis() — a command handled inside
// mqtt->loop() runs after that pass's `now` was taken. Boot step 1 drives
// every channel off again.
static void request_restart(const char* why) {
    SP_LOG(LOG_WARN, "[SYSTEM] restarting: %s", why);
    confirm_before_deliberate_restart(why);
    restart_pending = true;
    restart_requested_ms = millis();
}

// Per-channel max-on override persistence: NVS key "mo_<channel>" (NVS keys
// are <= 15 chars; every preset name fits). Value = seconds.
static bool max_on_nvs_key(const char* channel, char* out, size_t cap) {
    int n = snprintf(out, cap, "mo_%s", channel);
    return n > 0 && (size_t)n < cap && n <= 15;
}

// ── command handling ────────────────────────────────────────────

// Clock-gated HMAC policy: with a provisioned key, frames verify strictly
// (and only once NTP has a sane epoch). With NO key, accept + warn every
// time — the v1 migration posture, except v2 can actually provision the
// key (portal field), and an empty key really is empty (the build-flag
// stringify corruption that silently armed garbage keys is gone).
static bool verify_command(const char* raw, size_t raw_len,
                           const char* suffix) {
    // Policy (empty-key fail-open, clock gate, strict verify) is the pure,
    // host-tested sp::command_auth_decision (test_core_hmac). Verification
    // runs on the exact wire bytes MqttLink hands through — never on a
    // re-serialized document (lexeme fidelity is what makes the canonicalizer
    // byte-exact against Python).
    //
    // The arrival topic enables destination binding (a signed "topic"
    // member must name exactly this topic — frames without the member still
    // verify), and the replay guard rejects a second delivery of the same
    // signed frame to the same topic inside the window (fw-node#11).
    std::string topic = mqtt->topic("cmd/");
    topic += suffix;
    sp::CmdAuthResult r = sp::command_auth_decision(
        raw, raw_len, cfg.hmac_key.c_str(), cfg.hmac_key.size(),
        (uint64_t)time(nullptr), sp::hmac_sha256_host, topic.c_str(),
        &cmd_replay_guard);
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
        cadence.set_publish_interval(r.value);
        SP_LOG(LOG_INFO, "[CMD] publish_interval_ms=%u%s (heartbeat every %u s)",
               (unsigned)r.value, r.clamped ? " (clamped)" : "",
               (unsigned)(cadence.heartbeat_interval_ms() / 1000UL));
    }
    if (!doc["calibrate_co2"].isNull()) {
        if (doc["calibrate_co2"].is<bool>()) {
            // v1 semantics (true = enable ASC) were wrong for chambers —
            // refuse loudly instead of quietly doing the wrong thing.
            SP_LOG(LOG_WARN,
                   "[CMD] calibrate_co2:true is deprecated — send a target "
                   "ppm (e.g. {\"calibrate_co2\": 420}) with the chamber "
                   "open to fresh air");
        } else if (!doc["calibrate_co2"].is<int32_t>()) {
            SP_LOG(LOG_WARN,
                   "[CMD] calibrate_co2 must be an integer target ppm "
                   "(%d-%d)",
                   (int)sp::kMinCo2CalPpm, (int)sp::kMaxCo2CalPpm);
        } else if (!sp::co2_cal_target_valid(
                       doc["calibrate_co2"].as<int32_t>())) {
            // A typo (42 / 4200 for 420) or 0 would shift every later
            // reading by thousands of ppm and blind the CO2 safety rules.
            SP_LOG(LOG_WARN,
                   "[CMD] calibrate_co2 REFUSED: %d ppm is outside the "
                   "%d-%d ppm fresh-air reference range",
                   (int)doc["calibrate_co2"].as<int32_t>(),
                   (int)sp::kMinCo2CalPpm, (int)sp::kMaxCo2CalPpm);
        } else {
            // Dispatch to whichever CO₂ sensor this node actually has —
            // the SCD4x-only gate silently dropped the command on SCD30
            // and MH-Z19C nodes.
            uint16_t ppm = (uint16_t)doc["calibrate_co2"].as<int32_t>();
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
    // Tare / calibrate never use the cached read-pass sample (up to
    // read_interval_ms old — it could predate emptying the platform or
    // placing the mass). They start an averaged capture of FRESH samples
    // that loop() feeds; the result is applied and persisted there.
    if (doc["tare"].is<bool>() && doc["tare"].as<bool>()) {
        if (hx711 == nullptr) {
            SP_LOG(LOG_WARN, "[CMD] tare: hx711 not enabled");
        } else if (scale_cal.busy()) {
            SP_LOG(LOG_WARN, "[CMD] tare: a scale capture is already running");
        } else {
            scale_cal.start_tare(millis());
            SP_LOG(LOG_INFO,
                   "[CMD] tare: averaging %d fresh HX711 samples — keep the "
                   "platform empty",
                   sp::ScaleCalibrator::kSamples);
        }
    }
    if (doc["calibrate_scale"].is<float>()) {
        float known_g = doc["calibrate_scale"].as<float>();
        if (hx711 == nullptr) {
            SP_LOG(LOG_WARN, "[CMD] calibrate_scale: hx711 not enabled");
        } else if (scale_cal.busy()) {
            SP_LOG(LOG_WARN,
                   "[CMD] calibrate_scale: a scale capture is already running");
        } else if (!scale_cal.start_calibrate(known_g, cfg.hx711_tare,
                                              millis())) {
            SP_LOG(LOG_WARN, "[CMD] calibrate_scale: known mass must be > 0 g");
        } else {
            SP_LOG(LOG_INFO,
                   "[CMD] calibrate_scale: averaging %d fresh HX711 samples "
                   "with %.1f g on the platform",
                   sp::ScaleCalibrator::kSamples, (double)known_g);
        }
    }
    // Tier-3 peripheral switch (docs#0): {"peripherals": {"mhz19": true,
    // "hx711": true, "reed": false, "reed_inv": true}} — only boolean
    // members present are applied. Persisted to the same NVS flags the setup
    // portal writes; the drivers are built only in setup(), so a change to
    // the driver SET reboots the node (boot step 1 drives every channel off
    // again). reed_inv (door contact wired on its NO lead) applies live. An
    // unchanged request is a no-op, so a repeated command cannot reboot-loop
    // the node.
    if (!doc["peripherals"].isNull()) {
        sp::PeripheralFlags flags;
        flags.mhz19 = cfg.mhz19_enabled;
        flags.hx711 = cfg.hx711_enabled;
        flags.reed = cfg.reed_enabled;
        flags.reed_inv = cfg.reed_invert;
        sp::PeripheralCmdResult r =
            sp::apply_peripheral_cmd(doc["peripherals"], &flags);
        if (!r.is_object) {
            SP_LOG(LOG_WARN,
                   "[CMD] peripherals must be an object, e.g. "
                   "{\"peripherals\":{\"hx711\":true}}");
        } else {
            if (r.ignored > 0)
                SP_LOG(LOG_WARN,
                       "[CMD] peripherals: ignored %d entr%s (known keys: "
                       "mhz19, hx711, reed, reed_inv; values must be "
                       "true/false)",
                       r.ignored, r.ignored == 1 ? "y" : "ies");
            if (r.changed) {
                cfg.mhz19_enabled = flags.mhz19;
                cfg.hx711_enabled = flags.hx711;
                cfg.reed_enabled = flags.reed;
                cfg.reed_invert = flags.reed_inv;
                cfg.save(kv);
                SP_LOG(LOG_INFO,
                       "[CMD] peripherals saved: mhz19=%d hx711=%d reed=%d "
                       "reed_inv=%d",
                       (int)flags.mhz19, (int)flags.hx711, (int)flags.reed,
                       (int)flags.reed_inv);
                if (r.restart_needed) {
                    request_restart("peripheral set changed");
                } else if (reed != nullptr) {
                    // Re-read the door under the new convention; no event.
                    reed->set_invert(flags.reed_inv, millis());
                    SP_LOG(LOG_INFO, "[CMD] reed invert %s - door reads %s",
                           flags.reed_inv ? "on" : "off",
                           reed->is_closed() ? "closed" : "open");
                }
            } else if (r.applied > 0) {
                SP_LOG(LOG_INFO, "[CMD] peripherals unchanged (mhz19=%d "
                                 "hx711=%d reed=%d reed_inv=%d)",
                       (int)flags.mhz19, (int)flags.hx711, (int)flags.reed,
                       (int)flags.reed_inv);
            }
        }
    }
    // Per-channel max-on backstop: {"max_on_sec": {"aux": 60, ...}}.
    // Switch channels 1 s..30 min (larger clamps), dim 0 (none)..24 h.
    // Persisted in NVS, applied immediately without resetting the channel.
    if (doc["max_on_sec"].is<JsonObject>()) {
        for (JsonPair kvp : doc["max_on_sec"].as<JsonObject>()) {
            const char* name = kvp.key().c_str();
            int idx = -1;
            for (int i = 0; i < channel_count; ++i) {
                if (strcmp(channels[i].config().name, name) == 0) idx = i;
            }
            if (idx < 0) {
                SP_LOG(LOG_WARN, "[CMD] max_on_sec: no channel '%s'", name);
                continue;
            }
            if (!kvp.value().is<int32_t>()) {
                SP_LOG(LOG_WARN, "[CMD] max_on_sec.%s must be integer seconds",
                       name);
                continue;
            }
            int32_t sec = kvp.value().as<int32_t>();
            uint32_t ms = 0;
            bool clamped = false;
            if (!sp::max_on_override_ms(channels[idx].config().mode, sec, &ms,
                                        &clamped)) {
                SP_LOG(LOG_WARN,
                       "[CMD] max_on_sec.%s=%d refused (switch channels keep "
                       "a 1-1800 s backstop)",
                       name, (int)sec);
                continue;
            }
            channels[idx].set_max_on_ms(ms);
            char key[16];
            if (max_on_nvs_key(name, key, sizeof(key)))
                kv.set_int(key, (int32_t)(ms / 1000UL));
            SP_LOG(LOG_INFO, "[CMD] %s max_on=%u s%s", name,
                   (unsigned)(ms / 1000UL), clamped ? " (clamped)" : "");
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

// One HX711 sample if a conversion is ready (a single pin read otherwise —
// never a spin-wait). Feeds the read-pass cache AND any running tare /
// calibration capture.
static void sample_hx711(uint32_t now) {
    if (hx711 == nullptr || !hx711->is_ready()) return;
    noInterrupts();  // PD_SCK high >60 µs power-cycles the chip
    int32_t raw = hx711->read_raw();
    interrupts();
    hx711_raw = raw;
    have_hx711 = true;
    hx_fresh.mark_ok(now);
    scale_cal.add_sample(raw);
}

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
            scd_fresh.mark_ok(millis());
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
            scd_fresh.mark_ok(millis());
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
            lux_fresh.mark_ok(millis());
        }
    }

    if (mhz19 != nullptr && !mhz19->awaiting_reply()) {
        mhz19->request_read();  // completion handled in loop()
    }

    sample_hx711(millis());

    // Staleness: a reading whose sensor produced nothing fresh within the
    // window is dropped from telemetry (and alerted in check_alerts) instead
    // of being re-published as if it were current.
    uint32_t now = millis();
    uint32_t window = sp::stale_window_ms(read_interval_ms);
    if (mhz19 != nullptr && !mhz_warm &&
        sp::elapsed_ms(now, boot_ms) >= kMhz19WarmupMs) {
        mhz_warm = true;
        if (!mhz_fresh.ever_ok()) mhz_fresh.arm(now);  // start its clock now
    }
    bool scd_stale = (scd4x != nullptr || scd30 != nullptr)
                         ? scd_fresh.check_stale(now, window)
                         : true;
    bool mhz_stale = mhz19 != nullptr ? mhz_fresh.check_stale(now, window)
                                      : true;
    if (scd_stale && mhz_stale) have_co2 = false;
    if (bh1750 != nullptr && lux_fresh.check_stale(now, window))
        have_lux = false;
    if (hx711 != nullptr && hx_fresh.check_stale(now, window))
        have_hx711 = false;

    uint32_t took = millis() - t0;
    if (took > 50) {
        SP_LOG(LOG_WARN, "[SENSOR] read pass took %u ms (budget 50)",
               (unsigned)took);
    }
}

// Every alert is latched (alert_latch.h): published once on entry, then at
// most hourly while the condition persists, re-armed only after it clears
// (thresholds with hysteresis). Latches only update while their reading is
// available, so a flapping sensor cannot re-fire them on every recovery.
static void check_alerts() {
    if (!mqtt->connected()) return;
    uint32_t now = millis();
    if (have_temp_rh) {
        float temp_f = c_to_f(temp_c);
        if (temp_hi_alert.due(temp_f, now) &&
            emit_alert("temperature", temp_f, "Temperature critically high!"))
            temp_hi_alert.emitted(now);
        if (temp_lo_alert.due(temp_f, now) &&
            emit_alert("temperature", temp_f, "Temperature critically low!"))
            temp_lo_alert.emitted(now);
        if (rh_hi_alert.due(rh, now) &&
            emit_alert("humidity", rh, "Humidity saturated!"))
            rh_hi_alert.emitted(now);
        if (rh_lo_alert.due(rh, now) &&
            emit_alert("humidity", rh, "Humidity critically low!"))
            rh_lo_alert.emitted(now);
    }
    bool sht_failed = !have_temp_rh && (sht3x != nullptr || sht4x != nullptr);
    if (temp_rh_fail_alert.due(sht_failed, now) &&
        emit_alert("sensor_failure", 0.0f, "Temp/RH sensor read failed",
                   sht3x ? "SHT3x" : "SHT4x"))
        temp_rh_fail_alert.emitted(now);
    if (have_co2 && co2_hi_alert.due((float)co2_ppm, now) &&
        emit_alert("co2", (float)co2_ppm, "CO2 dangerously high!"))
        co2_hi_alert.emitted(now);

    // Stale sensors: the reading has already been dropped from telemetry;
    // tell the operator once (and hourly) instead of going silent.
    auto stale_alert = [now](bool present, const sp::ReadingFreshness& f,
                             sp::AlertLatch& latch, const char* msg,
                             const char* sensor) {
        if (latch.due(present && f.is_stale(), now) &&
            emit_alert("sensor_failure", 0.0f, msg, sensor))
            latch.emitted(now);
    };
    stale_alert(scd4x != nullptr || scd30 != nullptr, scd_fresh,
                scd_stale_alert, "CO2 sensor stale - no fresh reading",
                scd4x ? "SCD4x" : "SCD30");
    stale_alert(mhz19 != nullptr, mhz_fresh, mhz_stale_alert,
                "CO2 sensor stale - no fresh reading", "MH-Z19C");
    stale_alert(bh1750 != nullptr, lux_fresh, lux_stale_alert,
                "Light sensor stale - no fresh reading", "BH1750");
    stale_alert(hx711 != nullptr, hx_fresh, hx_stale_alert,
                "Scale stale - no HX711 samples", "HX711");

    // Secure MQTT asked for, plaintext in use (fw-node#2): entry + hourly
    // until the runtime CA fetch pins a CA and the link moves to TLS.
    if (tls_downgrade_alert.due(tls_link.fallback(), now) &&
        emit_alert(sp::kAlertTlsDowngrade, (float)cfg.broker_port,
                   "Secure MQTT is on but no Pi CA is pinned - running on "
                   "plaintext (credentials unencrypted); retrying the CA "
                   "fetch"))
        tls_downgrade_alert.emitted(now);
}

static void publish_telemetry() {
    sp::TelemetryInputs in;
    // Epoch seconds once NTP has synced (so a replayed frame keeps its real
    // capture time); uptime before that — the Pi stamps arrival time for
    // anything below the epoch floor.
    in.ts = sp::telemetry_ts((uint64_t)time(nullptr), millis() / 1000);
    if (have_temp_rh) {
        in.have_temp_rh = true;
        in.temp_c = temp_c;  // builder derives temp_f + rounds
        in.humidity = rh;
        in.dew_point_f = c_to_f(dew_point_c(temp_c, rh));
    }
    if (have_co2) {
        in.have_co2 = true;
        in.co2_ppm = co2_ppm;
    }
    if (have_lux) {
        in.have_lux = true;
        in.lux = lux;
    }
    if (have_hx711) {
        float grams;
        if (sp::Hx711::to_grams(hx711_raw, cfg.hx711_tare, cfg.hx711_scale,
                                &grams)) {
            in.have_weight = true;
            in.weight_g = grams;
        } else {
            // Uncalibrated (scale == 0) — publish raw counts so the
            // operator can watch the tare/calibrate flow move the needle.
            in.have_scale_raw = true;  // tolerated-not-stored
            in.scale_raw = hx711_raw;
        }
    }
    if (reed != nullptr) {
        in.have_door = true;
        in.door_open = !reed->is_closed();
    }

    JsonDocument doc;
    sp::build_telemetry(in, doc);

    std::string topic = mqtt->topic("telemetry");
    bool sent = false;
    if (mqtt->connected()) {
        // Drain the backlog FIRST so the live reading is the newest frame to
        // arrive (replayed frames are flagged and never become "latest").
        offline_buffer.flush([](const char* t, const char* p) {
            return mqtt->publish_raw(t, p);
        });
        sent = mqtt->publish(topic.c_str(), doc);
    }
    if (!sent) {
        // A buffered frame can only ever be published late: mark it as a
        // replay now so the Pi stores it but never runs automation on it.
        in.replay = true;
        doc.clear();
        sp::build_telemetry(in, doc);
        char buf[384];
        size_t need = measureJson(doc);
        if (need < sizeof(buf)) {
            serializeJson(doc, buf, sizeof(buf));
            offline_buffer.buffer(topic.c_str(), buf);
        } else {
            SP_LOG(LOG_WARN, "[MQTT] telemetry frame %u B too large to buffer",
                   (unsigned)need);
        }
    }
}

static void publish_heartbeat() {
    // v2 additive fields — the Pi upsert + cloud routing consume `type`;
    // `roles` carries the full capability set for the patched resolver.
    const char* roles[3];
    int n_roles = 0;
    if (sht3x || sht4x || scd4x || scd30 || bh1750 || mhz19)
        roles[n_roles++] = "climate";
    if (cfg.personality == sp::Personality::RelayBank) roles[n_roles++] = "relay";
    if (cfg.personality == sp::Personality::LightingBank)
        roles[n_roles++] = "lighting";

    // Keep the IP String alive until publish — build_heartbeat stores it as a
    // borrowed const char* (ArduinoJson does not copy char pointers).
    String ip = WiFi.localIP().toString();

    sp::HeartbeatInputs in;
    in.uptime_sec = millis() / 1000;
    in.free_heap = ESP.getFreeHeap();
    in.firmware_version = SPOREPRINT_FW_VERSION;
    in.wifi_rssi = WiFi.RSSI();
    in.ip = ip.c_str();
    in.reset_reason = (int)esp_reset_reason();
    in.emit_wifi_reconnects = true;
    in.wifi_reconnects = wifi_reconnects;  // link-watchdog STA re-begins
    in.mqtt_reconnects = mqtt->reconnect_count();
    in.type = sp::node_type_str(cfg.personality);
    in.roles = roles;
    in.n_roles = n_roles;
    in.fw_image = "node";
    in.migrated_from = cfg.migrated_from.c_str();
    // Additive keys: the MQTT transport actually in use (fw-node#2) and the
    // board profile (which image an OTA push needs).
    in.emit_tls = true;
    in.tls = tls_link.tls();
    in.tls_fallback = tls_link.fallback();
    in.board = SP_BOARD_NAME;

    JsonDocument doc;
    sp::build_heartbeat(in, doc);
    mqtt->publish(mqtt->topic("status/heartbeat").c_str(), doc);
}

static void publish_health() {
    sp::SensorHealthView sviews[8];
    int ns = 0;
    // A driver can look healthy while its reading is frozen (e.g. an SCD4x
    // that stays "not ready" without a bus fault, an HX711 that never
    // signals ready) — a stale reading must not report ok:true. (SCD4x/SCD30
    // data_ready() bus faults are recorded as driver failures themselves.)
    auto add_sensor = [&](const char* name, const sp::DriverHealth& h,
                          bool stale) {
        const char* err = h.last_error != nullptr
                              ? h.last_error
                              : (stale ? "stale: no fresh reading" : nullptr);
        sviews[ns++] = {name, err == nullptr, h.reads, h.fails, err};
    };
    if (sht3x) add_sensor("sht3x", sht3x->health(), false);
    if (sht4x) add_sensor("sht4x", sht4x->health(), false);
    if (scd4x) add_sensor("scd4x", scd4x->health(), scd_fresh.is_stale());
    if (scd30) add_sensor("scd30", scd30->health(), scd_fresh.is_stale());
    if (bh1750) add_sensor("bh1750", bh1750->health(), lux_fresh.is_stale());
    if (mhz19) add_sensor("mhz19", mhz19->health(), mhz_fresh.is_stale());
    if (hx711) add_sensor("hx711", hx711->health(), hx_fresh.is_stale());
    if (reed) add_sensor("reed", reed->health(), false);

    sp::ChannelHealthView cviews[SP_CHANNEL_COUNT];
    uint32_t now = millis();
    for (int i = 0; i < channel_count; ++i) {
        const sp::Channel& ch = channels[i];
        cviews[i] = {ch.config().name, ch.is_on(),
                     ch.config().mode == sp::ChannelMode::Switch
                         ? (uint16_t)ch.pwm8()
                         : ch.level10(),
                     ch.on_time_sec_live(now), ch.health().cycle_count,
                     ch.health().safety_cutoffs};
    }

    // Declared-but-missing sensors (each also raises a latched
    // sensor_failure alert from check_alerts):
    //   temp_rh — only a CLIMATE node is expected to carry a temp/RH sensor;
    //             sensorless relay/lighting banks used to report it forever.
    //   mhz19 / hx711 — config-enabled, but no fresh sample inside the
    //             staleness window (the driver object always exists once
    //             enabled, so the old `enabled && nullptr` test never fired).
    //   The reed switch is not listed: a correctly wired switch on a door
    //   that stays shut legitimately produces no edges, so an unwired one is
    //   electrically indistinguishable.
    const char* missing[4];
    int nm = 0;
    if (cfg.personality == sp::Personality::Climate && !sht3x && !sht4x)
        missing[nm++] = "temp_rh";
    if (mhz19 != nullptr && mhz_fresh.is_stale()) missing[nm++] = "mhz19";
    if (hx711 != nullptr && hx_fresh.is_stale()) missing[nm++] = "hx711";

    sp::HealthInputs in;
    in.node_id = cfg.node_id.c_str();
    in.type = sp::node_type_str(cfg.personality);
    in.uptime_sec = millis() / 1000;
    in.free_heap = ESP.getFreeHeap();
    in.wifi_rssi = WiFi.RSSI();
    in.sensors = sviews;
    in.n_sensors = ns;
    in.channels = channel_count > 0 ? cviews : nullptr;
    in.n_channels = channel_count;
    in.missing = missing;
    in.n_missing = nm;

    JsonDocument doc;
    sp::build_health(in, doc);
    mqtt->publish(mqtt->topic("health").c_str(), doc);
}

// ── boot ────────────────────────────────────────────────────────

static void enter_steady_state() {
    // The ONLY esp_task_wdt_add site in the image. Everything before this
    // point is protected by explicit deadlines, not the WDT.
    // One synchronous MQTT connect attempt is budgeted to fit inside this
    // timeout (link_budget.h static_assert).
    esp_task_wdt_init(sp::kLoopWdtTimeoutS, true);
    esp_task_wdt_add(NULL);
    SP_LOG(LOG_INFO, "[BOOT] steady state — WDT armed (%u s)",
           (unsigned)sp::kLoopWdtTimeoutS);
}

void setup() {
    // 1. Safe-state FIRST: all channel outputs driven off before anything
    //    else — including the Serial bring-up delay, which used to leave the
    //    gates at their reset state for an extra 500 ms on every boot (GPIO
    //    14 / aux has boot-time JTAG activity).
    for (int i = 0; i < SP_CHANNEL_COUNT; ++i) {
        ledcSetup(i, SP_LEDC_FREQ_HZ, SP_LEDC_RES_BITS);
        ledcAttachPin(kChannelPins[i], i);
        ledcWrite(i, 0);
    }
    pinMode(SP_PIN_FACTORY_RESET, INPUT_PULLUP);

    Serial.begin(115200);
    delay(500);
    Serial.printf("\n=== SporePrint Node v2 (%s) ===\n", SP_BOARD_NAME);

    // 2. Config + v1 migration.
    std::string migrated = sp_device::migrate_legacy(kv);
    cfg = sp_device::NodeConfig::load(kv);
    if (!migrated.empty())
        Serial.printf("[CONFIG] Migrated v1 namespace '%s'\n", migrated.c_str());

    // 3. Provisioning / WiFi — pre-WDT, deadline-bounded (boot_policy.h).
    //    The setup AP is OPEN and its form rewrites the broker host, HMAC
    //    key and OTA password, so a working node never falls into it on its
    //    own: a router slow to return after a power blip used to park the
    //    node in the portal for 10 minutes with anyone in range able to
    //    re-provision it (fw-node#9).
    bool portal_requested = kv.get_bool("portal_req", false);
    if (portal_requested) kv.set_bool("portal_req", false);  // one-shot
    if (sp::portal_at_boot(cfg.provisioned(), portal_requested)) {
        provisioner.run_portal(cfg);  // never returns (10-min ceiling)
    }
    if (provisioner.connect(cfg)) {
        if (!cfg.wifi_verified) {
            cfg.wifi_verified = true;
            kv.set_bool("wifi_ok", true);
        }
    } else if (sp::portal_after_connect_failure(cfg.wifi_verified)) {
        // Credentials just typed in the portal never connected — likely a
        // typo, and the operator is right there: give the form back.
        provisioner.run_portal(cfg);  // never returns
    } else {
        // These credentials have worked before: boot offline. The link
        // watchdog re-begins the STA connection every 60 s, telemetry
        // buffers, and every channel stays off until MQTT commands arrive.
        Serial.println("[WIFI] Network unreachable - booting offline and "
                       "retrying. Hold BOOT 3-10 s (then release) to open "
                       "the setup portal.");
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
        // Operator max-on override (cmd/config max_on_sec), if persisted.
        char key[16];
        if (max_on_nvs_key(channels[i].config().name, key, sizeof(key))) {
            int32_t sec = kv.get_int(key, -1);
            uint32_t ms = 0;
            if (sec >= 0 && sp::max_on_override_ms(channels[i].config().mode,
                                                   sec, &ms, nullptr)) {
                channels[i].set_max_on_ms(ms);
                Serial.printf("[CH] %s max_on override: %u s\n",
                              channels[i].config().name,
                              (unsigned)(ms / 1000UL));
            }
        }
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
        if (!scd4x->begin())  // ASC off + periodic start
            SP_LOG(LOG_ERROR, "[SENSOR] SCD4x begin failed - CO2 will go stale");
    }
    if (detected.co2 == sp::Co2Kind::Scd30) {
        scd30 = new sp::Scd30(i2c_bus, sys_clock);
        if (!scd30->begin())
            SP_LOG(LOG_ERROR, "[SENSOR] SCD30 begin failed - CO2 will go stale");
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
        // reed_inv: contact wired on its NO lead (pin HIGH = door shut).
        reed = new sp::ReedSwitch(reed_pin, 50, cfg.reed_invert);
        reed->begin(millis());
    }

    // 6. MQTT + services. The transport follows tls_policy.h: plain, TLS
    //    against the pinned Pi CA, the loud plaintext fallback, or (Require
    //    TLS) no MQTT until a CA is pinned.
    sp_device::MqttTransport xport = tls_link.select();
    mqtt = new sp_device::MqttLink(*xport.client, cfg.node_id.c_str(),
                                   sp::node_type_str(cfg.personality),
                                   SPOREPRINT_FW_VERSION);
    mqtt->on_command(on_command, nullptr);
    mqtt->begin(cfg.broker_host.c_str(), xport.port,
                cfg.mqtt_user.c_str(), cfg.mqtt_pass.c_str(),
                /*connect_now=*/sp::tls_mode_allows_mqtt(xport.mode));

    sp_device::logfwd::attach(mqtt);
    sp_device::coredump::upload_if_present(*mqtt);

    std::string hostname = "sporeprint-" + cfg.node_id;
    ota = new sp_device::OtaService(*mqtt, hostname.c_str(),
                                    cfg.ota_pass.c_str());
    // The OTA upload runs synchronously inside loop() for 30-60 s with no
    // channel ticks — drive every output off before it starts.
    ota->on_start([](void*) { force_all_off("OTA update started", true); },
                  nullptr);
    ota->begin();

    SP_LOG(LOG_INFO,
           "[BOOT] node ready: id=%s type=%s board=%s channels=%d mqtt=%s "
           "reset=%d",
           cfg.node_id.c_str(), sp::node_type_str(cfg.personality),
           SP_BOARD_NAME, channel_count, sp::tls_mode_str(xport.mode),
           (int)esp_reset_reason());
    sp_device::note_probation_at_boot(image_confirm);

    // Staleness clocks + link watchdog start at the end of boot (setup can
    // spend seconds in WiFi/NTP/autodetect). The MH-Z19C's clock starts
    // after its preheat (read_sensors), unless it answers sooner.
    boot_ms = millis();
    if (scd4x != nullptr || scd30 != nullptr) scd_fresh.arm(boot_ms);
    if (bh1750 != nullptr) lux_fresh.arm(boot_ms);
    if (hx711 != nullptr) hx_fresh.arm(boot_ms);
    link_wd.begin(boot_ms);

    // 7. Arm the watchdog LAST.
    enter_steady_state();
}

// ── loop ────────────────────────────────────────────────────────

void loop() {
    esp_task_wdt_reset();  // the single pet site
    uint32_t now = millis();

    // BOOT button: held > 10 s → factory reset; released after 3-10 s →
    // reboot into the setup portal (the only way a working, provisioned node
    // opens it — physical presence). Read here, with this pass's fresh `now`,
    // before anything can block: ButtonHold only times densely-sampled
    // stretches (a blocked pass used to stretch a 4 s press into a factory
    // reset), and no MQTT connect attempt starts while the button is down, so
    // a hold made while the broker is unreachable is still seen to release.
    bool boot_down = digitalRead(SP_PIN_FACTORY_RESET) == LOW;
    switch (boot_button.update(now, boot_down)) {
        case sp::ButtonHold::Action::FactoryReset:
            SP_LOG(LOG_ERROR, "[SYSTEM] Factory reset triggered");
            confirm_before_deliberate_restart("factory reset");
            sp_device::factory_reset_all();  // restarts
            break;
        case sp::ButtonHold::Action::OpenPortal:
            if (!restart_pending) {
                kv.set_bool("portal_req", true);
                request_restart("setup portal requested (BOOT held 3-10 s)");
            }
            break;
        default:
            break;
    }

    // Secure MQTT with no pinned CA: at most one bounded CA fetch per pass on
    // a backoff (tls_policy.h). A pass that fetched starts no MQTT connect
    // attempt — the two together would overrun the WDT (link_budget.h).
    const bool ca_fetched = tls_link.loop(now, boot_down, *mqtt);
    mqtt->loop(now, sp::mqtt_may_connect(tls_link.mode(), ca_fetched, boot_down));
    ota->loop();
    sp_device::logfwd::loop(now);

    // OTA probation: a new image proves itself with 60 s of continuous MQTT.
    if (image_confirm.update(now, mqtt->connected()))
        confirm_running_image("60 s of MQTT after boot");

    if (restart_pending &&
        sp::elapsed_ms(millis(), restart_requested_ms) >= kRestartDelayMs) {
        ESP.restart();
    }

    // Link-loss failsafe (CLAUDE.md §5c: 10-min MQTT watchdog → safe mode).
    sp::LinkWatchdog::Actions link =
        link_wd.update(now, WiFi.status() == WL_CONNECTED, mqtt->connected());
    if (link.enter_safe_mode) {
        // Nothing can command the bank until MQTT returns; hold the boot
        // state (all off) instead of the last command (lights lit through
        // the dark phase, relays running to their max-on).
        SP_LOG(LOG_ERROR, "[SAFETY] MQTT down %u s - SAFE MODE: all channels off",
               (unsigned)(sp::LinkWatchdog::kSafeModeAfterMs / 1000UL));
        safe_mode_cut_mask |= force_all_off("safe mode (MQTT lost)", false);
    }
    if (link.exit_safe_mode) {
        SP_LOG(LOG_WARN, "[SAFETY] MQTT restored after %u s - safe mode cleared",
               (unsigned)(link_wd.last_outage_ms() / 1000UL));
        // The cut happened offline; tell the Pi now.
        for (int i = 0; i < channel_count; ++i) {
            if ((safe_mode_cut_mask & (1u << i)) != 0 &&
                channels[i].config().mode == sp::ChannelMode::Switch)
                report_switch_channel(i, "safety_cutoff");
        }
        if (safe_mode_cut_mask != 0 && channel_count > 0 &&
            channels[0].config().mode == sp::ChannelMode::Dim)
            report_dim_levels();
        safe_mode_cut_mask = 0;
    }
    if (link.wifi_retry) {
        // The core's auto-reconnect gives up for good on some disconnect
        // reasons (e.g. AUTH_FAIL while a router reboots) — re-begin the
        // STA connection ourselves. No reboot: that would drop the offline
        // telemetry buffer and, with WiFi still down, land in the portal.
        ++wifi_reconnects;
        SP_LOG(LOG_WARN, "[WIFI] link down - re-begin STA (retry %u)",
               (unsigned)wifi_reconnects);
        WiFi.disconnect();
        WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
    }

    // HX711 tare / calibration capture: sample every pass until done.
    if (scale_cal.busy()) {
        sample_hx711(now);
        switch (scale_cal.poll(now)) {
            case sp::ScaleCalibrator::Status::Done:
                if (scale_cal.finished_op() == sp::ScaleCalibrator::Op::Tare) {
                    cfg.hx711_tare = scale_cal.tare();
                    cfg.save(kv);
                    SP_LOG(LOG_INFO, "[CMD] scale tared at %d counts (avg of %d)",
                           (int)cfg.hx711_tare, sp::ScaleCalibrator::kSamples);
                } else {
                    cfg.hx711_scale = scale_cal.scale();
                    cfg.save(kv);
                    SP_LOG(LOG_INFO,
                           "[CMD] scale calibrated: %.3f counts/g (avg %d "
                           "counts, tare %d)",
                           (double)cfg.hx711_scale, (int)scale_cal.mean(),
                           (int)cfg.hx711_tare);
                }
                break;
            case sp::ScaleCalibrator::Status::Rejected:
                SP_LOG(LOG_WARN,
                       "[CMD] calibrate_scale REFUSED: %.3f counts/g (avg %d, "
                       "tare %d) - %s. Tare empty, then place the known mass",
                       (double)scale_cal.scale(), (int)scale_cal.mean(),
                       (int)cfg.hx711_tare, scale_cal.reason());
                break;
            case sp::ScaleCalibrator::Status::TimedOut:
                SP_LOG(LOG_WARN, "[CMD] %s failed: %s",
                       scale_cal.finished_op() == sp::ScaleCalibrator::Op::Tare
                           ? "tare"
                           : "calibrate_scale",
                       scale_cal.reason());
                break;
            default:
                break;
        }
    }

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
            mhz_fresh.mark_ok(now);
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
    // Telemetry + health at publish_interval_ms; the heartbeat on its own
    // min(publish_interval_ms, 5 min) clock (srv-hw#22) — at the 60 s
    // default all three still go out on the same pass.
    const sp::PublishCadence::Due due = cadence.update(now);
    if (due.telemetry) publish_telemetry();
    if (due.heartbeat) publish_heartbeat();
    if (due.telemetry) publish_health();
    // Switch banks also report state every 60 s (v1 contract).
    if (channel_count > 0 &&
        channels[0].config().mode == sp::ChannelMode::Switch &&
        sp::elapsed_ms(now, last_switch_report_ms) >= 60000) {
        last_switch_report_ms = now;
        for (int i = 0; i < channel_count; ++i)
            report_switch_channel(i, "report");
    }
}
