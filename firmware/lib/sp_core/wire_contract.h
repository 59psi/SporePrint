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

namespace sp {

// Round a float to one decimal place — the telemetry wire precision.
inline float wire_round1(float v) { return roundf(v * 10.0f) / 10.0f; }

// ── telemetry (publish_telemetry) ──────────────────────────────
// Every sensor field is optional: the firmware emits only the ones whose
// sensor is present. `scale_raw` is the uncalibrated HX711 fallback — emitted
// but NOT in SENSOR_FIELDS (the Pi tolerates-but-drops it), mutually exclusive
// with `weight_g`.
struct TelemetryInputs {
    uint32_t ts = 0;  // uptime seconds; the Pi stamps real time

    bool have_temp_rh = false;
    float temp_c = 0.0f;   // raw °C — builder derives temp_f + dew_point_f
    float humidity = 0.0f; // %RH
    float dew_point_f = 0.0f;  // caller-computed °F (Magnus), builder rounds

    bool have_co2 = false;
    uint16_t co2_ppm = 0;

    bool have_lux = false;
    float lux = 0.0f;

    bool have_weight = false;  // HX711 present AND calibrated
    float weight_g = 0.0f;
    bool have_scale_raw = false;  // HX711 present, uncalibrated
    int32_t scale_raw = 0;

    bool have_door = false;
    bool door_open = false;
};

inline void build_telemetry(const TelemetryInputs& in, JsonDocument& doc) {
    doc["ts"] = in.ts;
    if (in.have_temp_rh) {
        float tf = in.temp_c * 9.0f / 5.0f + 32.0f;
        doc["temp_f"] = wire_round1(tf);
        doc["temp_c"] = wire_round1(in.temp_c);
        doc["humidity"] = wire_round1(in.humidity);
        doc["dew_point_f"] = wire_round1(in.dew_point_f);
    }
    if (in.have_co2) doc["co2_ppm"] = in.co2_ppm;
    if (in.have_lux) doc["lux"] = wire_round1(in.lux);
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
// image emits wifi_reconnects (always 0 — core owns WiFi recovery); the cam
// image omits it. `migrated_from` is present only post-migration.
struct HeartbeatInputs {
    uint32_t uptime_sec = 0;
    uint32_t free_heap = 0;
    const char* firmware_version = "";
    int32_t wifi_rssi = 0;
    const char* ip = "";
    int32_t reset_reason = 0;
    bool emit_wifi_reconnects = true;  // node: true, cam: false
    uint32_t mqtt_reconnects = 0;
    const char* type = "";  // node_type_str(personality) | "camera"
    const char* const* roles = nullptr;
    int n_roles = 0;
    const char* fw_image = "";       // "node" | "cam"
    const char* migrated_from = nullptr;  // nullptr/"" ⇒ omitted
};

inline void build_heartbeat(const HeartbeatInputs& in, JsonDocument& doc) {
    doc["uptime_sec"] = in.uptime_sec;
    doc["free_heap"] = in.free_heap;
    doc["firmware_version"] = in.firmware_version;
    doc["wifi_rssi"] = in.wifi_rssi;
    doc["ip"] = in.ip;
    doc["reset_reason"] = in.reset_reason;
    if (in.emit_wifi_reconnects) doc["wifi_reconnects"] = 0;
    doc["mqtt_reconnects"] = in.mqtt_reconnects;
    doc["type"] = in.type;
    JsonArray roles = doc["roles"].to<JsonArray>();
    for (int i = 0; i < in.n_roles; ++i) roles.add(in.roles[i]);
    doc["fw_image"] = in.fw_image;
    if (in.migrated_from != nullptr && in.migrated_from[0] != '\0')
        doc["migrated_from"] = in.migrated_from;
}

// ── health (publish_health) ────────────────────────────────────
// Nested: per-sensor {ok,reads,fails,last_error} keyed by driver name
// (sht3x/sht4x/scd4x/scd30/bh1750/mhz19/hx711/reed), per-channel
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
