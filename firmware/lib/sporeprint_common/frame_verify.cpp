#include "frame_verify.h"
#include <mbedtls/md.h>
#include <string.h>
#include <time.h>

namespace sporeprint {

// Lowercase-hex encode `len` bytes from `bytes` into `out`. `out` must have
// room for `2 * len + 1` chars (NUL-terminated).
static void bytesToHex(const uint8_t* bytes, size_t len, char* out) {
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < len; ++i) {
        out[2 * i]     = hex[(bytes[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[bytes[i] & 0xF];
    }
    out[2 * len] = '\0';
}

// Constant-time compare of two equal-length C strings. Returns 0 on match,
// nonzero otherwise. Mirrors `hmac.compare_digest`.
static int constTimeEq(const char* a, const char* b, size_t len) {
    unsigned char diff = 0;
    for (size_t i = 0; i < len; ++i) {
        diff |= (unsigned char)a[i] ^ (unsigned char)b[i];
    }
    return diff;
}

// Re-emit the frame as canonical JSON matching Python's
// `json.dumps(..., sort_keys=True, separators=(",", ":"))`:
//   * exclude the `signature` key
//   * keys emitted in lexicographic order at every object depth
//   * no whitespace between separators
//
// ArduinoJson 7 preserves insertion order; sort_keys=True requires us to
// walk the document and emit in sorted order. We implement this by copying
// the top-level keys into a sorted array then emitting by key. The v3.4.9
// signed frame schema is flat (no nested objects needed for recursive
// sorting), which matches cloud/app/relay/service.py:sign_frame.
static String canonicalize(const JsonDocument& doc) {
    JsonObjectConst src = doc.as<JsonObjectConst>();

    // Collect non-signature keys
    const int MAX_KEYS = 24;
    const char* keys[MAX_KEYS];
    int n = 0;
    for (JsonPairConst kv : src) {
        if (strcmp(kv.key().c_str(), "signature") == 0) continue;
        if (n >= MAX_KEYS) break;
        keys[n++] = kv.key().c_str();
    }

    // Simple insertion sort on the pointers — n is small.
    for (int i = 1; i < n; ++i) {
        const char* cur = keys[i];
        int j = i - 1;
        while (j >= 0 && strcmp(keys[j], cur) > 0) {
            keys[j + 1] = keys[j];
            --j;
        }
        keys[j + 1] = cur;
    }

    // Build sorted doc in a new JsonDocument so ArduinoJson emits keys in
    // our explicit insertion order (which is the sorted order).
    JsonDocument sorted;
    for (int i = 0; i < n; ++i) {
        sorted[keys[i]] = src[keys[i]];
    }

    String out;
    serializeJson(sorted, out);
    return out;
}

VerifyResult verifyFrame(const JsonDocument& doc,
                         const char* signingKey,
                         unsigned long nowEpochSec) {
    if (signingKey == nullptr || signingKey[0] == '\0') {
        return {false, "no signing key configured"};
    }

    JsonVariantConst sigVar = doc["signature"];
    if (!sigVar.is<const char*>()) {
        return {false, "missing signature field"};
    }
    const char* sigHex = sigVar.as<const char*>();
    if (strlen(sigHex) != 64) {
        return {false, "signature length != 64 hex chars"};
    }

    JsonVariantConst tsVar = doc["ts"];
    if (!tsVar.is<unsigned long>() && !tsVar.is<long>() &&
        !tsVar.is<double>() && !tsVar.is<float>()) {
        return {false, "missing or non-numeric ts"};
    }
    long ts = tsVar.as<long>();
    long now = (long)nowEpochSec;
    long delta = (now > ts) ? (now - ts) : (ts - now);
    if (delta > (long)REPLAY_WINDOW_SECONDS) {
        return {false, "ts outside replay window"};
    }

    String canonical = canonicalize(doc);

    uint8_t mac[32];
    const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (info == nullptr) {
        return {false, "mbedtls_md init failed"};
    }
    int rc = mbedtls_md_hmac(info,
                             (const uint8_t*)signingKey, strlen(signingKey),
                             (const uint8_t*)canonical.c_str(), canonical.length(),
                             mac);
    if (rc != 0) {
        return {false, "hmac compute failed"};
    }

    char computed[65];
    bytesToHex(mac, sizeof(mac), computed);

    if (constTimeEq(computed, sigHex, 64) != 0) {
        return {false, "signature mismatch"};
    }

    return {true, nullptr};
}

#ifndef SPOREPRINT_PROVISION_HMAC
#define SPOREPRINT_PROVISION_HMAC ""
#endif

// The build flag is stringified via macro concatenation tricks so the
// operator can write `-DSPOREPRINT_PROVISION_HMAC=<hex>` without quotes.
#define _SP_STRINGIFY(x) #x
#define _SP_TOSTRING(x) _SP_STRINGIFY(x)

void bootstrapHmacKeyFromBuildFlag(ConfigStore& config) {
    String flagKey = String(_SP_TOSTRING(SPOREPRINT_PROVISION_HMAC));
    // If build flag is empty, nothing to do. If NVS already has a key,
    // never overwrite — rotations go through a clean provisioning flow.
    if (flagKey.length() == 0) return;
    String nvsKey = config.getString("hmac_key");
    if (nvsKey.length() > 0) return;

    config.setString("hmac_key", flagKey);
    Serial.printf("[CFG] hmac_key stored from build flag (%u chars)\n",
                  (unsigned)flagKey.length());
}

bool verifyOrWarn(const JsonDocument& doc, ConfigStore& config, const char* topic) {
    String key = config.getString("hmac_key");

    // v3.4.9 migration path: if no key is provisioned yet, log a WARNING
    // on every command so the operator cannot miss it, but allow the frame
    // through. This lets an existing fleet upgrade to this firmware
    // without bricking until keys are deployed. A future release (v3.5+)
    // will flip this to fail-closed once the provisioning tooling ships.
    if (key.length() == 0) {
        Serial.printf(
            "[SEC] WARNING: hmac_key not provisioned — accepting unsigned command on %s. "
            "Run scripts/provision-node.sh to close this gap.\n", topic);
        return true;
    }

    time_t now = time(nullptr);
    if (now < 1577836800) {  // before 2020-01-01 → SNTP hasn't synced
        Serial.printf("[SEC] Rejecting command on %s: node clock not synced (now=%ld)\n",
                      topic, (long)now);
        return false;
    }

    VerifyResult r = verifyFrame(doc, key.c_str(), (unsigned long)now);
    if (!r.ok) {
        Serial.printf("[SEC] Rejecting command on %s: %s\n", topic, r.why);
        return false;
    }
    return true;
}

}  // namespace sporeprint
