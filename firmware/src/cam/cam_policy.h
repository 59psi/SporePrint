#pragma once
//
// cam_policy — the camera image's pure decisions, kept free of Arduino and
// esp32-camera headers so test/test_cam_url can assert them on the host.
// main.cpp is the only device-side consumer.
//
//   * sensor identity + per-sensor tuning (OV2640 / OV3660 / OV5640 on the
//     AI-Thinker pin map)
//   * JPEG-quality backoff after a dropped (overflowed) frame
//   * the X-Timestamp rule: epoch seconds only when NTP-synced
//   * the default upload URL (the portal's Pi address) and the hosts the
//     server_url command may point at
//   * HTTPS uploads: pinned-CA or refuse, never unverified TLS

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include <string>

#include "hmac_verify.h"       // sp::kMinValidEpoch
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

// An explicitly stored server_url (MQTT cmd, v1 migration) always wins.
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

}  // namespace sp_cam
