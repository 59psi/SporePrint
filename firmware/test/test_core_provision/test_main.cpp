// test_core_provision — the captive portal's /save policy and the cmd/config
// peripheral switch (sp_core/provisioning.h). The portal itself is
// Arduino-only (WebServer); every decision it makes lives here.
//
// Regressions pinned here (hardware audit):
//   docs#0 / fw-node#0 — the MH-Z19C / HX711 / reed enable flags had no
//     writer at all (no portal field, no command), so those drivers never ran
//   fw-node#10 — any node_id was accepted and never tied to the MQTT
//     username the broker ACL scopes by (%u): silent deny-all
//   fw-node#14 — Secure MQTT + an IP-literal broker host needs the IP on the
//     Pi's certificate; the portal must be able to recognise the case
//   fw-node#18 — stored values were injected into the form unescaped, and a
//     blank WiFi password wiped the stored one

#include <unity.h>

#include <ArduinoJson.h>

#include <string>

#include "provisioning.h"

void setUp() {}
void tearDown() {}

// ── HTML escaping (fw-node#18) ─────────────────────────────────

void test_html_escape_neutralises_attribute_breakers() {
    TEST_ASSERT_EQUAL_STRING("Bob&#39;s Lab", sp::html_escape("Bob's Lab").c_str());
    TEST_ASSERT_EQUAL_STRING("a&amp;b &lt;i&gt; &quot;q&quot;",
                             sp::html_escape("a&b <i> \"q\"").c_str());
    TEST_ASSERT_EQUAL_STRING("plain-ssid_01", sp::html_escape("plain-ssid_01").c_str());
    TEST_ASSERT_EQUAL_STRING("", sp::html_escape("").c_str());
    // Already-escaped text is escaped again (it is data, not markup).
    TEST_ASSERT_EQUAL_STRING("&amp;amp;", sp::html_escape("&amp;").c_str());
}

// ── WiFi password (fw-node#18) ─────────────────────────────────

void test_blank_wifi_password_keeps_the_stored_one_on_the_same_network() {
    // Re-opening the portal to change the Pi address must not erase the
    // WiFi password (every other secret field already keeps its value).
    TEST_ASSERT_EQUAL_STRING(
        "hunter2hunter2",
        sp::resolve_wifi_pass("Home", "hunter2hunter2", "Home", "", false).c_str());
}

void test_typed_wifi_password_replaces_the_stored_one() {
    TEST_ASSERT_EQUAL_STRING(
        "newpassword1",
        sp::resolve_wifi_pass("Home", "old", "Home", "newpassword1", false).c_str());
}

void test_blank_password_on_a_new_network_means_open() {
    // The stored password belongs to the old SSID — never carry it over.
    TEST_ASSERT_EQUAL_STRING(
        "", sp::resolve_wifi_pass("Home", "old-secret", "Cafe", "", false).c_str());
    // First provisioning: nothing stored, blank = open network.
    TEST_ASSERT_EQUAL_STRING("", sp::resolve_wifi_pass("", "", "Home", "", false).c_str());
}

void test_open_network_checkbox_clears_the_password() {
    TEST_ASSERT_EQUAL_STRING(
        "", sp::resolve_wifi_pass("Home", "old-secret", "Home", "", true).c_str());
    // Explicit "open" wins even over a typed password.
    TEST_ASSERT_EQUAL_STRING(
        "", sp::resolve_wifi_pass("Home", "old", "Home", "typed", true).c_str());
}

// ── node id (fw-node#10) ───────────────────────────────────────

void test_node_id_charset_matches_the_server_regex() {
    // server/app/hardware/service.py NODE_ID_RE = ^[a-zA-Z0-9_-]{1,32}$
    TEST_ASSERT_TRUE(sp::node_id_valid("climate-01"));
    TEST_ASSERT_TRUE(sp::node_id_valid("Relay_2"));
    TEST_ASSERT_TRUE(sp::node_id_valid("a"));
    TEST_ASSERT_TRUE(sp::node_id_valid(std::string(32, 'x')));
    TEST_ASSERT_FALSE(sp::node_id_valid(""));
    TEST_ASSERT_FALSE(sp::node_id_valid(std::string(33, 'x')));
    TEST_ASSERT_FALSE(sp::node_id_valid("closet.relay"));
    TEST_ASSERT_FALSE(sp::node_id_valid("my node"));
    // MQTT wildcards / level separator would corrupt every topic.
    TEST_ASSERT_FALSE(sp::node_id_valid("relay+"));
    TEST_ASSERT_FALSE(sp::node_id_valid("relay#"));
    TEST_ASSERT_FALSE(sp::node_id_valid("a/b"));
}

void test_blank_node_id_defaults_to_the_mqtt_username() {
    // The build guide's "accept the default" must land on the identity the
    // broker ACL (%u) actually grants.
    std::string out;
    const char* err = sp::resolve_node_id("", "climate-01", "node-ab12", &out);
    TEST_ASSERT_NULL(err);
    TEST_ASSERT_EQUAL_STRING("climate-01", out.c_str());
}

void test_blank_node_id_without_username_keeps_the_fallback() {
    std::string out;
    const char* err = sp::resolve_node_id("", "", "node-ab12", &out);
    TEST_ASSERT_NULL(err);
    TEST_ASSERT_EQUAL_STRING("node-ab12", out.c_str());
}

void test_node_id_that_differs_from_the_username_is_refused() {
    std::string out = "unchanged";
    const char* err = sp::resolve_node_id("node-ab12", "climate-01", "node-ab12", &out);
    TEST_ASSERT_NOT_NULL(err);
    TEST_ASSERT_EQUAL_STRING("unchanged", out.c_str());
}

void test_matching_node_id_and_username_accepted() {
    std::string out;
    TEST_ASSERT_NULL(sp::resolve_node_id("relay-01", "relay-01", "node-ab12", &out));
    TEST_ASSERT_EQUAL_STRING("relay-01", out.c_str());
    // No username (anonymous dev broker): any valid id is fine.
    TEST_ASSERT_NULL(sp::resolve_node_id("bench_node", "", "node-ab12", &out));
    TEST_ASSERT_EQUAL_STRING("bench_node", out.c_str());
}

void test_invalid_node_id_is_refused_even_without_username() {
    std::string out;
    TEST_ASSERT_NOT_NULL(sp::resolve_node_id("closet.relay", "", "node-ab12", &out));
    TEST_ASSERT_NOT_NULL(sp::resolve_node_id("a/b", "", "node-ab12", &out));
    TEST_ASSERT_NOT_NULL(sp::resolve_node_id(std::string(33, 'n'), "", "x", &out));
    // A username that could never be a valid topic segment is refused too
    // (it would have to BE the node id).
    TEST_ASSERT_NOT_NULL(sp::resolve_node_id("", "bad user", "node-ab12", &out));
}

// ── IPv4 literal detection (fw-node#14) ────────────────────────

void test_ipv4_literal_detection() {
    TEST_ASSERT_TRUE(sp::is_ipv4_literal("192.168.1.50"));
    TEST_ASSERT_TRUE(sp::is_ipv4_literal("10.0.0.1"));
    TEST_ASSERT_TRUE(sp::is_ipv4_literal("255.255.255.255"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("sporeprint.local"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("256.1.1.1"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("1.2.3"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("1.2.3.4.5"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("1..3.4"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("10.0.0.1a"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal("1234.1.1.1"));
    TEST_ASSERT_FALSE(sp::is_ipv4_literal(""));
}

// ── peripheral enable command (docs#0 / fw-node#0) ─────────────

static sp::PeripheralCmdResult apply(const char* json, sp::PeripheralFlags* f) {
    JsonDocument doc;
    TEST_ASSERT_FALSE(deserializeJson(doc, json));
    return sp::apply_peripheral_cmd(doc["peripherals"], f);
}

void test_peripherals_enable_each_flag() {
    sp::PeripheralFlags f;  // all off — the NVS default
    sp::PeripheralCmdResult r =
        apply("{\"peripherals\":{\"mhz19\":true,\"hx711\":true,\"reed\":true}}", &f);
    TEST_ASSERT_TRUE(r.is_object);
    TEST_ASSERT_TRUE(r.changed);
    TEST_ASSERT_EQUAL_INT(3, r.applied);
    TEST_ASSERT_EQUAL_INT(0, r.ignored);
    TEST_ASSERT_TRUE(f.mhz19);
    TEST_ASSERT_TRUE(f.hx711);
    TEST_ASSERT_TRUE(f.reed);
}

void test_peripherals_partial_update_leaves_other_flags() {
    sp::PeripheralFlags f;
    f.mhz19 = true;
    f.reed = true;
    sp::PeripheralCmdResult r = apply("{\"peripherals\":{\"hx711\":true}}", &f);
    TEST_ASSERT_TRUE(r.changed);
    TEST_ASSERT_TRUE(f.mhz19);
    TEST_ASSERT_TRUE(f.hx711);
    TEST_ASSERT_TRUE(f.reed);
    r = apply("{\"peripherals\":{\"reed\":false}}", &f);
    TEST_ASSERT_TRUE(r.changed);
    TEST_ASSERT_FALSE(f.reed);
    TEST_ASSERT_TRUE(f.hx711);
}

void test_peripherals_same_values_report_unchanged() {
    // A repeated / retained command must not trigger a reboot loop.
    sp::PeripheralFlags f;
    f.hx711 = true;
    sp::PeripheralCmdResult r =
        apply("{\"peripherals\":{\"hx711\":true,\"reed\":false}}", &f);
    TEST_ASSERT_TRUE(r.is_object);
    TEST_ASSERT_FALSE(r.changed);
    TEST_ASSERT_EQUAL_INT(2, r.applied);
}

void test_peripherals_ignore_non_bool_and_unknown_keys() {
    sp::PeripheralFlags f;
    sp::PeripheralCmdResult r = apply(
        "{\"peripherals\":{\"hx711\":1,\"reed\":\"yes\",\"scd41\":true,"
        "\"mhz19\":true}}",
        &f);
    TEST_ASSERT_TRUE(r.is_object);
    TEST_ASSERT_EQUAL_INT(1, r.applied);
    TEST_ASSERT_EQUAL_INT(3, r.ignored);
    TEST_ASSERT_TRUE(f.mhz19);
    TEST_ASSERT_FALSE(f.hx711);  // 1 is not a boolean — never coerced
    TEST_ASSERT_FALSE(f.reed);
    TEST_ASSERT_TRUE(r.changed);
}

void test_peripherals_non_object_is_rejected_without_changes() {
    sp::PeripheralFlags f;
    sp::PeripheralCmdResult r = apply("{\"peripherals\":true}", &f);
    TEST_ASSERT_FALSE(r.is_object);
    TEST_ASSERT_FALSE(r.changed);
    TEST_ASSERT_FALSE(f.mhz19 || f.hx711 || f.reed);
    r = apply("{\"peripherals\":[\"hx711\"]}", &f);
    TEST_ASSERT_FALSE(r.is_object);
    TEST_ASSERT_FALSE(r.changed);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_html_escape_neutralises_attribute_breakers);
    RUN_TEST(test_blank_wifi_password_keeps_the_stored_one_on_the_same_network);
    RUN_TEST(test_typed_wifi_password_replaces_the_stored_one);
    RUN_TEST(test_blank_password_on_a_new_network_means_open);
    RUN_TEST(test_open_network_checkbox_clears_the_password);
    RUN_TEST(test_node_id_charset_matches_the_server_regex);
    RUN_TEST(test_blank_node_id_defaults_to_the_mqtt_username);
    RUN_TEST(test_blank_node_id_without_username_keeps_the_fallback);
    RUN_TEST(test_node_id_that_differs_from_the_username_is_refused);
    RUN_TEST(test_matching_node_id_and_username_accepted);
    RUN_TEST(test_invalid_node_id_is_refused_even_without_username);
    RUN_TEST(test_ipv4_literal_detection);
    RUN_TEST(test_peripherals_enable_each_flag);
    RUN_TEST(test_peripherals_partial_update_leaves_other_flags);
    RUN_TEST(test_peripherals_same_values_report_unchanged);
    RUN_TEST(test_peripherals_ignore_non_bool_and_unknown_keys);
    RUN_TEST(test_peripherals_non_object_is_rejected_without_changes);
    return UNITY_END();
}
