#pragma once
//
// cam_policy — the camera image's pure decisions, kept free of Arduino and
// esp32-camera headers so test/test_cam_url can assert them on the host.
// main.cpp is the only device-side consumer.
//
//   * sensor identity + per-sensor tuning (OV2640 / OV3660 / OV5640)
//   * per-board orientation and flash (AI-Thinker ESP32-CAM, and the
//     ESP32-S3 camera boards of boards/board_profile_esp32s3cam.h)
//   * JPEG-quality backoff after a dropped (overflowed) frame
//   * the X-Timestamp rule: epoch seconds only when NTP-synced
//   * the default upload URL (the portal's Pi address) and the hosts the
//     server_url command may point at (or "" to reset to that default)
//   * HTTPS uploads: pinned-CA or refuse, never unverified TLS
//   * the upload's time budget against the cam's loop WDT

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include <string>

#include "hmac_verify.h"       // sp::kMinValidEpoch
#include "link_budget.h"       // sp::kDnsWorstCaseS, sp::kLoopWdtMarginS
#include "server_url_allow.h"  // sp::server_url_allowed

namespace sp_cam {

// ── sensor identity + tuning ────────────────────────────────────
//
// esp32-camera sensor PIDs (sensor.h camera_pid_t), mirrored so this header
// stays host-compilable; main.cpp static_asserts they match the driver's.
constexpr uint16_t kPidOv2640 = 0x26;
constexpr uint16_t kPidOv3660 = 0x3660;
constexpr uint16_t kPidOv5640 = 0x5640;

enum class Model : uint8_t { None, Unknown, Ov2640, Ov3660, Ov5640 };

// Frame size is deliberately NOT per-sensor: every supported sensor runs
// UXGA 1600x1200 (PSRAM) / VGA 640x480 (no PSRAM). UXGA is the OV2640's
// native maximum and a scaled mode on the OV3660 (QXGA max) and OV5640
// (QSXGA max), so one geometry covers the whole fleet — the gallery,
// SSIM frame differencing and the vision prompts see the same 4:3 frame
// from an old OV2640 and a new OV3660 — and it matches the JPEG buffer the
// driver allocates at init (w*h/5 = 384,000 B), before the sensor model is
// known. At the 15-30 cm working distance that is ~0.2 mm/px across a
// block: early trich/cobweb patches span many pixels.
struct SensorProfile {
    Model model;
    const char* name;            // wire string (health / heartbeat / header)
    uint8_t jpeg_quality_psram;  // UXGA, buffer in PSRAM (0-63, lower = better)
    uint8_t jpeg_quality_dram;   // VGA, buffer in internal DRAM
    bool apply_color_tuning;     // write vflip / brightness / saturation below
    int8_t vflip;
    int8_t brightness;
    int8_t saturation;
};

// Camera never initialized (dead / unseated module).
inline SensorProfile sensor_profile_none() {
    return {Model::None, "none", 10, 12, false, 0, 0, 0};
}

inline SensorProfile sensor_profile(uint16_t pid) {
    switch (pid) {
        case kPidOv2640:
            // Unchanged from the OV2640-only firmware: q10 UXGA / q12 VGA,
            // driver-default orientation and colour.
            return {Model::Ov2640, "ov2640", 10, 12, false, 0, 0, 0};
        case kPidOv3660:
            // Espressif's CameraWebServer correction for this sensor: it
            // initializes vertically flipped and over-saturated. q12 (vs the
            // OV2640's q10) keeps the OV3660's larger JPEGs inside the fixed
            // w*h/5 frame buffer; the backoff below covers a busy scene.
            return {Model::Ov3660, "ov3660", 12, 14, true, 1, 1, -2};
        case kPidOv5640:
            // Driver-default orientation/colour (no upstream correction);
            // same q12 headroom as the OV3660 for its larger JPEGs.
            return {Model::Ov5640, "ov5640", 12, 14, false, 0, 0, 0};
        default:
            // Some other sensor the driver could init — run it on the init
            // defaults and say so in health.
            return {Model::Unknown, "unknown", 10, 12, false, 0, 0, 0};
    }
}

// ── board ───────────────────────────────────────────────────────
//
// Which board the image was built for (the board profile's
// SP_CAM_BOARD_KIND; the AI-Thinker when it sets none).
enum class Board : uint8_t { AiThinker, FreenoveS3, XiaoS3, WaveshareS3 };

// The sensor sits on each board at its own angle. Only the Freenove
// ESP32-S3-WROOM CAM's vendor example corrects for it (Freenove
// Sketch_07.1_CameraWebServer camera_init: OV2640 mirrored + flipped, every
// other sensor mirrored only), and those values override the sensor
// profile's vflip there. The AI-Thinker, the XIAO and the Waveshare
// examples run Espressif's CameraWebServer correction alone, which the
// sensor profile already is.
struct Orientation {
    bool apply;  // false = keep the sensor profile's orientation
    int8_t hmirror;
    int8_t vflip;
};

inline Orientation board_orientation(Board board, uint16_t pid) {
    if (board != Board::FreenoveS3) return {false, 0, 0};
    if (pid == kPidOv2640) return {true, 1, 1};
    return {true, 1, 0};
}

// A capture uses the flash only when it was asked for AND the board has
// one (none of the S3 camera boards does). X-Flash-Used reports this
// value, so the Pi never records a flash that did not fire.
inline bool flash_for_capture(bool requested, bool board_has_flash) {
    return requested && board_has_flash;
}

// A JPEG larger than the driver's fixed buffer is dropped (FB-OVF / NO-EOI)
// and esp_camera_fb_get() times out with NULL. Each such failure steps the
// quality NUMBER up (smaller files) until the ceiling; it never steps back
// down within a boot, so a busy scene can't oscillate.
constexpr uint8_t kJpegQualityStep = 2;
constexpr uint8_t kJpegQualityCeiling = 20;

inline uint8_t backoff_jpeg_quality(uint8_t q) {
    if (q >= kJpegQualityCeiling) return q;
    unsigned next = (unsigned)q + kJpegQualityStep;
    return (uint8_t)(next > kJpegQualityCeiling ? kJpegQualityCeiling : next);
}

// ── X-Timestamp ─────────────────────────────────────────────────
//
// Shared contract: the cam sends X-Timestamp (Unix epoch seconds) ONLY when
// its clock is NTP-synced. Unsynced → false → the header is omitted and the
// Pi stamps arrival time. (The old firmware sent uptime seconds instead,
// which the Pi stored as 1970 timestamps and colliding filenames.)
inline bool frame_timestamp(int64_t now_epoch_s, char* out, size_t out_len) {
    if (out == nullptr || out_len == 0) return false;
    if (now_epoch_s < (int64_t)sp::kMinValidEpoch) return false;
    int n = snprintf(out, out_len, "%lld", (long long)now_epoch_s);
    return n > 0 && (size_t)n < out_len;
}

// ── upload URL ──────────────────────────────────────────────────

constexpr const char* kFallbackServerUrl = "http://sporeprint.local:8000";

inline std::string lowercase(const std::string& s) {
    std::string out = s;
    for (char& c : out)
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
    return out;
}

// No stored server_url → the Pi API on the host the operator typed into the
// portal's "Pi address" field (cfg.broker_host — Mosquitto and the API are
// the same Pi, the same assumption tls_transport's CA fetch makes). The
// portal default "sporeprint.local" reproduces the old hardcoded URL. A
// value that can't form an allow-listable URL falls back to that default.
inline std::string default_server_url(const std::string& pi_host) {
    const std::string host = lowercase(pi_host);
    if (!host.empty()) {
        const std::string url = "http://" + host + ":8000";
        if (sp::server_url_allowed(url.c_str(), host.c_str())) return url;
    }
    return kFallbackServerUrl;
}

// An explicitly stored server_url (MQTT cmd, v1 migration) wins. It is
// dropped when the portal saves a different Pi address
// (sp::portal_save_resets_server_url) or on {"server_url": ""}.
inline std::string resolve_server_url(const std::string& stored,
                                      const std::string& pi_host) {
    return stored.empty() ? default_server_url(pi_host) : stored;
}

// server_url command allow-list: the strict sp::server_url_allowed rules,
// with the operator-provisioned Pi address trusted like paired_pi_host
// (both come from physical-access provisioning, never from MQTT).
// `lowered_url` must already be lowercased by the caller.
inline bool server_url_cmd_allowed(const char* lowered_url,
                                   const std::string& paired_pi_host,
                                   const std::string& pi_host) {
    return sp::server_url_allowed(lowered_url, lowercase(paired_pi_host).c_str()) ||
           sp::server_url_allowed(lowered_url, lowercase(pi_host).c_str());
}

// What {"server_url": <url>} does. "" resets uploads to the portal default
// (the Pi address typed at provisioning — operator-set, never from MQTT; an
// empty URL used to be refused, leaving a stale stored URL in force until a
// factory reset); anything else must pass the allow-list.
enum class ServerUrlCmd : uint8_t { Set, Reset, Reject };

inline ServerUrlCmd server_url_cmd(const char* lowered_url,
                                   const std::string& paired_pi_host,
                                   const std::string& pi_host) {
    if (lowered_url != nullptr && lowered_url[0] == '\0') return ServerUrlCmd::Reset;
    return server_url_cmd_allowed(lowered_url, paired_pi_host, pi_host)
               ? ServerUrlCmd::Set
               : ServerUrlCmd::Reject;
}

// ── HTTPS uploads ───────────────────────────────────────────────
//
// Arduino-ESP32's HTTPClient::begin(url) on an https:// URL calls
// WiFiClientSecure::setInsecure() — TLS with no certificate check. The cam
// therefore only uploads over https when it has a pinned CA (the Pi CA that
// Secure-MQTT provisioning stores) and refuses otherwise.
enum class UploadTransport : uint8_t { Plain, TlsPinned, Refuse };

inline bool is_https(const std::string& url) {
    return lowercase(url.substr(0, 8)) == "https://";
}

inline UploadTransport upload_transport(const std::string& url,
                                        bool have_pinned_ca) {
    if (!is_https(url)) return UploadTransport::Plain;
    return have_pinned_ca ? UploadTransport::TlsPinned : UploadTransport::Refuse;
}

// ── the capture + upload time budget ────────────────────────────
//
// capture_and_post() runs in the loop task under the loop WDT main.cpp arms
// at the end of setup() (kCamLoopWdtTimeoutS, panic). HTTPClient::begin(url)
// builds its own NetworkClient(Secure): an unbounded lookup (lwIP gives up
// after up to 21 s) and a 120 s TLS handshake default, which together could
// outlast the WDT and panic the cam. The upload now goes through the cam's
// own clients: DNS capped at sp::kDnsWorstCaseS (bounded_dns.h), the TCP
// connect at kUploadConnectTimeoutS, the TLS handshake (an https server_url)
// at kUploadHandshakeTimeoutS, and every socket wait without progress — a
// stalled request write, the response read — at kUploadIoTimeoutS. The
// capture before it waits at most kCaptureWorstCaseS (the flash settle and
// three frame grabs, each bounded by the camera driver's 4 s frame timeout).
// A capture never starts in a pass that already blocked on an MQTT connect
// attempt or a CA fetch / probe (main.cpp), so these are the whole pass. An
// upload that keeps making progress is paced by the link; the margin below
// is its room.
constexpr uint32_t kCamLoopWdtTimeoutS = 90;
constexpr uint32_t kUploadConnectTimeoutS = 10;
constexpr uint32_t kUploadHandshakeTimeoutS = 10;
constexpr uint32_t kUploadIoTimeoutS = 10;
constexpr uint32_t kCaptureWorstCaseS = 13;
constexpr uint32_t kCaptureUploadWorstCaseS =
    kCaptureWorstCaseS + sp::kDnsWorstCaseS + kUploadConnectTimeoutS +
    kUploadHandshakeTimeoutS + 2 * kUploadIoTimeoutS;

static_assert(kCaptureUploadWorstCaseS + sp::kLoopWdtMarginS + 15 <=
                  kCamLoopWdtTimeoutS,
              "a capture + upload pass must fit inside the cam's loop WDT, "
              "with room for the body transfer itself");

// MQTT keepalive (MqttLink::set_keepalive). The broker drops a client it has
// heard nothing from for 1.5x the keepalive and publishes its LWT: with
// PubSubClient's 15 s default (22.5 s) a slow capture + upload pass — no MQTT
// pumping meanwhile — showed the cam offline and lost the commands sent in
// between. 1.5x the keepalive covers the longest pass the loop WDT allows.
constexpr uint16_t kCamMqttKeepaliveS = 60;

static_assert(kCamMqttKeepaliveS * 3u / 2u >= kCamLoopWdtTimeoutS,
              "the broker must not give up on the cam within one loop pass");

}  // namespace sp_cam
