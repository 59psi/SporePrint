#pragma once
//
// tls_policy — what the MQTT transport does when "Secure MQTT" is enabled
// but no Pi CA is pinned (fw-node#2). The device side (sp_device/
// tls_transport.h) performs the fetches and the transport switch; every
// decision is here so it is host-tested (test_core_tls).
//
// Before: the trust-on-first-use CA fetch failed (the Pi's
// /api/provision/ca 404'd on every Docker deployment) and the node quietly
// connected on plaintext 1883 — MQTT credentials in the clear, a single
// Serial line as the only trace, and no retry until a reboot.
//
// Now:
//   Plain       Secure MQTT off → plaintext, as provisioned.
//   Pinned      a VERIFIED CA (below) → TLS 8883, broker verified against it.
//   Fallback    no CA, default policy → plaintext, but LOUD: SP_LOG error, a
//               `tls_downgrade` alert (entry + hourly, and at once when the
//               reason changes), `tls:false` + `tls_fallback:true` in the
//               heartbeat — and the CA fetch is retried on a capped backoff.
//               Keeps deployed nodes that already run on the fallback
//               reachable.
//   FailClosed  no CA and the operator ticked "Require TLS" (NVS tls_req) →
//               no MQTT at all (the link watchdog's safe mode takes the
//               channels off after 10 min) while the fetch retries.
//   Trial       a CANDIDATE CA is being tried: the link runs TLS 8883 with
//               it from RAM; nothing is persisted yet.
//
// Verify before commit (final review, safety-contract). The first version
// wrote a fetched CA to NVS and moved the live link to TLS before any TLS
// connection had succeeded. When the broker certificate did not cover the
// node's broker host (an IP host with a certificate issued before the IP
// SANs, a changed IP, a name not in the SAN list) every handshake failed
// forever: a working plaintext node locked itself out of MQTT, fell into
// safe mode, and only physical access recovered it — the pinned CA survived
// OTA rollback. Now:
//   * a fetched CA, or one found in NVS without the verified marker (NVS
//     `broker_ca_ok`; older images pinned without verifying), is only a
//     candidate → Trial;
//   * a CONNACK on the candidate commits it: broker_ca + broker_ca_ok are
//     written, mode Pinned, final — a later failure never downgrades a
//     verified pin (an impostor broker must not be able to force plaintext);
//   * a failed trial reverts — Fallback (plaintext, the tls_downgrade alert
//     says why: cert name mismatch / other CA, 8883 unreachable, TLS error,
//     broker refused) or FailClosed — and backs off (CaFetchBackoff) before
//     the next fetch + trial.
// TlsPinMachine holds these decisions; sp_device/tls_transport.h does the
// fetches, NVS writes and transport switches it asks for.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include <string>

#include "alert_latch.h"
#include "sha256.h"
#include "wrap_time.h"

namespace sp {

// Trial is appended so the existing values keep their numbers.
enum class TlsMode : uint8_t { Plain, Pinned, Fallback, FailClosed, Trial };

// `ca_pinned` = a VERIFIED CA is pinned (see TlsPinMachine::begin for the
// candidate cases).
inline TlsMode tls_mode(bool tls_enabled, bool ca_pinned, bool require_tls) {
    if (!tls_enabled) return TlsMode::Plain;
    if (ca_pinned) return TlsMode::Pinned;
    return require_tls ? TlsMode::FailClosed : TlsMode::Fallback;
}

// Log / diagnostics string.
inline const char* tls_mode_str(TlsMode m) {
    switch (m) {
        case TlsMode::Plain: return "plain";
        case TlsMode::Pinned: return "tls";
        case TlsMode::Fallback: return "plain_fallback";
        case TlsMode::FailClosed: return "blocked";
        case TlsMode::Trial: return "tls_trial";
    }
    return "?";
}

// The link in use is TLS against a pinned or candidate CA (heartbeat `tls`).
// A trial link that is connected has verified its candidate — the next pass
// commits it — so `tls:true` is never reported for an unverified broker.
inline bool tls_mode_is_tls(TlsMode m) {
    return m == TlsMode::Pinned || m == TlsMode::Trial;
}
// TLS was asked for but the link runs plaintext (heartbeat `tls_fallback`,
// `tls_downgrade` alert).
inline bool tls_mode_is_fallback(TlsMode m) { return m == TlsMode::Fallback; }
// MQTT may connect at all in this mode.
inline bool tls_mode_allows_mqtt(TlsMode m) { return m != TlsMode::FailClosed; }
// Keep retrying the CA fetch.
inline bool tls_mode_wants_ca(TlsMode m) {
    return m == TlsMode::Fallback || m == TlsMode::FailClosed;
}

// May this loop pass start a (blocking) MQTT connect attempt? Not in fail-
// closed mode, not while the BOOT/reset button is held (the hold is timed
// over densely-sampled passes only), and not in a pass that already ran a
// blocking CA fetch — the two together would overrun the loop WDT
// (link_budget.h kCaFetchWorstCaseS).
inline bool mqtt_may_connect(TlsMode m, bool fetched_this_pass,
                             bool button_down) {
    return tls_mode_allows_mqtt(m) && !fetched_this_pass && !button_down;
}

// ── trust-on-first-use acceptance ──────────────────────────────
// The NVS string budget for the pinned PEM; the Pi's CA is ~1.2-2 KB.
constexpr size_t kMaxCaPemBytes = 4000;

// A fetched body becomes a candidate (and, once it verifies, the pin) only if
// it looks like a public certificate and nothing else: a 404/HTML page or
// anything carrying a private key is refused.
inline bool ca_pem_acceptable(const char* body, size_t len) {
    if (body == nullptr || len == 0 || len >= kMaxCaPemBytes) return false;
    const std::string s(body, len);
    return s.find("BEGIN CERTIFICATE") != std::string::npos &&
           s.find("PRIVATE KEY") == std::string::npos;
}

// ── runtime CA-fetch backoff ───────────────────────────────────
// 1, 2, 4, 8 min, then every 15 min. Starts counting at begin() — the
// boot-time attempt (pre-WDT) is the first try. A failed fetch and a failed
// trial of a fetched CA both count as a failure.
class CaFetchBackoff {
public:
    static constexpr uint32_t kFirstRetryMs = 60UL * 1000UL;
    static constexpr uint32_t kMaxRetryMs = 15UL * 60UL * 1000UL;

    void begin(uint32_t now_ms) {
        last_ms_ = now_ms;
        delay_ms_ = kFirstRetryMs;
        failures_ = 0;
    }

    // A fetch may run now (WiFi up, button released, backoff elapsed).
    bool due(uint32_t now_ms, bool wifi_up, bool button_down) const {
        return wifi_up && !button_down &&
               elapsed_ms(now_ms, last_ms_) >= delay_ms_;
    }

    // The fetch at `now_ms` failed: wait twice as long (capped).
    void failed(uint32_t now_ms) {
        last_ms_ = now_ms;
        ++failures_;
        delay_ms_ = delay_ms_ >= kMaxRetryMs / 2 ? kMaxRetryMs : delay_ms_ * 2u;
    }

    uint32_t delay_ms() const { return delay_ms_; }
    uint32_t failures() const { return failures_; }

private:
    uint32_t last_ms_ = 0;
    uint32_t delay_ms_ = kFirstRetryMs;
    uint32_t failures_ = 0;
};

// ── why the link is not on a verified pin ──────────────────────
enum class TlsFailReason : uint8_t {
    None = 0,        // Plain, Pinned, or a first trial nothing has failed yet
    CaUnavailable,   // no CA pinned, the fetch has not returned one
    CertRejected,    // the broker certificate did not verify against the
                     // candidate: the broker host is not in its names (cert
                     // name mismatch) or it was issued by another CA
    TlsUnreachable,  // nothing answered on 8883 (TCP / DNS / handshake timeout)
    TlsError,        // any other TLS failure
    MqttRefused,     // TLS came up but the broker refused the MQTT login or
                     // sent no CONNACK
};

inline const char* tls_fail_reason_str(TlsFailReason r) {
    switch (r) {
        case TlsFailReason::None: return "none";
        case TlsFailReason::CaUnavailable: return "ca_unavailable";
        case TlsFailReason::CertRejected: return "cert_rejected";
        case TlsFailReason::TlsUnreachable: return "tls_unreachable";
        case TlsFailReason::TlsError: return "tls_error";
        case TlsFailReason::MqttRefused: return "mqtt_refused";
    }
    return "?";
}

// The tls_downgrade alert `message` per reason (nullptr: no alert). The
// no-CA text is the one fw-node#2 shipped.
inline const char* tls_downgrade_message(TlsFailReason r) {
    switch (r) {
        case TlsFailReason::None:
            return nullptr;
        case TlsFailReason::CaUnavailable:
            return "Secure MQTT is on but no Pi CA is pinned - running on "
                   "plaintext (credentials unencrypted); retrying the CA "
                   "fetch";
        case TlsFailReason::CertRejected:
            return "Secure MQTT: the Pi's broker certificate did not verify "
                   "(cert name mismatch - the node's Pi address is not in the "
                   "certificate - or a different CA); CA NOT pinned, staying "
                   "on plaintext (credentials unencrypted) and retrying. "
                   "Re-run ./install.sh on the Pi or use sporeprint.local";
        case TlsFailReason::TlsUnreachable:
            return "Secure MQTT: nothing answered on the Pi's TLS port 8883; "
                   "CA NOT pinned, staying on plaintext (credentials "
                   "unencrypted) and retrying";
        case TlsFailReason::TlsError:
            return "Secure MQTT: the TLS handshake with the Pi failed; CA NOT "
                   "pinned, staying on plaintext (credentials unencrypted) "
                   "and retrying";
        case TlsFailReason::MqttRefused:
            return "Secure MQTT: the Pi's TLS listener refused the MQTT "
                   "login; CA NOT pinned, staying on plaintext (credentials "
                   "unencrypted) and retrying";
    }
    return nullptr;
}

// PubSubClient::state() after a failed connect(): MQTT_CONNECT_FAILED (-2)
// means the transport (DNS / TCP / TLS) never came up;
// MQTT_CONNECTION_TIMEOUT (-4, no CONNACK) and 1..5 (CONNACK refused) mean
// it did.
constexpr int kMqttStateConnectFailed = -2;
constexpr int kMqttStateConnectionTimeout = -4;
// WiFiClientSecure::lastError(): mbedTLS MBEDTLS_ERR_X509_CERT_VERIFY_FAILED
// — the peer certificate did not verify (CA or host name) — and the core's
// own -1 for "no TCP connection / handshake timed out".
constexpr int kTlsErrCertVerifyFailed = -0x2700;
constexpr int kTlsErrSocket = -1;

inline TlsFailReason classify_tls_trial_failure(int mqtt_state, int tls_error) {
    // The MQTT state decides whether TLS came up, so a stale lastError from
    // an earlier attempt cannot mislabel a CONNACK refusal.
    if (mqtt_state > 0 || mqtt_state == kMqttStateConnectionTimeout)
        return TlsFailReason::MqttRefused;
    if (tls_error == kTlsErrCertVerifyFailed) return TlsFailReason::CertRejected;
    if (tls_error < kTlsErrSocket) return TlsFailReason::TlsError;
    return TlsFailReason::TlsUnreachable;  // -1, or no TLS result at all (DNS)
}

// ── the verify-before-commit state machine ─────────────────────
class TlsPinMachine {
public:
    // What the caller must do this pass.
    enum class Step : uint8_t {
        Idle,    // nothing
        Fetch,   // run one CA fetch → fetch_failed() or (link moved to TLS
                 // with the fetched candidate) trial_started()
        Commit,  // the candidate got a CONNACK: persist it (broker_ca, then
                 // broker_ca_ok) → trial_verified()
        Revert,  // the candidate's connect attempt failed: persist nothing,
                 // move the link back → trial_failed(reason)
    };

    // Boot. `stored` = a CA is in NVS (broker_ca), `stored_verified` = its
    // verified marker is set (broker_ca_ok), `fetched` = the boot-time fetch
    // (run only when nothing is stored) returned a candidate. A Trial
    // candidate is the stored CA when there is one, else the fetched one.
    TlsMode begin(bool tls_enabled, bool require_tls, bool stored,
                  bool stored_verified, bool fetched, uint32_t now_ms) {
        tls_enabled_ = tls_enabled;
        require_tls_ = require_tls;
        backoff_.begin(now_ms);
        // A fresh MqttLink has made no attempt and no connection yet.
        trial_attempts_ = 0;
        trial_connects_ = 0;
        reason_ = TlsFailReason::None;
        if (!tls_enabled) {
            mode_ = TlsMode::Plain;
        } else if (stored && stored_verified) {
            mode_ = TlsMode::Pinned;
        } else if (stored || fetched) {
            mode_ = TlsMode::Trial;
        } else {
            mode_ = require_tls ? TlsMode::FailClosed : TlsMode::Fallback;
            reason_ = TlsFailReason::CaUnavailable;
        }
        return mode_;
    }

    // Once per loop pass, before the MQTT pump. `link_attempts` = connect
    // attempts the MQTT link actually started (WiFi-down skips don't count),
    // `link_connects` = attempts that got a CONNACK. Counters, not a
    // connected() sample: a CONNACK the broker drops again before the next
    // pass still proved the candidate.
    Step step(uint32_t now_ms, bool wifi_up, bool button_down,
              uint32_t link_attempts, uint32_t link_connects) const {
        if (mode_ == TlsMode::Trial) {
            // Only attempts made on the candidate transport count.
            if (link_connects != trial_connects_) return Step::Commit;
            if (link_attempts != trial_attempts_) return Step::Revert;
            return Step::Idle;
        }
        if (tls_mode_wants_ca(mode_) &&
            backoff_.due(now_ms, wifi_up, button_down))
            return Step::Fetch;
        return Step::Idle;
    }

    void fetch_failed(uint32_t now_ms) { backoff_.failed(now_ms); }

    // The fetch returned a candidate and the link now runs TLS with it.
    // `reason_` is kept: from Fallback the link is still not on a verified
    // pin, and clearing it would re-fire the alert on every trial.
    void trial_started(uint32_t link_attempts, uint32_t link_connects) {
        trial_attempts_ = link_attempts;
        trial_connects_ = link_connects;
        mode_ = TlsMode::Trial;
    }

    void trial_verified() {
        mode_ = TlsMode::Pinned;
        reason_ = TlsFailReason::None;
    }

    void trial_failed(TlsFailReason why, uint32_t now_ms) {
        mode_ = require_tls_ ? TlsMode::FailClosed : TlsMode::Fallback;
        reason_ = why == TlsFailReason::None ? TlsFailReason::TlsError : why;
        backoff_.failed(now_ms);
    }

    TlsMode mode() const { return mode_; }
    // Why the link is not on a verified pin (logs).
    TlsFailReason reason() const { return reason_; }
    // The tls_downgrade alert condition: the reason while the operator's
    // policy allows the plaintext fallback, else None (Require TLS never
    // runs plaintext; Plain/Pinned are not downgrades).
    TlsFailReason downgrade() const {
        if (!tls_enabled_ || require_tls_) return TlsFailReason::None;
        if (mode_ != TlsMode::Fallback && mode_ != TlsMode::Trial)
            return TlsFailReason::None;
        return reason_;
    }
    const CaFetchBackoff& backoff() const { return backoff_; }

private:
    TlsMode mode_ = TlsMode::Plain;
    bool tls_enabled_ = false;
    bool require_tls_ = false;
    uint32_t trial_attempts_ = 0;
    uint32_t trial_connects_ = 0;
    TlsFailReason reason_ = TlsFailReason::None;
    CaFetchBackoff backoff_;
};

// tls_downgrade alert rate limit: entry + hourly like every node alert
// (AlertLatch), and at once when the reason changes (the first alert said
// "no CA"; the trial then found a certificate name mismatch).
class TlsDowngradeLatch {
public:
    bool due(TlsFailReason reason, uint32_t now_ms) {
        if (reason != shown_) {
            latch_.due(false, now_ms);  // clear → the new reason is an entry
            shown_ = reason;
        }
        return latch_.due(reason != TlsFailReason::None, now_ms);
    }
    void emitted(uint32_t now_ms) { latch_.emitted(now_ms); }

private:
    AlertLatch latch_;
    TlsFailReason shown_ = TlsFailReason::None;
};

// ── heartbeat ca_fp ────────────────────────────────────────────
// Lowercase hex SHA-256 of the exact PEM bytes pinned — the body the Pi
// served from GET /api/provision/ca — so the Pi can compare it with its own
// ca.crt and spot a node that trusted another CA (TOFU on a hostile LAN).
constexpr size_t kCaFingerprintHexLen = 64;

inline void ca_fingerprint_hex(const char* pem, size_t len,
                               char out[kCaFingerprintHexLen + 1]) {
    static const char kHex[] = "0123456789abcdef";
    uint8_t digest[32];
    sha256_host(reinterpret_cast<const uint8_t*>(pem), len, digest);
    for (size_t i = 0; i < 32; ++i) {
        out[2 * i] = kHex[digest[i] >> 4];
        out[2 * i + 1] = kHex[digest[i] & 0x0F];
    }
    out[kCaFingerprintHexLen] = '\0';
}

}  // namespace sp
