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
// Destination binding + replay guard. The MAC covers only the
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
// Key rotation (node side only — the signed format is unchanged): besides
// the key it verifies with (NVS hmac_key), a re-keyed node keeps the key that
// one replaced (NVS hmac_key_prev) until the new key verifies a frame, so it
// can be re-keyed before the Pi switches keys. See "command-signing key
// rotation" below.
//
// Native-safe: no Arduino headers. HMAC arrives via injection (mbedTLS on
// device, vendored host impl in tests).

#include <stddef.h>
#include <stdint.h>

#include <string>

#include "kv_store.h"
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

// Remembers accepted frames for the replay window in a fixed table of
// kSlots entries. Nothing caps how many commands reach a node in a window,
// so the table can fill with live entries: then the entry with the oldest
// signed ts is evicted and the guard's floor rises to that ts. A frame the
// guard no longer remembers is refused when its ts is at or below the floor —
// it cannot be told from a replay of an evicted frame. (Evicting without a
// floor let any evicted frame, and in turn every frame of a busy window, be
// replayed.) A legitimate frame is refused only in a burst of more than
// kSlots frames signed in the same second. One instance per node image.
class ReplayGuard {
public:
    static constexpr size_t kSlots = 32;
    // An entry outlives any ts that can still pass the ±window check.
    static constexpr uint64_t kRememberSeconds = 2ULL * kReplayWindowSeconds;

    bool seen(uint32_t topic, const uint8_t mac[32], uint64_t now_epoch_s) const;
    // True when a frame signed at `frame_ts` is at or below the floor.
    bool below_floor(double frame_ts) const {
        return has_floor_ && frame_ts <= floor_ts_;
    }
    void remember(uint32_t topic, const uint8_t mac[32], uint64_t now_epoch_s,
                  double frame_ts);

private:
    struct Entry {
        bool used = false;
        uint32_t topic = 0;
        uint64_t expires_s = 0;
        double ts = 0.0;  // the frame's signed ts (eviction picks the oldest)
        uint8_t mac[32] = {0};
    };
    Entry slots_[kSlots];
    bool has_floor_ = false;
    double floor_ts_ = 0.0;
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
    Accept,               // key set, clock synced, signature verified (by the
                          // previous key during a rotation: .with_prev_key)
    Reject,               // key set, clock synced, verify failed (see .status)
};

struct CmdAuthResult {
    CmdAuthDecision decision;
    VerifyStatus status;  // meaningful only for Accept / Reject
    // Accept only: the frame verified with the previous key, not the current
    // one — a key rotation is under way and the Pi still signs with the old
    // key (see "command-signing key rotation" below).
    bool with_prev_key = false;
};

// Pure signing policy shared by both composition roots' verify_command(). The
// key comes from NodeConfig::hmac_key (empty ⇒ key_len 0 ⇒ fail-open). Kept
// here so the fail-open hinge + clock gate are host-tested, not buried in two
// Arduino-coupled main.cpp copies.
// `topic` / `replay` are passed through to verify_frame (see there).
// `prev_key` (NodeConfig::hmac_key_prev; empty = no rotation under way): a
// frame whose MAC does not match `key` is verified again with it, through
// the very same checks — window, topic binding, replay guard — so an old-key
// frame is accepted exactly when a new-key one would be. Only a MAC mismatch
// is retried: no other failure depends on the key. The clock gate and the
// fail-open hinge look at `key` alone, and a keyed node rejects an unsigned
// frame with or without a previous key.
CmdAuthResult command_auth_decision(const char* payload, size_t len,
                                    const char* key, size_t key_len,
                                    uint64_t now_epoch_s, HmacSha256Fn hmac,
                                    const char* topic = nullptr,
                                    ReplayGuard* replay = nullptr,
                                    const char* prev_key = nullptr,
                                    size_t prev_key_len = 0);

// ── command-signing key rotation ───────────────────────────────
// Holding a single key, a node rejected EVERY command from the moment the
// Pi signed with a new key until the node itself was re-keyed in its setup
// portal (or, re-keyed first, until the Pi had the key): lights stayed as
// they were and relay channels could not be switched on. So a portal save
// that changes the key keeps the key it replaces (NVS hmac_key_prev), and
// command_auth_decision falls back to it. The operator re-keys every node
// first and applies the key to the Pi last: the Pi keeps signing with the
// old key meanwhile, and the first frame accepted under the new key — the Pi
// has switched — retires the old key for good (retire_prev_key). The signed
// format and the Pi are unchanged.

// NVS key of the previous key (NVS key names are at most 15 characters).
constexpr const char* kHmacPrevKeyNvsKey = "hmac_key_prev";

// The previous key a node holds after its setup portal stores `new_key` over
// `key` while it holds `prev` ("" = none). `new_key` "" is a field left
// blank: nothing changes, and neither does re-entering the same key. A
// different key keeps the one it replaces; a node holds one previous key at
// most, so re-keying again before the new key verified a frame drops the
// older one. A node that had no key gets no previous key: once keyed, it
// never accepts an unsigned frame.
inline std::string prev_key_after_rekey(const std::string& key,
                                        const std::string& prev,
                                        const std::string& new_key) {
    if (new_key.empty() || new_key == key) return prev;
    return key;
}

// Ends a rotation: a frame accepted under the current key while a previous
// key is held shows the Pi signs with the new key, so the previous key is
// cleared from `prev` (the in-memory NodeConfig::hmac_key_prev) and erased
// from NVS (`kv`): it never verifies again. True when it did (log it).
inline bool retire_prev_key(const CmdAuthResult& r, std::string& prev,
                            KvStore& kv) {
    if (r.decision != CmdAuthDecision::Accept || r.with_prev_key ||
        prev.empty())
        return false;
    prev.clear();
    kv.set_string(kHmacPrevKeyNvsKey, std::string());
    return true;
}

// Constant-time equality for fixed-length buffers (exposed for tests).
bool const_time_eq(const uint8_t* a, const uint8_t* b, size_t len);

// Lowercase-hex encode (out must hold 2*len + 1 bytes; exposed for tests).
void to_hex_lower(const uint8_t* bytes, size_t len, char* out);

}  // namespace sp
