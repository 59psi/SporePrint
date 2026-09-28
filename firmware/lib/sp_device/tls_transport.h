#pragma once
//
// tls_transport — selects the MQTT transport per provisioning:
//   plain (default)  → WiFiClient, broker port 1883
//   Secure MQTT      → WiFiClientSecure pinned to the Pi's local CA,
//                      broker port 8883
//
// Trust-on-first-use: when TLS is enabled and no CA is pinned yet, the
// node fetches the PEM once from http://<pi>/api/provision/ca (the plain
// fetch happens exactly once, at provision time, on the operator's own
// LAN — SSH-key semantics) and stores it in NVS. Every connection after
// verifies the broker against the pinned CA; a different broker cert
// (rogue AP, swapped Pi) fails the handshake. Re-pinning = factory reset
// or re-provision.

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "link_budget.h"
#include "node_config.h"
#include "provisioning.h"

namespace sp_device {

struct MqttTransport {
    Client* client = nullptr;
    uint16_t port = 1883;
    bool tls = false;
};

// `plain` and `secure` must outlive the returned transport (the
// composition root owns them statically).
inline MqttTransport select_mqtt_transport(NodeConfig& cfg, NvsKvStore& kv,
                                           WiFiClient& plain,
                                           WiFiClientSecure& secure) {
    MqttTransport t;
    // Bound every connect attempt (link_budget.h): the core defaults — 30 s
    // TCP connect, 120 s TLS handshake — outlast the 30 s loop WDT, so an
    // unreachable broker panic-rebooted the node about once a minute.
    // Both setters take SECONDS on arduino-esp32 2.x.
    plain.setTimeout(sp::kTcpConnectTimeoutS);
    secure.setTimeout(sp::kTcpConnectTimeoutS);
    secure.setHandshakeTimeout(sp::kTlsHandshakeTimeoutS);
    if (!cfg.tls_enabled) {
        t.client = &plain;
        t.port = (uint16_t)cfg.broker_port;
        return t;
    }

    std::string ca = kv.get_string("broker_ca", "");
    if (ca.empty() && WiFi.status() != WL_CONNECTED) {
        // Offline boot (boot_policy.h). A portal save of Secure MQTT without
        // a pinned CA forces a WiFi connect at the next boot, so this is only
        // reached by a node that already ran TLS-intended on the fallback.
        Serial.println("[TLS] WiFi down at boot - CA not fetched this session.");
    } else if (ca.empty()) {
        // TOFU fetch — once, over plain HTTP, at provision time.
        HTTPClient http;
        std::string url = "http://" + cfg.broker_host + ":8000/api/provision/ca";
        http.setConnectTimeout(8000);
        http.setTimeout(8000);
        http.begin(url.c_str());
        int code = http.GET();
        if (code == 200) {
            String pem = http.getString();
            if (pem.indexOf("BEGIN CERTIFICATE") >= 0 &&
                pem.indexOf("PRIVATE KEY") < 0 && pem.length() < 4000) {
                ca = pem.c_str();
                kv.set_string("broker_ca", ca);
                Serial.printf("[TLS] Pinned broker CA (%u bytes)\n",
                              (unsigned)ca.size());
            } else {
                Serial.println("[TLS] CA fetch returned junk — refusing to pin");
            }
        } else {
            Serial.printf("[TLS] CA fetch failed (%d)\n", code);
        }
        http.end();
    }

    if (ca.empty()) {
        // No CA pinned and the fetch failed: fail CLOSED for the TLS
        // intent — fall back to plaintext but say so loudly, rather than
        // connecting TLS-without-verification (which would be theater).
        Serial.println("[TLS] No CA available — falling back to plaintext 1883. "
                       "Re-provision or check the Pi to enable TLS.");
        t.client = &plain;
        t.port = (uint16_t)cfg.broker_port;
        return t;
    }

    if (sp::is_ipv4_literal(cfg.broker_host)) {
        // WiFiClientSecure verifies the certificate against this exact
        // string; mbedTLS 2.28 matches it only against a DNS-type SAN entry
        // (install.sh lists the Pi's IPs as both IP: and DNS: entries).
        Serial.printf("[TLS] Broker host %s is an IP: the handshake only "
                      "verifies if the Pi's certificate lists it — prefer "
                      "sporeprint.local.\n",
                      cfg.broker_host.c_str());
    }

    // setCACert keeps the POINTER — the static buffer below persists it.
    static std::string pinned_ca;
    pinned_ca = ca;
    secure.setCACert(pinned_ca.c_str());
    t.client = &secure;
    t.port = 8883;
    t.tls = true;
    return t;
}

}  // namespace sp_device
