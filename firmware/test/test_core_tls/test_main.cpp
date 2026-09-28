// test_core_tls — Secure MQTT transport policy when no Pi CA is pinned
// (fw-node#2).
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
    // The fetch returned a CA; the glue moved the link to TLS with it. The
    // plaintext link had made 3 attempts and connected twice.
    m.trial_started(/*link_attempts=*/3, /*link_connects=*/2);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Trial, (int)m.mode());
    // Still a downgrade while the candidate is unproven, so the alert latch
    // does not clear + re-fire on every trial.
    TEST_ASSERT_EQUAL_INT((int)Why::CaUnavailable, (int)m.downgrade());
    // The trial's own attempt has not run yet: no verdict.
    TEST_ASSERT_EQUAL_INT((int)Step::Idle, (int)m.step(now + 1, true, false, 3, 2));
    // It ran and got no CONNACK.
    TEST_ASSERT_EQUAL_INT((int)Step::Revert, (int)m.step(now + 2, true, false, 4, 2));
    m.trial_failed(Why::MqttRefused, now + 2);
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Fallback, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused, (int)m.downgrade());
    // A failed fetch keeps the most recent reason and backs off further.
    now += 2 + 2 * kFirst;
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(now, true, false, 5, 3));
    m.fetch_failed(now);
    TEST_ASSERT_EQUAL_INT((int)Why::MqttRefused, (int)m.reason());
    TEST_ASSERT_EQUAL_UINT32(2, m.backoff().failures());
    // Next time it works.
    now += 4 * kFirst;
    TEST_ASSERT_EQUAL_INT((int)Step::Fetch, (int)m.step(now, true, false, 5, 3));
    m.trial_started(5, 3);
    // A CONNACK counts even if the broker dropped the link again before this
    // pass sampled it: the candidate verified.
    TEST_ASSERT_EQUAL_INT((int)Step::Commit, (int)m.step(now + 5, true, false, 6, 4));
    m.trial_verified();
    TEST_ASSERT_EQUAL_INT((int)sp::TlsMode::Pinned, (int)m.mode());
    TEST_ASSERT_EQUAL_INT((int)Why::None, (int)m.downgrade());
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
    RUN_TEST(test_mqtt_connect_is_suppressed_in_a_fetch_pass);
    RUN_TEST(test_only_a_plausible_public_pem_is_pinned);
    RUN_TEST(test_trial_mode_runs_tls_but_is_not_pinned);
    RUN_TEST(test_boot_modes);
    RUN_TEST(test_candidate_is_committed_only_after_a_connack);
    RUN_TEST(test_failed_trial_returns_to_the_plaintext_fallback);
    RUN_TEST(test_require_tls_trial_failure_fails_closed_again);
    RUN_TEST(test_runtime_trial_keeps_the_downgrade_latched_until_commit);
    RUN_TEST(test_unverified_stored_ca_that_fails_is_never_final);
    RUN_TEST(test_trial_failure_classification);
    RUN_TEST(test_downgrade_messages_name_the_reason);
    RUN_TEST(test_downgrade_latch_refires_on_a_new_reason_only);
    RUN_TEST(test_ca_fingerprint_is_lowercase_hex_sha256_of_the_pem_bytes);
    return UNITY_END();
}
