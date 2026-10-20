// test_core_channel — actuator state machine: dialect rejection, clamps,
// duration + max-on safety cutoffs, millis-wrap boundaries, ramp math,
// health counters, channel naming, command routing, scenes.

#include <unity.h>

#include <stdint.h>
#include <string.h>

#include "channel_runtime.h"
#include "clamps.h"
#include "cmd_router.h"
#include "personality.h"
#include "publish_cadence.h"
#include "scene_table.h"
#include "wrap_time.h"

void setUp() {}
void tearDown() {}

static sp::ChannelConfig switch_cfg(const char* name = "fae") {
    sp::ChannelConfig cfg;
    strncpy(cfg.name, name, sp::kChannelNameMax);
    cfg.mode = sp::ChannelMode::Switch;
    cfg.max_on_ms = sp::kDefaultMaxOnMs;
    return cfg;
}

static sp::ChannelConfig dim_cfg(const char* name = "white") {
    sp::ChannelConfig cfg;
    strncpy(cfg.name, name, sp::kChannelNameMax);
    cfg.mode = sp::ChannelMode::Dim;
    cfg.max_on_ms = 0;
    return cfg;
}

// ── switch dialect ─────────────────────────────────────────────

void test_switch_empty_payload_rejected() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand cmd;  // empty — the retained-{} latch bug
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Rejected,
                          (int)ch.apply(cmd, 1000));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_STRING("payload lacks state and pwm", ch.reason());
    // Dim-dialect keys on a switch channel are equally rejected.
    sp::ChannelCommand dimcmd;
    dimcmd.has_level = true;
    dimcmd.level = 512;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Rejected,
                          (int)ch.apply(dimcmd, 1000));
}

void test_switch_state_and_pwm() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.apply(on, 0));
    TEST_ASSERT_TRUE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT8(255, ch.pwm8());

    sp::ChannelCommand pwm;
    pwm.has_pwm = true;
    pwm.pwm = 300;  // out-of-range clamps, not wraps (old code wrapped to 44)
    ch.apply(pwm, 10);
    TEST_ASSERT_EQUAL_UINT8(255, ch.pwm8());
    pwm.pwm = 128;
    ch.apply(pwm, 20);
    TEST_ASSERT_EQUAL_UINT8(128, ch.pwm8());
    pwm.pwm = 0;
    ch.apply(pwm, 30);
    TEST_ASSERT_FALSE(ch.is_on());
    pwm.pwm = -5;
    ch.apply(pwm, 40);
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT8(0, ch.pwm8());
}

void test_duration_expiry_and_clamp() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand cmd;
    cmd.has_state = true;
    cmd.state_on = true;
    cmd.has_duration = true;
    cmd.duration_sec = 900;  // 15 min — inside the 30-min max-on budget
    ch.apply(cmd, 0);
    TEST_ASSERT_TRUE(ch.is_on());

    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                          (int)ch.tick(900UL * 1000UL - 1));
    TEST_ASSERT_TRUE(ch.is_on());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.tick(900UL * 1000UL + 1));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_TRUE(ch.last_change_was_cutoff());
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().safety_cutoffs);
    // A pulse ending on schedule is a timer expiry, not a max-on trip.
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::Timer, (int)ch.last_cutoff());
    TEST_ASSERT_EQUAL_UINT32(0, ch.health().max_on_trips);
}

void test_max_on_dominates_long_duration() {
    // duration_sec clamps to 3600, but a switch channel's max-on backstop
    // (30 min) still wins: effective ON time = min(duration, max_on). A
    // duration command must never be a way around the safety cutoff.
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand cmd;
    cmd.has_state = true;
    cmd.state_on = true;
    cmd.has_duration = true;
    cmd.duration_sec = 7200;  // clamps to 3600
    ch.apply(cmd, 0);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.tick(30UL * 60UL * 1000UL + 1));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_STRING("auto-off (max-on exceeded)", ch.reason());
}

void test_negative_duration_ignored_rest_applies() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand cmd;
    cmd.has_state = true;
    cmd.state_on = true;
    cmd.has_duration = true;
    cmd.duration_sec = -500;  // wrapped millis latch in the old handler
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.apply(cmd, 0));
    TEST_ASSERT_TRUE(ch.is_on());
    // No off-timer armed: only max-on will turn it off.
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                          (int)ch.tick(10UL * 60UL * 1000UL));
    TEST_ASSERT_TRUE(ch.is_on());
}

void test_max_on_fires_and_reon_does_not_extend() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 0);

    // Re-sending ON at minute 29 must not restart the 30-min clock.
    ch.apply(on, 29UL * 60UL * 1000UL);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.tick(30UL * 60UL * 1000UL + 1));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_STRING("auto-off (max-on exceeded)", ch.reason());
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().safety_cutoffs);
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().cycle_count);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::MaxOn, (int)ch.last_cutoff());
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().max_on_trips);
}

// ── production ordering: command inside mqtt->loop(), tick after ─
// loop() reads `now` once at the top; a command handled inside
// mqtt->loop() later in the same pass stamps the channel with a fresh,
// LATER millis(). A tick with that pass's `now` must read as no time
// elapsed — it used to read as ~49.7 days and cut the channel at once.

void test_tick_older_than_the_on_stamp_is_not_a_cutoff() {
    sp::ChannelConfig cfgs[4];
    sp::personality_channels(sp::Personality::RelayBank, cfgs);
    for (int i = 0; i < 4; ++i) {  // 30-min channels and the 60 s aux
        sp::Channel ch;
        ch.configure(cfgs[i]);
        sp::ChannelCommand on;
        on.has_state = true;
        on.state_on = true;
        ch.apply(on, 1001);
        TEST_ASSERT_EQUAL_INT_MESSAGE((int)sp::ChannelEvent::None,
                                      (int)ch.tick(1000), cfgs[i].name);
        TEST_ASSERT_TRUE_MESSAGE(ch.is_on(), cfgs[i].name);
        TEST_ASSERT_EQUAL_UINT32(0, ch.health().safety_cutoffs);
        TEST_ASSERT_EQUAL_UINT32(0, ch.health().max_on_trips);
        TEST_ASSERT_EQUAL_UINT32(0, ch.on_time_sec_live(1000));
        // The backstop still fires on time.
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                              (int)ch.tick(1001 + cfgs[i].max_on_ms));
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                              (int)ch.tick(1001 + cfgs[i].max_on_ms + 1));
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::MaxOn,
                              (int)ch.last_cutoff());
    }

    // A timed pulse and a pwm-only ON, same ordering.
    sp::Channel fae;
    fae.configure(switch_cfg());
    sp::ChannelCommand pulse;
    pulse.has_state = true;
    pulse.state_on = true;
    pulse.has_duration = true;
    pulse.duration_sec = 300;
    fae.apply(pulse, 5005);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)fae.tick(5000));
    TEST_ASSERT_TRUE(fae.is_on());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)fae.tick(5005 + 300000));
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::Timer, (int)fae.last_cutoff());
    TEST_ASSERT_EQUAL_UINT32(300, fae.health().on_time_sec);

    sp::Channel ex;
    ex.configure(switch_cfg("exhaust"));
    sp::ChannelCommand pwm;
    pwm.has_pwm = true;
    pwm.pwm = 180;
    // Also across the millis() wrap: stamped just after it, ticked with the
    // pass's `now` read just before it.
    ex.apply(pwm, 5u);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ex.tick(0xFFFFFFF0u));
    TEST_ASSERT_TRUE(ex.is_on());
    TEST_ASSERT_EQUAL_UINT8(180, ex.pwm8());
    TEST_ASSERT_EQUAL_UINT32(0, ex.health().safety_cutoffs);
}

void test_ramp_tick_older_than_its_start_stays_in_range() {
    // From dark: {level:1023, ramp_sec:60} stamped at t+1, ticked at t. The
    // level used to wrap to ~25480 — a full-brightness flash on LEDC and an
    // out-of-range level on the wire.
    sp::Channel ch;
    ch.configure(dim_cfg());
    sp::ChannelCommand ramp;
    ramp.has_level = true;
    ramp.level = 1023;
    ramp.has_ramp = true;
    ramp.ramp_sec = 60;
    ch.apply(ramp, 7001);
    TEST_ASSERT_EQUAL_UINT16(0, ch.level10());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(7000));
    TEST_ASSERT_EQUAL_UINT16(0, ch.level10());
    TEST_ASSERT_TRUE(ch.duty10() <= 1023);
    ch.tick(7001 + 30000);  // halfway
    TEST_ASSERT_TRUE(ch.level10() >= 500 && ch.level10() <= 523);
    ch.tick(7001 + 60000);
    TEST_ASSERT_EQUAL_UINT16(1023, ch.level10());

    // Ramp down between two lit levels, same ordering.
    sp::Channel dn;
    dn.configure(dim_cfg("blue"));
    sp::ChannelCommand lit;
    lit.has_level = true;
    lit.level = 900;
    dn.apply(lit, 0);
    sp::ChannelCommand down;
    down.has_level = true;
    down.level = 100;
    down.has_ramp = true;
    down.ramp_sec = 10;
    dn.apply(down, 2002);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)dn.tick(2000));
    TEST_ASSERT_EQUAL_UINT16(900, dn.level10());
    for (uint32_t t = 2002; t <= 2002 + 10000; t += 250) {
        dn.tick(t);
        TEST_ASSERT_TRUE(dn.level10() >= 100 && dn.level10() <= 900);
    }
    TEST_ASSERT_EQUAL_UINT16(100, dn.level10());
}

void test_off_stamped_before_the_on_adds_no_on_time() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand on, off;
    on.has_state = true;
    on.state_on = true;
    off.has_state = true;
    off.state_on = false;
    ch.apply(on, 1001);
    ch.apply(off, 1000);
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT32(0, ch.health().on_time_sec);
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().cycle_count);
}

void test_on_time_counts_runs_longer_than_the_wrap_window() {
    // A lit channel with no max-on can run for weeks: ticked every pass,
    // its on-time stays exact past 24.8 days (the signed window) and past
    // the 49.7-day millis() wrap.
    sp::Channel ch;
    ch.configure(dim_cfg());
    sp::ChannelCommand lit;
    lit.has_level = true;
    lit.level = 600;
    const uint32_t t0 = 123456789u;
    ch.apply(lit, t0);
    const uint64_t hour = 3600ULL * 1000ULL;
    const uint64_t days = 60;
    for (uint64_t t = hour; t <= days * 24ULL * hour; t += hour) {
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                              (int)ch.tick((uint32_t)(t0 + t)));
    }
    const uint32_t end = (uint32_t)(t0 + days * 24ULL * hour + 500);
    TEST_ASSERT_EQUAL_UINT32((uint32_t)(days * 86400ULL), ch.on_time_sec_live(end));
    sp::ChannelCommand off;
    off.has_state = true;
    off.state_on = false;
    ch.apply(off, end);
    TEST_ASSERT_EQUAL_UINT32((uint32_t)(days * 86400ULL), ch.health().on_time_sec);
}

// ── cutoff kinds: what counts as a stuck channel ───────────────

void test_cutoff_kinds_and_max_on_trips() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand pulse;
    pulse.has_state = true;
    pulse.state_on = true;
    pulse.has_duration = true;
    pulse.duration_sec = 120;
    // Scheduled pulses ending on time: safety_cutoffs (its wire meaning),
    // never max-on trips.
    for (int i = 0; i < 3; ++i) {
        const uint32_t t = (uint32_t)i * 1000000u;
        ch.apply(pulse, t);
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                              (int)ch.tick(t + 120000));
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::Timer,
                              (int)ch.last_cutoff());
    }
    TEST_ASSERT_EQUAL_UINT32(3, ch.health().safety_cutoffs);
    TEST_ASSERT_EQUAL_UINT32(0, ch.health().max_on_trips);

    // A forced off (safe mode / OTA start) is not a max-on trip either.
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 5000000);
    ch.force_off(5000500, "safe mode");
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::Forced, (int)ch.last_cutoff());
    TEST_ASSERT_EQUAL_UINT32(4, ch.health().safety_cutoffs);
    TEST_ASSERT_EQUAL_UINT32(0, ch.health().max_on_trips);

    // A plain ON that nothing turns off: the max-on backstop trips.
    ch.apply(on, 6000000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.tick(6000000 + sp::kDefaultMaxOnMs + 1));
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::MaxOn, (int)ch.last_cutoff());
    TEST_ASSERT_EQUAL_UINT32(5, ch.health().safety_cutoffs);
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().max_on_trips);

    // A command or a ramp step is not a cutoff.
    ch.apply(on, 9000000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::None, (int)ch.last_cutoff());
    TEST_ASSERT_FALSE(ch.last_change_was_cutoff());
}

// ── a plain ON ends a running pulse; tweaks keep its deadline ──

void test_plain_on_ends_a_running_pulse() {
    sp::ChannelCommand pulse;
    pulse.has_state = true;
    pulse.state_on = true;
    pulse.has_duration = true;
    pulse.duration_sec = 300;
    sp::ChannelCommand plain_on;
    plain_on.has_state = true;
    plain_on.state_on = true;

    // {state:on,duration_sec:300}, then {state:on}: held until max-on.
    sp::Channel ch;
    ch.configure(switch_cfg());
    ch.apply(pulse, 0);
    ch.apply(plain_on, 60000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(300001));
    TEST_ASSERT_TRUE(ch.is_on());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.tick(sp::kDefaultMaxOnMs + 1));  // from t=0
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::MaxOn, (int)ch.last_cutoff());

    // An ON whose duration_sec is ignored (<= 0) is indefinite too.
    sp::Channel neg;
    neg.configure(switch_cfg());
    neg.apply(pulse, 0);
    sp::ChannelCommand bad_duration = plain_on;
    bad_duration.has_duration = true;
    bad_duration.duration_sec = 0;
    neg.apply(bad_duration, 1000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)neg.tick(300001));

    // A pwm-only tweak mid-pulse keeps the deadline.
    sp::Channel tweak;
    tweak.configure(switch_cfg());
    tweak.apply(pulse, 0);
    sp::ChannelCommand pwm;
    pwm.has_pwm = true;
    pwm.pwm = 128;
    tweak.apply(pwm, 60000);
    TEST_ASSERT_EQUAL_UINT8(128, tweak.pwm8());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)tweak.tick(300001));
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelCutoff::Timer, (int)tweak.last_cutoff());

    // An ON with its own duration re-arms from its own start.
    sp::Channel rearm;
    rearm.configure(switch_cfg());
    rearm.apply(pulse, 0);
    sp::ChannelCommand longer = pulse;
    longer.duration_sec = 600;
    rearm.apply(longer, 60000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)rearm.tick(300001));
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)rearm.tick(660001));

    // Dim: a level-only change (what a scene sends) keeps a timed level's
    // deadline; an explicit {state:on} ends it.
    sp::Channel dim;
    dim.configure(dim_cfg());
    sp::ChannelCommand timed_level;
    timed_level.has_level = true;
    timed_level.level = 800;
    timed_level.has_duration = true;
    timed_level.duration_sec = 300;
    dim.apply(timed_level, 0);
    sp::ChannelCommand scene_level;
    scene_level.has_level = true;
    scene_level.level = 500;
    dim.apply(scene_level, 60000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)dim.tick(300001));
    TEST_ASSERT_FALSE(dim.is_on());

    sp::Channel dim2;
    dim2.configure(dim_cfg("red"));
    dim2.apply(timed_level, 0);
    dim2.apply(plain_on, 60000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)dim2.tick(300001));
    TEST_ASSERT_EQUAL_UINT16(1023, dim2.level10());
}

void test_millis_wrap_boundary() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    // Turn on 10 s before the uint32 wrap with a 60 s duration.
    uint32_t t_on = 0xFFFFFFFFu - 10000u;
    sp::ChannelCommand cmd;
    cmd.has_state = true;
    cmd.state_on = true;
    cmd.has_duration = true;
    cmd.duration_sec = 60;
    ch.apply(cmd, t_on);
    // 30 s later — clock has wrapped to ~20 s past zero. Naive `now >=
    // deadline` would fire the off-timer here (now is tiny). It must not.
    uint32_t t_mid = t_on + 30000u;  // wraps
    TEST_ASSERT_TRUE(t_mid < t_on);  // confirm we actually wrapped
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(t_mid));
    TEST_ASSERT_TRUE(ch.is_on());
    // Past the deadline (wrapped) — fires.
    uint32_t t_end = t_on + 61000u;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.tick(t_end));
    TEST_ASSERT_FALSE(ch.is_on());
}

void test_on_time_accounting() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand on, off;
    on.has_state = true;
    on.state_on = true;
    off.has_state = true;
    off.state_on = false;
    ch.apply(on, 0);
    TEST_ASSERT_EQUAL_UINT32(45, ch.on_time_sec_live(45000));
    ch.apply(off, 60000);
    TEST_ASSERT_EQUAL_UINT32(60, ch.health().on_time_sec);
    ch.apply(on, 100000);
    ch.apply(off, 130000);
    TEST_ASSERT_EQUAL_UINT32(90, ch.health().on_time_sec);
    TEST_ASSERT_EQUAL_UINT32(2, ch.health().cycle_count);
}

// ── dim dialect ────────────────────────────────────────────────

void test_dim_level_and_off() {
    sp::Channel ch;
    ch.configure(dim_cfg());
    sp::ChannelCommand cmd;
    cmd.has_level = true;
    cmd.level = 2000;  // clamps to 1023
    ch.apply(cmd, 0);
    TEST_ASSERT_EQUAL_UINT16(1023, ch.level10());
    TEST_ASSERT_TRUE(ch.is_on());

    sp::ChannelCommand off;
    off.has_state = true;
    off.state_on = false;
    ch.apply(off, 10);
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT16(0, ch.level10());

    // "on" without level restores full brightness.
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 20);
    TEST_ASSERT_EQUAL_UINT16(1023, ch.level10());

    // No max-on by default for dim — lights run long.
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                          (int)ch.tick(12UL * 3600UL * 1000UL));
    TEST_ASSERT_TRUE(ch.is_on());
}

void test_dim_ramp_interpolates() {
    sp::Channel ch;
    ch.configure(dim_cfg());
    sp::ChannelCommand setup;
    setup.has_level = true;
    setup.level = 100;
    ch.apply(setup, 0);

    sp::ChannelCommand ramp;
    ramp.has_level = true;
    ramp.level = 900;
    ramp.has_ramp = true;
    ramp.ramp_sec = 10;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.apply(ramp, 0));
    TEST_ASSERT_EQUAL_UINT16(100, ch.level10());  // starts from current

    ch.tick(5000);  // halfway
    TEST_ASSERT_TRUE(ch.level10() >= 480 && ch.level10() <= 520);
    ch.tick(10001);  // done
    TEST_ASSERT_EQUAL_UINT16(900, ch.level10());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(20000));
}

void test_dim_ramp_down_to_zero_turns_off() {
    sp::Channel ch;
    ch.configure(dim_cfg());
    sp::ChannelCommand setup;
    setup.has_level = true;
    setup.level = 800;
    ch.apply(setup, 0);

    sp::ChannelCommand ramp;
    ramp.has_level = true;
    ramp.level = 0;
    ramp.has_ramp = true;
    ramp.ramp_sec = 4;
    // level=0 means on=false; ramp applies only to a lit target — the
    // command degrades to an immediate off (no ramp-to-dark surprises).
    ch.apply(ramp, 0);
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT16(0, ch.level10());
}

// ── naming / routing / scenes ──────────────────────────────────

void test_channel_name_validation() {
    TEST_ASSERT_TRUE(sp::channel_name_valid("fae"));
    TEST_ASSERT_TRUE(sp::channel_name_valid("far_red"));
    TEST_ASSERT_TRUE(sp::channel_name_valid("pump-2"));
    TEST_ASSERT_FALSE(sp::channel_name_valid(""));
    TEST_ASSERT_FALSE(sp::channel_name_valid(nullptr));
    TEST_ASSERT_FALSE(sp::channel_name_valid("has space"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("sl/ash"));
    // Reserved endpoint names must not become channels.
    TEST_ASSERT_FALSE(sp::channel_name_valid("config"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("scene"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("telemetry"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("coredump"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("coredump_ack"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("ota_manifest"));
    // The lighting-level doc's envelope keys.
    TEST_ASSERT_FALSE(sp::channel_name_valid("ts"));
    TEST_ASSERT_FALSE(sp::channel_name_valid("report"));
    // Length cap.
    TEST_ASSERT_FALSE(sp::channel_name_valid("abcdefghijklmnopqrstuvwxyz"));
}

void test_cmd_router_exact_match() {
    sp::CmdRouter router;
    router.reset();
    router.enable_scene(true);
    TEST_ASSERT_TRUE(router.add_channel("fae", 0));
    TEST_ASSERT_TRUE(router.add_channel("white", 1));
    TEST_ASSERT_FALSE(router.add_channel("config", 2));  // reserved

    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::Config,
                          (int)router.route("config").target);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::Scene,
                          (int)router.route("scene").target);
    sp::CmdRoute r = router.route("fae");
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::Channel, (int)r.target);
    TEST_ASSERT_EQUAL_INT(0, r.channel_index);
    // No prefix/suffix sloppiness.
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::None,
                          (int)router.route("fae2").target);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::None,
                          (int)router.route("fa").target);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::None, (int)router.route("").target);
    // Scene disabled (no dim bank) → scene routes nowhere.
    router.enable_scene(false);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::None,
                          (int)router.route("scene").target);
}

void test_scene_table() {
    const sp::Scene* s = sp::find_scene("fruiting_standard");
    TEST_ASSERT_NOT_NULL(s);
    TEST_ASSERT_EQUAL_UINT16(800, s->levels[0]);
    TEST_ASSERT_EQUAL_UINT16(50, s->levels[3]);
    TEST_ASSERT_NOT_NULL(sp::find_scene("colonization_dark"));
    TEST_ASSERT_NOT_NULL(sp::find_scene("cordyceps_blue"));
    TEST_ASSERT_NOT_NULL(sp::find_scene("pinning_daylight"));
    TEST_ASSERT_NOT_NULL(sp::find_scene("lions_mane_gentle"));
    TEST_ASSERT_NULL(sp::find_scene("disco"));
    TEST_ASSERT_NULL(sp::find_scene(nullptr));
}

void test_clamp_helpers() {
    TEST_ASSERT_EQUAL_UINT32(1000, sp::clamp_read_interval_ms(0).value);
    TEST_ASSERT_TRUE(sp::clamp_read_interval_ms(0).clamped);
    TEST_ASSERT_EQUAL_UINT32(600000, sp::clamp_read_interval_ms(86400000).value);
    TEST_ASSERT_FALSE(sp::clamp_read_interval_ms(30000).clamped);
    TEST_ASSERT_EQUAL_UINT32(5000, sp::clamp_publish_interval_ms(1).value);
    TEST_ASSERT_EQUAL_UINT8(255, sp::clamp_pwm8(1000));
    TEST_ASSERT_EQUAL_UINT8(0, sp::clamp_pwm8(-1));
    TEST_ASSERT_EQUAL_UINT16(1023, sp::clamp_level10(99999));
}

void test_wrap_helpers() {
    TEST_ASSERT_TRUE(sp::deadline_reached(100, 100));
    TEST_ASSERT_TRUE(sp::deadline_reached(101, 100));
    TEST_ASSERT_FALSE(sp::deadline_reached(99, 100));
    // Across the wrap: deadline at 5 after wrapping, now just before wrap.
    TEST_ASSERT_FALSE(sp::deadline_reached(0xFFFFFFF0u, 5u));
    TEST_ASSERT_TRUE(sp::deadline_reached(6u, 5u));
    TEST_ASSERT_EQUAL_UINT32(21, sp::elapsed_ms(5u, 0xFFFFFFF0u));
    // elapsed_since: a `now` older than the stamp is 0, not ~49.7 days.
    TEST_ASSERT_EQUAL_UINT32(0, sp::elapsed_since(1000u, 1001u));
    TEST_ASSERT_EQUAL_UINT32(0, sp::elapsed_since(0xFFFFFFF0u, 5u));
    TEST_ASSERT_EQUAL_UINT32(21, sp::elapsed_since(5u, 0xFFFFFFF0u));
    TEST_ASSERT_EQUAL_UINT32(1, sp::elapsed_since(1001u, 1000u));
    TEST_ASSERT_EQUAL_UINT32(0, sp::elapsed_since(7u, 7u));
}

// ── personality (wire contract: node type + channel preset names) ──

void test_personality_str_round_trip() {
    // Every valid string round-trips through from_str → str.
    struct {
        const char* s;
        sp::Personality p;
    } cases[] = {
        {"climate", sp::Personality::Climate},
        {"relay", sp::Personality::RelayBank},
        {"lighting", sp::Personality::LightingBank},
    };
    for (auto& c : cases) {
        sp::Personality out;
        TEST_ASSERT_TRUE_MESSAGE(sp::personality_from_str(c.s, &out), c.s);
        TEST_ASSERT_EQUAL_INT((int)c.p, (int)out);
        TEST_ASSERT_EQUAL_STRING(c.s, sp::personality_str(c.p));
    }
}

void test_personality_from_str_rejects_unknown_and_null() {
    sp::Personality out = sp::Personality::RelayBank;  // sentinel
    TEST_ASSERT_FALSE(sp::personality_from_str("node", &out));
    TEST_ASSERT_FALSE(sp::personality_from_str("camera", &out));
    TEST_ASSERT_FALSE(sp::personality_from_str("", &out));
    TEST_ASSERT_FALSE(sp::personality_from_str(nullptr, &out));
    // On rejection, `out` is left untouched — the caller keeps its default.
    TEST_ASSERT_EQUAL_INT((int)sp::Personality::RelayBank, (int)out);
}

void test_node_type_str_is_never_node() {
    // The Pi routes commands by type and must receive climate/relay/lighting,
    // NEVER the literal "node" (the header's central invariant).
    TEST_ASSERT_EQUAL_STRING("climate",
                             sp::node_type_str(sp::Personality::Climate));
    TEST_ASSERT_EQUAL_STRING("relay",
                             sp::node_type_str(sp::Personality::RelayBank));
    TEST_ASSERT_EQUAL_STRING("lighting",
                             sp::node_type_str(sp::Personality::LightingBank));
    // node_type_str is exactly personality_str.
    for (int i = 0; i <= (int)sp::Personality::LightingBank; ++i) {
        sp::Personality p = (sp::Personality)i;
        TEST_ASSERT_EQUAL_STRING(sp::personality_str(p), sp::node_type_str(p));
        TEST_ASSERT_TRUE(strcmp(sp::node_type_str(p), "node") != 0);
    }
}

void test_personality_channels_climate_has_no_bank() {
    sp::ChannelConfig out[4];
    TEST_ASSERT_EQUAL_INT(0, sp::personality_channels(sp::Personality::Climate,
                                                      out));
}

void test_personality_channels_relay_bank_presets() {
    sp::ChannelConfig out[4];
    int n = sp::personality_channels(sp::Personality::RelayBank, out);
    TEST_ASSERT_EQUAL_INT(4, n);
    // Names are a Pi-automation wire contract (server/app/automation/
    // templates.py routes channel="fae"/"exhaust"/"circulation"/"aux").
    const char* names[] = {"fae", "exhaust", "circulation", "aux"};
    for (int i = 0; i < 4; ++i) {
        TEST_ASSERT_EQUAL_STRING(names[i], out[i].name);
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelMode::Switch, (int)out[i].mode);
        // Switch channels carry the 30-min max-on backstop — except aux,
        // the documented misting-pump channel, which gets 60 s.
        TEST_ASSERT_EQUAL_UINT32(i == 3 ? sp::kAuxMaxOnMs : sp::kDefaultMaxOnMs,
                                 out[i].max_on_ms);
        // Preset names must survive channel-name validation (topic-safe, not
        // shadowing a reserved endpoint).
        TEST_ASSERT_TRUE(sp::channel_name_valid(out[i].name));
    }
}

void test_personality_channels_lighting_bank_presets() {
    sp::ChannelConfig out[4];
    int n = sp::personality_channels(sp::Personality::LightingBank, out);
    TEST_ASSERT_EQUAL_INT(4, n);
    const char* names[] = {"white", "blue", "red", "far_red"};
    for (int i = 0; i < 4; ++i) {
        TEST_ASSERT_EQUAL_STRING(names[i], out[i].name);
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelMode::Dim, (int)out[i].mode);
        // Lights legitimately run 12 h — no max-on cutoff.
        TEST_ASSERT_EQUAL_UINT32(0, out[i].max_on_ms);
        TEST_ASSERT_TRUE(sp::channel_name_valid(out[i].name));
    }
}

// ── boundary backfills ─────────────────────────────────────────

void test_cmd_router_ninth_channel_overflow() {
    sp::CmdRouter router;
    router.reset();
    // kMaxChannels = 8 — the first 8 valid names register.
    const char* names[] = {"fae", "exhaust", "circulation", "aux",
                           "pump1", "pump2", "pump3", "pump4"};
    for (int i = 0; i < 8; ++i)
        TEST_ASSERT_TRUE_MESSAGE(router.add_channel(names[i], i), names[i]);
    // The 9th is refused (table full) — it must NOT silently overwrite.
    TEST_ASSERT_FALSE(router.add_channel("pump5", 8));
    // The overflow name routes nowhere; the 8 registered still resolve.
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::None,
                          (int)router.route("pump5").target);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::Channel,
                          (int)router.route("pump4").target);
    TEST_ASSERT_EQUAL_INT(7, router.route("pump4").channel_index);
}

void test_channel_duty10_switch_expansion() {
    // Switch-mode duty10 expands the 8-bit pwm to 10 bits as
    // (pwm<<2)|(pwm>>6) — full-scale maps to full-scale, not 1020.
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 0);  // pwm8 = 255
    TEST_ASSERT_EQUAL_UINT8(255, ch.pwm8());
    TEST_ASSERT_EQUAL_UINT16(1023, ch.duty10());  // (255<<2)|(255>>6)=1023

    sp::ChannelCommand pwm;
    pwm.has_pwm = true;
    pwm.pwm = 128;
    ch.apply(pwm, 10);
    TEST_ASSERT_EQUAL_UINT16((uint16_t)((128 << 2) | (128 >> 6)), ch.duty10());
    // Dim-mode duty10 is the raw 10-bit level, no expansion.
    sp::Channel dim;
    dim.configure(dim_cfg());
    sp::ChannelCommand lvl;
    lvl.has_level = true;
    lvl.level = 700;
    dim.apply(lvl, 0);
    TEST_ASSERT_EQUAL_UINT16(700, dim.duty10());
}

void test_cmd_suffix_split() {
    // Happy path — the seam that feeds route().
    const char* s = sp::cmd_suffix("sporeprint/relay-01/cmd/config", "relay-01");
    TEST_ASSERT_NOT_NULL(s);
    TEST_ASSERT_EQUAL_STRING("config", s);
    TEST_ASSERT_EQUAL_STRING(
        "fae", sp::cmd_suffix("sporeprint/relay-01/cmd/fae", "relay-01"));

    // Feed the extracted suffix straight into route() — closes the seam the
    // audit flagged (route was only ever tested with pre-split suffixes).
    sp::CmdRouter router;
    router.reset();
    router.add_channel("fae", 0);
    const char* suf = sp::cmd_suffix("sporeprint/relay-01/cmd/fae", "relay-01");
    TEST_ASSERT_EQUAL_INT((int)sp::CmdTarget::Channel,
                          (int)router.route(suf).target);

    // Bare .../cmd/ ⇒ empty suffix ⇒ nullptr (not "" that routes to None-by-luck).
    TEST_ASSERT_NULL(sp::cmd_suffix("sporeprint/relay-01/cmd/", "relay-01"));
    // No trailing slash after cmd ⇒ not a command.
    TEST_ASSERT_NULL(sp::cmd_suffix("sporeprint/relay-01/cmd", "relay-01"));
    // Nested suffix ⇒ rejected.
    TEST_ASSERT_NULL(sp::cmd_suffix("sporeprint/relay-01/cmd/a/b", "relay-01"));
    // Wrong node id (a prefix of the real segment must NOT match).
    TEST_ASSERT_NULL(sp::cmd_suffix("sporeprint/relay-01/cmd/fae", "relay"));
    // Different message type (telemetry, not cmd).
    TEST_ASSERT_NULL(
        sp::cmd_suffix("sporeprint/relay-01/telemetry", "relay-01"));
    // Wrong root prefix.
    TEST_ASSERT_NULL(sp::cmd_suffix("other/relay-01/cmd/fae", "relay-01"));
    // An id that itself contains "cmd" resolves against the real id, not a
    // stray "cmd" match.
    TEST_ASSERT_EQUAL_STRING(
        "scene", sp::cmd_suffix("sporeprint/cmd-node/cmd/scene", "cmd-node"));
    TEST_ASSERT_NULL(sp::cmd_suffix(nullptr, "relay-01"));
    TEST_ASSERT_NULL(sp::cmd_suffix("sporeprint/relay-01/cmd/fae", nullptr));
}

void test_scene_table_level_values() {
    // Pin the actual level rows, not just non-null presence — a silently
    // shifted scene changes what the lighting bank drives.
    const sp::Scene* s;
    s = sp::find_scene("colonization_dark");
    TEST_ASSERT_NOT_NULL(s);
    for (int i = 0; i < sp::kSceneChannels; ++i)
        TEST_ASSERT_EQUAL_UINT16_MESSAGE(0, s->levels[i], "colonization_dark");
    s = sp::find_scene("cordyceps_blue");
    TEST_ASSERT_NOT_NULL(s);
    // Cordyceps is a blue-forward scene: blue (index 1) must lead white (0).
    TEST_ASSERT_TRUE(s->levels[1] > s->levels[0]);
    s = sp::find_scene("pinning_daylight");
    TEST_ASSERT_NOT_NULL(s);
    TEST_ASSERT_TRUE(s->levels[0] > 0);  // white on for daylight
}

// ── audit regressions (hardware-audit) ─────────────────────────

void test_switch_explicit_off_wins_over_pwm() {
    // {"state":"off","pwm":200} used to turn the channel ON at
    // 200 (pwm overrode the explicit off) while the Pi recorded it as off
    // and cleared its safety watchdog. An explicit off always wins.
    sp::Channel ch;
    ch.configure(switch_cfg("aux"));
    sp::ChannelCommand off_pwm;
    off_pwm.has_state = true;
    off_pwm.state_on = false;
    off_pwm.has_pwm = true;
    off_pwm.pwm = 200;

    // From OFF: stays off.
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.apply(off_pwm, 0));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT8(0, ch.pwm8());
    TEST_ASSERT_EQUAL_UINT32(0, ch.health().cycle_count);

    // From ON: turns off.
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 10);
    TEST_ASSERT_TRUE(ch.is_on());
    ch.apply(off_pwm, 20);
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT8(0, ch.pwm8());

    // "on" + pwm still honours the pwm (and pwm 0 still means off).
    sp::ChannelCommand on_pwm;
    on_pwm.has_state = true;
    on_pwm.state_on = true;
    on_pwm.has_pwm = true;
    on_pwm.pwm = 128;
    ch.apply(on_pwm, 30);
    TEST_ASSERT_TRUE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT8(128, ch.pwm8());
    on_pwm.pwm = 0;
    ch.apply(on_pwm, 40);
    TEST_ASSERT_FALSE(ch.is_on());
}

void test_off_command_never_leaves_a_stale_off_timer() {
    // An off command carrying duration_sec used to arm the off-timer while
    // the channel was off; a later plain ON was then cut short by it.
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand off;
    off.has_state = true;
    off.state_on = false;
    off.has_duration = true;
    off.duration_sec = 10;
    ch.apply(off, 0);
    TEST_ASSERT_FALSE(ch.is_on());

    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 5000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(10001));
    TEST_ASSERT_TRUE(ch.is_on());

    // And an explicit off disarms a live timer even if a later ON follows.
    sp::ChannelCommand timed;
    timed.has_state = true;
    timed.state_on = true;
    timed.has_duration = true;
    timed.duration_sec = 30;
    sp::Channel ch2;
    ch2.configure(switch_cfg());
    ch2.apply(timed, 0);
    sp::ChannelCommand plain_off;
    plain_off.has_state = true;
    plain_off.state_on = false;
    ch2.apply(plain_off, 1000);
    ch2.apply(on, 2000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch2.tick(30001));
    TEST_ASSERT_TRUE(ch2.is_on());
}

void test_dim_accepts_pwm_as_level() {
    // The Pi automation only has `pwm` (documented 0-1023 for
    // lighting). A dim channel used to ignore it and jump to 1023 on
    // {"state":"on","pwm":300}, and reject a bare {"pwm":300}.
    sp::Channel ch;
    ch.configure(dim_cfg());

    sp::ChannelCommand bare;
    bare.has_pwm = true;
    bare.pwm = 300;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.apply(bare, 0));
    TEST_ASSERT_TRUE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT16(300, ch.level10());

    sp::ChannelCommand on_pwm;
    on_pwm.has_state = true;
    on_pwm.state_on = true;
    on_pwm.has_pwm = true;
    on_pwm.pwm = 450;
    ch.apply(on_pwm, 10);
    TEST_ASSERT_EQUAL_UINT16(450, ch.level10());

    // Explicit off wins over pwm here too (shared contract rule).
    sp::ChannelCommand off_pwm;
    off_pwm.has_state = true;
    off_pwm.state_on = false;
    off_pwm.has_pwm = true;
    off_pwm.pwm = 800;
    ch.apply(off_pwm, 20);
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT16(0, ch.level10());

    // `level` (the v1 lighting key) wins when both are present.
    sp::ChannelCommand both;
    both.has_level = true;
    both.level = 700;
    both.has_pwm = true;
    both.pwm = 100;
    ch.apply(both, 30);
    TEST_ASSERT_EQUAL_UINT16(700, ch.level10());

    // Out-of-range pwm clamps to the 10-bit range.
    bare.pwm = 5000;
    ch.apply(bare, 40);
    TEST_ASSERT_EQUAL_UINT16(1023, ch.level10());
    bare.pwm = 0;
    ch.apply(bare, 50);
    TEST_ASSERT_FALSE(ch.is_on());

    // pwm + ramp_sec ramps like level does.
    bare.pwm = 100;
    ch.apply(bare, 60);
    sp::ChannelCommand ramp;
    ramp.has_pwm = true;
    ramp.pwm = 900;
    ramp.has_ramp = true;
    ramp.ramp_sec = 10;
    ch.apply(ramp, 1000);
    TEST_ASSERT_EQUAL_UINT16(100, ch.level10());
    ch.tick(11001);
    TEST_ASSERT_EQUAL_UINT16(900, ch.level10());

    // Empty dim payload is still rejected.
    sp::ChannelCommand empty;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Rejected,
                          (int)ch.apply(empty, 70));
}

void test_force_off_is_a_counted_cutoff_and_disarms_timers() {
    // Safe mode (link lost) and OTA start drive every channel off through
    // force_off(): counted as a safety cutoff, timers/ramps disarmed.
    sp::Channel ch;
    ch.configure(switch_cfg());
    sp::ChannelCommand timed;
    timed.has_state = true;
    timed.state_on = true;
    timed.has_duration = true;
    timed.duration_sec = 600;
    ch.apply(timed, 0);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.force_off(1000, "safe mode"));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_TRUE(ch.last_change_was_cutoff());
    TEST_ASSERT_EQUAL_STRING("safe mode", ch.reason());
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().safety_cutoffs);
    TEST_ASSERT_EQUAL_UINT8(0, ch.pwm8());

    // Already off → no event, no double count.
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                          (int)ch.force_off(2000, "safe mode"));
    TEST_ASSERT_EQUAL_UINT32(1, ch.health().safety_cutoffs);

    // The old 600 s timer must not cut a later plain ON short.
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 3000);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(600001));
    TEST_ASSERT_TRUE(ch.is_on());

    // Dim channel mid-ramp: force_off stops the ramp for good.
    sp::Channel dim;
    dim.configure(dim_cfg());
    sp::ChannelCommand ramp;
    ramp.has_level = true;
    ramp.level = 900;
    ramp.has_ramp = true;
    ramp.ramp_sec = 10;
    dim.apply(ramp, 0);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)dim.force_off(2000, "OTA update"));
    TEST_ASSERT_FALSE(dim.is_on());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)dim.tick(5000));
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)dim.tick(20000));
    TEST_ASSERT_EQUAL_UINT16(0, dim.level10());
}

void test_max_on_override_runtime_and_bounds() {
    // Per-channel max-on is operator-tunable (cmd/config
    // {"max_on_sec":{...}}) without resetting channel state.
    sp::Channel ch;
    ch.configure(switch_cfg("aux"));
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    ch.apply(on, 0);
    ch.set_max_on_ms(10000);  // shortened while running
    TEST_ASSERT_TRUE(ch.is_on());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(9000));
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.tick(10001));
    TEST_ASSERT_EQUAL_STRING("auto-off (max-on exceeded)", ch.reason());
    // A switch channel can never lose its backstop.
    ch.set_max_on_ms(0);
    TEST_ASSERT_EQUAL_UINT32(sp::kDefaultMaxOnMs, ch.config().max_on_ms);

    uint32_t ms = 12345;
    bool clamped = true;
    // Switch: 1 s .. 30 min; larger values clamp; <= 0 refused.
    TEST_ASSERT_TRUE(sp::max_on_override_ms(sp::ChannelMode::Switch, 60, &ms, &clamped));
    TEST_ASSERT_EQUAL_UINT32(60000, ms);
    TEST_ASSERT_FALSE(clamped);
    TEST_ASSERT_TRUE(sp::max_on_override_ms(sp::ChannelMode::Switch, 7200, &ms, &clamped));
    TEST_ASSERT_EQUAL_UINT32(sp::kDefaultMaxOnMs, ms);
    TEST_ASSERT_TRUE(clamped);
    ms = 777;
    TEST_ASSERT_FALSE(sp::max_on_override_ms(sp::ChannelMode::Switch, 0, &ms, &clamped));
    TEST_ASSERT_FALSE(sp::max_on_override_ms(sp::ChannelMode::Switch, -5, &ms, &clamped));
    TEST_ASSERT_EQUAL_UINT32(777, ms);  // untouched on refusal
    // Dim: 0 (no cutoff) .. 24 h.
    TEST_ASSERT_TRUE(sp::max_on_override_ms(sp::ChannelMode::Dim, 0, &ms, &clamped));
    TEST_ASSERT_EQUAL_UINT32(0, ms);
    TEST_ASSERT_TRUE(sp::max_on_override_ms(sp::ChannelMode::Dim, 200000, &ms, &clamped));
    TEST_ASSERT_EQUAL_UINT32(24UL * 3600UL * 1000UL, ms);
    TEST_ASSERT_TRUE(clamped);
    TEST_ASSERT_FALSE(sp::max_on_override_ms(sp::ChannelMode::Dim, -1, &ms, &clamped));
}

void test_relay_aux_preset_has_short_pump_backstop() {
    // aux drives the misting pump in every documented build — a
    // lost off must not run it for 30 min (~3 L). Aux defaults to 60 s.
    sp::ChannelConfig out[4];
    sp::personality_channels(sp::Personality::RelayBank, out);
    TEST_ASSERT_EQUAL_STRING("aux", out[3].name);
    TEST_ASSERT_EQUAL_UINT32(sp::kAuxMaxOnMs, out[3].max_on_ms);
    TEST_ASSERT_EQUAL_UINT32(60UL * 1000UL, sp::kAuxMaxOnMs);
    sp::Channel aux;
    aux.configure(out[3]);
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    aux.apply(on, 0);
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)aux.tick(60001));
    TEST_ASSERT_FALSE(aux.is_on());
}

void test_co2_calibration_target_range() {
    // FRC targets outside Sensirion's
    // 400-2000 ppm reference range are refused before any sensor is told.
    TEST_ASSERT_TRUE(sp::co2_cal_target_valid(400));
    TEST_ASSERT_TRUE(sp::co2_cal_target_valid(420));
    TEST_ASSERT_TRUE(sp::co2_cal_target_valid(2000));
    TEST_ASSERT_FALSE(sp::co2_cal_target_valid(399));
    TEST_ASSERT_FALSE(sp::co2_cal_target_valid(42));     // typo for 420
    TEST_ASSERT_FALSE(sp::co2_cal_target_valid(4200));   // typo for 420
    TEST_ASSERT_FALSE(sp::co2_cal_target_valid(0));
    TEST_ASSERT_FALSE(sp::co2_cal_target_valid(-420));
    TEST_ASSERT_FALSE(sp::co2_cal_target_valid(65535));
}

// ── output stage failure (LEDC attach / duty write) ────────────

// A channel whose LEDC attach failed has its gate held LOW. It used to stay
// routed and accept {state:on}, then report state:on / pwm:255 while the fan
// or heater was off. Now it refuses anything that would turn it on and
// reports off; an explicit off is still accepted.
void test_output_fault_refuses_on_and_reports_off() {
    sp::Channel ch;
    ch.configure(switch_cfg());
    TEST_ASSERT_NULL(ch.output_fault());
    sp::ChannelCommand on;
    on.has_state = true;
    on.state_on = true;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.apply(on, 0));
    TEST_ASSERT_TRUE(ch.is_on());

    // The fault turns a running channel off (a forced off).
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed,
                          (int)ch.set_output_fault(100, "LEDC attach failed"));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_UINT8(0, ch.pwm8());
    TEST_ASSERT_EQUAL_UINT16(0, ch.duty10());
    TEST_ASSERT_EQUAL_STRING("LEDC attach failed", ch.output_fault());

    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Rejected, (int)ch.apply(on, 200));
    TEST_ASSERT_EQUAL_STRING("LEDC attach failed", ch.reason());
    TEST_ASSERT_FALSE(ch.is_on());
    sp::ChannelCommand pwm;
    pwm.has_pwm = true;
    pwm.pwm = 180;
    pwm.has_duration = true;
    pwm.duration_sec = 30;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Rejected, (int)ch.apply(pwm, 300));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)ch.tick(40000));

    sp::ChannelCommand off;
    off.has_state = true;
    off.state_on = false;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)ch.apply(off, 400));
    TEST_ASSERT_FALSE(ch.is_on());
    TEST_ASSERT_EQUAL_STRING("LEDC attach failed", ch.output_fault());

    // A dim channel faulted at boot (never on): no level, no scene, no ramp.
    sp::Channel light;
    light.configure(dim_cfg());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None,
                          (int)light.set_output_fault(0, "LEDC attach failed"));
    sp::ChannelCommand level;
    level.has_level = true;
    level.level = 800;
    level.has_ramp = true;
    level.ramp_sec = 10;
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Rejected, (int)light.apply(level, 10));
    TEST_ASSERT_FALSE(light.ramping());
    TEST_ASSERT_EQUAL_UINT16(0, light.level10());
    TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::None, (int)light.tick(20000));
}

// The lighting bank's level report during a ramp_sec ramp: the duty follows
// every step, but the report used to go out on every 1-LSB step of every
// channel (~17/s per channel for 0→1023 over 60 s), each one a live
// telemetry frame on the Pi. DimReportThrottle sends it at most once a
// second while only ramp steps are pending, and at once when the ramp ends.
void test_dim_ramp_level_report_is_throttled() {
    sp::Channel ch[2];
    ch[0].configure(dim_cfg("white"));
    ch[1].configure(dim_cfg("blue"));
    sp::DimReportThrottle throttle;
    sp::ChannelCommand up;
    up.has_level = true;
    up.level = 1023;
    up.has_ramp = true;
    up.ramp_sec = 60;
    for (sp::Channel& c : ch) {
        TEST_ASSERT_EQUAL_INT((int)sp::ChannelEvent::Changed, (int)c.apply(up, 0));
        TEST_ASSERT_TRUE(c.ramping());
    }
    throttle.reported(0);  // the command's own report

    int changes = 0, reports = 0;
    uint32_t last_report = 0, longest_gap = 0;
    for (uint32_t now = 5; now <= 61000; now += 5) {  // a 5 ms loop pass
        for (sp::Channel& c : ch) {
            if (c.tick(now) == sp::ChannelEvent::Changed) {
                ++changes;
                throttle.note_change(c.ramping());
            }
        }
        if (throttle.due(now)) {
            ++reports;
            if (now - last_report > longest_gap) longest_gap = now - last_report;
            last_report = now;
            throttle.reported(now);
        }
    }
    TEST_ASSERT_FALSE(ch[0].ramping());
    TEST_ASSERT_EQUAL_UINT16(1023, ch[0].level10());
    TEST_ASSERT_TRUE(changes > 2000);  // every step still reached the duty
    // ~1 per second for 60 s (+ the final level), not one per step.
    TEST_ASSERT_TRUE(reports >= 60 && reports <= 62);
    TEST_ASSERT_TRUE(longest_gap <= 1005);
    // The ramp's end went out on the pass it happened.
    TEST_ASSERT_EQUAL_UINT32(60000, last_report);

    // A non-ramp change (a timer cutoff) is reported on the same pass.
    sp::DimReportThrottle t2;
    t2.reported(1000);
    t2.note_change(/*ramp_step=*/true);
    TEST_ASSERT_FALSE(t2.due(1500));
    t2.note_change(/*ramp_step=*/false);
    TEST_ASSERT_TRUE(t2.due(1500));
    t2.reported(1500);
    TEST_ASSERT_FALSE(t2.due(1600));  // nothing pending
    // A `now` taken before a command's report in the same pass is not a
    // ~49.7-day gap.
    t2.note_change(true);
    TEST_ASSERT_FALSE(t2.due(1499));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_switch_empty_payload_rejected);
    RUN_TEST(test_switch_state_and_pwm);
    RUN_TEST(test_duration_expiry_and_clamp);
    RUN_TEST(test_max_on_dominates_long_duration);
    RUN_TEST(test_negative_duration_ignored_rest_applies);
    RUN_TEST(test_max_on_fires_and_reon_does_not_extend);
    RUN_TEST(test_tick_older_than_the_on_stamp_is_not_a_cutoff);
    RUN_TEST(test_ramp_tick_older_than_its_start_stays_in_range);
    RUN_TEST(test_off_stamped_before_the_on_adds_no_on_time);
    RUN_TEST(test_on_time_counts_runs_longer_than_the_wrap_window);
    RUN_TEST(test_cutoff_kinds_and_max_on_trips);
    RUN_TEST(test_plain_on_ends_a_running_pulse);
    RUN_TEST(test_millis_wrap_boundary);
    RUN_TEST(test_on_time_accounting);
    RUN_TEST(test_dim_level_and_off);
    RUN_TEST(test_dim_ramp_interpolates);
    RUN_TEST(test_dim_ramp_down_to_zero_turns_off);
    RUN_TEST(test_channel_name_validation);
    RUN_TEST(test_cmd_router_exact_match);
    RUN_TEST(test_scene_table);
    RUN_TEST(test_clamp_helpers);
    RUN_TEST(test_wrap_helpers);
    RUN_TEST(test_personality_str_round_trip);
    RUN_TEST(test_personality_from_str_rejects_unknown_and_null);
    RUN_TEST(test_node_type_str_is_never_node);
    RUN_TEST(test_personality_channels_climate_has_no_bank);
    RUN_TEST(test_personality_channels_relay_bank_presets);
    RUN_TEST(test_personality_channels_lighting_bank_presets);
    RUN_TEST(test_cmd_router_ninth_channel_overflow);
    RUN_TEST(test_channel_duty10_switch_expansion);
    RUN_TEST(test_cmd_suffix_split);
    RUN_TEST(test_scene_table_level_values);
    RUN_TEST(test_switch_explicit_off_wins_over_pwm);
    RUN_TEST(test_off_command_never_leaves_a_stale_off_timer);
    RUN_TEST(test_dim_accepts_pwm_as_level);
    RUN_TEST(test_force_off_is_a_counted_cutoff_and_disarms_timers);
    RUN_TEST(test_max_on_override_runtime_and_bounds);
    RUN_TEST(test_relay_aux_preset_has_short_pump_backstop);
    RUN_TEST(test_co2_calibration_target_range);
    RUN_TEST(test_output_fault_refuses_on_and_reports_off);
    RUN_TEST(test_dim_ramp_level_report_is_throttled);
    return UNITY_END();
}
