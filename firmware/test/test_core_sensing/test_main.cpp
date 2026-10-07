// test_core_sensing — reading staleness, alert latching/hysteresis, and the
// averaged HX711 tare/calibration state machine. All pure sp_core logic the
// node composition root drives with millis() timestamps.
//
// Regressions pinned here (hardware audit):
//   fw-node#5 / fw-drivers-cam#2 — a dead CO2/lux/scale sensor kept
//     publishing its last value forever (have_* never cleared)
//   fw-node#20 — threshold alerts re-fired every read pass (2,880/day)
//   fw-drivers-cam#9 — tare/calibrate used a cached sample up to 30 s old
//     and saved a noise-level scale to NVS

#include <unity.h>

#include <math.h>
#include <stdint.h>

#include "alert_latch.h"
#include "freshness.h"
#include "scale_calibrator.h"

void setUp() {}
void tearDown() {}

// ── ReadingFreshness ───────────────────────────────────────────

void test_stale_window_floor_and_scaling() {
    // 3x the read cadence, never below 30 s (SCD4x samples every 5 s, so a
    // 1 s read interval must not flag it stale between samples).
    TEST_ASSERT_EQUAL_UINT32(90000, sp::stale_window_ms(30000));
    TEST_ASSERT_EQUAL_UINT32(sp::kMinStaleWindowMs, sp::stale_window_ms(1000));
    TEST_ASSERT_EQUAL_UINT32(30000, sp::kMinStaleWindowMs);
    TEST_ASSERT_EQUAL_UINT32(1800000, sp::stale_window_ms(600000));
}

void test_fresh_reading_goes_stale_and_recovers() {
    sp::ReadingFreshness f;
    f.arm(0);
    TEST_ASSERT_FALSE(f.ever_ok());
    f.mark_ok(1000);
    TEST_ASSERT_TRUE(f.ever_ok());
    TEST_ASSERT_FALSE(f.check_stale(91000, 90000));  // exactly the window
    TEST_ASSERT_FALSE(f.is_stale());
    TEST_ASSERT_TRUE(f.check_stale(91001, 90000));   // past it
    TEST_ASSERT_TRUE(f.is_stale());
    // A good sample clears it.
    f.mark_ok(95000);
    TEST_ASSERT_FALSE(f.is_stale());
    TEST_ASSERT_FALSE(f.check_stale(96000, 90000));
}

void test_never_delivering_sensor_goes_stale_from_arm_time() {
    // An enabled-but-unwired HX711 / MH-Z19 never produces a sample: it
    // must still be flagged (declared-but-missing is an alert, not silence).
    sp::ReadingFreshness f;
    f.arm(5000);
    TEST_ASSERT_FALSE(f.check_stale(35000, 30000));
    TEST_ASSERT_TRUE(f.check_stale(35001, 30000));
    TEST_ASSERT_FALSE(f.ever_ok());
}

void test_unarmed_freshness_never_stale() {
    // Absent sensor (never armed) must never report stale.
    sp::ReadingFreshness f;
    TEST_ASSERT_FALSE(f.check_stale(0xFFFFFFF0u, 30000));
    TEST_ASSERT_FALSE(f.is_stale());
}

void test_stale_latches_across_millis_wrap() {
    // Once stale it stays stale until a good sample — the unsigned elapsed
    // math wrapping after 49.7 days must not flip it back to fresh.
    sp::ReadingFreshness f;
    f.arm(0);
    f.mark_ok(100);
    TEST_ASSERT_TRUE(f.check_stale(200000, 30000));
    TEST_ASSERT_TRUE(f.check_stale(150, 30000));  // "elapsed" 50 ms after wrap
    TEST_ASSERT_TRUE(f.is_stale());
    // Freshness itself is wrap-safe around the boundary.
    sp::ReadingFreshness g;
    g.arm(0xFFFFFFFFu - 1000u);
    g.mark_ok(0xFFFFFFFFu - 1000u);
    TEST_ASSERT_FALSE(g.check_stale(20000u, 30000));  // ~21 s later, wrapped
    TEST_ASSERT_TRUE(g.check_stale(40000u, 30000));
}

// ── AlertLatch / ThresholdAlert ────────────────────────────────

void test_alert_latch_fires_on_entry_then_reminds() {
    sp::AlertLatch a(60000);
    TEST_ASSERT_FALSE(a.due(false, 0));
    TEST_ASSERT_TRUE(a.due(true, 1000));   // entry
    a.emitted(1000);
    TEST_ASSERT_FALSE(a.due(true, 31000));  // the old code re-fired here
    TEST_ASSERT_FALSE(a.due(true, 60999));
    TEST_ASSERT_TRUE(a.due(true, 61000));   // reminder
    a.emitted(61000);
    TEST_ASSERT_FALSE(a.due(true, 62000));
    // Clears, then a fresh entry fires immediately.
    TEST_ASSERT_FALSE(a.due(false, 63000));
    TEST_ASSERT_FALSE(a.active());
    TEST_ASSERT_TRUE(a.due(true, 64000));
}

void test_alert_latch_retries_until_published() {
    // A publish that failed (MQTT down) must not count as delivered.
    sp::AlertLatch a(3600000);
    TEST_ASSERT_TRUE(a.due(true, 0));
    // no emitted() call — publish failed
    TEST_ASSERT_TRUE(a.due(true, 30000));
    a.emitted(30000);
    TEST_ASSERT_FALSE(a.due(true, 60000));
}

void test_default_reminder_interval() {
    TEST_ASSERT_EQUAL_UINT32(60UL * 60UL * 1000UL, sp::kAlertReemitMs);
    sp::AlertLatch a;
    TEST_ASSERT_TRUE(a.due(true, 0));
    a.emitted(0);
    // A saturated-RH fruiting chamber: one alert, then hourly — not every
    // 30 s read pass.
    int fired = 0;
    for (uint32_t t = 30000; t <= 24UL * 3600UL * 1000UL; t += 30000) {
        if (a.due(true, t)) {
            ++fired;
            a.emitted(t);
        }
    }
    TEST_ASSERT_EQUAL_INT(24, fired);
}

void test_threshold_alert_hysteresis_above() {
    // RH > 99 enters; must drop below 97 (2 % margin) to re-arm.
    sp::ThresholdAlert rh(sp::ThresholdAlert::Dir::Above, 99.0f, 2.0f, 3600000);
    TEST_ASSERT_FALSE(rh.due(98.9f, 0));
    TEST_ASSERT_TRUE(rh.due(99.5f, 1000));
    rh.emitted(1000);
    // Chatter around the limit does not re-fire.
    TEST_ASSERT_FALSE(rh.due(98.5f, 2000));
    TEST_ASSERT_FALSE(rh.due(99.8f, 3000));
    TEST_ASSERT_FALSE(rh.due(97.5f, 4000));
    TEST_ASSERT_TRUE(rh.active());
    // Genuinely back in band → re-armed; next excursion fires again.
    TEST_ASSERT_FALSE(rh.due(96.9f, 5000));
    TEST_ASSERT_FALSE(rh.active());
    TEST_ASSERT_TRUE(rh.due(99.2f, 6000));
}

void test_threshold_alert_hysteresis_below() {
    sp::ThresholdAlert lo(sp::ThresholdAlert::Dir::Below, 40.0f, 1.0f, 3600000);
    TEST_ASSERT_FALSE(lo.due(40.0f, 0));  // at the limit: not below
    TEST_ASSERT_TRUE(lo.due(39.5f, 1000));
    lo.emitted(1000);
    TEST_ASSERT_FALSE(lo.due(40.5f, 2000));  // inside the margin: still latched
    TEST_ASSERT_TRUE(lo.active());
    TEST_ASSERT_FALSE(lo.due(41.1f, 3000));  // cleared
    TEST_ASSERT_FALSE(lo.active());
}

void test_threshold_alert_nan_clears() {
    sp::ThresholdAlert hi(sp::ThresholdAlert::Dir::Above, 90.0f, 1.0f, 3600000);
    TEST_ASSERT_TRUE(hi.due(95.0f, 0));
    hi.emitted(0);
    TEST_ASSERT_FALSE(hi.due(NAN, 1000));
    TEST_ASSERT_FALSE(hi.active());
}

// ── ScaleCalibrator (HX711 tare / calibrate) ───────────────────

void test_scale_idle_ignores_samples() {
    sp::ScaleCalibrator c;
    TEST_ASSERT_FALSE(c.busy());
    c.add_sample(1234);
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Idle,
                          (int)c.poll(1000));
}

void test_scale_tare_averages_fresh_samples_only() {
    sp::ScaleCalibrator c;
    c.start_tare(0);
    TEST_ASSERT_TRUE(c.busy());
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Op::Tare, (int)c.op());
    // The first ready sample may predate the command — discarded.
    c.add_sample(999999);
    for (int i = 0; i < sp::ScaleCalibrator::kSamples - 1; ++i) {
        c.add_sample(1000 + (i % 2 == 0 ? 4 : -4));
        TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Collecting,
                              (int)c.poll(100 * (i + 1)));
    }
    c.add_sample(996);  // 8 samples: 4x1004 + 4x996 → mean exactly 1000
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Done,
                          (int)c.poll(900));
    TEST_ASSERT_EQUAL_INT32(1000, c.tare());
    TEST_ASSERT_FALSE(c.busy());
    // Terminal status is reported once.
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Idle,
                          (int)c.poll(1000));
}

void test_scale_tare_negative_counts_round_correctly() {
    sp::ScaleCalibrator c;
    c.start_tare(0);
    c.add_sample(0);  // discarded
    for (int i = 0; i < sp::ScaleCalibrator::kSamples; ++i)
        c.add_sample(i < 4 ? -80001 : -80002);  // mean -80001.5
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Done,
                          (int)c.poll(1000));
    TEST_ASSERT_TRUE(c.tare() == -80001 || c.tare() == -80002);
}

void test_scale_calibrate_computes_counts_per_gram() {
    sp::ScaleCalibrator c;
    TEST_ASSERT_TRUE(c.start_calibrate(200.0f, /*tare=*/1000, 0));
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Op::Calibrate, (int)c.op());
    c.add_sample(1000);  // stale pre-command sample (the empty platform)
    for (int i = 0; i < sp::ScaleCalibrator::kSamples; ++i)
        c.add_sample(1000 + 200 * 420);  // 420 counts/g x 200 g
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Done,
                          (int)c.poll(1000));
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 420.0f, c.scale());
}

void test_scale_calibrate_rejects_noise_level_delta() {
    // The audit scenario: cached empty-platform sample + 4 counts of noise
    // over 200 g = 0.02 counts/g, which the old >0 guard saved to NVS.
    sp::ScaleCalibrator c;
    c.start_calibrate(200.0f, 1000, 0);
    c.add_sample(0);
    for (int i = 0; i < sp::ScaleCalibrator::kSamples; ++i) c.add_sample(1004);
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Rejected,
                          (int)c.poll(1000));
    TEST_ASSERT_FALSE(c.busy());
    TEST_ASSERT_TRUE(c.reason() != nullptr && c.reason()[0] != '\0');

    // Negative delta (mass not on the platter / cell reversed) — rejected,
    // same policy as before.
    c.start_calibrate(200.0f, 1000, 2000);
    c.add_sample(0);
    for (int i = 0; i < sp::ScaleCalibrator::kSamples; ++i) c.add_sample(-50000);
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Rejected,
                          (int)c.poll(3000));
}

void test_scale_calibrate_rejects_bad_known_mass() {
    sp::ScaleCalibrator c;
    TEST_ASSERT_FALSE(c.start_calibrate(0.0f, 0, 0));
    TEST_ASSERT_FALSE(c.start_calibrate(-5.0f, 0, 0));
    TEST_ASSERT_FALSE(c.start_calibrate(NAN, 0, 0));
    TEST_ASSERT_FALSE(c.start_calibrate(INFINITY, 0, 0));
    TEST_ASSERT_FALSE(c.busy());
}

void test_scale_times_out_without_samples() {
    // Unwired HX711: DOUT never goes low, no samples → bounded timeout.
    sp::ScaleCalibrator c;
    c.start_tare(1000);
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Collecting,
                          (int)c.poll(1000 + sp::ScaleCalibrator::kTimeoutMs - 1));
    TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::TimedOut,
                          (int)c.poll(1000 + sp::ScaleCalibrator::kTimeoutMs));
    TEST_ASSERT_FALSE(c.busy());
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_stale_window_floor_and_scaling);
    RUN_TEST(test_fresh_reading_goes_stale_and_recovers);
    RUN_TEST(test_never_delivering_sensor_goes_stale_from_arm_time);
    RUN_TEST(test_unarmed_freshness_never_stale);
    RUN_TEST(test_stale_latches_across_millis_wrap);
    RUN_TEST(test_alert_latch_fires_on_entry_then_reminds);
    RUN_TEST(test_alert_latch_retries_until_published);
    RUN_TEST(test_default_reminder_interval);
    RUN_TEST(test_threshold_alert_hysteresis_above);
    RUN_TEST(test_threshold_alert_hysteresis_below);
    RUN_TEST(test_threshold_alert_nan_clears);
    RUN_TEST(test_scale_idle_ignores_samples);
    RUN_TEST(test_scale_tare_averages_fresh_samples_only);
    RUN_TEST(test_scale_tare_negative_counts_round_correctly);
    RUN_TEST(test_scale_calibrate_computes_counts_per_gram);
    RUN_TEST(test_scale_calibrate_rejects_noise_level_delta);
    RUN_TEST(test_scale_calibrate_rejects_bad_known_mass);
    RUN_TEST(test_scale_times_out_without_samples);
    return UNITY_END();
}
