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
// Destination binding + replay guard (fw-node#11). The MAC covers only the
// payload, so on its own a captured frame could be re-published to another
// channel / node or replayed inside the window. Both checks are additive —
// the signed format and the golden vectors are unchanged:
//   * OPTIONAL "topic" member: a signer that includes
//     "topic":"sporeprint/<node>/cmd/<suffix>" in the signed body binds the
//     frame to that topic; the node rejects it on any other (TopicMismatch).
//     Frames without the member (today's Pi + cloud signers) still verify.
//   * ReplayGuard: every accepted (topic, MAC) is remembered for the replay
//     window; a second delivery is rejected (Replayed). Keyed on the topic
//     too, because an unbound body sent to two channels in the same second
//     is legitimate.
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
    TopicMismatch,    // signed "topic" member names a different destination
    Replayed,         // this (topic, MAC) was already accepted in the window
};

const char* verify_status_str(VerifyStatus s);

// FNV-1a over a NUL-terminated topic (replay-guard key; nullptr → 0).
uint32_t topic_hash(const char* topic);

// Remembers accepted frames for the replay window. Fixed table of kSlots
// entries (the oldest is evicted when full — the Pi sends far fewer than
// kSlots commands per node per minute). One instance per node image.
class ReplayGuard {
public:
    static constexpr size_t kSlots = 32;
    // An entry outlives any ts that can still pass the ±window check.
    static constexpr uint64_t kRememberSeconds = 2ULL * kReplayWindowSeconds;

    bool seen(uint32_t topic, const uint8_t mac[32], uint64_t now_epoch_s) const;
    void remember(uint32_t topic, const uint8_t mac[32], uint64_t now_epoch_s);

private:
    struct Entry {
        bool used = false;
        uint32_t topic = 0;
        uint32_t seq = 0;  // insertion order (eviction picks the smallest)
        uint64_t expires_s = 0;
        uint8_t mac[32] = {0};
    };
    Entry slots_[kSlots];
    uint32_t next_seq_ = 0;
};

// Verify a wire payload. `now_epoch_s` is wall-clock seconds (caller is
// responsible for refusing to verify when the clock is not yet synced —
// that policy lives at the call site so it can log per-topic).
//   `topic`  — the topic the frame ARRIVED on; enables the "topic" member
//              binding check (nullptr skips it).
//   `replay` — enables the replay guard (nullptr skips it). Only frames that
//              pass every other check are remembered.
VerifyStatus verify_frame(const char* payload, size_t len,
                          const char* key, size_t key_len,
                          uint64_t now_epoch_s, HmacSha256Fn hmac,
                          const char* topic = nullptr,
                          ReplayGuard* replay = nullptr);

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
// `topic` / `replay` are passed through to verify_frame (see there).
CmdAuthResult command_auth_decision(const char* payload, size_t len,
                                    const char* key, size_t key_len,
                                    uint64_t now_epoch_s, HmacSha256Fn hmac,
                                    const char* topic = nullptr,
                                    ReplayGuard* replay = nullptr);

// Constant-time equality for fixed-length buffers (exposed for tests).
bool const_time_eq(const uint8_t* a, const uint8_t* b, size_t len);

// Lowercase-hex encode (out must hold 2*len + 1 bytes; exposed for tests).
void to_hex_lower(const uint8_t* bytes, size_t len, char* out);

}  // namespace sp
