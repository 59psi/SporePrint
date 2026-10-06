#pragma once
//
// wire_contract — pure, native-safe builders for every device→cloud JSON
// document the node/cam images publish.
//
// WHY THIS EXISTS: the device→cloud key set is the codebase's proven-recurring
// failure (the design `RelayTelemetry` co2/vpd/light lie; the weight_g xfail).
// Before this module the only guard was a cross-repo regex text-parse of
// main.cpp that missed heartbeat/health/switch/logs keys and broke on a
// reformat. Here the key set + type literals are assembled in ONE pure place
// that both the firmware composition roots AND a host test (test_wire_contract)
// compile against — so a rename is a firmware compile/test failure, not silent
// drift caught only if another repo's vitest runs at the right submodule SHA.
//
// Cross-referenced contracts (asserted in test_wire_contract):
//   telemetry keys      == design TELEMETRY_KEYS  == Pi SENSOR_FIELDS
//                          (server/app/telemetry/service.py)
//   alert `type` values == design ALERT_TYPES
//   `type` personality  == design COMPONENT_TYPES == personality.h strings
//   switch report keys  -> Pi actuator_events (server/app/mqtt.py telemetry/<ch>)
//   log entry keys      -> Pi logs consumer (ts_ms/level/msg)
//
// Native-safe: this header pulls in no Arduino core. It uses ArduinoJson, which
// is header-only and host-compilable. (The CI native-safe guard greps sp_core /
// sp_drivers for a bare Arduino-core header include; ArduinoJson.h never trips
// it.) Numbers are rounded here so the wire format lives in exactly one spot.

#include <ArduinoJson.h>

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "hmac_verify.h"  // kMinValidEpoch — the one "clock is synced" floor

namespace sp {

// Round a float to one decimal place — the telemetry wire precision.
inline float wire_round1(float v) { return roundf(v * 10.0f) / 10.0f; }

// ── telemetry (publish_telemetry) ──────────────────────────────
// Every sensor field is optional: the firmware emits only the ones whose
// sensor is present. `scale_raw` is the uncalibrated HX711 fallback — emitted
// but NOT in SENSOR_FIELDS (the Pi tolerates-but-drops it), mutually exclusive
// with `weight_g`. `pressure_hpa` (additive) is barometric pressure from a
// BME280 / BMP280, hPa (= mbar) to one decimal.
//
// Envelope keys (not sensor fields, never persisted as readings):
//   ts      Unix-epoch seconds once NTP has synced; uptime seconds before
//           that (see telemetry_ts). The Pi treats ts < 1e9 as unsynced and
//           stamps arrival time.
//   replay  OPTIONAL, emitted only as `true` — the frame was buffered while
//           the broker was unreachable and is being replayed late. The Pi
//           stores it (at its own ts) but never evaluates automation rules
//           on it and never lets it overwrite a newer latest reading.
//           Absent on live frames, so pre-replay consumers see no change.
struct TelemetryInputs {
    uint32_t ts = 0;  // telemetry_ts(): epoch when synced, else uptime
    bool replay = false;  // buffered frame replayed after an outage

    bool have_temp_rh = false;
    float temp_c = 0.0f;   // raw °C — builder derives temp_f + dew_point_f
    float humidity = 0.0f; // %RH
    float dew_point_f = 0.0f;  // caller-computed °F (Magnus), builder rounds

    bool have_co2 = false;
    uint16_t co2_ppm = 0;

    bool have_lux = false;
    float lux = 0.0f;

    bool have_pressure = false;  // BME280 / BMP280 present + fresh
    float pressure_hpa = 0.0f;

    bool have_weight = false;  // HX711 present AND calibrated
    float weight_g = 0.0f;
    bool have_scale_raw = false;  // HX711 present, uncalibrated
    int32_t scale_raw = 0;

    bool have_door = false;
    bool door_open = false;
};

// The telemetry `ts`: wall-clock epoch seconds when the clock has synced
// (>= kMinValidEpoch, 2020-01-01), otherwise the uptime seconds the Pi has
// always accepted (and re-stamps at arrival). The two ranges cannot overlap:
// uptime would need ~50 years to reach the epoch floor.
inline uint32_t telemetry_ts(uint64_t epoch_s, uint32_t uptime_s) {
    return epoch_s >= kMinValidEpoch ? (uint32_t)epoch_s : uptime_s;
}

inline void build_telemetry(const TelemetryInputs& in, JsonDocument& doc) {
    doc["ts"] = in.ts;
    if (in.replay) doc["replay"] = true;
    if (in.have_temp_rh) {
        float tf = in.temp_c * 9.0f / 5.0f + 32.0f;
        doc["temp_f"] = wire_round1(tf);
        doc["temp_c"] = wire_round1(in.temp_c);
        doc["humidity"] = wire_round1(in.humidity);
        doc["dew_point_f"] = wire_round1(in.dew_point_f);
    }
    if (in.have_co2) doc["co2_ppm"] = in.co2_ppm;
    if (in.have_lux) doc["lux"] = wire_round1(in.lux);
    if (in.have_pressure) doc["pressure_hpa"] = wire_round1(in.pressure_hpa);
    if (in.have_weight) {
        doc["weight_g"] = wire_round1(in.weight_g);
    } else if (in.have_scale_raw) {
        doc["scale_raw"] = in.scale_raw;  // tolerated-not-stored
    }
    if (in.have_door) doc["door_open"] = in.door_open;
}

// ── alert (emit_alert) ─────────────────────────────────────────
// `sensor` is optional (nullptr ⇒ omitted). The Pi's forward_event lets the
// payload's own `type` win, so `type` is what reaches the cloud event channel.
//
// Types: temperature, humidity, co2, door, sensor_failure (design
// ALERT_TYPES) plus the firmware-only additions below. The Pi pages an
// unknown node alert type at WARNING and forwards it unchanged, so each
// addition is backward compatible.
//
// tls_downgrade — Secure MQTT is enabled but no Pi CA could be pinned, so the
// node is running on plaintext (value = the plaintext port in use). Entry +
// hourly while it lasts (alert_latch.h). fw-node#2.
constexpr const char* kAlertTlsDowngrade = "tls_downgrade";

inline void build_alert(const char* type, float value, const char* message,
                        const char* sensor, JsonDocument& doc) {
    doc["type"] = type;
    doc["value"] = value;
    doc["message"] = message;
    if (sensor != nullptr) doc["sensor"] = sensor;
}

// ── switch-channel report (report_switch_channel) ──────────────
// Published on telemetry/<channel>; feeds the Pi actuator_events table.
inline void build_switch_report(const char* channel, bool on, uint8_t pwm,
                                const char* trigger, JsonDocument& doc) {
    doc["channel"] = channel;
    doc["state"] = on ? "on" : "off";
    doc["pwm"] = pwm;
    doc["trigger"] = trigger;
}

// ── dim-level report (report_dim_levels) ───────────────────────
// Aggregate lighting doc: one key per channel NAME → 10-bit level, published
// on the bare `telemetry` topic. NB: the Pi's store_bulk_readings persists
// only SENSOR_FIELDS, so these channel-named levels are forwarded live but
// NOT written to telemetry history — pinned here so that asymmetry is visible.
struct DimLevel {
    const char* name;
    uint16_t level;
};
inline void build_dim_levels(const DimLevel* levels, int n, JsonDocument& doc) {
    for (int i = 0; i < n; ++i) doc[levels[i].name] = levels[i].level;
}

// ── heartbeat (publish_heartbeat) ──────────────────────────────
// `type` + `roles` drive the Pi upsert and cloud command routing. The node
// image emits wifi_reconnects (its app-level WiFi re-begin count — the core's
// auto-reconnect gives up on some disconnect reasons, so the node's link
// watchdog retries itself); the cam image omits it. `migrated_from` is
// present only post-migration.
//
// Optional, additive keys (the Pi ignores keys it doesn't know):
//   tls           bool — the MQTT transport in use is TLS with the pinned Pi
//                 CA (emitted by current node + cam images; fw-node#2)
//   tls_fallback  true — only while Secure MQTT is enabled but the node runs
//                 on plaintext because no CA could be pinned (omitted else)
//   board         the board profile the image was built for (e.g.
//                 "esp32-wroom-32", "esp32-s3-devkitc-1-n32r16v") — tells the
//                 operator which image an OTA push needs
//   ca_fp         lowercase hex SHA-256 (64 chars) of the exact CA PEM the
//                 TLS link verifies the broker against — the bytes the Pi
//                 served from GET /api/provision/ca, i.e. Python
//                 hashlib.sha256(pem.encode()).hexdigest() of its ca.crt.
//                 Only while `tls` is true (omitted else). Lets the Pi spot a
//                 node that trust-on-first-use pinned some other CA.
struct HeartbeatInputs {
    uint32_t uptime_sec = 0;
    uint32_t free_heap = 0;
    const char* firmware_version = "";
    int32_t wifi_rssi = 0;
    const char* ip = "";
    int32_t reset_reason = 0;
    bool emit_wifi_reconnects = true;  // node: true, cam: false
    uint32_t wifi_reconnects = 0;
    uint32_t mqtt_reconnects = 0;
    const char* type = "";  // node_type_str(personality) | "camera"
    const char* const* roles = nullptr;
    int n_roles = 0;
    const char* fw_image = "";       // "node" | "cam"
    const char* migrated_from = nullptr;  // nullptr/"" ⇒ omitted
    bool emit_tls = false;           // emit `tls` (current images: true)
    bool tls = false;
    bool tls_fallback = false;       // emitted only when true
    const char* board = nullptr;     // nullptr/"" ⇒ omitted
    const char* ca_fp = nullptr;     // nullptr/"" ⇒ omitted
};

inline void build_heartbeat(const HeartbeatInputs& in, JsonDocument& doc) {
    doc["uptime_sec"] = in.uptime_sec;
    doc["free_heap"] = in.free_heap;
    doc["firmware_version"] = in.firmware_version;
    doc["wifi_rssi"] = in.wifi_rssi;
    doc["ip"] = in.ip;
    doc["reset_reason"] = in.reset_reason;
    if (in.emit_wifi_reconnects) doc["wifi_reconnects"] = in.wifi_reconnects;
    doc["mqtt_reconnects"] = in.mqtt_reconnects;
    doc["type"] = in.type;
    JsonArray roles = doc["roles"].to<JsonArray>();
    for (int i = 0; i < in.n_roles; ++i) roles.add(in.roles[i]);
    doc["fw_image"] = in.fw_image;
    if (in.migrated_from != nullptr && in.migrated_from[0] != '\0')
        doc["migrated_from"] = in.migrated_from;
    if (in.emit_tls) doc["tls"] = in.tls;
    if (in.tls_fallback) doc["tls_fallback"] = true;
    if (in.board != nullptr && in.board[0] != '\0') doc["board"] = in.board;
    if (in.ca_fp != nullptr && in.ca_fp[0] != '\0') doc["ca_fp"] = in.ca_fp;
}

// ── health (publish_health) ────────────────────────────────────
// Nested: per-sensor {ok,reads,fails,last_error} keyed by driver name
// (sht3x/sht4x/aht20/bme280/bmp280/scd4x/scd30/bh1750/mhz19/hx711/reed),
// per-channel
// {state,pwm,on_time_sec,cycle_count,safety_cutoffs} keyed by channel name,
// plus an expected_missing[] array.
struct SensorHealthView {
    const char* name;
    bool ok;
    uint32_t reads;
    uint32_t fails;
    const char* last_error;  // static string or nullptr
};
struct ChannelHealthView {
    const char* name;
    bool state;
    uint16_t pwm;  // pwm8 for switch, level10 for dim
    uint32_t on_time_sec;
    uint32_t cycle_count;
    uint32_t safety_cutoffs;
};
struct HealthInputs {
    const char* node_id = "";
    const char* type = "";
    uint32_t uptime_sec = 0;
    uint32_t free_heap = 0;
    int32_t wifi_rssi = 0;
    const SensorHealthView* sensors = nullptr;
    int n_sensors = 0;
    const ChannelHealthView* channels = nullptr;  // null/0 ⇒ omit `channels`
    int n_channels = 0;
    const char* const* missing = nullptr;
    int n_missing = 0;
};

inline void build_health(const HealthInputs& in, JsonDocument& doc) {
    doc["node_id"] = in.node_id;
    doc["type"] = in.type;
    doc["uptime_sec"] = in.uptime_sec;
    doc["free_heap"] = in.free_heap;
    doc["wifi_rssi"] = in.wifi_rssi;

    JsonObject sensors = doc["sensors"].to<JsonObject>();
    for (int i = 0; i < in.n_sensors; ++i) {
        const SensorHealthView& s = in.sensors[i];
        JsonObject o = sensors[s.name].to<JsonObject>();
        o["ok"] = s.ok;
        o["reads"] = s.reads;
        o["fails"] = s.fails;
        o["last_error"] = s.last_error;
    }
    if (in.n_channels > 0) {
        JsonObject chans = doc["channels"].to<JsonObject>();
        for (int i = 0; i < in.n_channels; ++i) {
            const ChannelHealthView& c = in.channels[i];
            JsonObject o = chans[c.name].to<JsonObject>();
            o["state"] = c.state;
            o["pwm"] = c.pwm;
            o["on_time_sec"] = c.on_time_sec;
            o["cycle_count"] = c.cycle_count;
            o["safety_cutoffs"] = c.safety_cutoffs;
        }
    }
    JsonArray missing = doc["expected_missing"].to<JsonArray>();
    for (int i = 0; i < in.n_missing; ++i) missing.add(in.missing[i]);
}

// ── log batch entry (log_forward loop) ─────────────────────────
// One entry inside the {"entries":[...],"dropped"?} batch on sporeprint/<id>/
// logs. Keys {ts_ms,level,msg} are the contract the Pi reads.
inline void build_log_entry(JsonObject obj, uint32_t ts_ms, uint8_t level,
                            const char* msg) {
    obj["ts_ms"] = ts_ms;
    obj["level"] = level;
    obj["msg"] = msg;
}

}  // namespace sp
