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

#include <unity.h>

#include <stdint.h>
#include <string.h>

#include <string>

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
    return UNITY_END();
}
