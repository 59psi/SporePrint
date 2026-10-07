#pragma once
//
// tls_transport — selects the MQTT transport per provisioning:
//   plain (default)  → WiFiClient, broker port 1883
//   Secure MQTT      → WiFiClientSecure pinned to the Pi's local CA,
//                      broker port 8883
//
// Trust-on-first-use: when TLS is enabled and no CA is pinned yet, the
// node fetches the PEM from http://<pi>:8000/api/provision/ca (plain HTTP,
// on the operator's own LAN — SSH-key semantics). Every connection after the
// pin verifies the broker against the pinned CA; a different broker cert
// (rogue AP, swapped Pi) fails the handshake. Re-pinning = factory reset.
//
// Verify before commit (policy + host tests: sp_core/tls_policy.h
// TlsPinMachine). A fetched CA is only a CANDIDATE: the link tries TLS 8883
// with it from RAM, and only a CONNACK on that connection writes it to NVS
// (`broker_ca`, then the verified marker `broker_ca_ok`) and keeps the node
// on TLS. A failed trial persists nothing and goes back where it came from —
// the working plaintext link, or fail-closed with "Require TLS" — with the
// reason in the log and the tls_downgrade alert (cert name mismatch / other
// CA, 8883 unreachable, TLS error, login refused), then backs off before the
// next fetch + trial. Before this, the CA was pinned and the link switched
// before any TLS connection had worked, and a broker certificate that did
// not cover the node's broker host locked a working node out of MQTT for
// good. A CA an older image stored WITHOUT the marker gets the same trial,
// so a node that image locked out recovers on this one (e.g. after a
// network OTA push over the LAN).
//
// No CA can be pinned (fw-node#2):
//   default     plaintext fallback, but never silently: SP_LOG error, heartbeat
//               `tls:false, tls_fallback:true`, a `tls_downgrade` alert from
//               the composition root, and the CA fetch + trial retried from
//               loop() on a capped backoff — no reboot needed.
//   tls_req     ("Require TLS" in the portal) fail closed: MQTT stays down
//               while the fetch + trial retries; a verified trial brings it up
//               on TLS.
// Never TLS-without-verification. The heartbeat's `ca_fp` (SHA-256 of the
// PEM in use) lets the Pi check that the CA a node trusts is its own.

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <string>

#include "bounded_dns.h"
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
    // Declared before `http`, which keeps a pointer to it until end(). The
    // bounded-DNS client keeps the lookup inside kCaFetchWorstCaseS.
    BoundedDnsClient client;
    HTTPClient http;
    std::string url = "http://" + host + ":8000/api/provision/ca";
    http.setConnectTimeout(connect_timeout_ms);
    http.setTimeout(read_timeout_ms);
    if (!http.begin(client, url.c_str())) {
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
    // transport per tls_policy.h. A Trial transport connects on TLS with the
    // candidate; loop() commits or reverts it once the attempt has run.
    MqttTransport select() {
        // Bound every connect attempt (link_budget.h): the core defaults —
        // 30 s TCP connect on the secure client, 120 s TLS handshake —
        // outlast the 30 s loop WDT. Units (arduino-esp32 3.x):
        // setConnectionTimeout takes MILLISECONDS (it bounds the TCP connect
        // and the socket send/receive waits); setHandshakeTimeout still takes
        // SECONDS. Core 2.x's setTimeout(seconds) did the former; on 3.x
        // setTimeout() is plain Stream::setTimeout(ms) and no longer touches
        // the connect, so it must not be used here.
        plain_.setConnectionTimeout(sp::kTcpConnectTimeoutS * 1000UL);
        secure_.setConnectionTimeout(sp::kTcpConnectTimeoutS * 1000UL);
        secure_.setHandshakeTimeout(sp::kTlsHandshakeTimeoutS);

        std::string stored;
        bool stored_ok = false;
        bool fetched = false;
        candidate_.clear();
        if (cfg_.tls_enabled) {
            stored = kv_.get_string(kCaKey, "");
            stored_ok = !stored.empty() && kv_.get_bool(kCaOkKey, false);
            if (!stored.empty()) {
                candidate_ = stored;
            } else if (WiFi.status() != WL_CONNECTED) {
                // Offline boot (boot_policy.h). A portal save of Secure MQTT
                // without a pinned CA forces a WiFi connect at the next boot,
                // so this is only reached by a node that already ran on the
                // fallback; loop() retries once WiFi is back.
                SP_LOG(LOG_WARN, "[TLS] WiFi down at boot - CA fetch deferred");
            } else if (fetch_pi_ca(cfg_.broker_host, 8000, 8000, &candidate_)) {
                fetched = true;
            }
        }
        const sp::TlsMode mode =
            pin_.begin(cfg_.tls_enabled, cfg_.tls_required, !stored.empty(),
                       stored_ok, fetched, millis());

        MqttTransport t;
        t.mode = mode;
        switch (mode) {
            case sp::TlsMode::Plain:
                t.client = &plain_;
                t.port = (uint16_t)cfg_.broker_port;
                break;
            case sp::TlsMode::Pinned:
            case sp::TlsMode::Trial:
                warn_if_ip_host();
                use_ca(candidate_);
                if (mode == sp::TlsMode::Trial)
                    SP_LOG(LOG_INFO,
                           "[TLS] Trying TLS 8883 with the %s Pi CA (%u bytes, "
                           "sha256 %.16s...) - pinned only once the broker "
                           "accepts the connection",
                           fetched ? "fetched" : "stored (unverified)",
                           (unsigned)candidate_.size(), ca_fp_.c_str());
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

    // Call once per loop pass, BEFORE MqttLink::loop(). Judges a running
    // trial (commit / revert — no network I/O), or runs at most one blocking
    // CA fetch (<= kCaFetchWorstCaseS) when the backoff is due. Returns true
    // when it fetched: the caller must not start an MQTT connect attempt in
    // the same pass (sp::mqtt_may_connect).
    bool loop(uint32_t now_ms, bool button_down, MqttLink& link) {
        using Step = sp::TlsPinMachine::Step;
        switch (pin_.step(now_ms, WiFi.status() == WL_CONNECTED, button_down,
                          link.connect_attempts(), link.connect_successes())) {
            case Step::Idle:
                return false;
            case Step::Commit:
                commit();
                return false;
            case Step::Revert:
                revert(link);
                return false;
            case Step::Fetch:
                break;
        }
        std::string ca;
        if (!fetch_pi_ca(cfg_.broker_host,
                         (int32_t)(sp::kCaFetchConnectTimeoutS * 1000UL),
                         (uint16_t)(sp::kCaFetchReadTimeoutS * 1000UL), &ca)) {
            pin_.fetch_failed(millis());
            SP_LOG(LOG_WARN, "[TLS] CA fetch attempt %u failed - still %s, "
                             "next try in %u s",
                   (unsigned)pin_.backoff().failures(),
                   sp::tls_mode_str(pin_.mode()),
                   (unsigned)(pin_.backoff().delay_ms() / 1000UL));
            return true;
        }
        const sp::TlsMode was = pin_.mode();
        candidate_ = ca;
        warn_if_ip_host();
        use_ca(candidate_);
        // The candidate lives in RAM only; the next allowed pass connects on
        // it and the pass after that commits or reverts.
        link.switch_transport(secure_, 8883);
        pin_.trial_started(link.connect_attempts(), link.connect_successes());
        SP_LOG(LOG_INFO, "[TLS] Fetched the Pi CA (%u bytes, sha256 %.16s...) "
                         "- trying MQTT on TLS 8883 (was %s); pinned only once "
                         "the broker accepts the connection",
               (unsigned)ca.size(), ca_fp_.c_str(), sp::tls_mode_str(was));
        return true;
    }

    sp::TlsMode mode() const { return pin_.mode(); }
    bool tls() const { return sp::tls_mode_is_tls(pin_.mode()); }
    bool fallback() const { return sp::tls_mode_is_fallback(pin_.mode()); }
    // The tls_downgrade alert condition + reason (None: no alert).
    sp::TlsFailReason downgrade() const { return pin_.downgrade(); }
    // Heartbeat `ca_fp`: the fingerprint of the CA the TLS link verifies
    // against; "" (omitted) when the link is not TLS.
    const char* ca_fp() const { return tls() ? ca_fp_.c_str() : ""; }

private:
    static constexpr const char* kCaKey = "broker_ca";
    // Set only after a CONNACK on broker_ca. Missing (older images pinned
    // without verifying) = the stored CA gets a trial, not blind trust.
    static constexpr const char* kCaOkKey = "broker_ca_ok";

    void use_ca(const std::string& ca) {
        apply_pinned_ca(secure_, ca);
        char fp[sp::kCaFingerprintHexLen + 1];
        sp::ca_fingerprint_hex(ca.data(), ca.size(), fp);
        ca_fp_ = fp;
    }

    // The trial connected: the broker proved it holds a certificate the
    // candidate CA signed for this broker host. Persist the CA first, then
    // the marker — power lost in between leaves an unverified CA, which only
    // earns another trial.
    void commit() {
        if (kv_.get_string(kCaKey, "") != candidate_)
            kv_.set_string(kCaKey, candidate_);
        kv_.set_bool(kCaOkKey, true);
        pin_.trial_verified();
        SP_LOG(LOG_INFO, "[TLS] Broker verified against the Pi CA - pinned "
                         "(%u bytes, sha256 %.16s...); MQTT stays on TLS 8883",
               (unsigned)candidate_.size(), ca_fp_.c_str());
    }

    // The trial's connect attempt failed: nothing is persisted. Back to the
    // plaintext fallback (or fail-closed), with the reason, on the backoff.
    void revert(MqttLink& link) {
        char err[80] = {0};
        const int tls_err = secure_.lastError(err, sizeof(err));
        const int state = link.state();
        const sp::TlsFailReason why =
            sp::classify_tls_trial_failure(state, tls_err);
        pin_.trial_failed(why, millis());
        if (pin_.mode() == sp::TlsMode::Fallback)
            link.switch_transport(plain_, (uint16_t)cfg_.broker_port);
        // FailClosed stays on the secure client: no connect is allowed.
        // (Log lines are capped at logfwd::kEntryMsgLen — mbedTLS text cut.)
        SP_LOG(LOG_ERROR,
               "[TLS] Pi CA trial failed: %s (mqtt %d, tls %d %.40s) - NOT "
               "pinned, back to %s, retry in %u s",
               sp::tls_fail_reason_str(why), state, tls_err,
               tls_err < 0 ? err : "", sp::tls_mode_str(pin_.mode()),
               (unsigned)(pin_.backoff().delay_ms() / 1000UL));
        if (why == sp::TlsFailReason::CertRejected)
            SP_LOG(LOG_ERROR,
                   "[TLS] The broker certificate must list '%s' (cert name "
                   "mismatch) and be signed by the CA the Pi serves - re-run "
                   "./install.sh on the Pi, or use sporeprint.local",
                   cfg_.broker_host.c_str());
    }

    void warn_if_ip_host() const {
        if (!sp::is_ipv4_literal(cfg_.broker_host)) return;
        // The TLS client verifies the certificate against this exact string.
        // mbedTLS 3.6 (core 3.x) matches an IP against the certificate's
        // IP-type SAN entries; the 2.28 in older (core 2.x) images matched it
        // only against DNS-type ones — install.sh lists the Pi's IPs as both,
        // so a mixed fleet verifies either way.
        SP_LOG(LOG_WARN, "[TLS] Broker host %s is an IP: the handshake only "
                         "verifies if the Pi's certificate lists it - prefer "
                         "sporeprint.local",
               cfg_.broker_host.c_str());
    }

    NodeConfig& cfg_;
    NvsKvStore& kv_;
    WiFiClient& plain_;
    WiFiClientSecure& secure_;
    sp::TlsPinMachine pin_;
    std::string candidate_;  // the CA in use on TLS (pinned or on trial)
    std::string ca_fp_;      // its sha256, lowercase hex
};

}  // namespace sp_device
