// test_core_sensing — reading staleness, alert latching/hysteresis, and the
// averaged HX711 tare/calibration state machine. All pure sp_core logic the
// node composition root drives with millis() timestamps.
//
// Regressions pinned here:
//   a dead CO2/lux/scale sensor kept publishing its last value forever
//     (have_* never cleared)
//   threshold alerts re-fired every read pass (2,880/day)
//   tare/calibrate used a cached sample up to 30 s old and saved a
//     noise-level scale to NVS

#include <unity.h>

#include <math.h>
#include <stdint.h>

#include "alert_latch.h"
#include "freshness.h"
#include "kv_store.h"
#include "scale_calibrator.h"
#include "sensor_memory.h"

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

void test_scale_tare_rounds_half_away_from_zero() {
    // Raw HX711 counts are signed (a load cell mounted either way): a mean of
    // ±80001.5 rounds to ±80002, the same magnitude for both signs, not
    // toward +infinity (C division truncates toward zero).
    const int32_t signs[] = {1, -1};
    for (int32_t sign : signs) {
        sp::ScaleCalibrator c;
        c.start_tare(0);
        c.add_sample(0);  // discarded
        for (int i = 0; i < sp::ScaleCalibrator::kSamples; ++i)
            c.add_sample(sign * (i < 4 ? 80001 : 80002));  // mean ±80001.5
        TEST_ASSERT_EQUAL_INT((int)sp::ScaleCalibrator::Status::Done,
                              (int)c.poll(1000));
        TEST_ASSERT_EQUAL_INT32(sign * 80002, c.tare());
    }
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

// ── StaleRecovery ──────────────────────────────────────────────

// An SCD4x that lost power on its own wakes idle and never reports a sample
// again; the node re-starts it once per staleness window while its reading
// stays stale (not every pass: each try is two bus writes).
void test_stale_recovery_is_paced_once_per_window() {
    sp::StaleRecovery r;
    const uint32_t w = 90000;
    TEST_ASSERT_FALSE(r.due(false, 1000, w));     // fresh: nothing to do
    TEST_ASSERT_TRUE(r.due(true, 2000, w));       // went stale: try now
    TEST_ASSERT_FALSE(r.due(true, 2000 + w - 1, w));
    TEST_ASSERT_TRUE(r.due(true, 2000 + w, w));   // still stale: again
    TEST_ASSERT_FALSE(r.due(true, 2000 + w + 1, w));
    TEST_ASSERT_FALSE(r.due(false, 2000 + w + 2, w));  // recovered: reset
    TEST_ASSERT_TRUE(r.due(true, 2000 + w + 3, w));    // a new stale spell
    // Wrap-safe.
    sp::StaleRecovery wrap;
    const uint32_t t0 = 0xFFFFFFFFu - 1000u;
    TEST_ASSERT_TRUE(wrap.due(true, t0, w));
    TEST_ASSERT_FALSE(wrap.due(true, t0 + w - 1, w));
    TEST_ASSERT_TRUE(wrap.due(true, t0 + w, w));
}

// ── EdgeAlertQueue (door edges) ────────────────────────────────

// A door that opened or closed while MQTT was down used to raise nothing:
// emit_alert() refuses while disconnected and the edge was never retried.
void test_edge_alert_queue_delivers_edges_raised_while_offline() {
    sp::EdgeAlertQueue q;
    TEST_ASSERT_FALSE(q.pending());
    // Online: pushed and delivered on the same pass, not late.
    q.push(true);
    TEST_ASSERT_TRUE(q.pending());
    TEST_ASSERT_TRUE(q.front().high);
    TEST_ASSERT_FALSE(q.front().late);
    q.delivered();
    TEST_ASSERT_FALSE(q.pending());

    // Offline: the door closes, the delivery fails, then it opens again.
    q.push(false);
    q.undeliverable();
    q.push(true);
    q.undeliverable();
    TEST_ASSERT_TRUE(q.pending());
    // MQTT is back: both go out, in order, both marked late.
    TEST_ASSERT_FALSE(q.front().high);
    TEST_ASSERT_TRUE(q.front().late);
    q.delivered();
    TEST_ASSERT_TRUE(q.front().high);
    TEST_ASSERT_TRUE(q.front().late);
    q.delivered();
    TEST_ASSERT_FALSE(q.pending());
}

void test_edge_alert_queue_collapses_back_to_the_first_state() {
    sp::EdgeAlertQueue q;
    // opened, closed, opened while offline → "opened" (it is open now).
    q.push(true);
    q.push(false);
    q.push(true);
    TEST_ASSERT_TRUE(q.front().high);
    q.delivered();
    TEST_ASSERT_FALSE(q.pending());
    // opened, closed, opened, closed → opened then closed.
    q.push(true);
    q.push(false);
    q.push(true);
    q.push(false);
    TEST_ASSERT_TRUE(q.front().high);
    q.delivered();
    TEST_ASSERT_FALSE(q.front().high);
    q.delivered();
    TEST_ASSERT_FALSE(q.pending());
    // A repeated state is not an edge.
    q.push(false);
    q.push(false);
    q.delivered();
    TEST_ASSERT_FALSE(q.pending());
    q.delivered();  // empty: harmless
    TEST_ASSERT_FALSE(q.pending());
}

// ── sensor_memory (autodetected sensors seen before) ───────────

// A CO2 sensor that died before a reboot was simply not built: no staleness,
// no alert, no expected_missing — and the Pi's CO2 rules went quiet. The
// node now remembers what it found and reports a remembered sensor that is
// missing at boot.
void test_seen_sensors_report_a_remembered_sensor_missing_at_boot() {
    sp::MemKvStore kv;
    // First boot with an SCD4x (Co2Kind 1) and a BH1750: learned, stored.
    sp::SeenCheck c = sp::check_seen_sensors(sp::load_seen_sensors(kv), 1, true);
    TEST_ASSERT_FALSE(c.co2_missing);
    TEST_ASSERT_FALSE(c.lux_missing);
    TEST_ASSERT_TRUE(c.changed);
    sp::store_seen_sensors(kv, c.remember);
    TEST_ASSERT_EQUAL_INT32(1, kv.get_int(sp::kSeenCo2Key, 0));
    TEST_ASSERT_TRUE(kv.get_bool(sp::kSeenLuxKey, false));

    // Same hardware: nothing to write (no NVS wear every boot).
    c = sp::check_seen_sensors(sp::load_seen_sensors(kv), 1, true);
    TEST_ASSERT_FALSE(c.changed);
    TEST_ASSERT_FALSE(c.co2_missing);

    // The SCD4x stopped answering: missing, and still remembered.
    c = sp::check_seen_sensors(sp::load_seen_sensors(kv), 0, true);
    TEST_ASSERT_TRUE(c.co2_missing);
    TEST_ASSERT_EQUAL_INT32(1, c.co2_missing_kind);
    TEST_ASSERT_FALSE(c.lux_missing);
    TEST_ASSERT_FALSE(c.changed);
    TEST_ASSERT_EQUAL_INT32(1, c.remember.co2);
    // …every boot until it is back.
    c = sp::check_seen_sensors(sp::load_seen_sensors(kv), 0, false);
    TEST_ASSERT_TRUE(c.co2_missing);
    TEST_ASSERT_TRUE(c.lux_missing);

    // A swap (SCD30 = Co2Kind 2 replacing the SCD4x) is no alert.
    c = sp::check_seen_sensors(sp::load_seen_sensors(kv), 2, true);
    TEST_ASSERT_FALSE(c.co2_missing);
    TEST_ASSERT_TRUE(c.changed);
    sp::store_seen_sensors(kv, c.remember);
    TEST_ASSERT_EQUAL_INT32(2, kv.get_int(sp::kSeenCo2Key, 0));

    // Removed on purpose: forgotten (portal box / factory reset), and the
    // next boot without the parts reports nothing.
    sp::forget_seen_sensors(kv);
    c = sp::check_seen_sensors(sp::load_seen_sensors(kv), 0, false);
    TEST_ASSERT_FALSE(c.co2_missing);
    TEST_ASSERT_FALSE(c.lux_missing);
    TEST_ASSERT_FALSE(c.changed);

    // A node that never had either behaves exactly as before.
    sp::MemKvStore fresh;
    c = sp::check_seen_sensors(sp::load_seen_sensors(fresh), 0, false);
    TEST_ASSERT_FALSE(c.co2_missing);
    TEST_ASSERT_FALSE(c.lux_missing);
    TEST_ASSERT_FALSE(c.changed);
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
    RUN_TEST(test_scale_tare_rounds_half_away_from_zero);
    RUN_TEST(test_scale_calibrate_computes_counts_per_gram);
    RUN_TEST(test_scale_calibrate_rejects_noise_level_delta);
    RUN_TEST(test_scale_calibrate_rejects_bad_known_mass);
    RUN_TEST(test_scale_times_out_without_samples);
    RUN_TEST(test_stale_recovery_is_paced_once_per_window);
    RUN_TEST(test_edge_alert_queue_delivers_edges_raised_while_offline);
    RUN_TEST(test_edge_alert_queue_collapses_back_to_the_first_state);
    RUN_TEST(test_seen_sensors_report_a_remembered_sensor_missing_at_boot);
    return UNITY_END();
}
