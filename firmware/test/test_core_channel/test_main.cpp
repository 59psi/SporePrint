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
        // Switch channels carry the 30-min max-on backstop.
        TEST_ASSERT_EQUAL_UINT32(sp::kDefaultMaxOnMs, out[i].max_on_ms);
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

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_switch_empty_payload_rejected);
    RUN_TEST(test_switch_state_and_pwm);
    RUN_TEST(test_duration_expiry_and_clamp);
    RUN_TEST(test_max_on_dominates_long_duration);
    RUN_TEST(test_negative_duration_ignored_rest_applies);
    RUN_TEST(test_max_on_fires_and_reon_does_not_extend);
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
    return UNITY_END();
}
