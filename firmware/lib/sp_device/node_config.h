#pragma once
//
// node_config — unified NVS-backed configuration for the v2 node image,
// plus the one-shot migration from v1's per-role namespaces.
//
// v1 stored everything under Preferences namespaces named after the node
// role ("climate", "relay", "lighting", "camera"). A unified image reading
// only its own namespace would boot a freshly-OTA'd field node straight
// into the captive portal — WiFi creds "gone", farm dark, OTA password
// gone with it. migrate_legacy() probes the four legacy namespaces on
// first boot, copies what it finds into the unified namespace, marks the
// migration, and NEVER deletes the source (a later release reclaims it).
//
// Secrets (hmac key, ota_pass, mqtt creds) are provisioned via the captive
// portal into NVS. There is NO build-flag secret path in v2 — the v1
// -DSPOREPRINT_PROVISION_HMAC stringify bug class is gone with it.

#include <Arduino.h>
#include <Preferences.h>

#include <string>

#include "kv_store.h"
#include "personality.h"

namespace sp_device {

// KvStore over ESP32 Preferences/NVS, one namespace.
class NvsKvStore : public sp::KvStore {
public:
    explicit NvsKvStore(const char* ns = "spnode") : ns_(ns) {}

    std::string get_string(const char* key, const std::string& def) override {
        Preferences p;
        p.begin(ns_, /*readOnly=*/true);
        String v = p.getString(key, String(def.c_str()));
        p.end();
        return std::string(v.c_str());
    }
    void set_string(const char* key, const std::string& value) override {
        Preferences p;
        p.begin(ns_, false);
        p.putString(key, value.c_str());
        p.end();
    }
    int32_t get_int(const char* key, int32_t def) override {
        Preferences p;
        p.begin(ns_, true);
        int32_t v = p.getInt(key, def);
        p.end();
        return v;
    }
    void set_int(const char* key, int32_t value) override {
        Preferences p;
        p.begin(ns_, false);
        p.putInt(key, value);
        p.end();
    }
    bool get_bool(const char* key, bool def) override {
        Preferences p;
        p.begin(ns_, true);
        bool v = p.getBool(key, def);
        p.end();
        return v;
    }
    void set_bool(const char* key, bool value) override {
        Preferences p;
        p.begin(ns_, false);
        p.putBool(key, value);
        p.end();
    }
    void erase_all() override {
        Preferences p;
        p.begin(ns_, false);
        p.clear();
        p.end();
    }

private:
    const char* ns_;
};

// Typed view over the unified key set.
struct NodeConfig {
    std::string ssid;
    std::string pass;
    std::string broker_host;   // default sporeprint.local
    int32_t broker_port = 1883;
    std::string mqtt_user;
    std::string mqtt_pass;
    std::string node_id;       // default node-XXXX from MAC
    std::string hmac_key;      // empty = unprovisioned (warn+accept posture)
    std::string ota_pass;      // empty = OTA disabled
    std::string ntp_host;      // default pool.ntp.org (Pi-as-NTP for airgap)
    std::string paired_pi_host;
    sp::Personality personality = sp::Personality::Climate;
    bool tls_enabled = false;  // Secure MQTT: pin the Pi CA, broker :8883
    bool hx711_enabled = false;
    int32_t hx711_tare = 0;    // raw counts with the scale empty
    float hx711_scale = 0.0f;  // counts per gram; 0 = uncalibrated
    bool reed_enabled = false;
    bool mhz19_enabled = false;
    std::string migrated_from;  // legacy namespace name, "" if fresh

    static NodeConfig load(sp::KvStore& kv);
    void save(sp::KvStore& kv) const;
    bool provisioned() const { return !ssid.empty(); }
};

// One-shot v1 → v2 migration. Returns the legacy namespace migrated from
// ("" if none found or already migrated). Safe to call every boot.
std::string migrate_legacy(sp::KvStore& kv);

// Factory reset: clears the unified namespace AND the legacy ones (the v1
// behavior users expect from the 10-second hold), then restarts.
void factory_reset_all();

}  // namespace sp_device
