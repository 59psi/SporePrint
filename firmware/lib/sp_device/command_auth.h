#pragma once
//
// command_auth — the inbound-command prologue both images (node and camera)
// run on every cmd/<suffix> frame before routing it: the clock-gated HMAC
// check with destination binding and the replay guard (the policy is the
// pure, host-tested sp::command_auth_decision in sp_core/hmac_verify.h —
// test_core_hmac), its log lines, and the two reserved suffixes every image
// answers the same way (cmd/coredump_ack → coredump_uploader,
// cmd/ota_manifest → OtaService). One copy, so the security-critical path
// cannot drift between the two composition roots.

#include <ArduinoJson.h>

#include <stddef.h>

#include "hmac_verify.h"
#include "kv_store.h"
#include "mqtt_link.h"
#include "node_config.h"
#include "ota_service.h"

namespace sp_device {

// Clock-gated HMAC policy: with a provisioned key, frames verify strictly
// (and only once NTP has a sane epoch). With NO key, accept + warn every time
// — the v1 migration posture, except v2 can actually provision the key
// (portal field), and an empty key really is empty. Verification runs on the
// exact wire bytes MqttLink hands through, never on a re-serialized document
// (lexeme fidelity is what makes the canonicalizer byte-exact against
// Python). The arrival topic enables destination binding (a signed "topic"
// member must name exactly this topic; frames without the member still
// verify), and `guard` rejects a second delivery of the same signed frame to
// the same topic inside the replay window.
// Key rotation: while cfg.hmac_key_prev is held, a frame the current key
// does not verify is tried with it (logged as such); the first frame
// accepted under the current key retires it, in `cfg` and in NVS (`kv`).
bool verify_command(MqttLink& link, NodeConfig& cfg, sp::KvStore& kv,
                    sp::ReplayGuard& guard, const char* raw, size_t raw_len,
                    const char* suffix);

// A cmd/coredump_ack the image would accept right now: none is needed
// without a signing key, and with one the frame only verifies once NTP has
// synced (coredump_uploader paces its retries on this).
bool coredump_ack_verifiable(const NodeConfig& cfg);

enum class CmdPrologue : uint8_t {
    Rejected,  // failed verification (logged): drop the frame
    Handled,   // a reserved suffix, handled here
    Route,     // verified and image-specific: the caller routes it
};

// verify_command(), then cmd/coredump_ack and cmd/ota_manifest. `ota` may be
// null (not constructed yet): a manifest is then ignored.
CmdPrologue command_prologue(MqttLink& link, NodeConfig& cfg, sp::KvStore& kv,
                             sp::ReplayGuard& guard, OtaService* ota,
                             const char* suffix, const char* raw,
                             size_t raw_len, JsonDocument& doc);

}  // namespace sp_device
