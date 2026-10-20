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
// Probe before switching: on the plaintext fallback a fetched CA is first
// PROBED — one bare TLS handshake to 8883 with it on a pass of its own, the
// live plaintext MQTT link untouched — and only a candidate whose handshake
// verifies moves the link to TLS. A certificate that does not name the
// node's Pi address used to take the node off MQTT on every 15-minute retry.
//
// The fetch itself reads the whole HTTP response under one deadline into a
// bounded buffer (sp::scan_ca_response) — no per-read timeout a slow-drip
// server can stretch past the loop WDT, no unbounded chunked body.
//
// No CA can be pinned:
//   default     plaintext fallback, but never silently: SP_LOG error, heartbeat
//               `tls:false, tls_fallback:true`, a `tls_downgrade` alert from
//               the composition root, and the CA fetch + probe + trial
//               retried from loop() on a capped backoff — no reboot needed.
//   tls_req     ("Require TLS" in the portal) fail closed: MQTT stays down
//               while the fetch + trial retries; a verified trial brings it up
//               on TLS.
// Never TLS-without-verification. The heartbeat's `ca_fp` (SHA-256 of the
// PEM in use) lets the Pi check that the CA a node trusts is its own.

#include <Arduino.h>
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

// GET the Pi CA once (HTTP/1.0 on :8000). Returns true with the PEM in *out
// when the response is a 200 whose body is a plausible public certificate
// (sp::ca_pem_acceptable); logs why otherwise. Every step is bounded: DNS
// (bounded_dns.h), the TCP connect (`connect_timeout_ms`), then the whole
// response — status line, headers and body — under ONE deadline
// (`response_timeout_ms`) into a buffer of at most sp::kMaxCaResponseBytes;
// sp::scan_ca_response decides when it is complete or refused.
inline bool fetch_pi_ca(const std::string& host, uint32_t connect_timeout_ms,
                        uint32_t response_timeout_ms, std::string* out) {
    BoundedDnsClient client;
    client.setConnectionTimeout(connect_timeout_ms);
    if (!client.connect(host.c_str(), 8000)) {
        SP_LOG(LOG_WARN, "[TLS] CA fetch: no connection to %s:8000",
               host.c_str());
        return false;
    }
    const std::string request = "GET /api/provision/ca HTTP/1.0\r\nHost: " +
                                host + ":8000\r\nConnection: close\r\n\r\n";
    if (client.write(reinterpret_cast<const uint8_t*>(request.data()),
                     request.size()) != request.size()) {
        SP_LOG(LOG_WARN, "[TLS] CA fetch: sending the request to %s failed",
               host.c_str());
        client.stop();
        return false;
    }
    using State = sp::CaResponseScan::State;
    std::string response;
    response.reserve(1024);
    sp::CaResponseScan scan;
    const uint32_t deadline = millis() + response_timeout_ms;
    uint8_t chunk[256];
    for (;;) {
        scan = sp::scan_ca_response(response.data(), response.size());
        if (scan.state != State::NeedMore) break;
        if (response.size() >= sp::kMaxCaResponseBytes) {
            scan.state = State::Refused;
            scan.why = "response too large";
            break;
        }
        if (sp::deadline_reached(millis(), deadline)) {
            scan.state = State::Refused;
            scan.why = "no complete response in time";
            break;
        }
        int avail = client.available();
        // Closed by the server: one last look, the final bytes may have
        // landed together with the close.
        if (avail <= 0 && !client.connected()) {
            avail = client.available();
            if (avail <= 0) {
                scan.state = State::Refused;
                scan.why = "connection closed mid-response";
                break;
            }
        }
        if (avail > 0) {
            size_t want = sp::kMaxCaResponseBytes - response.size();
            if (want > sizeof(chunk)) want = sizeof(chunk);
            if (want > (size_t)avail) want = (size_t)avail;
            const int n = client.read(chunk, want);
            if (n > 0) response.append(reinterpret_cast<const char*>(chunk), n);
        } else {
            delay(1);  // waiting on the network, bounded by `deadline`
        }
    }
    client.stop();

    if (scan.state == State::Refused) {
        SP_LOG(LOG_ERROR, "[TLS] CA fetch from %s refused: %s - not pinned",
               host.c_str(), scan.why);
        return false;
    }
    if (scan.status != 200) {
        SP_LOG(LOG_WARN, "[TLS] CA fetch from %s failed (%d)%s", host.c_str(),
               scan.status,
               scan.status == 401 ? " - the Pi's API key gate blocks "
                                    "/api/provision/ca"
                                  : "");
        return false;
    }
    const char* body = response.data() + scan.body_offset;
    if (!sp::ca_pem_acceptable(body, scan.body_len)) {
        SP_LOG(LOG_ERROR, "[TLS] CA fetch returned something that is not a "
                          "public certificate - refusing to pin");
        return false;
    }
    out->assign(body, scan.body_len);
    return true;
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
    // step: a CA fetch (<= kCaFetchWorstCaseS) when the backoff is due, or
    // the TLS probe of a fetched candidate (<= kTlsProbeWorstCaseS). Returns
    // true when it blocked: the caller must not start an MQTT connect attempt
    // in the same pass (sp::mqtt_may_connect).
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
            case Step::Probe:
                probe(link);
                return true;
            case Step::Fetch:
                break;
        }
        std::string ca;
        if (!fetch_pi_ca(cfg_.broker_host, sp::kCaFetchConnectTimeoutS * 1000UL,
                         sp::kCaFetchReadTimeoutS * 1000UL, &ca)) {
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
        if (!pin_.fetch_succeeded()) {
            // On the plaintext fallback: probe it on the next pass, with the
            // working link left alone.
            SP_LOG(LOG_INFO, "[TLS] Fetched the Pi CA (%u bytes, sha256 "
                             "%.16s...) - checking it with a TLS handshake "
                             "to 8883 before MQTT moves off plaintext",
                   (unsigned)ca.size(), ca_fp_.c_str());
            return true;
        }
        // Fail-closed: nothing is up to protect. The candidate lives in RAM
        // only; the next allowed pass connects on it and the pass after that
        // commits or reverts.
        start_trial(link);
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
    // earns another trial — and the marker only once the stored CA reads
    // back as the candidate (sp::persist_verified_ca).
    void commit() {
        const bool persisted =
            sp::persist_verified_ca(kv_, kCaKey, kCaOkKey, candidate_);
        pin_.trial_verified();
        if (persisted)
            SP_LOG(LOG_INFO, "[TLS] Broker verified against the Pi CA - pinned "
                             "(%u bytes, sha256 %.16s...); MQTT stays on TLS 8883",
                   (unsigned)candidate_.size(), ca_fp_.c_str());
        else
            SP_LOG(LOG_ERROR, "[TLS] Broker verified against the Pi CA, but "
                              "saving it to NVS FAILED - TLS stays up this "
                              "boot; the next boot tries the CA again");
    }

    // Move the live link onto TLS with the candidate (in RAM only).
    void start_trial(MqttLink& link) {
        link.switch_transport(secure_, 8883);
        pin_.trial_started(link.connect_attempts(), link.connect_successes());
    }

    // One bare TLS handshake to the broker with the candidate CA — what an
    // MQTT connect on 8883 would verify (CA and broker host name), without
    // touching the plaintext MQTT link. DNS is resolved first so a lookup
    // failure is never read through a TLS error left by an earlier attempt.
    // Bounded by link_budget.h kTlsProbeWorstCaseS (select() set the
    // connect and handshake timeouts).
    sp::TlsFailReason probe_candidate() {
        IPAddress ip;
        if (!resolve_host(cfg_.broker_host.c_str(), dns_timeout_ms(), &ip))
            return sp::TlsFailReason::TlsUnreachable;
        const int ok = secure_.connect(cfg_.broker_host.c_str(), 8883);
        char err[80] = {0};
        const int tls_err = ok ? 0 : secure_.lastError(err, sizeof(err));
        secure_.stop();
        if (ok) return sp::TlsFailReason::None;
        return sp::classify_tls_trial_failure(sp::kMqttStateConnectFailed,
                                              tls_err);
    }

    // Step::Probe: the candidate verified → the trial moves the link to TLS;
    // it did not → back off with the reason, the link never touched.
    void probe(MqttLink& link) {
        const sp::TlsFailReason why = probe_candidate();
        if (why == sp::TlsFailReason::None) {
            pin_.probe_passed();
            start_trial(link);
            SP_LOG(LOG_INFO, "[TLS] The broker's certificate verifies against "
                             "the fetched Pi CA (sha256 %.16s...) - moving MQTT "
                             "to TLS 8883; pinned once the broker accepts the "
                             "login",
                   ca_fp_.c_str());
            return;
        }
        pin_.probe_failed(why, millis());
        SP_LOG(LOG_ERROR,
               "[TLS] Pi CA check failed: %s - NOT pinned, MQTT stays on "
               "plaintext, retry in %u s",
               sp::tls_fail_reason_str(why),
               (unsigned)(pin_.backoff().delay_ms() / 1000UL));
        if (why == sp::TlsFailReason::CertRejected) log_cert_name_hint();
    }

    void log_cert_name_hint() const {
        SP_LOG(LOG_ERROR,
               "[TLS] The broker certificate must list '%s' (cert name "
               "mismatch) and be signed by the CA the Pi serves - re-run "
               "./install.sh on the Pi, or use sporeprint.local",
               cfg_.broker_host.c_str());
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
        if (why == sp::TlsFailReason::CertRejected) log_cert_name_hint();
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
