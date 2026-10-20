// test_core_tls — Secure MQTT transport policy when no Pi CA is pinned.
//
// Regression pinned here: with "Secure MQTT" ticked and the CA fetch failing
// (the Pi's /api/provision/ca 404'd on every Docker deployment), the node
// silently fell back to plaintext 1883 — credentials in the clear, a single
// Serial line as the only trace, and no retry until a reboot. The policy now:
//   * says which transport is actually in use (heartbeat `tls`,
//     `tls_fallback`; a `tls_downgrade` alert while on the fallback)
//   * retries the CA fetch at runtime on a capped exponential backoff and
//     switches to TLS as soon as one is pinned
//   * fails CLOSED (no MQTT at all until a CA is pinned) when the operator
//     ticked "Require TLS"
//   * keeps a runtime CA fetch inside the loop WDT and never stacks it on an
//     MQTT connect attempt in the same pass
//
// Regression pinned here too (final review, safety-contract): the fetched CA
// was written to NVS and the live link moved to TLS 8883 BEFORE any TLS
// connection had succeeded. A broker certificate that did not cover the
// node's broker host (an IP host with a DNS-only certificate, a changed IP)
// then failed every handshake forever: a working plaintext node locked
// itself out of MQTT, fell into safe mode after 10 min, and only physical
// access recovered it. Now a fetched CA (or one an older image stored
// without verifying it) is only a CANDIDATE: the link tries TLS with it
// from RAM, and it is persisted — and the node stays on TLS — only after a
// CONNACK on it. A failed trial goes back to the plaintext fallback (or to
// fail-closed with "Require TLS"), says why in the tls_downgrade alert, and
// backs off before trying again.

#include <unity.h>

#include <stdint.h>
#include <string.h>

#include <string>

#include "alert_latch.h"
#include "link_budget.h"
#include "tls_policy.h"

void setUp() {}
void tearDown() {}

// ── transport mode ─────────────────────────────────────────────

void test_tls_off_is_plain_and_never_fetches() {
    for (int pinned = 0; pinned < 2; ++pinned)
        for (int req = 0; req < 2; ++req) {
            sp::TlsMode m = sp::tls_mode(false, pinned, req);
            TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Plain, (int)m);
            TEST_ASSERT_FALSE(sp::tls_mode_wants_ca(m));
            TEST_ASSERT_TRUE(sp::tls_mode_allows_mqtt(m));
            TEST_ASSERT_FALSE(sp::tls_mode_is_tls(m));
            TEST_ASSERT_FALSE(sp::tls_mode_is_fallback(m));
        }
}

void test_pinned_ca_runs_tls() {
    for (int req = 0; req < 2; ++req) {
        sp::TlsMode m = sp::tls_mode(true, true, req);
        TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Pinned, (int)m);
        TEST_ASSERT_TRUE(sp::tls_mode_is_tls(m));
        TEST_ASSERT_TRUE(sp::tls_mode_allows_mqtt(m));
        TEST_ASSERT_FALSE(sp::tls_mode_wants_ca(m));
    }
}

void test_missing_ca_is_a_loud_fallback_by_default() {
    sp::TlsMode m = sp::tls_mode(true, false, /*require_tls=*/false);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m);
    TEST_ASSERT_FALSE(sp::tls_mode_is_tls(m));
    TEST_ASSERT_TRUE(sp::tls_mode_is_fallback(m));  // → heartbeat + alert
    TEST_ASSERT_TRUE(sp::tls_mode_allows_mqtt(m));  // deployed behavior kept
    TEST_ASSERT_TRUE(sp::tls_mode_wants_ca(m));     // … but keeps retrying
}

void test_missing_ca_fails_closed_when_tls_is_required() {
    sp::TlsMode m = sp::tls_mode(true, false, /*require_tls=*/true);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::FailClosed, (int)m);
    TEST_ASSERT_FALSE(sp::tls_mode_allows_mqtt(m));  // never plaintext
    TEST_ASSERT_TRUE(sp::tls_mode_wants_ca(m));
    TEST_ASSERT_FALSE(sp::tls_mode_is_fallback(m));
}

void test_mode_strings_are_stable() {
    TEST_ASSERT_EQUAL_STRING("plain", sp::tls_mode_str(sp::TlsMode::Plain));
    TEST_ASSERT_EQUAL_STRING("tls", sp::tls_mode_str(sp::TlsMode::Pinned));
    TEST_ASSERT_EQUAL_STRING("plain_fallback",
                             sp::tls_mode_str(sp::TlsMode::Fallback));
    TEST_ASSERT_EQUAL_STRING("blocked",
                             sp::tls_mode_str(sp::TlsMode::FailClosed));
}

// ── CA fetch backoff ───────────────────────────────────────────

void test_backoff_doubles_to_the_cap() {
    sp::CaFetchBackoff b;
    b.begin(0);
    uint32_t now = 0;
    const uint32_t expect[] = {60000, 120000, 240000, 480000, 900000, 900000};
    for (uint32_t d : expect) {
        TEST_ASSERT_EQUAL_UINT32(d, b.delay_ms());
        TEST_ASSERT_FALSE(b.due(now + d - 1, true, false));
        TEST_ASSERT_TRUE(b.due(now + d, true, false));
        now += d;
        b.failed(now);
    }
    TEST_ASSERT_EQUAL_UINT32(6, b.failures());
}

void test_backoff_waits_for_wifi_and_a_released_button() {
    sp::CaFetchBackoff b;
    b.begin(1000);
    const uint32_t t = 1000 + sp::CaFetchBackoff::kFirstRetryMs;
    TEST_ASSERT_FALSE(b.due(t, /*wifi_up=*/false, false));
    // The BOOT/reset gesture is timed over densely-sampled passes only — a
    // blocking fetch must not start while the button is down.
    TEST_ASSERT_FALSE(b.due(t, true, /*button_down=*/true));
    TEST_ASSERT_TRUE(b.due(t, true, false));
}

void test_backoff_is_wrap_safe() {
    sp::CaFetchBackoff b;
    uint32_t t0 = 0xFFFFFFFFu - 10000u;
    b.begin(t0);
    uint32_t due_at = t0 + sp::CaFetchBackoff::kFirstRetryMs;  // wrapped
    TEST_ASSERT_TRUE(due_at < t0);
    TEST_ASSERT_FALSE(b.due(due_at - 1, true, false));
    TEST_ASSERT_TRUE(b.due(due_at, true, false));
}

// ── time budget ────────────────────────────────────────────────

void test_runtime_ca_fetch_fits_inside_the_loop_wdt() {
    // A runtime fetch blocks one loop pass: DNS + TCP connect + HTTP read.
    TEST_ASSERT_TRUE(sp::kCaFetchWorstCaseS + sp::kLoopWdtMarginS <=
                     sp::kLoopWdtTimeoutS);
    TEST_ASSERT_EQUAL_UINT32(sp::kDnsWorstCaseS + sp::kCaFetchConnectTimeoutS +
                                 sp::kCaFetchReadTimeoutS,
                             sp::kCaFetchWorstCaseS);
    // …and never shares a pass with an MQTT connect attempt: together they
    // would not fit.
    TEST_ASSERT_TRUE(sp::kCaFetchWorstCaseS + sp::kConnectAttemptWorstCaseS >
                     sp::kLoopWdtTimeoutS);
}

void test_tls_probe_fits_inside_the_loop_wdt() {
    // The probe of a fetched CA: DNS + TCP connect + handshake, no CONNACK.
    TEST_ASSERT_EQUAL_UINT32(sp::kDnsWorstCaseS + sp::kTcpConnectTimeoutS +
                                 sp::kTlsHandshakeTimeoutS,
                             sp::kTlsProbeWorstCaseS);
    TEST_ASSERT_TRUE(sp::kTlsProbeWorstCaseS + sp::kLoopWdtMarginS <=
                     sp::kLoopWdtTimeoutS);
    // A pass of its own, like a fetch: with a connect attempt it would not fit.
    TEST_ASSERT_TRUE(sp::kTlsProbeWorstCaseS + sp::kConnectAttemptWorstCaseS >
                     sp::kLoopWdtTimeoutS);
}

void test_mqtt_connect_is_suppressed_in_a_fetch_pass() {
    // mqtt_may_connect(mode, fetched_this_pass, button_down)
    TEST_ASSERT_TRUE(sp::mqtt_may_connect(sp::TlsMode::Plain, false, false));
    TEST_ASSERT_TRUE(sp::mqtt_may_connect(sp::TlsMode::Fallback, false, false));
    TEST_ASSERT_FALSE(sp::mqtt_may_connect(sp::TlsMode::Fallback, true, false));
    TEST_ASSERT_FALSE(sp::mqtt_may_connect(sp::TlsMode::Pinned, false, true));
    TEST_ASSERT_FALSE(sp::mqtt_may_connect(sp::TlsMode::FailClosed, false, false));
    TEST_ASSERT_TRUE(sp::mqtt_may_connect(sp::TlsMode::Pinned, false, false));
}

// ── CA acceptance (TOFU) ───────────────────────────────────────

void test_only_a_plausible_public_pem_is_pinned() {
    const char* good =
        "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n";
    TEST_ASSERT_TRUE(sp::ca_pem_acceptable(good, strlen(good)));
    TEST_ASSERT_FALSE(sp::ca_pem_acceptable("", 0));
    TEST_ASSERT_FALSE(sp::ca_pem_acceptable("<html>404</html>", 16));
    const char* with_key =
        "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n"
        "-----BEGIN PRIVATE KEY-----\ny\n-----END PRIVATE KEY-----\n";
    TEST_ASSERT_FALSE(sp::ca_pem_acceptable(with_key, strlen(with_key)));
    // Oversize (NVS string budget) is refused, even if it looks like a cert.
    std::string big(good);
    big.resize(sp::kMaxCaPemBytes, 'A');
    TEST_ASSERT_FALSE(sp::ca_pem_acceptable(big.c_str(), big.size()));
    big.resize(sp::kMaxCaPemBytes - 1);
    TEST_ASSERT_TRUE(sp::ca_pem_acceptable(big.c_str(), big.size()));
}

// ── the CA fetch's HTTP response (bounded) ─────────────────────
//
// The runtime fetch read the body with HTTPClient::getString(): only a
// per-read timeout and, for a chunked or close-delimited 200, no size cap — a
// slow-drip or endless answer on :8000 held the loop past the WDT or ate the
// heap. The response is now scanned as it arrives: a 200 must carry a sane
// Content-Length (the Pi always sends one), and the device stops reading at
// Done / Refused or its one deadline.

using Scan = sp::CaResponseScan;

static const char kPem[] =
    "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n";

static std::string ca_response(const std::string& headers,
                               const std::string& body) {
    return "HTTP/1.1 200 OK\r\n" + headers + "\r\n" + body;
}

void test_ca_response_with_content_length_is_complete_when_the_body_is() {
    const std::string body = kPem;
    // uvicorn's lowercase header names, as the Pi sends them.
    const std::string resp = ca_response(
        "date: Sat, 17 Oct 2026 10:00:00 GMT\r\nserver: uvicorn\r\n"
        "content-length: " + std::to_string(body.size()) +
            "\r\ncontent-type: text/plain; charset=utf-8\r\n",
        body);
    // Every prefix short of the full body still needs more.
    for (size_t n = 0; n < resp.size(); ++n)
        TEST_ASSERT_EQUAL_INT((int)Scan::State::NeedMore,
                              (int)sp::scan_ca_response(resp.data(), n).state);
    Scan s = sp::scan_ca_response(resp.data(), resp.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Done, (int)s.state);
    TEST_ASSERT_EQUAL_INT(200, s.status);
    TEST_ASSERT_EQUAL_size_t(body.size(), s.body_len);
    TEST_ASSERT_EQUAL_STRING(body.c_str(),
                             resp.substr(s.body_offset, s.body_len).c_str());
    // Bytes past Content-Length are not part of the body.
    const std::string extra = resp + "garbage";
    s = sp::scan_ca_response(extra.data(), extra.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Done, (int)s.state);
    TEST_ASSERT_EQUAL_size_t(body.size(), s.body_len);
    // Header names are case-insensitive, values may be padded.
    const std::string caps =
        ca_response("Content-Length:   " + std::to_string(body.size()) + " \r\n",
                    body);
    s = sp::scan_ca_response(caps.data(), caps.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Done, (int)s.state);
    TEST_ASSERT_EQUAL_size_t(body.size(), s.body_len);
}

void test_ca_response_without_a_sane_length_is_refused_before_the_body() {
    // Chunked, or close-delimited: refused as soon as the headers are in.
    const std::string chunked =
        ca_response("transfer-encoding: chunked\r\n", "7d0\r\n");
    Scan s = sp::scan_ca_response(chunked.data(), chunked.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Refused, (int)s.state);
    TEST_ASSERT_NOT_NULL(s.why);
    const std::string unsized = ca_response("server: x\r\n", kPem);
    s = sp::scan_ca_response(unsized.data(), unsized.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Refused, (int)s.state);
    // At or over the NVS budget, zero, junk, or two disagreeing lengths.
    const std::string too_big = ca_response(
        "content-length: " + std::to_string(sp::kMaxCaPemBytes) + "\r\n", "");
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Refused,
                          (int)sp::scan_ca_response(too_big.data(), too_big.size()).state);
    const std::string max_ok = ca_response(
        "content-length: " + std::to_string(sp::kMaxCaPemBytes - 1) + "\r\n", "");
    TEST_ASSERT_EQUAL_INT((int)Scan::State::NeedMore,
                          (int)sp::scan_ca_response(max_ok.data(), max_ok.size()).state);
    for (const char* bad : {"content-length: 0\r\n", "content-length: 12a\r\n",
                            "content-length: \r\n", "content-length: 99999999\r\n",
                            "content-length: 10\r\ncontent-length: 11\r\n"}) {
        const std::string r = ca_response(bad, "");
        TEST_ASSERT_EQUAL_INT_MESSAGE(
            (int)Scan::State::Refused,
            (int)sp::scan_ca_response(r.data(), r.size()).state, bad);
    }
    // Endless headers: refused once the header budget is used up.
    std::string endless = "HTTP/1.1 200 OK\r\n";
    while (endless.size() < sp::kMaxCaResponseHeaderBytes) endless += "x-pad: 0\r\n";
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Refused,
                          (int)sp::scan_ca_response(endless.data(), endless.size()).state);
    // Not HTTP at all.
    const char* junk = "SSH-2.0-OpenSSH_9.6\r\n\r\n";
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Refused,
                          (int)sp::scan_ca_response(junk, strlen(junk)).state);
    // The worst case the device buffer must hold fits its cap.
    TEST_ASSERT_TRUE(sp::kMaxCaResponseHeaderBytes + sp::kMaxCaPemBytes - 1 <=
                     sp::kMaxCaResponseBytes);
}

void test_ca_response_error_status_is_done_without_a_body() {
    // 404 (no CA on the Pi yet) and 401 (API-key gate) are reported by status;
    // the body is never needed.
    const std::string not_found =
        "HTTP/1.1 404 Not Found\r\ncontent-length: 120\r\n\r\n";
    Scan s = sp::scan_ca_response(not_found.data(), not_found.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Done, (int)s.state);
    TEST_ASSERT_EQUAL_INT(404, s.status);
    const std::string unauthorized = "HTTP/1.0 401 Unauthorized\r\n\r\n";
    s = sp::scan_ca_response(unauthorized.data(), unauthorized.size());
    TEST_ASSERT_EQUAL_INT((int)Scan::State::Done, (int)s.state);
    TEST_ASSERT_EQUAL_INT(401, s.status);
}

// ── verify-before-commit (TlsPinMachine) ───────────────────────

using Step = sp::TlsPinMachine::Step;
using Why = sp::TlsFailReason;

static constexpr uint32_t kFirst = sp::CaFetchBackoff::kFirstRetryMs;

void test_trial_mode_runs_tls_but_is_not_pinned() {
    const sp::TlsMode t = sp::TlsMode::Trial;
    TEST_ASSERT_TRUE(sp::tls_mode_is_tls(t));        // the link IS TLS …
    TEST_ASSERT_FALSE(sp::tls_mode_is_fallback(t));
    TEST_ASSERT_TRUE(sp::tls_mode_allows_mqtt(t));   // … and must connect
    TEST_ASSERT_FALSE(sp::tls_mode_wants_ca(t));     // it has a candidate
    TEST_ASSERT_EQUAL_STRING("tls_trial", sp::tls_mode_str(t));
    TEST_ASSERT_TRUE(sp::mqtt_may_connect(t, false, false));
    TEST_ASSERT_FALSE(sp::mqtt_may_connect(t, true, false));
    TEST_ASSERT_FALSE(sp::mqtt_may_connect(t, false, true));
}

void test_boot_modes() {
    sp::TlsPinMachine m;
    // begin(tls_enabled, require_tls, stored, stored_verified, fetched, now)
    // Secure MQTT off: plain, whatever is stored, never fetches.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Plain,
                          (int)m.begin(false, false, true, true, false, 0));
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(10 * kFirst, true, false, 0, 0));
    // A CA this image verified (broker_ca_ok) is trusted as before.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Pinned,
                          (int)m.begin(true, false, true, true, false, 0));
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.reason());
    // A CA stored WITHOUT the verified marker — pinned unverified by an older
    // image — only gets a trial: it may be the one locking the node out.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Trial,
                          (int)m.begin(true, false, true, false, false, 0));
    // Nothing stored, the boot fetch returned one: a trial, not a pin.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Trial,
                          (int)m.begin(true, false, false, false, true, 0));
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.downgrade());  // not plaintext
    // Nothing stored, nothing fetched: the existing fallback / fail-closed.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback,
                          (int)m.begin(true, false, false, false, false, 0));
    TEST_ASSERT_EQUAL_INT((int)Why::CaUnavailable, (int)m.reason());
    TEST_ASSERT_EQUAL_INT((int)Why::CaUnavailable, (int)m.downgrade());
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::FailClosed,
                          (int)m.begin(true, true, false, false, false, 0));
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.downgrade());  // no plaintext
}

void test_candidate_is_committed_only_after_a_connack() {
    sp::TlsPinMachine m;
    m.begin(true, false, false, false, /*fetched=*/true, 0);
    // No connect attempt has run yet (WiFi down, button held, first pass):
    // nothing is decided — and nothing persisted — however long it takes.
    TEST_ASSERT_EQUAL_INT((int)Step::Idle, (int)m.step(1000, true, false, 0, 0));
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(100 * kFirst, false, false, 0, 0));
    // step(now, wifi_up, button_down, link_attempts, link_connects)
    // The attempt got a CONNACK on the candidate: commit.
    TEST_ASSERT_EQUAL_INT((int)Step::Commit, (int)m.step(2000, true, false, 1, 1));
    m.trial_verified();
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Pinned, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.reason());
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.downgrade());
    // A verified pin is final: no more fetches, no revert on a later outage
    // (a broker that is down, or an impostor, must not downgrade it).
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(100 * kFirst, true, false, 9, 3));
}

void test_failed_trial_returns_to_the_plaintext_fallback() {
    // The lockout regression: a candidate whose handshake fails must leave
    // the node on the working plaintext link, not on TLS forever.
    sp::TlsPinMachine m;
    m.begin(true, false, false, false, /*fetched=*/true, 0);
    TEST_ASSERT_EQUAL_INT((int)Step::Revert, (int)m.step(3000, true, false, 1, 0));
    m.trial_failed(Why::CertRejected, 3000);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
    TEST_ASSERT_TRUE(sp::tls_mode_allows_mqtt(m.mode()));
    TEST_ASSERT_TRUE(sp::tls_mode_is_fallback(m.mode()));
    // The alert says why.
    TEST_ASSERT_EQUAL_INT((int)Why::CertRejected, (int)m.reason());
    TEST_ASSERT_EQUAL_INT((int)Why::CertRejected, (int)m.downgrade());
    // … and backs off before the next fetch + trial (1 min → 2 min).
    TEST_ASSERT_EQUAL_UINT32(1, m.backoff().failures());
    TEST_ASSERT_EQUAL_UINT32(2 * kFirst, m.backoff().delay_ms());
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(3000 + 2 * kFirst - 1, true, false, 1, 0));
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch,
                          (int)m.step(3000 + 2 * kFirst, true, false, 1, 0));
}

void test_require_tls_trial_failure_fails_closed_again() {
    sp::TlsPinMachine m;
    m.begin(true, /*require_tls=*/true, false, false, /*fetched=*/true, 0);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Trial, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Step::Revert, (int)m.step(10, true, false, 1, 0));
    m.trial_failed(Why::TlsUnreachable, 10);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::FailClosed, (int)m.mode());
    TEST_ASSERT_FALSE(sp::tls_mode_allows_mqtt(m.mode()));  // never plaintext
    TEST_ASSERT_EQUAL_INT((int)Why::TlsUnreachable, (int)m.reason());  // logged
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.downgrade());  // not a downgrade
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch,
                          (int)m.step(10 + 2 * kFirst, true, false, 1, 0));
}

void test_runtime_trial_keeps_the_downgrade_latched_until_commit() {
    sp::TlsPinMachine m;
    m.begin(true, false, false, false, /*fetched=*/false, 0);  // Fallback
    uint32_t now = kFirst;
    TEST_ASSERT_EQUAL_INT((int)Step::Idle, (int)m.step(now - 1, true, false, 3, 2));
    TEST_ASSERT_EQUAL_INT((int)Step::Idle, (int)m.step(now, /*wifi=*/false, false, 3, 2));
    TEST_ASSERT_EQUAL_INT((int)Step::Idle, (int)m.step(now, true, /*btn=*/true, 3, 2));
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(now, true, false, 3, 2));
    // The fetch returned a CA. On the fallback it is probed before the
    // working plaintext link moves: nothing switches in the fetch pass.
    TEST_ASSERT_FALSE(m.fetch_succeeded());
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Step::Probe, (int)m.step(now + 1, true, false, 3, 2));
    // The handshake verified; the glue moved the link to TLS with it. The
    // plaintext link had made 3 attempts and connected twice.
    m.probe_passed();
    m.trial_started(/*link_attempts=*/3, /*link_connects=*/2);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Trial, (int)m.mode());
    // Still a downgrade while the candidate is unproven, so the alert latch
    // does not clear + re-fire on every trial.
    TEST_ASSERT_EQUAL_INT((int)Why::CaUnavailable, (int)m.downgrade());
    // The trial's own attempt has not run yet: no verdict.
    TEST_ASSERT_EQUAL_INT((int)Step::Idle, (int)m.step(now + 1, true, false, 3, 2));
    // It ran and got no CONNACK: TLS verified (the probe saw to that) but the
    // broker refused the login on 8883.
    TEST_ASSERT_EQUAL_INT((int)Step::Revert, (int)m.step(now + 2, true, false, 4, 2));
    m.trial_failed(Why::MqttRefused, now + 2);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused, (int)m.downgrade());
    // A probe cannot see that failure, and each trial drops the working
    // plaintext link: it is retried hourly, not on the minutes backoff.
    TEST_ASSERT_EQUAL_UINT32(sp::CaFetchBackoff::kLinkTrialRetryMs,
                             m.backoff().delay_ms());
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(now + 2 + 15 * 60 * 1000, true, false, 5, 3));
    // A failed fetch keeps the most recent reason; after the long wait the
    // backoff steps back to its 15-min cap.
    now += 2 + sp::CaFetchBackoff::kLinkTrialRetryMs;
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(now, true, false, 5, 3));
    m.fetch_failed(now);
    TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused, (int)m.reason());
    TEST_ASSERT_EQUAL_UINT32(2, m.backoff().failures());
    TEST_ASSERT_EQUAL_UINT32(sp::CaFetchBackoff::kMaxRetryMs, m.backoff().delay_ms());
    // Next time it works.
    now += sp::CaFetchBackoff::kMaxRetryMs;
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(now, true, false, 5, 3));
    TEST_ASSERT_FALSE(m.fetch_succeeded());
    TEST_ASSERT_EQUAL_INT((int)Step::Probe, (int)m.step(now + 1, true, false, 5, 3));
    m.probe_passed();
    m.trial_started(5, 3);
    // A CONNACK counts even if the broker dropped the link again before this
    // pass sampled it: the candidate verified.
    TEST_ASSERT_EQUAL_INT((int)Step::Commit, (int)m.step(now + 5, true, false, 6, 4));
    m.trial_verified();
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Pinned, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.downgrade());
}

// The plaintext fallback used to move its WORKING link to TLS for every
// fetched candidate: a broker certificate that does not list the node's Pi
// address (DHCP moved the Pi; a certificate older than the IP SANs) failed
// each trial, so the node dropped off MQTT — retained "offline", commands
// lost in the gap — every 15 minutes for as long as that lasted. The
// candidate is now probed with a bare handshake first; a failed probe never
// touches the link.
void test_probe_failure_keeps_the_plaintext_link() {
    sp::TlsPinMachine m;
    m.begin(true, false, false, false, /*fetched=*/false, 0);  // Fallback
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(kFirst, true, false, 7, 7));
    TEST_ASSERT_FALSE(m.fetch_succeeded());  // no switch requested
    TEST_ASSERT_TRUE(m.probe_pending());
    // The probe blocks its pass: never while the button is held or WiFi is
    // down — it waits for a pass where it can run.
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(kFirst + 1, true, /*btn=*/true, 7, 7));
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(kFirst + 1, /*wifi=*/false, false, 7, 7));
    TEST_ASSERT_EQUAL_INT((int)Step::Probe, (int)m.step(kFirst + 2, true, false, 7, 7));
    m.probe_failed(Why::CertRejected, kFirst + 2);
    TEST_ASSERT_FALSE(m.probe_pending());
    // Still on the plaintext fallback: the link was never moved.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
    TEST_ASSERT_TRUE(sp::tls_mode_allows_mqtt(m.mode()));
    // The alert says why, and the next fetch + probe backs off as before.
    TEST_ASSERT_EQUAL_INT((int)Why::CertRejected, (int)m.downgrade());
    TEST_ASSERT_EQUAL_UINT32(1, m.backoff().failures());
    TEST_ASSERT_EQUAL_UINT32(2 * kFirst, m.backoff().delay_ms());
    // MQTT keeps running on plaintext meanwhile (more attempts and connects
    // on the plaintext link decide nothing: no trial is running).
    TEST_ASSERT_EQUAL_INT((int)Step::Idle,
                          (int)m.step(kFirst + 2 + 2 * kFirst - 1, true, false, 9, 9));
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch,
                          (int)m.step(kFirst + 2 + 2 * kFirst, true, false, 9, 9));
    // Across the whole cycle the mode never left Fallback.
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
}

// "Require TLS" keeps MQTT down until a CA verifies: there is no live link to
// protect, so a fetched candidate is tried at once, and a login refused on
// TLS keeps the ordinary backoff (an hour offline would only delay recovery).
void test_require_tls_tries_a_fetched_candidate_at_once() {
    sp::TlsPinMachine m;
    m.begin(true, /*require_tls=*/true, false, false, false, 0);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::FailClosed, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(kFirst, true, false, 0, 0));
    TEST_ASSERT_TRUE(m.fetch_succeeded());  // move the link now
    TEST_ASSERT_FALSE(m.probe_pending());
    m.trial_started(0, 0);
    TEST_ASSERT_EQUAL_INT((int)Step::Revert, (int)m.step(kFirst + 5, true, false, 1, 0));
    m.trial_failed(Why::MqttRefused, kFirst + 5);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::FailClosed, (int)m.mode());
    TEST_ASSERT_EQUAL_UINT32(2 * kFirst, m.backoff().delay_ms());
}

void test_unverified_stored_ca_that_fails_is_never_final() {
    // An older image pinned the CA without verifying it and the handshake
    // fails: the new image falls back and keeps fetching the Pi's CA.
    sp::TlsPinMachine m;
    m.begin(true, false, /*stored=*/true, /*verified=*/false, false, 0);
    TEST_ASSERT_EQUAL_INT((int)Step::Revert, (int)m.step(5, true, false, 1, 0));
    m.trial_failed(Why::CertRejected, 5);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
    TEST_ASSERT_TRUE(sp::tls_mode_wants_ca(m.mode()));
}

void test_trial_failure_classification() {
    // PubSubClient::state() after connect(): -2 = the transport never came
    // up (DNS / TCP / TLS); -4 = no CONNACK in time; 1..5 = CONNACK refused.
    // WiFiClientSecure::lastError(): -0x2700 = the broker certificate did
    // not verify (other CA, or the broker host is not in the certificate's
    // names); -1 = TCP connect failed or the handshake timed out.
    TEST_ASSERT_EQUAL_INT((int)Why::CertRejected,
                          (int)sp::classify_tls_trial_failure(-2, -0x2700));
    TEST_ASSERT_EQUAL_INT((int)Why::TlsUnreachable,
                          (int)sp::classify_tls_trial_failure(-2, -1));
    TEST_ASSERT_EQUAL_INT((int)Why::TlsUnreachable,
                          (int)sp::classify_tls_trial_failure(-2, 0));  // DNS
    TEST_ASSERT_EQUAL_INT((int)Why::TlsError,
                          (int)sp::classify_tls_trial_failure(-2, -0x7280));
    TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused,
                          (int)sp::classify_tls_trial_failure(-4, 54));
    for (int rc = 1; rc <= 5; ++rc)
        TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused,
                              (int)sp::classify_tls_trial_failure(rc, 54));
    // A stale TLS error from an earlier attempt can't mislabel a CONNACK
    // refusal: the MQTT state decides whether the transport came up.
    TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused,
                          (int)sp::classify_tls_trial_failure(5, -0x2700));
}

void test_downgrade_messages_name_the_reason() {
    TEST_ASSERT_NULL(sp::tls_downgrade_message(Why::None));
    // The pre-existing message is unchanged for the no-CA case.
    TEST_ASSERT_EQUAL_STRING(
        "Secure MQTT is on but no Pi CA is pinned - running on plaintext "
        "(credentials unencrypted); retrying the CA fetch",
        sp::tls_downgrade_message(Why::CaUnavailable));
    TEST_ASSERT_NOT_NULL(strstr(sp::tls_downgrade_message(Why::CertRejected),
                                "name mismatch"));
    const Why all[] = {Why::CaUnavailable, Why::CertRejected,
                       Why::TlsUnreachable, Why::TlsError, Why::MqttRefused};
    for (Why a : all) {
        const char* msg = sp::tls_downgrade_message(a);
        TEST_ASSERT_NOT_NULL(msg);
        TEST_ASSERT_NOT_NULL(strstr(msg, "plaintext"));
        TEST_ASSERT_TRUE(strlen(sp::tls_fail_reason_str(a)) > 0);
        for (Why b : all)
            if (a != b)
                TEST_ASSERT_TRUE(strcmp(msg, sp::tls_downgrade_message(b)) != 0);
    }
    TEST_ASSERT_EQUAL_STRING("cert_rejected",
                             sp::tls_fail_reason_str(Why::CertRejected));
}

void test_downgrade_latch_refires_on_a_new_reason_only() {
    sp::TlsDowngradeLatch l;
    const uint32_t hour = sp::kAlertReemitMs;
    TEST_ASSERT_FALSE(l.due(Why::None, 0));
    TEST_ASSERT_TRUE(l.due(Why::CaUnavailable, 1000));  // entry
    TEST_ASSERT_TRUE(l.due(Why::CaUnavailable, 1500));  // not yet published
    l.emitted(1500);
    TEST_ASSERT_FALSE(l.due(Why::CaUnavailable, 2000));
    // A trial failed for a NEW reason: say so now, not in an hour.
    TEST_ASSERT_TRUE(l.due(Why::CertRejected, 3000));
    l.emitted(3000);
    // The same failure on every retry (1, 2, 4, 8, 15 min): quiet …
    TEST_ASSERT_FALSE(l.due(Why::CertRejected, 3000 + 15 * 60 * 1000));
    // … apart from the hourly reminder.
    TEST_ASSERT_TRUE(l.due(Why::CertRejected, 3000 + hour));
    l.emitted(3000 + hour);
    // Pinned: cleared; a later downgrade is a new entry.
    TEST_ASSERT_FALSE(l.due(Why::None, 3000 + hour + 1));
    TEST_ASSERT_TRUE(l.due(Why::CertRejected, 3000 + hour + 2));
}

// ── heartbeat ca_fp ────────────────────────────────────────────

void test_ca_fingerprint_is_lowercase_hex_sha256_of_the_pem_bytes() {
    char fp[sp::kCaFingerprintHexLen + 1];
    sp::ca_fingerprint_hex("abc", 3, fp);
    TEST_ASSERT_EQUAL_STRING(
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", fp);
    // Same bytes the Pi serves from GET /api/provision/ca — value from
    // Python: hashlib.sha256(pem.encode()).hexdigest().
    const char* pem =
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBszCCAVmgAwIBAgIUSporePrintTestCA0000000000000wCgYIKoZIzj0EAwIw\n"
        "-----END CERTIFICATE-----\n";
    sp::ca_fingerprint_hex(pem, strlen(pem), fp);
    TEST_ASSERT_EQUAL_STRING(
        "cab3b27e4135403fdb3b368802d2b1bce67d4b8c1ab4c73245961524ceab0ef4", fp);
    TEST_ASSERT_EQUAL_size_t(64, strlen(fp));
}

// ── persisting a verified pin (commit) ─────────────────────────

// A store whose string writes are lost (full NVS, flash fault), while the
// small bool entry still writes.
class DroppingStringsKv : public sp::MemKvStore {
public:
    bool drop_strings = false;
    void set_string(const char* key, const std::string& value) override {
        if (!drop_strings) sp::MemKvStore::set_string(key, value);
    }
};

void test_verified_marker_only_vouches_for_the_stored_ca() {
    const char* kCa = "broker_ca";
    const char* kOk = "broker_ca_ok";
    // Normal commit: CA stored, marker set.
    DroppingStringsKv kv;
    TEST_ASSERT_TRUE(sp::persist_verified_ca(kv, kCa, kOk, "PEM-B"));
    TEST_ASSERT_EQUAL_STRING("PEM-B", kv.get_string(kCa, "").c_str());
    TEST_ASSERT_TRUE(kv.get_bool(kOk, false));

    // An older, unverified CA A is stored; B verified on the trial, but its
    // write is lost. The marker must not end up vouching for A.
    DroppingStringsKv stale;
    stale.set_string(kCa, "PEM-A");
    stale.set_bool(kOk, false);
    stale.drop_strings = true;
    TEST_ASSERT_FALSE(sp::persist_verified_ca(stale, kCa, kOk, "PEM-B"));
    TEST_ASSERT_EQUAL_STRING("PEM-A", stale.get_string(kCa, "").c_str());
    TEST_ASSERT_FALSE(stale.get_bool(kOk, true));
    // Even a marker some older image left set is cleared.
    stale.set_bool(kOk, true);
    TEST_ASSERT_FALSE(sp::persist_verified_ca(stale, kCa, kOk, "PEM-B"));
    TEST_ASSERT_FALSE(stale.get_bool(kOk, true));
    // Once the write goes through, the next commit persists it.
    stale.drop_strings = false;
    TEST_ASSERT_TRUE(sp::persist_verified_ca(stale, kCa, kOk, "PEM-B"));
    TEST_ASSERT_TRUE(stale.get_bool(kOk, false));
    // An empty candidate is never marked verified.
    sp::MemKvStore empty;
    TEST_ASSERT_FALSE(sp::persist_verified_ca(empty, kCa, kOk, ""));
    TEST_ASSERT_FALSE(empty.get_bool(kOk, false));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_tls_off_is_plain_and_never_fetches);
    RUN_TEST(test_pinned_ca_runs_tls);
    RUN_TEST(test_missing_ca_is_a_loud_fallback_by_default);
    RUN_TEST(test_missing_ca_fails_closed_when_tls_is_required);
    RUN_TEST(test_mode_strings_are_stable);
    RUN_TEST(test_backoff_doubles_to_the_cap);
    RUN_TEST(test_backoff_waits_for_wifi_and_a_released_button);
    RUN_TEST(test_backoff_is_wrap_safe);
    RUN_TEST(test_runtime_ca_fetch_fits_inside_the_loop_wdt);
    RUN_TEST(test_tls_probe_fits_inside_the_loop_wdt);
    RUN_TEST(test_mqtt_connect_is_suppressed_in_a_fetch_pass);
    RUN_TEST(test_only_a_plausible_public_pem_is_pinned);
    RUN_TEST(test_ca_response_with_content_length_is_complete_when_the_body_is);
    RUN_TEST(test_ca_response_without_a_sane_length_is_refused_before_the_body);
    RUN_TEST(test_ca_response_error_status_is_done_without_a_body);
    RUN_TEST(test_trial_mode_runs_tls_but_is_not_pinned);
    RUN_TEST(test_boot_modes);
    RUN_TEST(test_candidate_is_committed_only_after_a_connack);
    RUN_TEST(test_failed_trial_returns_to_the_plaintext_fallback);
    RUN_TEST(test_require_tls_trial_failure_fails_closed_again);
    RUN_TEST(test_runtime_trial_keeps_the_downgrade_latched_until_commit);
    RUN_TEST(test_probe_failure_keeps_the_plaintext_link);
    RUN_TEST(test_require_tls_tries_a_fetched_candidate_at_once);
    RUN_TEST(test_unverified_stored_ca_that_fails_is_never_final);
    RUN_TEST(test_trial_failure_classification);
    RUN_TEST(test_downgrade_messages_name_the_reason);
    RUN_TEST(test_downgrade_latch_refires_on_a_new_reason_only);
    RUN_TEST(test_ca_fingerprint_is_lowercase_hex_sha256_of_the_pem_bytes);
    RUN_TEST(test_verified_marker_only_vouches_for_the_stored_ca);
    return UNITY_END();
}
