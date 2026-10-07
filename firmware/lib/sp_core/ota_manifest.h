#pragma once
//
// ota_manifest — the signed release manifest on the node: Ed25519 over the
// exact canonical bytes, the v1 field grammar, and the node's policy. The
// format is server/app/cloud/ota_manifest.py's, byte for byte (one schema
// for the Pi-server bundle and node images); test_core_ota_manifest checks
// both against the shared vectors (test/fixtures/ota_manifest_vectors.json,
// a byte-identical copy of server/tests/fixtures/ota_manifest_vectors.json).
//
// A manifest v1 is exactly
//   {"artifact":"<a>","channel":"<c>","published_at":"<t>",
//    "schema":"sporeprint.ota.manifest.v1","sha256":"<h>","size":<n>,
//    "version":"<v>"}
// with no whitespace (keys sorted, as Python's json.dumps(sort_keys=True,
// separators=(",", ":")) writes it). Every value comes from a fixed ASCII
// grammar, so the canonical form is unique and the node can check it by
// rebuilding the bytes — no JSON library involved.
//
// For node images: artifact = the PlatformIO env the image was built for
// (node_esp32, cam, ...), sha256/size = firmware.bin's.
//
// Native-safe: no Arduino headers. Ed25519: vendored Monocypher 4.0.3
// (vendor/monocypher, crypto_ed25519_check — RFC 8032 with SHA-512).

#include <stddef.h>
#include <stdint.h>

namespace sp {

constexpr const char* kOtaManifestSchema = "sporeprint.ota.manifest.v1";
// ota_manifest.py MAX_MANIFEST_BYTES. A node gets its manifest inside one
// <1024-byte command frame, so in practice it is ~300 bytes.
constexpr size_t kOtaManifestMaxBytes = 4096;
constexpr size_t kOtaSignatureBytes = 64;
constexpr size_t kOtaPubkeyBytes = 32;
constexpr size_t kOtaVersionMaxLen = 64;
constexpr size_t kOtaArtifactMaxLen = 64;
constexpr uint64_t kOtaMaxSize = (1ULL << 53) - 1;

struct OtaManifest {
    char artifact[kOtaArtifactMaxLen + 1];
    char channel[16];  // stable | beta | dev
    char published_at[21];
    char sha256[65];
    uint64_t size;
    char version[kOtaVersionMaxLen + 1];
};

enum class ManifestStatus : uint8_t {
    Ok = 0,
    TooLarge,      // more than kOtaManifestMaxBytes
    BadSignature,  // not signed by the pinned key
    NotCanonical,  // not the exact v1 byte form (incl. not JSON at all, and
                   // a value too long for its field)
    BadField,      // canonical shape, a value outside its grammar
};
const char* manifest_status_str(ManifestStatus s);

// The canonical v1 bytes → fields (no signature check).
ManifestStatus parse_manifest(const uint8_t* bytes, size_t len,
                              OtaManifest* out);

// Ed25519 over exactly `bytes`, then parse_manifest().
ManifestStatus verify_manifest(const uint8_t* bytes, size_t len,
                               const uint8_t sig[kOtaSignatureBytes],
                               const uint8_t pubkey[kOtaPubkeyBytes],
                               OtaManifest* out);

// Rebuild the canonical bytes. Returns the length (a NUL follows), or 0 when
// `cap` is too small.
size_t manifest_canonical(const OtaManifest& m, char* out, size_t cap);

// The leading X.Y.Z of a version ("v" prefix allowed, any suffix ignored —
// pre-release suffixes are not ordered, as on the Pi). False when there is
// no such prefix or a part exceeds 9 digits ("dev" builds).
struct FwVersion {
    uint32_t major = 0;
    uint32_t minor = 0;
    uint32_t patch = 0;
};
bool parse_fw_version(const char* s, FwVersion* out);
int compare_fw_version(const FwVersion& a, const FwVersion& b);

enum class ManifestPolicy : uint8_t {
    Ok = 0,
    NoArtifact,     // this image does not know its own artifact name
    WrongArtifact,  // signed for another image (board / node vs cam)
    Downgrade,      // older than the running image
    BelowFloor,     // older than the newest manifest-verified update (NVS)
};
const char* manifest_policy_str(ManifestPolicy p);

// May this (already verified) manifest be flashed here? `running_version`
// that does not parse (a "dev" build) is not compared; an empty `floor`
// means none was recorded. Equal X.Y.Z is allowed (a re-flash).
ManifestPolicy manifest_policy(const OtaManifest& m, const char* my_artifact,
                               const char* running_version,
                               const char* floor_version);

}  // namespace sp
