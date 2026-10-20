#pragma once
//
// ota_service — network OTA with the v1 password policy (no default, min 12
// chars) and MQTT lifecycle events. v2 provisions ota_pass via the captive
// portal, which v1 never could — its "set a strong password via captive
// portal" message referred to a field that didn't exist, so OTA was
// permanently disabled in practice.
//
// The receiver speaks the espota handshake exactly as arduino-esp32 2.x
// ArduinoOTA did (sp_core/espota.h: MD5 challenge-response on UDP 3232, the
// image pulled back over TCP) and advertises "<hostname>.local" with the
// _arduino._tcp mDNS service as ArduinoOTA did. It no longer uses the core's
// ArduinoOTA: from arduino-esp32 3.3 that library answers only a
// PBKDF2-SHA256 handshake that Pis before 2026-10 do not speak, which would
// have locked every node out of their OTA pushes after its first 3.x image
// (see espota.h; server/app/hardware/ota_push.py now answers both).
//
// Signed manifests (sp_core/ota_gate.h): an image built with an OTA verify
// key (SPOREPRINT_OTA_PUBKEY_B64 at build time, ota_build.h) accepts
// cmd/ota_manifest {manifest_b64, sig_b64} from the Pi. A manifest that
// verifies, names this image's PlatformIO env and is not older than the
// running image or the last manifest-verified update confirmed on this node
// (NVS "ota_floor") arms
// the gate: the next push must be exactly that image (size + SHA-256 of every
// flashed byte) or it is aborted before Update.end(). Without a manifest the
// push is flashed unverified, as before — unless the image was built with
// SPOREPRINT_OTA_REQUIRE_MANIFEST=1. Results go out on sporeprint/<id>/ota as
// manifest_armed {version, sha256} / manifest_rejected {reason}.
//
// A verified flash records its version as PENDING ("ota_floor_next"); the
// floor itself rises only once that image is confirmed on this node
// (image_confirmed(); sp::ota_floor_promotable), so an image that fails its
// probation and rolls back does not lock the node to versions at or above
// the one that failed.
//
// Every refusal of an authenticated push (the manifest gate, an image on
// probation, Update.begin) is decided BEFORE the espota "OK": the node
// answers "ERR <reason>" instead, so the pusher reports why. (After "OK" the
// pusher only waits for a connect-back that never comes.)

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFiUdp.h>

#include "espota.h"
#include "kv_store.h"
#include "mqtt_link.h"
#include "ota_gate.h"

namespace sp_device {

// Build identity the manifest check needs (filled by ota_build.h).
struct OtaManifestConfig {
    const char* pubkey_b64 = "";  // "" = this image takes no manifests
    bool require = false;         // refuse pushes that come without one
    const char* artifact = "";    // the PlatformIO env this image is
    const char* fw_version = "dev";
    sp::KvStore* kv = nullptr;    // ota_floor
};

class OtaService {
public:
    OtaService(MqttLink& link, const char* hostname, const char* ota_pass)
        : link_(link), hostname_(hostname), pass_(ota_pass) {}

    // Safe-state hook, run BEFORE the first byte is written to flash. The
    // whole upload runs synchronously inside loop(), so channel duration /
    // max-on timers are not ticked for its 30-60 s; the composition root uses
    // this to drive every channel off first (they come back off after the
    // reboot anyway, and a failed OTA resumes from off).
    using StartFn = void (*)(void* ctx);
    void on_start(StartFn fn, void* ctx) {
        start_fn_ = fn;
        start_ctx_ = ctx;
    }

    // Probation hook, run when an authenticated FIRMWARE push is about to be
    // accepted, before anything is written: nullptr to go ahead, or the
    // refusal reason (static) the push is answered with. The composition
    // roots wire sp_device::clear_probation_for_ota (image_rollback.h).
    using ReadyFn = const char* (*)(void* ctx);
    void before_flash(ReadyFn fn, void* ctx) {
        ready_fn_ = fn;
        ready_ctx_ = ctx;
    }

    // Call before begin(). Without it, manifests are unsupported.
    void configure_manifests(const OtaManifestConfig& cfg);

    // Returns true when OTA is armed (password present + strong enough).
    bool begin();

    // cmd/ota_manifest (the caller has verified the frame's HMAC).
    void on_manifest(JsonDocument& doc);
    // One received datagram per call; an authenticated invitation runs the
    // whole upload (and the reboot into the new image) from here.
    void loop();
    bool armed() const { return armed_; }

    // The running image was just confirmed: raise the anti-rollback floor to
    // the version a manifest-verified push left pending, if that is this
    // image (sp::ota_floor_promotable). The pending record is consumed.
    void image_confirmed();

private:
    enum class State : uint8_t { Idle, WaitAuth };

    void on_datagram(const char* data, size_t len);
    // Every check that can refuse the push, before the espota "OK":
    // nullptr = accepted (Update begun), else the refusal reason.
    const char* prepare_update();
    void run_update();
    void reply(const char* text, const char* arg = nullptr);
    void fail(const char* reason);
    void publish_event(const char* event, const char* extra_key = nullptr,
                       const char* extra_val = nullptr,
                       const char* extra_key2 = nullptr,
                       const char* extra_val2 = nullptr);
    void reject_manifest(const char* reason);

    MqttLink& link_;
    String hostname_;
    String pass_;  // cleared once hashed in begin()
    bool armed_ = false;
    StartFn start_fn_ = nullptr;
    void* start_ctx_ = nullptr;
    ReadyFn ready_fn_ = nullptr;
    void* ready_ctx_ = nullptr;

    WiFiUDP udp_;
    State state_ = State::Idle;
    char pass_digest_[sp::espota::kHexLen + 1] = {0};
    char nonce_[sp::espota::kHexLen + 1] = {0};
    sp::espota::Invitation invitation_;
    IPAddress peer_ip_;

    OtaManifestConfig manifest_cfg_;
    uint8_t pubkey_[sp::kOtaPubkeyBytes] = {0};
    bool pubkey_ok_ = false;
    sp::OtaGate gate_;
    // The accepted push (prepare_update → run_update).
    sp::OtaGate::Begin gate_result_ = sp::OtaGate::Begin::Unverified;
    // Copied at acceptance: the arming is consumed, the events outlive it.
    char manifest_version_[sp::kOtaVersionMaxLen + 1] = {0};
};

}  // namespace sp_device
