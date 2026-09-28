#pragma once
//
// tls_transport — selects the MQTT transport per provisioning:
//   plain (default)  → WiFiClient, broker port 1883
//   Secure MQTT      → WiFiClientSecure pinned to the Pi's local CA,
//                      broker port 8883
//
// Trust-on-first-use: when TLS is enabled and no CA is pinned yet, the
// node fetches the PEM from http://<pi>:8000/api/provision/ca (plain HTTP,
// on the operator's own LAN — SSH-key semantics) and stores it in NVS. Every
// connection after verifies the broker against the pinned CA; a different
// broker cert (rogue AP, swapped Pi) fails the handshake. Re-pinning =
// factory reset or re-provision.
//
// No CA can be pinned (fw-node#2) — policy in sp_core/tls_policy.h:
//   default     plaintext fallback, but never silently: SP_LOG error, heartbeat
//               `tls:false, tls_fallback:true`, a `tls_downgrade` alert from
//               the composition root, and the CA fetch retried from loop() on
//               a capped backoff. The first success pins the CA and moves the
//               live link to TLS — no reboot.
//   tls_req     ("Require TLS" in the portal) fail closed: MQTT stays down
//               while the fetch retries; the first success brings it up on TLS.
// Never TLS-without-verification.

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <string>

#include "link_budget.h"
#include "log_forward.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "provisioning.h"
#include "tls_policy.h"

namespace sp_device {

struct MqttTransport {
    Client* client = nullptr;
    uint16_t port = 1883;
    bool tls = false;
    sp::TlsMode mode = sp::TlsMode::Plain;
};

// GET the Pi CA once. Returns true with the PEM in *out when the body is a
// plausible public certificate (sp::ca_pem_acceptable). Logs why otherwise.
inline bool fetch_pi_ca(const std::string& host, int32_t connect_timeout_ms,
                        uint16_t read_timeout_ms, std::string* out) {
    HTTPClient http;
    std::string url = "http://" + host + ":8000/api/provision/ca";
    http.setConnectTimeout(connect_timeout_ms);
    http.setTimeout(read_timeout_ms);
    if (!http.begin(url.c_str())) {
        SP_LOG(LOG_ERROR, "[TLS] CA fetch: bad URL %s", url.c_str());
        return false;
    }
    bool ok = false;
    int code = http.GET();
    if (code == 200) {
        const int size = http.getSize();  // -1 when chunked
        if (size > 0 && (size_t)size >= sp::kMaxCaPemBytes) {
            SP_LOG(LOG_ERROR, "[TLS] CA fetch returned %d bytes - too large to "
                              "be the Pi CA, refusing to pin", size);
        } else {
            String pem = http.getString();
            if (sp::ca_pem_acceptable(pem.c_str(), pem.length())) {
                *out = pem.c_str();
                ok = true;
            } else {
                SP_LOG(LOG_ERROR, "[TLS] CA fetch returned something that is "
                                  "not a public certificate - refusing to pin");
            }
        }
    } else {
        SP_LOG(LOG_WARN, "[TLS] CA fetch from %s failed (%d)%s", url.c_str(),
               code,
               code == 401 ? " - the Pi's API key gate blocks "
                             "/api/provision/ca"
                           : "");
    }
    http.end();
    return ok;
}

// setCACert keeps the POINTER — the static buffer persists it.
inline void apply_pinned_ca(WiFiClientSecure& secure, const std::string& ca) {
    static std::string pinned_ca;
    pinned_ca = ca;
    secure.setCACert(pinned_ca.c_str());
}

// Owns the transport decision for one image (node or cam). `cfg`, `kv` and
// both clients must outlive it (the composition root holds them statically).
class TlsSupervisor {
public:
    TlsSupervisor(NodeConfig& cfg, NvsKvStore& kv, WiFiClient& plain,
                  WiFiClientSecure& secure)
        : cfg_(cfg), kv_(kv), plain_(plain), secure_(secure) {}

    // Boot: one pre-WDT CA fetch when needed (8 s timeouts), then the
    // transport per tls_policy.h.
    MqttTransport select() {
        // Bound every connect attempt (link_budget.h): the core defaults —
        // 30 s TCP connect, 120 s TLS handshake — outlast the 30 s loop WDT.
        // Both setters take SECONDS on arduino-esp32 2.x.
        plain_.setTimeout(sp::kTcpConnectTimeoutS);
        secure_.setTimeout(sp::kTcpConnectTimeoutS);
        secure_.setHandshakeTimeout(sp::kTlsHandshakeTimeoutS);

        std::string ca;
        if (cfg_.tls_enabled) {
            ca = kv_.get_string("broker_ca", "");
            if (ca.empty() && WiFi.status() != WL_CONNECTED) {
                // Offline boot (boot_policy.h). A portal save of Secure MQTT
                // without a pinned CA forces a WiFi connect at the next boot,
                // so this is only reached by a node that already ran on the
                // fallback; loop() retries once WiFi is back.
                SP_LOG(LOG_WARN, "[TLS] WiFi down at boot - CA fetch deferred");
            } else if (ca.empty() &&
                       fetch_pi_ca(cfg_.broker_host, 8000, 8000, &ca)) {
                kv_.set_string("broker_ca", ca);
                SP_LOG(LOG_INFO, "[TLS] Pinned broker CA (%u bytes)",
                       (unsigned)ca.size());
            }
        }
        mode_ = sp::tls_mode(cfg_.tls_enabled, !ca.empty(), cfg_.tls_required);
        backoff_.begin(millis());

        MqttTransport t;
        t.mode = mode_;
        switch (mode_) {
            case sp::TlsMode::Plain:
                t.client = &plain_;
                t.port = (uint16_t)cfg_.broker_port;
                break;
            case sp::TlsMode::Pinned:
                warn_if_ip_host();
                apply_pinned_ca(secure_, ca);
                t.client = &secure_;
                t.port = 8883;
                t.tls = true;
                break;
            case sp::TlsMode::Fallback:
                SP_LOG(LOG_ERROR,
                       "[TLS] Secure MQTT is ON but no Pi CA is pinned - "
                       "running PLAINTEXT on %d (credentials unencrypted). "
                       "Retrying the CA fetch; check GET /api/provision/ca "
                       "on the Pi",
                       (int)cfg_.broker_port);
                t.client = &plain_;
                t.port = (uint16_t)cfg_.broker_port;
                break;
            case sp::TlsMode::FailClosed:
                SP_LOG(LOG_ERROR,
                       "[TLS] Secure MQTT is REQUIRED but no Pi CA is pinned - "
                       "MQTT stays DOWN until the CA fetch succeeds (retrying)");
                t.client = &secure_;  // never connects until a CA is set
                t.port = 8883;
                break;
        }
        return t;
    }

    // Call once per loop pass, BEFORE MqttLink::loop(). Runs at most one
    // blocking CA fetch (<= kCaFetchWorstCaseS) when the backoff is due.
    // Returns true when it fetched: the caller must not start an MQTT connect
    // attempt in the same pass (sp::mqtt_may_connect).
    bool loop(uint32_t now_ms, bool button_down, MqttLink& link) {
        if (!sp::tls_mode_wants_ca(mode_)) return false;
        if (!backoff_.due(now_ms, WiFi.status() == WL_CONNECTED, button_down))
            return false;
        std::string ca;
        if (!fetch_pi_ca(cfg_.broker_host,
                         (int32_t)(sp::kCaFetchConnectTimeoutS * 1000UL),
                         (uint16_t)(sp::kCaFetchReadTimeoutS * 1000UL), &ca)) {
            backoff_.failed(millis());
            SP_LOG(LOG_WARN, "[TLS] CA fetch attempt %u failed - still %s, "
                             "next try in %u s",
                   (unsigned)backoff_.failures(), sp::tls_mode_str(mode_),
                   (unsigned)(backoff_.delay_ms() / 1000UL));
            return true;
        }
        kv_.set_string("broker_ca", ca);
        warn_if_ip_host();
        apply_pinned_ca(secure_, ca);
        link.switch_transport(secure_, 8883);
        SP_LOG(LOG_INFO, "[TLS] Pinned broker CA (%u bytes) - MQTT moves to "
                         "TLS 8883 (was %s)",
               (unsigned)ca.size(), sp::tls_mode_str(mode_));
        mode_ = sp::TlsMode::Pinned;
        return true;
    }

    sp::TlsMode mode() const { return mode_; }
    bool tls() const { return sp::tls_mode_is_tls(mode_); }
    bool fallback() const { return sp::tls_mode_is_fallback(mode_); }

private:
    void warn_if_ip_host() const {
        if (!sp::is_ipv4_literal(cfg_.broker_host)) return;
        // WiFiClientSecure verifies the certificate against this exact
        // string; mbedTLS 2.28 matches it only against a DNS-type SAN entry
        // (install.sh lists the Pi's IPs as both IP: and DNS: entries).
        SP_LOG(LOG_WARN, "[TLS] Broker host %s is an IP: the handshake only "
                         "verifies if the Pi's certificate lists it - prefer "
                         "sporeprint.local",
               cfg_.broker_host.c_str());
    }

    NodeConfig& cfg_;
    NvsKvStore& kv_;
    WiFiClient& plain_;
    WiFiClientSecure& secure_;
    sp::TlsMode mode_ = sp::TlsMode::Plain;
    sp::CaFetchBackoff backoff_;
};

}  // namespace sp_device
