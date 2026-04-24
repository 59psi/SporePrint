#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "config_store.h"

// HMAC-SHA256 verification for inbound MQTT command frames — mirrors the
// Python `verify_frame` in sporeprint/server/app/cloud/signing.py.
//
// Both sides share this contract:
//   * canonical body = json.dumps(frame - {signature}, sort_keys=True,
//     separators=(",", ":")).encode("utf-8")
//   * signature = HMAC-SHA256(signing_key, canonical_body), lowercase hex
//   * ts = epoch seconds; must be within REPLAY_WINDOW_SECONDS of now
//
// The canonical form is critical: any mismatch in key ordering or separator
// whitespace breaks the signature. This implementation uses ArduinoJson 7's
// `serializeJson` which is insertion-order. We re-build the doc with sorted
// keys before hashing to match Python's `sort_keys=True`.
//
// Returns true on valid signature AND fresh timestamp AND all-required-fields.
// `why` is populated with a short reason string on failure (for Serial log).

namespace sporeprint {

struct VerifyResult {
    bool ok;
    const char* why;  // static string literal; do not free.
};

static const unsigned long REPLAY_WINDOW_SECONDS = 30;

// Verify a command frame against the provided signing key. The frame must
// contain at minimum: `signature` (hex string), `ts` (number). The caller
// must already have parsed the topic/payload into `doc`.
//
// `nowEpochSec` is the current wall-clock (seconds since epoch). If the
// node has no NTP sync this will be 0-ish; the caller should skip
// verification (or use ts-based relative window) if time is unreliable.
VerifyResult verifyFrame(const JsonDocument& doc,
                         const char* signingKey,
                         unsigned long nowEpochSec);

// Call once at boot after ConfigStore::begin() but before command handling
// starts. If the firmware was built with -DSPOREPRINT_PROVISION_HMAC=<hex>
// and the NVS `hmac_key` slot is empty, writes the build-flag value into
// NVS and logs the event. No-op if NVS already has a key or the build
// flag is unset. Safe to call on every boot.
void bootstrapHmacKeyFromBuildFlag(ConfigStore& config);

// Convenience wrapper for the on-node command callback:
//   * reads `hmac_key` from NVS via the shared ConfigStore
//   * reads wall-clock via time(nullptr)
//   * during migration period: if NVS has no `hmac_key`, logs WARNING and
//     returns {ok=true} so existing deployments don't brick — but the
//     operator sees it every command
//   * if the clock hasn't been NTP-synced yet (time() < 2020), returns
//     {ok=false, why="clock not synced"}
//   * otherwise calls verifyFrame and logs the reason on rejection
//
// Return ok=true means the caller may proceed to actuate. ok=false means
// drop the frame (a line has already been logged to Serial).
bool verifyOrWarn(const JsonDocument& doc, ConfigStore& config, const char* topic);

}  // namespace sporeprint
