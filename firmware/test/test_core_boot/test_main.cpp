// test_core_boot — boot-time WiFi fallback, the BOOT-button hold actions,
// OTA image confirmation, and the MQTT connect-attempt time budget.
//
// Regressions pinned here (hardware audit):
//   fw-node#8  — a TLS connect attempt could block loop() for 30 s (TCP) +
//     120 s (handshake) against a 30 s task WDT: panic-reboot loop while the
//     broker was unreachable
//   fw-node#9  — ANY boot-time WiFi failure opened an unauthenticated setup
//     AP for 10 minutes on an already-provisioned node
//   fw-node#12 — OTA rollback compiled in but defeated: the new image was
//     marked valid before setup(), so a bad OTA crash-looped forever
//   review of the above — (a) a 3-10 s BOOT press sampled across a blocked
//     loop pass (15 s .local DNS / 3 s TCP timeout with the broker down) was
//     timed across the gap and factory-reset the node; (b) a deliberate
//     restart confirmed an OTA image that had never reached MQTT; (c) ticking
//     Secure MQTT without a pinned CA, then booting with WiFi down, ran the
//     whole session on plaintext

#include <unity.h>

#include <stdint.h>

#include "boot_policy.h"
#include "link_budget.h"

void setUp() {}
void tearDown() {}

// ── boot WiFi fallback (fw-node#9) ─────────────────────────────

void test_unprovisioned_node_opens_the_portal() {
    TEST_ASSERT_TRUE(sp::portal_at_boot(/*provisioned=*/false, false));
}

void test_provisioned_node_skips_the_portal_unless_requested() {
    TEST_ASSERT_FALSE(sp::portal_at_boot(true, /*portal_requested=*/false));
    TEST_ASSERT_TRUE(sp::portal_at_boot(true, /*portal_requested=*/true));
}

void test_connect_failure_with_verified_creds_continues_offline() {
    // Router rebooting after a power blip: the credentials have worked
    // before, so the node must NOT sit in an open AP — it boots offline and
    // the link watchdog keeps re-trying the STA connection.
    TEST_ASSERT_FALSE(sp::portal_after_connect_failure(/*creds_verified=*/true));
}

void test_connect_failure_with_fresh_creds_reopens_the_portal() {
    // Just typed in the portal and never connected: most likely a typo, and
    // the operator is standing there — give the form back.
    TEST_ASSERT_TRUE(sp::portal_after_connect_failure(/*creds_verified=*/false));
}

void test_portal_save_requires_a_first_connect_for_new_settings() {
    // Unchanged WiFi, TLS off (or CA already pinned): the settings have
    // worked before — a later WiFi-down boot stays offline.
    TEST_ASSERT_FALSE(sp::portal_save_needs_first_connect(
        /*wifi_creds_changed=*/false, /*tls_enabled=*/false, /*ca_pinned=*/false));
    TEST_ASSERT_FALSE(sp::portal_save_needs_first_connect(false, true, true));
    // New SSID / password.
    TEST_ASSERT_TRUE(sp::portal_save_needs_first_connect(true, false, false));
    // Secure MQTT ticked but no CA pinned yet: the TOFU fetch needs WiFi at
    // the next boot. Booting offline instead would fetch nothing and run the
    // whole session on plaintext 1883 — reopen the portal on a WiFi failure.
    TEST_ASSERT_TRUE(sp::portal_save_needs_first_connect(false, true, false));
}

// ── BOOT button hold ───────────────────────────────────────────

static sp::ButtonHold::Action hold_for(sp::ButtonHold& b, uint32_t start,
                                       uint32_t held_ms, uint32_t step = 50) {
    sp::ButtonHold::Action last = sp::ButtonHold::Action::None;
    // Iterate by offset: `start + held_ms` itself may wrap past 2^32.
    for (uint32_t off = 0; off <= held_ms; off += step) {
        sp::ButtonHold::Action a = b.update(start + off, true);
        if (a != sp::ButtonHold::Action::None) last = a;
    }
    sp::ButtonHold::Action rel = b.update(start + held_ms + step, false);
    return rel != sp::ButtonHold::Action::None ? rel : last;
}

void test_short_press_does_nothing() {
    sp::ButtonHold b;
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                          (int)hold_for(b, 1000, 500));
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                          (int)hold_for(b, 5000, sp::ButtonHold::kPortalHoldMs - 100));
}

void test_three_to_ten_second_hold_opens_the_portal_on_release() {
    sp::ButtonHold b;
    // Nothing fires while still held — only the release decides.
    for (uint32_t t = 0; t <= 5000; t += 50)
        TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                              (int)b.update(t, true));
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::OpenPortal,
                          (int)b.update(5050, false));
    // Released again: idle.
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                          (int)b.update(5100, false));
}

void test_ten_second_hold_factory_resets_while_held() {
    sp::ButtonHold b;
    int resets = 0;
    for (uint32_t t = 0; t <= 15000; t += 50) {
        sp::ButtonHold::Action a = b.update(t, true);
        if (a == sp::ButtonHold::Action::FactoryReset) {
            ++resets;
            TEST_ASSERT_TRUE(t > sp::ButtonHold::kFactoryResetHoldMs);
        }
        TEST_ASSERT_NOT_EQUAL((int)sp::ButtonHold::Action::OpenPortal, (int)a);
    }
    TEST_ASSERT_EQUAL_INT(1, resets);
    // Releasing after a factory reset never also opens the portal.
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                          (int)b.update(15050, false));
}

void test_button_hold_is_wrap_safe() {
    sp::ButtonHold b;
    uint32_t start = 0xFFFFFFFFu - 1000u;
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::OpenPortal,
                          (int)hold_for(b, start, 4000));
}

// Loop passes are NOT evenly spaced: with WiFi up and the broker down, a
// connect attempt blocks one pass for up to 15 s (.local DNS) or 3 s (TCP
// timeout to an IP). The button is only seen at sample instants, so a hold
// is timed over densely-sampled stretches only — and a factory reset is
// never inferred at release time.
static sp::ButtonHold::Action run_samples(sp::ButtonHold& b, uint32_t from,
                                          uint32_t to, uint32_t step,
                                          bool pressed, int* resets) {
    sp::ButtonHold::Action last = sp::ButtonHold::Action::None;
    for (uint32_t t = from; t <= to; t += step) {
        sp::ButtonHold::Action a = b.update(t, pressed);
        if (a == sp::ButtonHold::Action::FactoryReset && resets) ++*resets;
        if (a != sp::ButtonHold::Action::None) last = a;
    }
    return last;
}

void test_sparse_sampling_never_factory_resets_a_short_press() {
    // The reviewer's reproduction: 15 s passes; a 4 s press (t = 14-18 s)
    // covers exactly one sample instant (t = 15 s).
    sp::ButtonHold b;
    for (uint32_t t = 0; t <= 60000; t += 15000) {
        bool pressed = t >= 14000 && t < 18000;
        TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                              (int)b.update(t, pressed));
    }
    // 3 s passes (IP broker host, TCP timeout): a 9.2 s press (t = 2.9 s to
    // 12.1 s) is seen at 3, 6, 9 and 12 s and released by 15 s — it used to
    // time as 12 s and factory-reset on release.
    sp::ButtonHold c;
    for (uint32_t t = 0; t <= 30000; t += 3000) {
        bool pressed = t >= 2900 && t <= 12100;
        TEST_ASSERT_NOT_EQUAL((int)sp::ButtonHold::Action::FactoryReset,
                              (int)c.update(t, pressed));
    }
}

void test_a_blocked_pass_restarts_the_hold_clock() {
    // Two pressed samples 15 s apart may be two separate presses: the hold
    // restarts at the second one instead of counting the gap.
    sp::ButtonHold b;
    int resets = 0;
    run_samples(b, 0, 6000, 50, true, &resets);            // dense 6 s
    run_samples(b, 21000, 25000, 50, true, &resets);       // gap, dense 4 s
    TEST_ASSERT_EQUAL_INT(0, resets);                      // 25 s span, no reset
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::OpenPortal,
                          (int)b.update(25050, false));    // 4 s observed
    // A real >10 s hold after a blocked pass still factory-resets — timed
    // from the first sample after the gap.
    sp::ButtonHold c;
    resets = 0;
    run_samples(c, 0, 3000, 50, true, &resets);
    uint32_t fired_at = 0;
    for (uint32_t t = 18000; t <= 30000; t += 50) {
        if (c.update(t, true) == sp::ButtonHold::Action::FactoryReset) {
            ++resets;
            fired_at = t;
        }
    }
    TEST_ASSERT_EQUAL_INT(1, resets);
    TEST_ASSERT_TRUE(fired_at > 18000 + sp::ButtonHold::kFactoryResetHoldMs);
}

void test_short_gaps_do_not_restart_the_hold() {
    // Ordinary passes (sensor reads, publishes) stay well under the gap
    // bound: a 12 s hold with a 600 ms pass every 2 s still resets once.
    sp::ButtonHold b;
    int resets = 0;
    uint32_t t = 0;
    while (t <= 12000) {
        if (b.update(t, true) == sp::ButtonHold::Action::FactoryReset) ++resets;
        t += (t % 2000 == 0) ? 600 : 50;
    }
    TEST_ASSERT_EQUAL_INT(1, resets);
}

void test_release_seen_late_is_timed_to_the_last_pressed_sample() {
    // Dense 4 s hold, then the release is only seen 15 s later: the
    // observed hold is 4 s (portal) — never the 19 s span (reset).
    sp::ButtonHold b;
    run_samples(b, 0, 4000, 50, true, nullptr);
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::OpenPortal,
                          (int)b.update(19000, false));
    // Dense 2 s, release seen 15 s later: too short to mean anything.
    sp::ButtonHold c;
    run_samples(c, 0, 2000, 50, true, nullptr);
    TEST_ASSERT_EQUAL_INT((int)sp::ButtonHold::Action::None,
                          (int)c.update(17000, false));
}

// ── OTA image confirmation (fw-node#12) ────────────────────────

void test_image_confirms_after_stable_mqtt() {
    sp::ImageConfirm c;
    TEST_ASSERT_FALSE(c.update(0, false));
    TEST_ASSERT_FALSE(c.update(1000, true));  // first connected pass
    TEST_ASSERT_FALSE(c.update(1000 + sp::ImageConfirm::kStableMs - 1, true));
    TEST_ASSERT_TRUE(c.update(1000 + sp::ImageConfirm::kStableMs, true));
    TEST_ASSERT_TRUE(c.done());
    // Exactly once.
    TEST_ASSERT_FALSE(c.update(1000 + 2 * sp::ImageConfirm::kStableMs, true));
}

void test_mqtt_flap_restarts_the_stability_clock() {
    sp::ImageConfirm c;
    c.update(0, true);
    c.update(sp::ImageConfirm::kStableMs - 10, false);  // dropped just short
    TEST_ASSERT_FALSE(c.update(sp::ImageConfirm::kStableMs, true));
    TEST_ASSERT_FALSE(c.update(sp::ImageConfirm::kStableMs + 5000, true));
    TEST_ASSERT_TRUE(c.update(2 * sp::ImageConfirm::kStableMs, true));
}

void test_never_connected_never_confirms() {
    sp::ImageConfirm c;
    for (uint32_t t = 0; t < 30UL * 60UL * 1000UL; t += 1000)
        TEST_ASSERT_FALSE(c.update(t, false));
    TEST_ASSERT_FALSE(c.done());
}

void test_reached_broker_gates_deliberate_restart_confirmation() {
    // An operator restart (BOOT gesture) confirms a probation image only if
    // it reached MQTT this boot; otherwise the reboot must roll back, as a
    // power cycle would.
    sp::ImageConfirm c;
    TEST_ASSERT_FALSE(c.reached_broker());
    c.update(0, false);
    c.update(5000, false);
    TEST_ASSERT_FALSE(c.reached_broker());
    c.update(6000, true);
    TEST_ASSERT_TRUE(c.reached_broker());
    c.update(7000, false);  // a later drop does not un-prove it
    TEST_ASSERT_TRUE(c.reached_broker());
    // Tracked even when there is nothing to confirm (USB-flashed image).
    sp::ImageConfirm d;
    d.mark_done();
    d.update(0, true);
    TEST_ASSERT_TRUE(d.reached_broker());
}

void test_explicit_confirm_is_final() {
    sp::ImageConfirm c;
    c.mark_done();
    TEST_ASSERT_TRUE(c.done());
    TEST_ASSERT_FALSE(c.update(0, true));
    TEST_ASSERT_FALSE(c.update(10UL * sp::ImageConfirm::kStableMs, true));
}

// ── connect-attempt time budget (fw-node#8) ────────────────────

void test_connect_attempt_fits_inside_the_loop_wdt() {
    // One MqttLink::connect_attempt() runs synchronously in loop() right after
    // the single WDT pet: DNS + TCP connect + TLS handshake + CONNACK must
    // all fit, with margin, inside the task-WDT timeout. (The core defaults
    // were 15 + 30 + 120 + 15 s against a 30 s WDT.)
    uint32_t worst = sp::kDnsWorstCaseS + sp::kTcpConnectTimeoutS +
                     sp::kTlsHandshakeTimeoutS + sp::kMqttSocketTimeoutS;
    TEST_ASSERT_EQUAL_UINT32(worst, sp::kConnectAttemptWorstCaseS);
    TEST_ASSERT_TRUE(worst + sp::kLoopWdtMarginS <= sp::kLoopWdtTimeoutS);
    // Each timeout is still long enough for a LAN broker (an ESP32 ECDHE
    // handshake takes ~1-2 s).
    TEST_ASSERT_TRUE(sp::kTlsHandshakeTimeoutS >= 5);
    TEST_ASSERT_TRUE(sp::kTcpConnectTimeoutS >= 2);
    TEST_ASSERT_TRUE(sp::kMqttSocketTimeoutS >= 2);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_unprovisioned_node_opens_the_portal);
    RUN_TEST(test_provisioned_node_skips_the_portal_unless_requested);
    RUN_TEST(test_connect_failure_with_verified_creds_continues_offline);
    RUN_TEST(test_connect_failure_with_fresh_creds_reopens_the_portal);
    RUN_TEST(test_portal_save_requires_a_first_connect_for_new_settings);
    RUN_TEST(test_short_press_does_nothing);
    RUN_TEST(test_three_to_ten_second_hold_opens_the_portal_on_release);
    RUN_TEST(test_ten_second_hold_factory_resets_while_held);
    RUN_TEST(test_button_hold_is_wrap_safe);
    RUN_TEST(test_sparse_sampling_never_factory_resets_a_short_press);
    RUN_TEST(test_a_blocked_pass_restarts_the_hold_clock);
    RUN_TEST(test_short_gaps_do_not_restart_the_hold);
    RUN_TEST(test_release_seen_late_is_timed_to_the_last_pressed_sample);
    RUN_TEST(test_image_confirms_after_stable_mqtt);
    RUN_TEST(test_mqtt_flap_restarts_the_stability_clock);
    RUN_TEST(test_never_connected_never_confirms);
    RUN_TEST(test_reached_broker_gates_deliberate_restart_confirmation);
    RUN_TEST(test_explicit_confirm_is_final);
    RUN_TEST(test_connect_attempt_fits_inside_the_loop_wdt);
    return UNITY_END();
}
