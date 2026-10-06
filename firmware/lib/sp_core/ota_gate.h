#pragma once
//
// ota_gate — binds the next network OTA to a verified, signed manifest.
//
// The Pi sends cmd/ota_manifest {manifest_b64, sig_b64} just before it pushes
// an image. Once the manifest verifies against the image's compiled-in key
// and passes manifest_policy() (ota_manifest.h), the gate is ARMED with its
// sha256 + size for kArmMs. The next authenticated espota invitation then:
//   * armed: must be a firmware (not filesystem) image of exactly the
//     manifest's size; every flashed byte is hashed, and the image is only
//     finalized (Update.end) when the SHA-256 matches — otherwise the update
//     is aborted and the running image stays;
//   * not armed: refused when the image requires manifests
//     (SPOREPRINT_OTA_REQUIRE_MANIFEST), else flashed unverified, as before.
// One arming covers one invitation, whatever its outcome; an arming older
// than kArmMs counts as none (the push it announced never came).
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include "ota_manifest.h"
#include "sha256.h"

namespace sp {

// cmd/<suffix> the Pi sends {manifest_b64, sig_b64} on before a push.
constexpr const char* kOtaManifestSuffix = "ota_manifest";

class OtaGate {
public:
    static constexpr uint32_t kArmMs = 5UL * 60UL * 1000UL;
    // espota command numbers (espota.h kCmdFlash / kCmdFilesystem).
    static constexpr int kCmdFlash = 0;

    void arm(const OtaManifest& m, uint32_t now_ms);
    void disarm() {
        armed_ = false;
        verifying_ = false;
    }
    bool armed(uint32_t now_ms) const;
    const OtaManifest& manifest() const { return m_; }

    enum class Begin : uint8_t {
        Unverified,        // no manifest armed, none required: flash as before
        Verified,          // armed and matching: hash every byte, check at end
        RefuseNoManifest,  // manifests required and none armed
        RefuseSize,        // armed for a different image size
        RefuseFilesystem,  // armed for firmware, offered a filesystem image
    };
    // An authenticated invitation: espota command and image size.
    Begin begin(uint32_t now_ms, int cmd, uint32_t size, bool require_manifest);

    // Every byte written to flash, in order (only hashed when Verified).
    void update(const uint8_t* data, size_t len);

    enum class End : uint8_t {
        Unverified,  // this update was not verified
        Match,       // size and SHA-256 equal the manifest's
        Mismatch,    // abort — do not finalize the image
    };
    End finish();

private:
    OtaManifest m_{};
    bool armed_ = false;
    uint32_t armed_at_ms_ = 0;
    bool verifying_ = false;
    uint64_t fed_ = 0;
    Sha256 sha_;
};

const char* ota_gate_begin_str(OtaGate::Begin b);

}  // namespace sp
