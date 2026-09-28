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
//   Pinned      CA pinned → TLS 8883, broker verified against the pinned CA.
//   Fallback    no CA, default policy → plaintext, but LOUD: SP_LOG error, a
//               `tls_downgrade` alert (entry + hourly), `tls:false` +
//               `tls_fallback:true` in the heartbeat — and the CA fetch is
//               retried on a capped backoff; the first success switches the
//               live link to TLS (no reboot). Keeps deployed nodes that
//               already run on the fallback reachable.
//   FailClosed  no CA and the operator ticked "Require TLS" (NVS tls_req) →
//               no MQTT at all (the link watchdog's safe mode takes the
//               channels off after 10 min) while the fetch retries; the
//               first success brings the link up on TLS.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include <string>

#include "wrap_time.h"

namespace sp {

enum class TlsMode : uint8_t { Plain, Pinned, Fallback, FailClosed };

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
    }
    return "?";
}

// The link in use is TLS against the pinned CA (heartbeat `tls`).
inline bool tls_mode_is_tls(TlsMode m) { return m == TlsMode::Pinned; }
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

// A fetched body is pinned only if it looks like a public certificate and
// nothing else: a 404/HTML page or anything carrying a private key is refused.
inline bool ca_pem_acceptable(const char* body, size_t len) {
    if (body == nullptr || len == 0 || len >= kMaxCaPemBytes) return false;
    const std::string s(body, len);
    return s.find("BEGIN CERTIFICATE") != std::string::npos &&
           s.find("PRIVATE KEY") == std::string::npos;
}

// ── runtime CA-fetch backoff ───────────────────────────────────
// 1, 2, 4, 8 min, then every 15 min. Starts counting at begin() — the
// boot-time attempt (pre-WDT) is the first try.
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

}  // namespace sp
