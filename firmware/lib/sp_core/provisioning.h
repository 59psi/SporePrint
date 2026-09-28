#pragma once
//
// provisioning — pure policy behind the captive portal's /save handler and
// the cmd/config peripheral switch. The portal (sp_device/wifi_provisioner)
// is Arduino-only; every decision it makes lives here so it is host-tested
// (test_core_provision).
//
//   * html_escape      — stored values are rendered back into the form; an
//                        SSID like "Bob's Lab" used to break out of value='…'
//   * resolve_wifi_pass — a blank WiFi password keeps the stored one on the
//                        same network (it used to erase it)
//   * resolve_node_id   — the broker ACL scopes every node to topics under its
//                        own MQTT username (config/mosquitto/acl.conf, %u), so
//                        node id == username whenever a username is set, and
//                        the id must match the server's NODE_ID_RE
//   * is_ipv4_literal   — Secure MQTT with an IP host only verifies if the
//                        Pi's certificate lists that IP
//   * apply_peripheral_cmd — the Tier-3 peripheral enable flags (MH-Z19C,
//                        HX711, reed) had no writer at all; plus the reed's
//                        level-invert option (reed_inv)
//
// Native-safe: no Arduino headers (ArduinoJson is header-only).

#include <ArduinoJson.h>

#include <stddef.h>
#include <string.h>

#include <string>

namespace sp {

// Escape for HTML text AND quoted attribute values (both quote styles).
inline std::string html_escape(const std::string& in) {
    std::string out;
    out.reserve(in.size());
    for (char c : in) {
        switch (c) {
            case '&': out += "&amp;"; break;
            case '<': out += "&lt;"; break;
            case '>': out += "&gt;"; break;
            case '"': out += "&quot;"; break;
            case '\'': out += "&#39;"; break;
            default: out += c; break;
        }
    }
    return out;
}

// WiFi password to store from a portal submission. The password field is
// never pre-filled, so blank means "unchanged" — but only for the SAME
// network: a stored password is never carried over to a different SSID.
// `open_network` (explicit checkbox) clears it.
inline std::string resolve_wifi_pass(const std::string& stored_ssid,
                                     const std::string& stored_pass,
                                     const std::string& new_ssid,
                                     const std::string& form_pass,
                                     bool open_network) {
    if (open_network) return std::string();
    if (!form_pass.empty()) return form_pass;
    if (new_ssid == stored_ssid) return stored_pass;
    return std::string();
}

constexpr size_t kMaxNodeIdLen = 32;

// ^[A-Za-z0-9_-]{1,32}$ — the server's NODE_ID_RE
// (server/app/hardware/service.py). Also keeps MQTT wildcards / the level
// separator out of every topic the node builds.
inline bool node_id_valid(const std::string& id) {
    if (id.empty() || id.size() > kMaxNodeIdLen) return false;
    for (char c : id) {
        bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                  (c >= '0' && c <= '9') || c == '_' || c == '-';
        if (!ok) return false;
    }
    return true;
}

// Node id from a portal submission. Blank form value → the MQTT username
// when one is set (that is the identity the broker grants), else
// `fallback_id` (the stored / MAC-derived id). Returns nullptr on success
// (writes *out) or an operator-facing error (leaves *out untouched).
inline const char* resolve_node_id(const std::string& form_node_id,
                                   const std::string& mqtt_user,
                                   const std::string& fallback_id,
                                   std::string* out) {
    std::string id = !form_node_id.empty()
                         ? form_node_id
                         : (!mqtt_user.empty() ? mqtt_user : fallback_id);
    if (!node_id_valid(id))
        return "Node id must be 1-32 characters: letters, digits, '-' or '_'.";
    if (!mqtt_user.empty() && id != mqtt_user)
        return "Node id must equal the MQTT username: the broker only lets a "
               "node use topics under its own username (add-node-mqtt-user.sh "
               "prints both). Leave Node id blank to use the username.";
    *out = id;
    return nullptr;
}

// Dotted-quad IPv4 literal: exactly four 0-255 decimal octets.
inline bool is_ipv4_literal(const std::string& host) {
    int octets = 0;
    size_t i = 0;
    const size_t n = host.size();
    while (i < n) {
        size_t start = i;
        unsigned v = 0;
        while (i < n && host[i] >= '0' && host[i] <= '9') {
            v = v * 10u + (unsigned)(host[i] - '0');
            if (i - start >= 3 || v > 255u) return false;
            ++i;
        }
        if (i == start) return false;  // empty octet / non-digit
        ++octets;
        if (i == n) break;
        if (host[i] != '.' || octets == 4) return false;
        ++i;
        if (i == n) return false;  // trailing dot
    }
    return octets == 4;
}

// ── Tier-3 peripheral enable flags ─────────────────────────────
// Persisted as NVS mhz19_en / hx711_en / reed_en (missing keys = off, so
// nodes provisioned before these were settable boot exactly as before).
// Drivers are constructed only in setup(): a change to the driver SET takes
// effect on reboot.
//
// reed_inv (NVS reed_inv, missing = false) is an option of the reed driver,
// not a driver: false = contact closed while the magnet is present (pin LOW
// = door shut, the original convention); true = contact wired on its NO lead
// (pin HIGH = door shut). It applies live — no reboot.

struct PeripheralFlags {
    bool mhz19 = false;
    bool hx711 = false;
    bool reed = false;
    bool reed_inv = false;
};

// Same driver set (the flags that decide which drivers setup() builds).
inline bool same_driver_set(const PeripheralFlags& a, const PeripheralFlags& b) {
    return a.mhz19 == b.mhz19 && a.hx711 == b.hx711 && a.reed == b.reed;
}

inline bool operator==(const PeripheralFlags& a, const PeripheralFlags& b) {
    return same_driver_set(a, b) && a.reed_inv == b.reed_inv;
}
inline bool operator!=(const PeripheralFlags& a, const PeripheralFlags& b) {
    return !(a == b);
}

struct PeripheralCmdResult {
    bool is_object = false;  // the value was a JSON object
    bool changed = false;    // *flags differs from its value before the call
    bool restart_needed = false;  // the driver set changed (reboot to apply)
    int applied = 0;         // boolean members applied (changed or not)
    int ignored = 0;         // unknown keys / non-boolean values (never coerced)
};

// cmd/config {"peripherals": {"mhz19": bool, "hx711": bool, "reed": bool,
// "reed_inv": bool}}. Only members present with a JSON boolean are applied;
// anything else is counted in `ignored` and leaves the flag untouched.
inline PeripheralCmdResult apply_peripheral_cmd(JsonVariantConst value,
                                                PeripheralFlags* flags) {
    PeripheralCmdResult r;
    if (flags == nullptr || !value.is<JsonObjectConst>()) return r;
    r.is_object = true;
    const PeripheralFlags before = *flags;
    for (JsonPairConst kv : value.as<JsonObjectConst>()) {
        const char* key = kv.key().c_str();
        bool* target = nullptr;
        if (strcmp(key, "mhz19") == 0) target = &flags->mhz19;
        else if (strcmp(key, "hx711") == 0) target = &flags->hx711;
        else if (strcmp(key, "reed") == 0) target = &flags->reed;
        else if (strcmp(key, "reed_inv") == 0) target = &flags->reed_inv;
        if (target == nullptr || !kv.value().is<bool>()) {
            ++r.ignored;
            continue;
        }
        *target = kv.value().as<bool>();
        ++r.applied;
    }
    r.changed = (*flags != before);
    r.restart_needed = !same_driver_set(*flags, before);
    return r;
}

}  // namespace sp
