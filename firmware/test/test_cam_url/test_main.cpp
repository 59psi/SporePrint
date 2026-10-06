// test_cam_url — server_url allowlist, including the v1 hole where
// "10.attacker.com" passed the RFC1918 check via startsWith("10."), plus the
// cam image's pure policy (src/cam/cam_policy.h): default upload URL from the
// portal's Pi address, the X-Timestamp sync rule, HTTPS pinning, sensor
// identity/tuning for OV2640/OV3660/OV5640, and JPEG-quality backoff.

#include <unity.h>

#include <string.h>

#include <string>

#include "server_url_allow.h"

#include "../../src/cam/cam_policy.h"

void setUp() {}
void tearDown() {}

void test_allowed_hosts() {
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://sporeprint.local:8000", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("https://sporeprint.ai", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://sporeprint.local/api", ""));
    TEST_ASSERT_TRUE(
        sp::server_url_allowed("http://mypi.lan:8000", "mypi.lan"));
}

void test_rfc1918_literals() {
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://10.0.0.5:8000", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://192.168.1.7", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://172.16.0.1", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://172.31.255.254:8000", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://172.32.0.1", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://172.15.0.1", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://8.8.8.8", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://11.0.0.1", ""));
}

void test_v1_hole_closed() {
    // The exact v1 bypass: a HOSTNAME starting with "10.".
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.attacker.com/x", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://192.168.evil.io", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5.evil.com", ""));
    // Malformed quads are hostnames, not IPs.
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.999", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5.6", ""));
}

void test_structure_rules() {
    TEST_ASSERT_FALSE(sp::server_url_allowed("ftp://10.0.0.5", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://user@10.0.0.5/", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5/?q=1", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5/#frag", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5:80x", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed(nullptr, ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://", ""));
    // Length cap.
    char big[160];
    memset(big, 'a', sizeof(big));
    memcpy(big, "http://10.0.0.5/", 16);
    big[sizeof(big) - 1] = '\0';
    TEST_ASSERT_FALSE(sp::server_url_allowed(big, ""));
    // Empty paired host must not match an empty-host comparison trick.
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://evil.com", ""));
}

// ── default upload URL (fw-drivers-cam#6 / docs#20) ────────────

void test_default_server_url_follows_portal_pi_address() {
    // The portal's "Pi address" (cfg.broker_host) is the Pi — the same host
    // tls_transport already fetches http://<host>:8000/api/provision/ca from.
    TEST_ASSERT_EQUAL_STRING(
        "http://192.168.1.50:8000",
        sp_cam::resolve_server_url("", "192.168.1.50").c_str());
    TEST_ASSERT_EQUAL_STRING(
        "http://mypi.lan:8000",
        sp_cam::resolve_server_url("", "MyPi.LAN").c_str());
    // The untouched portal default reproduces the old hardcoded URL exactly.
    TEST_ASSERT_EQUAL_STRING(
        "http://sporeprint.local:8000",
        sp_cam::resolve_server_url("", "sporeprint.local").c_str());
}

void test_stored_server_url_still_wins() {
    // An explicit server_url (MQTT cmd or v1 migration) is never overridden.
    TEST_ASSERT_EQUAL_STRING(
        "http://10.0.0.9:8080",
        sp_cam::resolve_server_url("http://10.0.0.9:8080", "192.168.1.50").c_str());
}

void test_default_server_url_rejects_malformed_pi_address() {
    // Empty or structurally bad portal values fall back to the old default
    // rather than building a URL the allow-list would never accept.
    TEST_ASSERT_EQUAL_STRING("http://sporeprint.local:8000",
                             sp_cam::resolve_server_url("", "").c_str());
    TEST_ASSERT_EQUAL_STRING(
        "http://sporeprint.local:8000",
        sp_cam::resolve_server_url("", "192.168.1.5:1883").c_str());
    TEST_ASSERT_EQUAL_STRING(
        "http://sporeprint.local:8000",
        sp_cam::resolve_server_url("", "pi/evil").c_str());
    TEST_ASSERT_EQUAL_STRING(
        "http://sporeprint.local:8000",
        sp_cam::resolve_server_url("", "user@pi").c_str());
}

void test_cmd_allowlist_accepts_portal_pi_address() {
    // The operator-provisioned Pi address is trusted like paired_pi_host.
    TEST_ASSERT_TRUE(sp_cam::server_url_cmd_allowed("http://mypi.lan:8000", "",
                                                    "MyPi.lan"));
    TEST_ASSERT_TRUE(sp_cam::server_url_cmd_allowed("http://mypi.lan:8000",
                                                    "mypi.lan", ""));
    // Neither host matches → still the strict allow-list.
    TEST_ASSERT_FALSE(sp_cam::server_url_cmd_allowed("http://evil.com", "",
                                                     "mypi.lan"));
    TEST_ASSERT_FALSE(sp_cam::server_url_cmd_allowed("http://10.attacker.com",
                                                     "", "mypi.lan"));
    // RFC1918 literals + sporeprint.local keep working with empty hosts.
    TEST_ASSERT_TRUE(sp_cam::server_url_cmd_allowed("http://10.0.0.5:8000", "", ""));
    TEST_ASSERT_TRUE(
        sp_cam::server_url_cmd_allowed("http://sporeprint.local:8000", "", ""));
}

// ── X-Timestamp (fw-drivers-cam#5, shared contract 2) ──────────

void test_timestamp_header_only_when_epoch_synced() {
    char buf[24];
    // Uptime-scale clock (NTP never resolved) → omit the header entirely.
    TEST_ASSERT_FALSE(sp_cam::frame_timestamp(0, buf, sizeof(buf)));
    TEST_ASSERT_FALSE(sp_cam::frame_timestamp(900, buf, sizeof(buf)));
    TEST_ASSERT_FALSE(sp_cam::frame_timestamp(1577836799LL, buf, sizeof(buf)));
    // Synced → decimal epoch seconds.
    TEST_ASSERT_TRUE(sp_cam::frame_timestamp(1577836800LL, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("1577836800", buf);
    TEST_ASSERT_TRUE(sp_cam::frame_timestamp(1790000000LL, buf, sizeof(buf)));
    TEST_ASSERT_EQUAL_STRING("1790000000", buf);
    // A buffer too small to hold the value never yields a truncated header.
    char tiny[4];
    TEST_ASSERT_FALSE(sp_cam::frame_timestamp(1790000000LL, tiny, sizeof(tiny)));
}

// ── HTTPS uploads (fw-drivers-cam#14) ──────────────────────────

void test_https_upload_requires_pinned_ca() {
    using sp_cam::UploadTransport;
    TEST_ASSERT_EQUAL_INT((int)UploadTransport::Plain,
                          (int)sp_cam::upload_transport("http://10.0.0.5:8000", false));
    TEST_ASSERT_EQUAL_INT((int)UploadTransport::Plain,
                          (int)sp_cam::upload_transport("http://10.0.0.5:8000", true));
    // No CA → refuse (HTTPClient would otherwise call setInsecure()).
    TEST_ASSERT_EQUAL_INT((int)UploadTransport::Refuse,
                          (int)sp_cam::upload_transport("https://sporeprint.ai", false));
    TEST_ASSERT_EQUAL_INT((int)UploadTransport::Refuse,
                          (int)sp_cam::upload_transport("HTTPS://sporeprint.ai", false));
    TEST_ASSERT_EQUAL_INT((int)UploadTransport::TlsPinned,
                          (int)sp_cam::upload_transport("https://mypi.lan", true));
}

// ── sensor identity + tuning (fw-drivers-cam#4) ────────────────

void test_sensor_profile_ov2640_keeps_legacy_behavior() {
    sp_cam::SensorProfile p = sp_cam::sensor_profile(0x26);
    TEST_ASSERT_EQUAL_INT((int)sp_cam::Model::Ov2640, (int)p.model);
    TEST_ASSERT_EQUAL_STRING("ov2640", p.name);
    // Exactly the pre-OV3660 settings: UXGA q10 (PSRAM) / VGA q12 (DRAM),
    // no orientation/colour overrides.
    TEST_ASSERT_EQUAL_UINT8(10, p.jpeg_quality_psram);
    TEST_ASSERT_EQUAL_UINT8(12, p.jpeg_quality_dram);
    TEST_ASSERT_FALSE(p.apply_color_tuning);
}

void test_sensor_profile_ov3660_matches_espressif_example() {
    sp_cam::SensorProfile p = sp_cam::sensor_profile(0x3660);
    TEST_ASSERT_EQUAL_INT((int)sp_cam::Model::Ov3660, (int)p.model);
    TEST_ASSERT_EQUAL_STRING("ov3660", p.name);
    // CameraWebServer.ino: vflip 1, brightness +1, saturation -2.
    TEST_ASSERT_TRUE(p.apply_color_tuning);
    TEST_ASSERT_EQUAL_INT8(1, p.vflip);
    TEST_ASSERT_EQUAL_INT8(1, p.brightness);
    TEST_ASSERT_EQUAL_INT8(-2, p.saturation);
    // Valid JPEG quality (0-63, lower = better) with headroom in the
    // driver's fixed w*h/5 JPEG buffer.
    TEST_ASSERT_TRUE(p.jpeg_quality_psram >= 10 && p.jpeg_quality_psram <= 63);
    TEST_ASSERT_TRUE(p.jpeg_quality_dram >= p.jpeg_quality_psram);
}

void test_sensor_profile_ov5640_and_unknown() {
    sp_cam::SensorProfile p = sp_cam::sensor_profile(0x5640);
    TEST_ASSERT_EQUAL_INT((int)sp_cam::Model::Ov5640, (int)p.model);
    TEST_ASSERT_EQUAL_STRING("ov5640", p.name);
    TEST_ASSERT_FALSE(p.apply_color_tuning);
    TEST_ASSERT_TRUE(p.jpeg_quality_psram >= 10 && p.jpeg_quality_psram <= 63);

    sp_cam::SensorProfile u = sp_cam::sensor_profile(0x2145);  // GC2145 clone
    TEST_ASSERT_EQUAL_INT((int)sp_cam::Model::Unknown, (int)u.model);
    TEST_ASSERT_EQUAL_STRING("unknown", u.name);
    TEST_ASSERT_FALSE(u.apply_color_tuning);
    TEST_ASSERT_EQUAL_UINT8(10, u.jpeg_quality_psram);  // driver-init default

    sp_cam::SensorProfile n = sp_cam::sensor_profile_none();
    TEST_ASSERT_EQUAL_INT((int)sp_cam::Model::None, (int)n.model);
    TEST_ASSERT_EQUAL_STRING("none", n.name);
}

void test_board_orientation_only_overrides_on_the_freenove() {
    // AI-Thinker, XIAO, Waveshare: the sensor profile's orientation stands.
    const sp_cam::Board keep[] = {sp_cam::Board::AiThinker, sp_cam::Board::XiaoS3,
                                  sp_cam::Board::WaveshareS3};
    for (sp_cam::Board b : keep) {
        TEST_ASSERT_FALSE(sp_cam::board_orientation(b, 0x26).apply);
        TEST_ASSERT_FALSE(sp_cam::board_orientation(b, 0x3660).apply);
        TEST_ASSERT_FALSE(sp_cam::board_orientation(b, 0x5640).apply);
    }
    // Freenove Sketch_07.1 camera_init: OV2640 hmirror 1 / vflip 1, every
    // other sensor hmirror 1 / vflip 0.
    sp_cam::Orientation o =
        sp_cam::board_orientation(sp_cam::Board::FreenoveS3, 0x26);
    TEST_ASSERT_TRUE(o.apply);
    TEST_ASSERT_EQUAL_INT8(1, o.hmirror);
    TEST_ASSERT_EQUAL_INT8(1, o.vflip);
    o = sp_cam::board_orientation(sp_cam::Board::FreenoveS3, 0x3660);
    TEST_ASSERT_TRUE(o.apply);
    TEST_ASSERT_EQUAL_INT8(1, o.hmirror);
    TEST_ASSERT_EQUAL_INT8(0, o.vflip);
    o = sp_cam::board_orientation(sp_cam::Board::FreenoveS3, 0x5640);
    TEST_ASSERT_EQUAL_INT8(1, o.hmirror);
    TEST_ASSERT_EQUAL_INT8(0, o.vflip);
}

void test_flash_only_when_requested_and_fitted() {
    TEST_ASSERT_TRUE(sp_cam::flash_for_capture(true, true));
    TEST_ASSERT_FALSE(sp_cam::flash_for_capture(false, true));
    // S3 camera boards have no flash LED: a {"capture":true,"flash":true}
    // command still captures, without a flash, and says so.
    TEST_ASSERT_FALSE(sp_cam::flash_for_capture(true, false));
    TEST_ASSERT_FALSE(sp_cam::flash_for_capture(false, false));
}

void test_jpeg_quality_backoff_is_bounded() {
    // A dropped frame (JPEG overflowed the fixed buffer → fb_get NULL)
    // steps the quality NUMBER up (smaller files), never past the ceiling.
    TEST_ASSERT_EQUAL_UINT8(12, sp_cam::backoff_jpeg_quality(10));
    TEST_ASSERT_EQUAL_UINT8(14, sp_cam::backoff_jpeg_quality(12));
    TEST_ASSERT_EQUAL_UINT8(sp_cam::kJpegQualityCeiling,
                            sp_cam::backoff_jpeg_quality(sp_cam::kJpegQualityCeiling - 1));
    TEST_ASSERT_EQUAL_UINT8(sp_cam::kJpegQualityCeiling,
                            sp_cam::backoff_jpeg_quality(sp_cam::kJpegQualityCeiling));
    TEST_ASSERT_EQUAL_UINT8(40, sp_cam::backoff_jpeg_quality(40));  // never lowers
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_allowed_hosts);
    RUN_TEST(test_rfc1918_literals);
    RUN_TEST(test_v1_hole_closed);
    RUN_TEST(test_structure_rules);
    RUN_TEST(test_default_server_url_follows_portal_pi_address);
    RUN_TEST(test_stored_server_url_still_wins);
    RUN_TEST(test_default_server_url_rejects_malformed_pi_address);
    RUN_TEST(test_cmd_allowlist_accepts_portal_pi_address);
    RUN_TEST(test_timestamp_header_only_when_epoch_synced);
    RUN_TEST(test_https_upload_requires_pinned_ca);
    RUN_TEST(test_sensor_profile_ov2640_keeps_legacy_behavior);
    RUN_TEST(test_sensor_profile_ov3660_matches_espressif_example);
    RUN_TEST(test_sensor_profile_ov5640_and_unknown);
    RUN_TEST(test_jpeg_quality_backoff_is_bounded);
    RUN_TEST(test_board_orientation_only_overrides_on_the_freenove);
    RUN_TEST(test_flash_only_when_requested_and_fitted);
    return UNITY_END();
}
