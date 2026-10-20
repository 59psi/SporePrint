#pragma once
//
// tls_policy — what the MQTT transport does when "Secure MQTT" is enabled
// but no Pi CA is pinned. The device side (sp_device/
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
//     the next fetch + trial;
//   * on the Fallback a fetched CA is probed (a bare TLS handshake, the
//     plaintext link untouched) before any trial moves the live link — see
//     TlsPinMachine.
// TlsPinMachine holds these decisions; sp_device/tls_transport.h does the
// fetches, probes, NVS writes and transport switches it asks for.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include <string>

#include "alert_latch.h"
#include "hmac_verify.h"  // to_hex_lower
#include "kv_store.h"
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
// blocking CA fetch or TLS probe — the two together would overrun the loop
// WDT (link_budget.h kCaFetchWorstCaseS, kTlsProbeWorstCaseS).
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

// ── the CA fetch's HTTP response ───────────────────────────────
// The runtime fetch runs inside a loop pass, so the WHOLE response — status
// line, headers and body — is read into one bounded buffer under ONE overall
// deadline (link_budget.h kCaFetchReadTimeoutS), never a per-read timeout. A
// host answering on :8000 with a slow drip used to hold the loop past the
// WDT, and a chunked or close-delimited body was read without any size cap.
// The Pi always sends Content-Length for its CA, so a 200 without one (or
// with Transfer-Encoding), or with one at or over the NVS budget, is refused
// before its body is read. scan_ca_response() is run on the bytes received
// so far after every read.
constexpr size_t kMaxCaResponseHeaderBytes = 2048;  // incl. the blank line
constexpr size_t kMaxCaResponseBytes = kMaxCaResponseHeaderBytes + kMaxCaPemBytes;

struct CaResponseScan {
    enum class State : uint8_t { NeedMore, Done, Refused };
    State state = State::NeedMore;
    int status = 0;             // Done: the HTTP status code
    size_t body_offset = 0;     // Done, status 200: the body is
    size_t body_len = 0;        //   buf[body_offset, body_offset + body_len)
    const char* why = nullptr;  // Refused: static reason for the log
};

namespace detail {

inline char ascii_lower(char c) {
    return (c >= 'A' && c <= 'Z') ? (char)(c - 'A' + 'a') : c;
}

// Header line `line[0, len)` is "<name>:<value>" for `name` (lowercase,
// case-insensitive match); *value / *value_len get the value without
// surrounding blanks.
inline bool header_is(const char* line, size_t len, const char* name,
                      const char** value, size_t* value_len) {
    size_t i = 0;
    for (; name[i] != '\0'; ++i)
        if (i >= len || ascii_lower(line[i]) != name[i]) return false;
    if (i >= len || line[i] != ':') return false;
    size_t b = i + 1, e = len;
    while (b < e && (line[b] == ' ' || line[b] == '\t')) ++b;
    while (e > b && (line[e - 1] == ' ' || line[e - 1] == '\t')) --e;
    *value = line + b;
    *value_len = e - b;
    return true;
}

}  // namespace detail

inline CaResponseScan scan_ca_response(const char* buf, size_t len) {
    CaResponseScan r;
    auto refuse = [&r](const char* why) {
        r.state = CaResponseScan::State::Refused;
        r.why = why;
        return r;
    };
    // End of the header block.
    size_t hdr_end = 0;
    for (size_t i = 0; i + 3 < len; ++i) {
        if (buf[i] == '\r' && buf[i + 1] == '\n' && buf[i + 2] == '\r' &&
            buf[i + 3] == '\n') {
            hdr_end = i + 4;
            break;
        }
    }
    if (hdr_end == 0) {
        if (len >= kMaxCaResponseHeaderBytes)
            return refuse("response headers too large");
        return r;  // NeedMore
    }
    if (hdr_end > kMaxCaResponseHeaderBytes)
        return refuse("response headers too large");

    // Status line: "HTTP/1.x NNN ...".
    if (hdr_end < 12 || buf[0] != 'H' || buf[1] != 'T' || buf[2] != 'T' ||
        buf[3] != 'P' || buf[4] != '/' || buf[5] != '1' || buf[6] != '.' ||
        buf[8] != ' ' || buf[9] < '0' || buf[9] > '9' || buf[10] < '0' ||
        buf[10] > '9' || buf[11] < '0' || buf[11] > '9')
        return refuse("not an HTTP response");
    r.status = (buf[9] - '0') * 100 + (buf[10] - '0') * 10 + (buf[11] - '0');
    if (r.status != 200) {
        r.state = CaResponseScan::State::Done;  // the caller logs the status
        return r;
    }

    // Headers: exactly one sane Content-Length, no Transfer-Encoding.
    bool have_length = false;
    size_t length = 0;
    size_t pos = 0;
    while (pos < hdr_end && buf[pos] != '\n') ++pos;  // skip the status line
    ++pos;
    while (pos + 2 <= hdr_end - 2) {
        size_t eol = pos;
        while (eol < hdr_end && buf[eol] != '\r') ++eol;
        const char* v = nullptr;
        size_t vlen = 0;
        if (detail::header_is(buf + pos, eol - pos, "transfer-encoding", &v,
                              &vlen))
            return refuse("Transfer-Encoding body (the Pi sends Content-Length)");
        if (detail::header_is(buf + pos, eol - pos, "content-length", &v, &vlen)) {
            if (vlen == 0 || vlen > 7) return refuse("bad Content-Length");
            size_t n = 0;
            for (size_t i = 0; i < vlen; ++i) {
                if (v[i] < '0' || v[i] > '9') return refuse("bad Content-Length");
                n = n * 10 + (size_t)(v[i] - '0');
            }
            if (have_length && n != length) return refuse("bad Content-Length");
            have_length = true;
            length = n;
        }
        pos = eol + 2;  // past "\r\n"
    }
    if (!have_length) return refuse("no Content-Length (the Pi always sends one)");
    if (length == 0 || length >= kMaxCaPemBytes)
        return refuse("Content-Length out of range - too large to be the Pi CA");
    if (len - hdr_end < length) return r;  // NeedMore: the body is still coming
    r.state = CaResponseScan::State::Done;
    r.body_offset = hdr_end;
    r.body_len = length;
    return r;
}

// ── runtime CA-fetch backoff ───────────────────────────────────
// 1, 2, 4, 8 min, then every 15 min. Starts counting at begin() — the
// boot-time attempt (pre-WDT) is the first try. A failed fetch, a failed
// probe and a failed trial of a fetched CA all count as a failure. A trial
// that dropped the working plaintext link and then failed for a reason a
// probe cannot see (the broker refused the MQTT login on 8883) waits
// kLinkTrialRetryMs instead.
class CaFetchBackoff {
public:
    static constexpr uint32_t kFirstRetryMs = 60UL * 1000UL;
    static constexpr uint32_t kMaxRetryMs = 15UL * 60UL * 1000UL;
    static constexpr uint32_t kLinkTrialRetryMs = 60UL * 60UL * 1000UL;

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

    // A trial cost the live link and failed where a probe cannot look: wait
    // kLinkTrialRetryMs (a later plain failure steps back to the 15 min cap).
    void failed_long(uint32_t now_ms) {
        last_ms_ = now_ms;
        ++failures_;
        delay_ms_ = kLinkTrialRetryMs;
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
// no-CA text is the one the first fallback release shipped.
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
//
// Probe before switching. On the plaintext fallback the MQTT link works; a
// trial moves it to TLS, so a candidate that fails for a lasting reason (a
// broker certificate that does not name the node's Pi address, nothing on
// 8883) used to take a working node off MQTT on every retry — a retained
// "offline", a 2-5 s gap in which commands were lost — every 15 minutes for
// as long as the misconfiguration lasted. Now a CA fetched while on the
// fallback is first PROBED: one bare TLS handshake to 8883 with it, on a
// pass of its own, with the live plaintext link left alone. Only a candidate
// whose handshake verifies moves the link (the trial, as before); a failed
// probe just backs off with its reason. A trial that then fails because the
// broker refused the MQTT login on TLS — the one thing a handshake cannot
// see — retries only hourly (CaFetchBackoff::failed_long). With "Require
// TLS" there is no live link to protect: a fetched candidate is tried at once.
class TlsPinMachine {
public:
    // What the caller must do this pass.
    enum class Step : uint8_t {
        Idle,    // nothing
        Fetch,   // run one CA fetch → fetch_failed(), or fetch_succeeded():
                 // true = move the link to TLS with the candidate now, then
                 // trial_started(); false = it is probed on a later pass
        Commit,  // the candidate got a CONNACK: persist it (broker_ca, then
                 // broker_ca_ok) → trial_verified()
        Revert,  // the candidate's connect attempt failed: persist nothing,
                 // move the link back → trial_failed(reason)
        Probe,   // run one bare TLS handshake with the fetched candidate (no
                 // MQTT, the live link untouched) → probe_passed() (then move
                 // the link to TLS and trial_started()) or probe_failed(reason)
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
        probe_pending_ = false;
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
        // The probe blocks its pass like a fetch: never while the button is
        // held (its hold is timed over densely-sampled passes only).
        if (probe_pending_)
            return wifi_up && !button_down ? Step::Probe : Step::Idle;
        if (tls_mode_wants_ca(mode_) &&
            backoff_.due(now_ms, wifi_up, button_down))
            return Step::Fetch;
        return Step::Idle;
    }

    void fetch_failed(uint32_t now_ms) { backoff_.failed(now_ms); }

    // The fetch returned a candidate. On the plaintext fallback it is probed
    // first (Step::Probe on a later pass): returns false and the caller
    // leaves the link alone. With Require TLS (fail-closed, nothing is up):
    // returns true — the caller moves the link to TLS with it now and calls
    // trial_started().
    bool fetch_succeeded() {
        if (mode_ == TlsMode::Fallback) {
            probe_pending_ = true;
            return false;
        }
        return true;
    }

    // The candidate's handshake verified: the caller moves the link to TLS
    // with it and calls trial_started().
    void probe_passed() { probe_pending_ = false; }

    // The handshake failed: the link was never touched. The reason feeds the
    // tls_downgrade alert; back off before the next fetch.
    void probe_failed(TlsFailReason why, uint32_t now_ms) {
        probe_pending_ = false;
        reason_ = why == TlsFailReason::None ? TlsFailReason::TlsError : why;
        backoff_.failed(now_ms);
    }

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
        // TLS verified but the broker refused the MQTT login on 8883: a probe
        // cannot see that, and every retry would drop the working plaintext
        // link again — retry it hourly. (Fail-closed has no link to drop.)
        if (mode_ == TlsMode::Fallback && reason_ == TlsFailReason::MqttRefused)
            backoff_.failed_long(now_ms);
        else
            backoff_.failed(now_ms);
    }

    TlsMode mode() const { return mode_; }
    // A fetched candidate waits for its probe.
    bool probe_pending() const { return probe_pending_; }
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
    bool probe_pending_ = false;
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
    uint8_t digest[32];
    sha256_host(reinterpret_cast<const uint8_t*>(pem), len, digest);
    to_hex_lower(digest, sizeof(digest), out);
}

// ── persisting a verified pin ──────────────────────────────────
// A trial connected on `ca`: store it, then set the verified marker — but
// only once a read-back shows the store holds exactly `ca`. A failed write
// (full NVS, flash fault) must not leave the marker vouching for an older,
// unverified CA still stored: the next boot would pin that one without a
// trial, and Pinned never fetches, so TLS would stay locked out. On a
// mismatch the marker is cleared instead; the link stays on TLS this boot and
// the next boot runs the trial again. True when the pin was persisted.
inline bool persist_verified_ca(KvStore& kv, const char* ca_key,
                                const char* ok_key, const std::string& ca) {
    if (ca.empty()) return false;
    if (kv.get_string(ca_key, "") != ca) kv.set_string(ca_key, ca);
    if (kv.get_string(ca_key, "") != ca) {
        kv.set_bool(ok_key, false);
        return false;
    }
    kv.set_bool(ok_key, true);
    return true;
}

}  // namespace sp
