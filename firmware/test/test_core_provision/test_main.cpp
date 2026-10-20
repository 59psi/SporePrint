// test_core_provision — the captive portal's /save policy and the cmd/config
// peripheral switch (sp_core/provisioning.h). The portal itself is
// Arduino-only (WebServer); every decision it makes lives here.
//
// Regressions pinned here:
//   the MH-Z19C / HX711 / reed enable flags had no writer at all (no portal
//     field, no command), so those drivers never ran
//   any node_id was accepted and never tied to the MQTT username the broker
//     ACL scopes by (%u): silent deny-all
//   Secure MQTT + an IP-literal broker host needs the IP on the Pi's
//     certificate; the portal must be able to recognise the case
//   stored values were injected into the form unescaped, and a blank WiFi
//     password wiped the stored one

#include <unity.h>

#include <ArduinoJson.h>

#include <string>

#include "provisioning.h"

void setUp() {}
void tearDown() {}

// ── HTML escaping ──────────────────────────────────────────────

void test_html_escape_neutralises_attribute_breakers() {
    TEST_ASSERT_EQUAL_STRING("Bob&#39;s Lab", sp::html_escape("Bob's Lab").c_str());
    TEST_ASSERT_EQUAL_STRING("a&amp;b &lt;i&gt; &quot;q&quot;",
                             sp::html_escape("a&b <i> \"q\"").c_str());
    TEST_ASSERT_EQUAL_STRING("plain-ssid_01", sp::html_escape("plain-ssid_01").c_str());
    TEST_ASSERT_EQUAL_STRING("", sp::html_escape("").c_str());
    // Already-escaped text is escaped again (it is data, not markup).
    TEST_ASSERT_EQUAL_STRING("&amp;amp;", sp::html_escape("&amp;").c_str());
}

// ── WiFi password ──────────────────────────────────────────────

void test_resolve_wifi_pass() {
    struct {
        const char* label;
        const char* stored_ssid;
        const char* stored_pass;
        const char* new_ssid;
        const char* form_pass;
        bool open_network;
        const char* want;
    } cases[] = {
        // Re-opening the portal to change the Pi address must not erase the
        // WiFi password (every other secret field already keeps its value).
        {"blank keeps the stored one on the same network", "Home", "hunter2hunter2",
         "Home", "", false, "hunter2hunter2"},
        {"typed replaces the stored one", "Home", "old", "Home", "newpassword1",
         false, "newpassword1"},
        // The stored password belongs to the old SSID: never carry it over.
        {"blank on a new network is open", "Home", "old-secret", "Cafe", "", false,
         ""},
        {"first provisioning, blank is open", "", "", "Home", "", false, ""},
        {"open-network box clears it", "Home", "old-secret", "Home", "", true, ""},
        {"open-network box beats a typed one", "Home", "old", "Home", "typed", true,
         ""},
    };
    for (auto& c : cases)
        TEST_ASSERT_EQUAL_STRING_MESSAGE(
            c.want,
            sp::resolve_wifi_pass(c.stored_ssid, c.stored_pass, c.new_ssid,
                                  c.form_pass, c.open_network)
                .c_str(),
            c.label);
}

// ── node id ────────────────────────────────────────────────────

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

// The broker ACL scopes every node to topics under its own MQTT username
// (%u): when a username is set the node id must BE it (any other id was
// accepted and silently denied everything), and a blank id takes it — the
// build guide's "accept the default" lands on the identity the ACL grants.
void test_resolve_node_id() {
    const std::string too_long(33, 'n');
    struct {
        const char* label;
        std::string form_id;
        const char* mqtt_user;
        const char* fallback;
        const char* want;  // nullptr: refused, *out untouched
    } cases[] = {
        {"blank takes the MQTT username", "", "climate-01", "node-ab12", "climate-01"},
        {"blank, no username: the fallback", "", "", "node-ab12", "node-ab12"},
        {"equal to the username", "relay-01", "relay-01", "node-ab12", "relay-01"},
        {"anonymous broker: any valid id", "bench_node", "", "node-ab12", "bench_node"},
        {"differs from the username", "node-ab12", "climate-01", "node-ab12", nullptr},
        {"invalid charset", "closet.relay", "", "node-ab12", nullptr},
        {"topic separator", "a/b", "", "node-ab12", nullptr},
        {"33 characters", too_long, "", "x", nullptr},
        // A username that could never be a topic segment (it would have to
        // BE the node id).
        {"invalid username", "", "bad user", "node-ab12", nullptr},
    };
    for (auto& c : cases) {
        std::string out = "unchanged";
        const char* err = sp::resolve_node_id(c.form_id, c.mqtt_user, c.fallback, &out);
        if (c.want != nullptr) {
            TEST_ASSERT_NULL_MESSAGE(err, c.label);
            TEST_ASSERT_EQUAL_STRING_MESSAGE(c.want, out.c_str(), c.label);
        } else {
            TEST_ASSERT_NOT_NULL_MESSAGE(err, c.label);
            TEST_ASSERT_EQUAL_STRING_MESSAGE("unchanged", out.c_str(), c.label);
        }
    }
}

// ── v1 → v2 migration keeps the node's identity ────────────────
// No v1 image ever wrote node_id: each ran as its role's hard-coded
// default. Migrating only a stored id turned every v1 node into a new
// MAC-derived node-XXXX.

void test_migrated_node_id_keeps_the_v1_identity() {
    struct {
        const char* v1_node_id;
        const char* v1_mqtt_user;
        const char* v1_namespace;
        const char* want;
    } cases[] = {
        // No stored id: the role's hard-coded v1 default.
        {"", "", "relay", "relay-01"},
        {"", "", "lighting", "light-01"},
        {"", "", "climate", "climate-01"},
        {"", "", "camera", "cam-01"},
        // Unknown namespace: nothing to keep (the MAC-derived default).
        {"", "", "wifi", ""},
        {"", "", nullptr, ""},
        // A hand-written v1 node_id is what that node ran as.
        {"relay-07", "", "relay", "relay-07"},
        {"relay-07", "tent-a", "relay", "relay-07"},
        // No stored id but an MQTT username: the identity the broker's ACL
        // scopes the node to, which the v2 portal enforces.
        {"", "tent-a", "relay", "tent-a"},
        // Ids that could never be a topic segment fall through.
        {"bad/id", "tent-a", "relay", "tent-a"},
        {"", "bad user", "lighting", "light-01"},
    };
    for (auto& c : cases) {
        const std::string label = std::string(c.v1_node_id) + " | " + c.v1_mqtt_user +
                                  " | " + (c.v1_namespace ? c.v1_namespace : "null");
        TEST_ASSERT_EQUAL_STRING_MESSAGE(
            c.want, sp::migrated_node_id(c.v1_node_id, c.v1_mqtt_user, c.v1_namespace).c_str(),
            label.c_str());
    }
    TEST_ASSERT_NULL(sp::legacy_default_node_id("spnode"));
    // Every kept default passes the server's NODE_ID_RE.
    const char* namespaces[] = {"climate", "relay", "lighting", "camera"};
    for (const char* ns : namespaces)
        TEST_ASSERT_TRUE(sp::node_id_valid(sp::migrated_node_id("", "", ns)));
}

// ── IPv4 literal detection ─────────────────────────────────────

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

// A camera's stored server_url (an MQTT command, a v1 migration) used to
// survive re-provisioning: after the operator typed the Pi's NEW address in
// the portal the camera kept uploading to the old one. A changed Pi address
// now clears the stored URL; an unchanged one (any case) keeps it.
void test_portal_pi_address_change_resets_the_camera_upload_url() {
    TEST_ASSERT_TRUE(sp::portal_save_resets_server_url("192.168.1.50",
                                                       "192.168.1.60"));
    TEST_ASSERT_TRUE(sp::portal_save_resets_server_url("sporeprint.local",
                                                       "192.168.1.60"));
    TEST_ASSERT_TRUE(sp::portal_save_resets_server_url("192.168.1.5",
                                                       "192.168.1.50"));
    TEST_ASSERT_FALSE(sp::portal_save_resets_server_url("192.168.1.50",
                                                        "192.168.1.50"));
    TEST_ASSERT_FALSE(sp::portal_save_resets_server_url("SporePrint.local",
                                                        "sporeprint.local"));
}

// ── peripheral enable command ──────────────────────────────────

// cmd/config {"peripherals": {...}}: the MH-Z19C / HX711 / reed enable flags
// had no writer at all, so those drivers never ran. Only JSON booleans
// apply (never coerced); a changed driver set (mhz19 / hx711 / reed) needs a
// reboot, the reed's level-invert option (reed_inv: a door contact wired on
// its NO lead) applies live, and a repeated / retained command changes
// nothing, so it cannot cause a reboot loop.
void test_peripherals_cmd() {
    struct Flags {
        bool mhz19, hx711, reed, reed_inv;
    };
    struct {
        const char* label;
        Flags before;
        const char* value;  // the "peripherals" member
        bool is_object, changed, restart_needed;
        int applied, ignored;
        Flags after;
    } cases[] = {
        {"enable each driver", {0, 0, 0, 0},
         "{\"mhz19\":true,\"hx711\":true,\"reed\":true}", 1, 1, 1, 3, 0, {1, 1, 1, 0}},
        {"partial update leaves the rest", {1, 0, 1, 0}, "{\"hx711\":true}",
         1, 1, 1, 1, 0, {1, 1, 1, 0}},
        {"disable one", {1, 1, 1, 0}, "{\"reed\":false}", 1, 1, 1, 1, 0, {1, 1, 0, 0}},
        {"same values: unchanged, no reboot", {0, 1, 0, 0},
         "{\"hx711\":true,\"reed\":false}", 1, 0, 0, 2, 0, {0, 1, 0, 0}},
        {"non-booleans and unknown keys ignored", {0, 0, 0, 0},
         "{\"hx711\":1,\"reed\":\"yes\",\"scd41\":true,\"mhz19\":true}", 1, 1, 1, 1, 3,
         {1, 0, 0, 0}},
        {"not an object: true", {0, 0, 0, 0}, "true", 0, 0, 0, 0, 0, {0, 0, 0, 0}},
        {"not an object: array", {0, 0, 0, 0}, "[\"hx711\"]", 0, 0, 0, 0, 0,
         {0, 0, 0, 0}},
        {"reed_inv applies live", {0, 0, 1, 0}, "{\"reed_inv\":true}", 1, 1, 0, 1, 0,
         {0, 0, 1, 1}},
        {"reed_inv again: nothing to do", {0, 0, 1, 1}, "{\"reed_inv\":true}",
         1, 0, 0, 1, 0, {0, 0, 1, 1}},
        {"reed_inv non-boolean ignored", {0, 0, 1, 1}, "{\"reed_inv\":0}", 1, 0, 0, 0, 1,
         {0, 0, 1, 1}},
        {"reed + reed_inv: the reed driver must be built", {0, 0, 0, 0},
         "{\"reed\":true,\"reed_inv\":true}", 1, 1, 1, 2, 0, {0, 0, 1, 1}},
        {"hx711 on: reboot", {0, 0, 1, 1}, "{\"hx711\":true}", 1, 1, 1, 1, 0,
         {0, 1, 1, 1}},
    };
    for (auto& c : cases) {
        sp::PeripheralFlags f;
        f.mhz19 = c.before.mhz19;
        f.hx711 = c.before.hx711;
        f.reed = c.before.reed;
        f.reed_inv = c.before.reed_inv;
        JsonDocument doc;
        const std::string json = std::string("{\"peripherals\":") + c.value + "}";
        TEST_ASSERT_FALSE_MESSAGE(deserializeJson(doc, json), c.label);
        sp::PeripheralCmdResult r = sp::apply_peripheral_cmd(doc["peripherals"], &f);
        TEST_ASSERT_EQUAL_MESSAGE(c.is_object, r.is_object, c.label);
        TEST_ASSERT_EQUAL_MESSAGE(c.changed, r.changed, c.label);
        TEST_ASSERT_EQUAL_MESSAGE(c.restart_needed, r.restart_needed, c.label);
        TEST_ASSERT_EQUAL_INT_MESSAGE(c.applied, r.applied, c.label);
        TEST_ASSERT_EQUAL_INT_MESSAGE(c.ignored, r.ignored, c.label);
        TEST_ASSERT_EQUAL_MESSAGE(c.after.mhz19, f.mhz19, c.label);
        TEST_ASSERT_EQUAL_MESSAGE(c.after.hx711, f.hx711, c.label);
        TEST_ASSERT_EQUAL_MESSAGE(c.after.reed, f.reed, c.label);
        TEST_ASSERT_EQUAL_MESSAGE(c.after.reed_inv, f.reed_inv, c.label);
    }
    // The NVS default is every peripheral off, LOW-closed reed.
    sp::PeripheralFlags d;
    TEST_ASSERT_FALSE(d.mhz19 || d.hx711 || d.reed || d.reed_inv);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_html_escape_neutralises_attribute_breakers);
    RUN_TEST(test_resolve_wifi_pass);
    RUN_TEST(test_node_id_charset_matches_the_server_regex);
    RUN_TEST(test_resolve_node_id);
    RUN_TEST(test_migrated_node_id_keeps_the_v1_identity);
    RUN_TEST(test_ipv4_literal_detection);
    RUN_TEST(test_portal_pi_address_change_resets_the_camera_upload_url);
    RUN_TEST(test_peripherals_cmd);
    return UNITY_END();
}
