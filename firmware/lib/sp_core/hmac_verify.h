#pragma once
//
// hmac_verify — signed-command frame verification.
//
// Contract (mirrors sporeprint/server/app/mqtt.py::_sign_cmd_payload and
// cloud/signing.py; golden vectors in test/fixtures/signing_vectors.json):
//   canonical = canonicalize(wire_payload minus top-level "signature")
//   signature = lowercase hex HMAC-SHA256(key, canonical)
//   ts        = epoch seconds (int from the Pi, float in cloud vectors);
//               |now - ts| must be <= kReplayWindowSeconds
//
// Works on the RAW wire bytes — never on a re-serialized document — so the
// Python signer's number formatting survives verbatim (see canonical_json.h).
//
// Native-safe: no Arduino headers. HMAC arrives via injection (mbedTLS on
// device, vendored host impl in tests).

#include <stddef.h>
#include <stdint.h>

#include "sha256.h"

namespace sp {

constexpr uint32_t kReplayWindowSeconds = 30;

enum class VerifyStatus : uint8_t {
    Ok = 0,
    NoKey,            // empty signing key configured
    BadFrame,         // canonicalization rejected the payload (see CanonStatus)
    NoSignature,      // missing or non-string "signature" member
    BadSignatureLen,  // signature not 64 hex chars
    NoTimestamp,      // missing or non-numeric "ts" member
    StaleTimestamp,   // outside the replay window
    Mismatch,         // HMAC comparison failed
};

const char* verify_status_str(VerifyStatus s);

// Verify a wire payload. `now_epoch_s` is wall-clock seconds (caller is
// responsible for refusing to verify when the clock is not yet synced —
// that policy lives at the call site so it can log per-topic).
VerifyStatus verify_frame(const char* payload, size_t len,
                          const char* key, size_t key_len,
                          uint64_t now_epoch_s, HmacSha256Fn hmac);

// Constant-time equality for fixed-length buffers (exposed for tests).
bool const_time_eq(const uint8_t* a, const uint8_t* b, size_t len);

// Lowercase-hex encode (out must hold 2*len + 1 bytes; exposed for tests).
void to_hex_lower(const uint8_t* bytes, size_t len, char* out);

}  // namespace sp
