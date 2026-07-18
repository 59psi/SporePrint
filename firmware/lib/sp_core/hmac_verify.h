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

// Earliest epoch we treat as a synced wall clock (2020-01-01T00:00:00Z). A
// smaller `now` means NTP has not resolved yet, so a signature can't be
// replay-checked and the command is refused.
constexpr uint64_t kMinValidEpoch = 1577836800ULL;

// Command-authorization decision at the call site (node + cam verify_command).
enum class CmdAuthDecision : uint8_t {
    AcceptUnsigned,       // NO key provisioned — fail-OPEN + warn (the v2
                          // migration posture; a provisioned key flips it to
                          // strict). Load-bearing: never let a refactor turn
                          // this into a silent accept-everything for keyed
                          // nodes, nor a reject for unprovisioned ones.
    RejectClockUnsynced,  // key set but now < kMinValidEpoch (NTP not synced)
    Accept,               // key set, clock synced, signature verified
    Reject,               // key set, clock synced, verify failed (see .status)
};

struct CmdAuthResult {
    CmdAuthDecision decision;
    VerifyStatus status;  // meaningful only for Accept / Reject
};

// Pure signing policy shared by both composition roots' verify_command(). The
// key comes from NodeConfig::hmac_key (empty ⇒ key_len 0 ⇒ fail-open). Kept
// here so the fail-open hinge + clock gate are host-tested, not buried in two
// Arduino-coupled main.cpp copies.
CmdAuthResult command_auth_decision(const char* payload, size_t len,
                                    const char* key, size_t key_len,
                                    uint64_t now_epoch_s, HmacSha256Fn hmac);

// Constant-time equality for fixed-length buffers (exposed for tests).
bool const_time_eq(const uint8_t* a, const uint8_t* b, size_t len);

// Lowercase-hex encode (out must hold 2*len + 1 bytes; exposed for tests).
void to_hex_lower(const uint8_t* bytes, size_t len, char* out);

}  // namespace sp
