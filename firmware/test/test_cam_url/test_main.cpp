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

// Where a camera may send its frames. Accepted: the Pi's names, the paired
// Pi host, RFC 1918 IPv4 literals. Everything else is refused, including the
// v1 hole: "10.attacker.com" passed the private-range check through
// startsWith("10.").
void test_server_url_allow_list() {
    const std::string at_cap = "http://10.0.0.5/" + std::string(128 - 16, 'a');
    const std::string over_cap = at_cap + "a";
    const std::string long_host = "http://" + std::string(64, 'a') + "/";
    struct {
        const char* label;
        const char* url;
        const char* paired;
        bool want;
    } cases[] = {
        {"sporeprint.local", "http://sporeprint.local:8000", "", true},
        {"sporeprint.ai over https", "https://sporeprint.ai", "", true},
        {"with a path", "http://sporeprint.local/api", "", true},
        {"the paired Pi host", "http://mypi.lan:8000", "mypi.lan", true},
        {"128 characters", at_cap.c_str(), "", true},
        // RFC 1918 literals, edge to edge.
        {"10/8", "http://10.0.0.5:8000", "", true},
        {"192.168/16", "http://192.168.1.7", "", true},
        {"172.16/12 low", "http://172.16.0.1", "", true},
        {"172.16/12 high", "http://172.31.255.254:8000", "", true},
        {"172.32 is public", "http://172.32.0.1", "", false},
        {"172.15 is public", "http://172.15.0.1", "", false},
        {"192.169 is public", "http://192.169.0.1", "", false},
        {"8.8.8.8", "http://8.8.8.8", "", false},
        {"11/8", "http://11.0.0.1", "", false},
        // The v1 hole: hostnames that only look private.
        {"10.attacker.com", "http://10.attacker.com/x", "", false},
        {"192.168.evil.io", "http://192.168.evil.io", "", false},
        {"10.0.0.5.evil.com", "http://10.0.0.5.evil.com", "", false},
        // Malformed quads are hostnames, not IPs.
        {"octet > 255", "http://10.0.0.999", "", false},
        {"three octets", "http://10.0.0", "", false},
        {"five octets", "http://10.0.0.5.6", "", false},
        {"four-digit octet", "http://10.0.0.0005", "", false},
        {"empty octet", "http://10..0.5", "", false},
        // Structure.
        {"ftp scheme", "ftp://10.0.0.5", "", false},
        {"userinfo", "http://user@10.0.0.5/", "", false},
        {"query", "http://10.0.0.5/?q=1", "", false},
        {"fragment", "http://10.0.0.5/#frag", "", false},
        {"letter in port", "http://10.0.0.5:80x", "", false},
        {"sign in port", "http://10.0.0.5:8-0", "", false},
        {"empty", "", "", false},
        {"null", nullptr, "", false},
        {"no host", "http://", "", false},
        {"port only", "http://:8000", "", false},
        {"64-character host", long_host.c_str(), "", false},
        {"129 characters", over_cap.c_str(), "", false},
        // An empty or missing paired host never matches anything.
        {"empty paired host", "http://evil.com", "", false},
        {"null paired host", "http://evil.com", nullptr, false},
    };
    for (auto& c : cases)
        TEST_ASSERT_EQUAL_MESSAGE(c.want, sp::server_url_allowed(c.url, c.paired),
                                  c.label);
}

// ── default upload URL ─────────────────────────────────────────

// The upload URL: a stored server_url (an MQTT command, a v1 migration) is
// never overridden; otherwise the portal's "Pi address" (cfg.broker_host,
// the host tls_transport already fetches the CA from) on :8000; an empty or
// structurally bad Pi address falls back to the old default rather than
// building a URL the allow-list would never accept.
void test_resolve_server_url() {
    struct {
        const char* stored;
        const char* pi_host;
        const char* want;
    } cases[] = {
        {"", "192.168.1.50", "http://192.168.1.50:8000"},
        {"", "MyPi.LAN", "http://mypi.lan:8000"},
        // The untouched portal default reproduces the old hardcoded URL.
        {"", "sporeprint.local", "http://sporeprint.local:8000"},
        {"http://10.0.0.9:8080", "192.168.1.50", "http://10.0.0.9:8080"},
        {"", "", "http://sporeprint.local:8000"},
        {"", "192.168.1.5:1883", "http://sporeprint.local:8000"},
        {"", "pi/evil", "http://sporeprint.local:8000"},
        {"", "user@pi", "http://sporeprint.local:8000"},
    };
    for (auto& c : cases)
        TEST_ASSERT_EQUAL_STRING_MESSAGE(
            c.want, sp_cam::resolve_server_url(c.stored, c.pi_host).c_str(),
            c.pi_host);
}

// {"server_url": <url>}. A stored URL could only be replaced, never removed:
// an empty URL was refused by the allow-list, so a stale one (a v1
// migration, an old command) stayed in force until a factory reset. "" now
// resets the cam to the portal default; every other value goes through the
// allow-list, with the operator-provisioned Pi address trusted like
// paired_pi_host (both come from physical-access provisioning, never MQTT).
void test_server_url_cmd_sets_resets_or_rejects() {
    using sp_cam::ServerUrlCmd;
    struct {
        const char* label;
        const char* url;
        const char* paired;
        const char* pi_host;
        ServerUrlCmd want;
    } cases[] = {
        {"empty resets", "", "", "192.168.1.60", ServerUrlCmd::Reset},
        {"the portal Pi address", "http://mypi.lan:8000", "", "MyPi.lan",
         ServerUrlCmd::Set},
        {"the paired Pi host", "http://mypi.lan:8000", "mypi.lan", "",
         ServerUrlCmd::Set},
        {"RFC 1918, no hosts", "http://10.0.0.5:8000", "", "", ServerUrlCmd::Set},
        {"sporeprint.local, no hosts", "http://sporeprint.local:8000", "", "",
         ServerUrlCmd::Set},
        {"neither host", "http://evil.com", "", "mypi.lan", ServerUrlCmd::Reject},
        {"the v1 hole", "http://10.attacker.com", "", "mypi.lan",
         ServerUrlCmd::Reject},
        {"null", nullptr, "", "mypi.lan", ServerUrlCmd::Reject},
    };
    for (auto& c : cases)
        TEST_ASSERT_EQUAL_INT_MESSAGE(
            (int)c.want, (int)sp_cam::server_url_cmd(c.url, c.paired, c.pi_host),
            c.label);
    // A reset uploads to the portal default from then on.
    TEST_ASSERT_EQUAL_STRING(
        "http://192.168.1.60:8000",
        sp_cam::resolve_server_url("", "192.168.1.60").c_str());
}

// The upload used HTTPClient's own clients: an unbounded DNS lookup (up to
// 21 s on core 3.x) and a 120 s TLS handshake default against the cam's 90 s
// loop WDT. Every wait of a capture + upload pass is bounded now, and the
// sum leaves room for the body transfer.
void test_capture_and_upload_fit_inside_the_cam_wdt() {
    TEST_ASSERT_EQUAL_UINT32(90u, sp_cam::kCamLoopWdtTimeoutS);
    TEST_ASSERT_EQUAL_UINT32(
        sp_cam::kCaptureWorstCaseS + sp::kDnsWorstCaseS +
            sp_cam::kUploadConnectTimeoutS + sp_cam::kUploadHandshakeTimeoutS +
            2 * sp_cam::kUploadIoTimeoutS,
        sp_cam::kCaptureUploadWorstCaseS);
    TEST_ASSERT_TRUE(sp_cam::kCaptureUploadWorstCaseS + sp::kLoopWdtMarginS <
                     sp_cam::kCamLoopWdtTimeoutS);
    // The core's 120 s handshake default alone would overrun it.
    TEST_ASSERT_TRUE(sp_cam::kUploadHandshakeTimeoutS < 120u);
}

// ── X-Timestamp (shared contract 2) ────────────────────────────

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

// ── HTTPS uploads ──────────────────────────────────────────────

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

// ── sensor identity + tuning ───────────────────────────────────

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
    RUN_TEST(test_server_url_allow_list);
    RUN_TEST(test_resolve_server_url);
    RUN_TEST(test_server_url_cmd_sets_resets_or_rejects);
    RUN_TEST(test_capture_and_upload_fit_inside_the_cam_wdt);
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
