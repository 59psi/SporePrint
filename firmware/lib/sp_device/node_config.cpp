#include "node_config.h"

#include <WiFi.h>

namespace sp_device {

namespace {

std::string default_node_id() {
    uint8_t mac[6];
    WiFi.macAddress(mac);
    char buf[16];
    snprintf(buf, sizeof(buf), "node-%02x%02x", mac[4], mac[5]);
    return std::string(buf);
}

}  // namespace

NodeConfig NodeConfig::load(sp::KvStore& kv) {
    NodeConfig c;
    c.ssid = kv.get_string("ssid", "");
    c.pass = kv.get_string("pass", "");
    c.broker_host = kv.get_string("host", "sporeprint.local");
    c.broker_port = kv.get_int("port", 1883);
    c.mqtt_user = kv.get_string("mqtt_user", "");
    c.mqtt_pass = kv.get_string("mqtt_pass", "");
    c.node_id = kv.get_string("node_id", "");
    if (c.node_id.empty()) c.node_id = default_node_id();
    c.hmac_key = kv.get_string("hmac_key", "");
    c.ota_pass = kv.get_string("ota_pass", "");
    c.ntp_host = kv.get_string("ntp_host", "pool.ntp.org");
    c.paired_pi_host = kv.get_string("paired_pi_host", "");
    sp::Personality p;
    if (sp::personality_from_str(kv.get_string("personality", "climate").c_str(),
                                 &p)) {
        c.personality = p;
    }
    c.hx711_enabled = kv.get_bool("hx711_en", false);
    c.reed_enabled = kv.get_bool("reed_en", false);
    c.mhz19_enabled = kv.get_bool("mhz19_en", false);
    c.migrated_from = kv.get_string("migrated_from", "");
    return c;
}

void NodeConfig::save(sp::KvStore& kv) const {
    kv.set_string("ssid", ssid);
    kv.set_string("pass", pass);
    kv.set_string("host", broker_host);
    kv.set_int("port", broker_port);
    kv.set_string("mqtt_user", mqtt_user);
    kv.set_string("mqtt_pass", mqtt_pass);
    kv.set_string("node_id", node_id);
    kv.set_string("hmac_key", hmac_key);
    kv.set_string("ota_pass", ota_pass);
    kv.set_string("ntp_host", ntp_host);
    kv.set_string("paired_pi_host", paired_pi_host);
    kv.set_string("personality", sp::personality_str(personality));
    kv.set_bool("hx711_en", hx711_enabled);
    kv.set_bool("reed_en", reed_enabled);
    kv.set_bool("mhz19_en", mhz19_enabled);
}

std::string migrate_legacy(sp::KvStore& kv) {
    if (kv.get_bool("migrated", false)) return kv.get_string("migrated_from", "");
    if (!kv.get_string("ssid", "").empty()) {
        // Already provisioned through the v2 portal — nothing to migrate.
        kv.set_bool("migrated", true);
        return "";
    }

    // v1 namespaces in the order a combined node would prefer them
    // (actuator roles carry the most operational state).
    const struct {
        const char* ns;
        sp::Personality personality;
    } legacy[] = {
        {"relay", sp::Personality::RelayBank},
        {"lighting", sp::Personality::LightingBank},
        {"climate", sp::Personality::Climate},
        {"camera", sp::Personality::Climate},
    };

    for (const auto& l : legacy) {
        Preferences p;
        if (!p.begin(l.ns, /*readOnly=*/true)) continue;
        String ssid = p.getString("ssid", "");
        if (ssid.length() == 0) {
            p.end();
            continue;
        }
        // Found a provisioned v1 namespace — copy everything it may hold.
        // v1's bootstrapHmacKeyFromBuildFlag bug could have stored a
        // quote-wrapped or literal "" hmac key; strip wrapping quotes and
        // drop keys that collapse to empty so the bug doesn't migrate.
        String pass = p.getString("pass", "");
        String host = p.getString("host", "");
        int32_t port = p.getInt("port", 0);
        String mqtt_user = p.getString("mqtt_user", "");
        String mqtt_pass = p.getString("mqtt_pass", "");
        String node_id = p.getString("node_id", "");
        String hmac = p.getString("hmac_key", "");
        String ota = p.getString("ota_pass", "");
        String server_url = p.getString("server_url", "");
        String paired = p.getString("paired_pi_host", "");
        p.end();

        if (hmac.length() >= 2 && hmac[0] == '"' &&
            hmac[hmac.length() - 1] == '"') {
            hmac = hmac.substring(1, hmac.length() - 1);
        }

        kv.set_string("ssid", ssid.c_str());
        kv.set_string("pass", pass.c_str());
        if (host.length()) kv.set_string("host", host.c_str());
        if (port) kv.set_int("port", port);
        if (mqtt_user.length()) kv.set_string("mqtt_user", mqtt_user.c_str());
        if (mqtt_pass.length()) kv.set_string("mqtt_pass", mqtt_pass.c_str());
        if (node_id.length()) kv.set_string("node_id", node_id.c_str());
        if (hmac.length()) kv.set_string("hmac_key", hmac.c_str());
        if (ota.length()) kv.set_string("ota_pass", ota.c_str());
        if (server_url.length()) kv.set_string("server_url", server_url.c_str());
        if (paired.length()) kv.set_string("paired_pi_host", paired.c_str());
        kv.set_string("personality", sp::personality_str(l.personality));
        kv.set_bool("migrated", true);
        kv.set_string("migrated_from", l.ns);
        return std::string(l.ns);
    }

    kv.set_bool("migrated", true);
    return "";
}

void factory_reset_all() {
    const char* namespaces[] = {"spnode", "climate", "relay", "lighting",
                                "camera", "wifi", "mqtt"};
    for (const char* ns : namespaces) {
        Preferences p;
        if (p.begin(ns, false)) {
            p.clear();
            p.end();
        }
    }
    Serial.println("[CONFIG] Factory reset complete. Restarting...");
    delay(1000);
    ESP.restart();
}

}  // namespace sp_device
