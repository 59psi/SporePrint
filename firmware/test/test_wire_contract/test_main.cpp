// test_wire_contract — the device→cloud JSON key contract, compile-checked on
// the firmware side.
//
// Every builder in lib/sp_core/wire_contract.h is exercised here from mock
// inputs, and the EXACT key set + the load-bearing string literals are pinned.
// The composition roots (src/node/main.cpp, src/cam/main.cpp,
// lib/sp_device/log_forward.cpp) call these same builders, so a key rename is a
// firmware test failure — not silent drift caught only if another repo's vitest
// runs at the right submodule SHA.
//
// The canonical key lists below are transcribed from the single sources of
// truth and cross-checked against them:
//   design  frontend/packages/design/src/data/wire.ts (TELEMETRY_KEYS,
//           ALERT_TYPES, COMPONENT_TYPES)
//   Pi      server/app/telemetry/service.py (SENSOR_FIELDS),
//           server/app/mqtt.py (actuator_events: channel/state/pwm/trigger)

#include <unity.h>

#include <ArduinoJson.h>

#include <set>
#include <string>

#include "personality.h"
#include "wire_contract.h"

void setUp() {}
void tearDown() {}

// ── canonical contract (transcribed from the sources named above) ──

// design TELEMETRY_KEYS — sensor fields on a telemetry frame (envelope `ts`
// excluded; `scale_raw` excluded — emitted but not persisted).
static const char* const kTelemetryKeys[] = {
    "temp_f", "temp_c", "humidity", "dew_point_f",
    "co2_ppm", "lux", "weight_g", "door_open"};
// Pi SENSOR_FIELDS — the fields store_bulk_readings actually persists. Must be
// the SAME set as TELEMETRY_KEYS (different declaration order in the Python).
static const char* const kSensorFields[] = {
    "temp_f", "temp_c", "humidity", "co2_ppm",
    "lux", "dew_point_f", "weight_g", "door_open"};
// design ALERT_TYPES — the `type` values emit_alert() may publish.
static const char* const kAlertTypes[] = {
    "temperature", "humidity", "co2", "door", "sensor_failure"};
// design COMPONENT_TYPES — the `type` a node reports in heartbeat/health.
static const char* const kComponentTypes[] = {
    "climate", "relay", "lighting", "camera"};

// ── helpers ────────────────────────────────────────────────────

static std::set<std::string> keys_of(JsonObject obj) {
    std::set<std::string> out;
    for (JsonPair kv : obj) out.insert(kv.key().c_str());
    return out;
}

static void assert_exact_keys(JsonObject obj, const char* const* expected,
                              int n, const char* what) {
    std::set<std::string> actual = keys_of(obj);
    TEST_ASSERT_EQUAL_INT_MESSAGE(n, (int)actual.size(), what);
    for (int i = 0; i < n; ++i) {
        TEST_ASSERT_TRUE_MESSAGE(actual.count(expected[i]) == 1, expected[i]);
    }
}

static bool in_list(const char* const* list, int n, const std::string& k) {
    for (int i = 0; i < n; ++i)
        if (k == list[i]) return true;
    return false;
}

// ── telemetry ──────────────────────────────────────────────────

void test_telemetry_all_present_matches_contract() {
    sp::TelemetryInputs in;
    in.ts = 1234;
    in.have_temp_rh = true;
    in.temp_c = 21.35f;
    in.humidity = 55.5f;
    in.dew_point_f = 51.87f;
    in.have_co2 = true;
    in.co2_ppm = 812;
    in.have_lux = true;
    in.lux = 340.44f;
    in.have_weight = true;
    in.weight_g = 128.44f;
    in.have_door = true;
    in.door_open = true;

    JsonDocument doc;
    sp::build_telemetry(in, doc);
    std::set<std::string> k = keys_of(doc.as<JsonObject>());

    // ts (envelope) + every TELEMETRY_KEY, nothing else.
    TEST_ASSERT_EQUAL_INT(9, (int)k.size());
    TEST_ASSERT_TRUE(k.count("ts") == 1);
    for (const char* key : kTelemetryKeys)
        TEST_ASSERT_TRUE_MESSAGE(k.count(key) == 1, key);
    // The sensor keys (doc minus ts) must equal the Pi SENSOR_FIELDS set.
    for (const std::string& key : k) {
        if (key == "ts") continue;
        TEST_ASSERT_TRUE_MESSAGE(
            in_list(kSensorFields, 8, key),
            "telemetry key not in Pi SENSOR_FIELDS (would be dropped)");
    }

    // Types + rounding (real behavior, not a mock echo).
    TEST_ASSERT_TRUE(doc["door_open"].is<bool>());
    TEST_ASSERT_TRUE(doc["co2_ppm"].is<int>());
    TEST_ASSERT_EQUAL_UINT16(812, doc["co2_ppm"].as<uint16_t>());
    // temp_f = round1(21.35*9/5+32) = round1(70.43) = 70.4
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 70.4f, doc["temp_f"].as<float>());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 21.4f, doc["temp_c"].as<float>());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 55.5f, doc["humidity"].as<float>());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 51.9f, doc["dew_point_f"].as<float>());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 340.4f, doc["lux"].as<float>());
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 128.4f, doc["weight_g"].as<float>());
    TEST_ASSERT_TRUE(doc["door_open"].as<bool>());
}

void test_telemetry_partial_presence_omits_absent_keys() {
    // CO2-only node: no temp/rh, no lux, no scale, no door.
    sp::TelemetryInputs in;
    in.ts = 5;
    in.have_co2 = true;
    in.co2_ppm = 450;

    JsonDocument doc;
    sp::build_telemetry(in, doc);
    std::set<std::string> k = keys_of(doc.as<JsonObject>());
    TEST_ASSERT_EQUAL_INT(2, (int)k.size());  // ts + co2_ppm only
    TEST_ASSERT_TRUE(k.count("ts") == 1);
    TEST_ASSERT_TRUE(k.count("co2_ppm") == 1);
    TEST_ASSERT_FALSE(k.count("temp_f") == 1);
    TEST_ASSERT_FALSE(k.count("door_open") == 1);
}

void test_telemetry_uncalibrated_emits_scale_raw_not_weight() {
    sp::TelemetryInputs in;
    in.ts = 9;
    in.have_scale_raw = true;
    in.scale_raw = -80123;

    JsonDocument doc;
    sp::build_telemetry(in, doc);
    std::set<std::string> k = keys_of(doc.as<JsonObject>());
    TEST_ASSERT_TRUE(k.count("scale_raw") == 1);
    TEST_ASSERT_FALSE(k.count("weight_g") == 1);
    TEST_ASSERT_EQUAL_INT32(-80123, doc["scale_raw"].as<int32_t>());
    // scale_raw is deliberately NOT a persisted sensor field.
    TEST_ASSERT_FALSE(in_list(kSensorFields, 8, "scale_raw"));
}

// ── alert ──────────────────────────────────────────────────────

void test_alert_keys_and_types() {
    JsonDocument doc;
    sp::build_alert("co2", 4200.0f, "CO2 dangerously high!", nullptr, doc);
    const char* expected[] = {"type", "value", "message"};
    assert_exact_keys(doc.as<JsonObject>(), expected, 3, "alert (no sensor)");
    TEST_ASSERT_EQUAL_STRING("co2", doc["type"]);
    TEST_ASSERT_EQUAL_STRING("CO2 dangerously high!", doc["message"]);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 4200.0f, doc["value"].as<float>());

    JsonDocument doc2;
    sp::build_alert("sensor_failure", 0.0f, "Temp/RH sensor read failed",
                    "SHT3x", doc2);
    const char* expected2[] = {"type", "value", "message", "sensor"};
    assert_exact_keys(doc2.as<JsonObject>(), expected2, 4, "alert (sensor)");
    TEST_ASSERT_EQUAL_STRING("SHT3x", doc2["sensor"]);
}

void test_alert_every_firmware_type_is_a_known_alert_type() {
    // Each `type` the firmware's check_alerts/reed paths publish must be a
    // declared ALERT_TYPE the cloud understands.
    const char* fw_types[] = {"temperature", "humidity", "co2",
                              "door", "sensor_failure"};
    for (const char* t : fw_types) {
        JsonDocument doc;
        sp::build_alert(t, 1.0f, "m", nullptr, doc);
        TEST_ASSERT_TRUE_MESSAGE(
            in_list(kAlertTypes, 5, doc["type"].as<const char*>()), t);
    }
}

// ── switch-channel report ──────────────────────────────────────

void test_switch_report_contract() {
    JsonDocument doc;
    sp::build_switch_report("exhaust", true, 180, "command", doc);
    const char* expected[] = {"channel", "state", "pwm", "trigger"};
    assert_exact_keys(doc.as<JsonObject>(), expected, 4, "switch report");
    TEST_ASSERT_EQUAL_STRING("exhaust", doc["channel"]);
    TEST_ASSERT_EQUAL_STRING("on", doc["state"]);  // literal, not bool
    TEST_ASSERT_EQUAL_INT(180, doc["pwm"].as<int>());
    TEST_ASSERT_EQUAL_STRING("command", doc["trigger"]);

    JsonDocument off;
    sp::build_switch_report("fae", false, 0, "safety_cutoff", off);
    TEST_ASSERT_EQUAL_STRING("off", off["state"]);
    TEST_ASSERT_EQUAL_STRING("safety_cutoff", off["trigger"]);
}

// ── dim-levels (pins the "feed with no writer" asymmetry) ──────

void test_dim_levels_keyed_by_channel_name_and_not_persisted() {
    sp::ChannelConfig cfgs[4];
    int n = sp::personality_channels(sp::Personality::LightingBank, cfgs);
    TEST_ASSERT_EQUAL_INT(4, n);
    sp::DimLevel levels[4];
    for (int i = 0; i < 4; ++i) {
        levels[i].name = cfgs[i].name;
        levels[i].level = (uint16_t)(100 * (i + 1));
    }
    JsonDocument doc;
    sp::build_dim_levels(levels, 4, doc);
    std::set<std::string> k = keys_of(doc.as<JsonObject>());
    TEST_ASSERT_EQUAL_INT(4, (int)k.size());
    const char* names[] = {"white", "blue", "red", "far_red"};
    for (const char* nm : names) {
        TEST_ASSERT_TRUE_MESSAGE(k.count(nm) == 1, nm);
        // Documented drop: dim channel names are NOT SENSOR_FIELDS, so the Pi
        // forwards them live but never persists them to telemetry history.
        TEST_ASSERT_FALSE(in_list(kSensorFields, 8, nm));
    }
    TEST_ASSERT_EQUAL_UINT16(100, doc["white"].as<uint16_t>());
    TEST_ASSERT_EQUAL_UINT16(400, doc["far_red"].as<uint16_t>());
}

// ── heartbeat ──────────────────────────────────────────────────

static sp::HeartbeatInputs node_hb_inputs(const char** roles, int n_roles) {
    sp::HeartbeatInputs in;
    in.uptime_sec = 3600;
    in.free_heap = 200000;
    in.firmware_version = "2.0.0";
    in.wifi_rssi = -55;
    in.ip = "192.168.1.42";
    in.reset_reason = 1;
    in.emit_wifi_reconnects = true;
    in.mqtt_reconnects = 3;
    in.type = "relay";
    in.roles = roles;
    in.n_roles = n_roles;
    in.fw_image = "node";
    return in;
}

void test_node_heartbeat_contract() {
    const char* roles[] = {"climate", "relay"};
    sp::HeartbeatInputs in = node_hb_inputs(roles, 2);
    JsonDocument doc;
    sp::build_heartbeat(in, doc);
    const char* expected[] = {"uptime_sec",      "free_heap",
                              "firmware_version", "wifi_rssi",
                              "ip",              "reset_reason",
                              "wifi_reconnects", "mqtt_reconnects",
                              "type",            "roles",
                              "fw_image"};
    assert_exact_keys(doc.as<JsonObject>(), expected, 11,
                      "node heartbeat (no migration)");
    TEST_ASSERT_EQUAL_STRING("node", doc["fw_image"]);
    TEST_ASSERT_TRUE_MESSAGE(in_list(kComponentTypes, 4, doc["type"].as<const char*>()),
                             "heartbeat type must be a COMPONENT_TYPE");
    TEST_ASSERT_EQUAL_INT(0, doc["wifi_reconnects"].as<int>());
    TEST_ASSERT_EQUAL_INT(3, doc["mqtt_reconnects"].as<int>());
    // roles array carries the transcribed capability set.
    JsonArray r = doc["roles"].as<JsonArray>();
    TEST_ASSERT_EQUAL_INT(2, (int)r.size());
    TEST_ASSERT_EQUAL_STRING("climate", r[0]);
    TEST_ASSERT_EQUAL_STRING("relay", r[1]);
}

void test_node_heartbeat_migrated_from_appears_only_when_set() {
    const char* roles[] = {"lighting"};
    sp::HeartbeatInputs in = node_hb_inputs(roles, 1);
    in.migrated_from = "lighting";
    JsonDocument doc;
    sp::build_heartbeat(in, doc);
    TEST_ASSERT_TRUE(keys_of(doc.as<JsonObject>()).count("migrated_from") == 1);
    TEST_ASSERT_EQUAL_STRING("lighting", doc["migrated_from"]);

    // Empty string must be treated as unset (omitted).
    in.migrated_from = "";
    JsonDocument doc2;
    sp::build_heartbeat(in, doc2);
    TEST_ASSERT_FALSE(keys_of(doc2.as<JsonObject>()).count("migrated_from") == 1);
}

void test_cam_heartbeat_omits_wifi_reconnects_and_pins_literals() {
    const char* roles[] = {"camera"};
    sp::HeartbeatInputs in;
    in.uptime_sec = 10;
    in.free_heap = 100;
    in.firmware_version = "2.0.0";
    in.wifi_rssi = -60;
    in.ip = "10.0.0.9";
    in.reset_reason = 0;
    in.emit_wifi_reconnects = false;  // cam distinction
    in.mqtt_reconnects = 0;
    in.type = "camera";
    in.roles = roles;
    in.n_roles = 1;
    in.fw_image = "cam";

    JsonDocument doc;
    sp::build_heartbeat(in, doc);
    std::set<std::string> k = keys_of(doc.as<JsonObject>());
    TEST_ASSERT_FALSE_MESSAGE(k.count("wifi_reconnects") == 1,
                              "cam heartbeat must NOT emit wifi_reconnects");
    TEST_ASSERT_EQUAL_STRING("camera", doc["type"]);
    TEST_ASSERT_EQUAL_STRING("cam", doc["fw_image"]);
    TEST_ASSERT_TRUE(in_list(kComponentTypes, 4, "camera"));
}

// ── health ─────────────────────────────────────────────────────

void test_node_health_contract_with_sensors_and_channels() {
    sp::SensorHealthView sensors[] = {
        {"sht3x", true, 120, 0, nullptr},
        {"scd4x", false, 55, 3, "bus write rejected"},
    };
    sp::ChannelHealthView channels[] = {
        {"fae", true, 200, 42, 7, 1},
    };
    const char* missing[] = {"hx711"};
    sp::HealthInputs in;
    in.node_id = "relay-01";
    in.type = "relay";
    in.uptime_sec = 7200;
    in.free_heap = 180000;
    in.wifi_rssi = -50;
    in.sensors = sensors;
    in.n_sensors = 2;
    in.channels = channels;
    in.n_channels = 1;
    in.missing = missing;
    in.n_missing = 1;

    JsonDocument doc;
    sp::build_health(in, doc);
    const char* top[] = {"node_id", "type",     "uptime_sec",
                         "free_heap", "wifi_rssi", "sensors",
                         "channels", "expected_missing"};
    assert_exact_keys(doc.as<JsonObject>(), top, 8, "health top-level");
    TEST_ASSERT_TRUE(in_list(kComponentTypes, 4, doc["type"].as<const char*>()));

    // Sensor sub-object keyed by driver name, with the fixed sub-keys.
    JsonObject sobj = doc["sensors"].as<JsonObject>();
    TEST_ASSERT_TRUE(keys_of(sobj).count("sht3x") == 1);
    TEST_ASSERT_TRUE(keys_of(sobj).count("scd4x") == 1);
    const char* sub[] = {"ok", "reads", "fails", "last_error"};
    assert_exact_keys(doc["sensors"]["scd4x"].as<JsonObject>(), sub, 4,
                      "sensor health sub-keys");
    TEST_ASSERT_TRUE(doc["sensors"]["sht3x"]["ok"].as<bool>());
    TEST_ASSERT_FALSE(doc["sensors"]["scd4x"]["ok"].as<bool>());
    TEST_ASSERT_EQUAL_STRING("bus write rejected",
                             doc["sensors"]["scd4x"]["last_error"]);

    // Channel sub-object keyed by channel name.
    const char* csub[] = {"state", "pwm", "on_time_sec", "cycle_count",
                          "safety_cutoffs"};
    assert_exact_keys(doc["channels"]["fae"].as<JsonObject>(), csub, 5,
                      "channel health sub-keys");
    TEST_ASSERT_TRUE(doc["channels"]["fae"]["state"].as<bool>());
    TEST_ASSERT_EQUAL_INT(1, doc["channels"]["fae"]["safety_cutoffs"].as<int>());

    JsonArray miss = doc["expected_missing"].as<JsonArray>();
    TEST_ASSERT_EQUAL_INT(1, (int)miss.size());
    TEST_ASSERT_EQUAL_STRING("hx711", miss[0]);
}

void test_climate_health_omits_channels_object() {
    // A sensors-only (climate) node has no channel bank — `channels` absent.
    sp::SensorHealthView sensors[] = {{"sht4x", true, 10, 0, nullptr}};
    sp::HealthInputs in;
    in.node_id = "climate-01";
    in.type = "climate";
    in.sensors = sensors;
    in.n_sensors = 1;
    in.n_channels = 0;

    JsonDocument doc;
    sp::build_health(in, doc);
    std::set<std::string> k = keys_of(doc.as<JsonObject>());
    TEST_ASSERT_FALSE_MESSAGE(k.count("channels") == 1,
                              "climate node must not emit a channels object");
    TEST_ASSERT_TRUE(k.count("sensors") == 1);
    TEST_ASSERT_TRUE(k.count("expected_missing") == 1);
}

// ── log batch entry ────────────────────────────────────────────

void test_log_entry_contract() {
    JsonDocument doc;
    JsonArray entries = doc["entries"].to<JsonArray>();
    JsonObject obj = entries.add<JsonObject>();
    sp::build_log_entry(obj, 123456u, 2 /* LOG_WARN */, "reconnected");
    const char* expected[] = {"ts_ms", "level", "msg"};
    assert_exact_keys(obj, expected, 3, "log entry");
    TEST_ASSERT_EQUAL_UINT32(123456u, obj["ts_ms"].as<uint32_t>());
    TEST_ASSERT_EQUAL_INT(2, obj["level"].as<int>());
    TEST_ASSERT_EQUAL_STRING("reconnected", obj["msg"]);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_telemetry_all_present_matches_contract);
    RUN_TEST(test_telemetry_partial_presence_omits_absent_keys);
    RUN_TEST(test_telemetry_uncalibrated_emits_scale_raw_not_weight);
    RUN_TEST(test_alert_keys_and_types);
    RUN_TEST(test_alert_every_firmware_type_is_a_known_alert_type);
    RUN_TEST(test_switch_report_contract);
    RUN_TEST(test_dim_levels_keyed_by_channel_name_and_not_persisted);
    RUN_TEST(test_node_heartbeat_contract);
    RUN_TEST(test_node_heartbeat_migrated_from_appears_only_when_set);
    RUN_TEST(test_cam_heartbeat_omits_wifi_reconnects_and_pins_literals);
    RUN_TEST(test_node_health_contract_with_sensors_and_channels);
    RUN_TEST(test_climate_health_omits_channels_object);
    RUN_TEST(test_log_entry_contract);
    return UNITY_END();
}
