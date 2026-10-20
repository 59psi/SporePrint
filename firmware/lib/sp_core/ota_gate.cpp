#include "ota_gate.h"

#include <string.h>

#include "hmac_verify.h"  // to_hex_lower
#include "wrap_time.h"

namespace sp {

void OtaGate::arm(const OtaManifest& m, uint32_t now_ms) {
    m_ = m;
    armed_ = true;
    armed_at_ms_ = now_ms;
    verifying_ = false;
}

bool OtaGate::armed(uint32_t now_ms) const {
    return armed_ && elapsed_ms(now_ms, armed_at_ms_) < kArmMs;
}

OtaGate::Begin OtaGate::begin(uint32_t now_ms, int cmd, uint32_t size,
                              bool require_manifest) {
    verifying_ = false;
    const bool live = armed(now_ms);
    armed_ = false;  // one arming, one invitation — whatever happens next
    if (!live) {
        return require_manifest ? Begin::RefuseNoManifest : Begin::Unverified;
    }
    if (cmd != kCmdFlash) return Begin::RefuseFilesystem;
    if ((uint64_t)size != m_.size) return Begin::RefuseSize;
    sha_ = Sha256();
    fed_ = 0;
    verifying_ = true;
    return Begin::Verified;
}

void OtaGate::update(const uint8_t* data, size_t len) {
    if (!verifying_ || data == nullptr || len == 0) return;
    sha_.update(data, len);
    fed_ += len;
}

OtaGate::End OtaGate::finish() {
    if (!verifying_) return End::Unverified;
    verifying_ = false;
    uint8_t digest[32];
    sha_.finish(digest);
    char hex[65];
    to_hex_lower(digest, sizeof(digest), hex);
    if (fed_ != m_.size || strcmp(hex, m_.sha256) != 0) return End::Mismatch;
    return End::Match;
}

const char* ota_gate_begin_str(OtaGate::Begin b) {
    switch (b) {
        case OtaGate::Begin::Unverified: return "unverified";
        case OtaGate::Begin::Verified: return "verified";
        case OtaGate::Begin::RefuseNoManifest: return "manifest_required";
        case OtaGate::Begin::RefuseSize: return "manifest_size_mismatch";
        case OtaGate::Begin::RefuseFilesystem: return "manifest_not_firmware";
    }
    return "manifest_refused";
}

}  // namespace sp
