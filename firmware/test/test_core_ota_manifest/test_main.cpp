// test_core_ota_manifest — signed OTA manifests on the node
// (sp_core/ota_manifest.h, sp_core/ota_gate.h) and the base64 the command
// carries them in (sp_core/base64.h).
//
// Pinned here:
//   * the vendored Ed25519 (Monocypher 4.0.3) against RFC 8032 §7.1 tests
//     1-3, the fixture's test seed deriving the fixture's public key (so
//     node and Pi agree on key bytes), and a malleated S + L signature
//     refused, as the Pi refuses it
//   * every case of test/fixtures/ota_manifest_vectors.json — a byte-identical
//     copy of the Pi's server/tests/fixtures/ota_manifest_vectors.json:
//     valid → ok, tampered → bad signature, signed-but-invalid → refused
//   * the v1 field grammar edge by edge (artifact, version, channel, sha256,
//     size, published_at incl. leap days), canonical re-encoding
//   * the node policy: own artifact only, no downgrade below the running
//     image or the recorded floor, "dev" builds not compared
//   * the gate: one arming per invitation, 5-minute expiry, size / filesystem
//     refusals, required-manifest refusal, SHA-256 match vs mismatch
//   * strict base64 decode (padding, pad bits, alphabet)

#include <ArduinoJson.h>
#include <unity.h>

#include <stdio.h>
#include <string.h>

#include <string>
#include <vector>

#include "base64_codec.h"
#include "ota_gate.h"
#include "ota_manifest.h"
#include "sha256.h"
#include "vendor/monocypher/monocypher-ed25519.h"

void setUp() {}
void tearDown() {}

using sp::ManifestPolicy;
using sp::ManifestStatus;
using sp::OtaGate;
using sp::OtaManifest;

#define ASSERT_STATUS(want, got) TEST_ASSERT_EQUAL((int)(want), (int)(got))

static std::vector<uint8_t> unhex(const char* hex) {
    std::vector<uint8_t> out;
    const size_t n = strlen(hex);
    for (size_t i = 0; i + 1 < n; i += 2) {
        unsigned v = 0;
        sscanf(hex + i, "%2x", &v);
        out.push_back((uint8_t)v);
    }
    return out;
}

static std::string hexs(const uint8_t* b, size_t n) {
    static const char k[] = "0123456789abcdef";
    std::string s;
    for (size_t i = 0; i < n; ++i) {
        s.push_back(k[b[i] >> 4]);
        s.push_back(k[b[i] & 15]);
    }
    return s;
}

// ── fixture ────────────────────────────────────────────────────

static JsonDocument g_vectors;
static uint8_t g_pub[32];
static uint8_t g_secret[64];  // Monocypher's secret key: seed || public key

static bool load_vectors() {
    const char* candidates[] = {
        "test/fixtures/ota_manifest_vectors.json",
        "fixtures/ota_manifest_vectors.json",
        "../fixtures/ota_manifest_vectors.json",
    };
    for (const char* path : candidates) {
        FILE* f = fopen(path, "rb");
        if (!f) continue;
        std::string text;
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof(buf), f)) > 0) text.append(buf, n);
        fclose(f);
        return deserializeJson(g_vectors, text) == DeserializationError::Ok;
    }
    return false;
}

void test_fixture_loads_and_seed_derives_the_pinned_key() {
    TEST_ASSERT_TRUE_MESSAGE(load_vectors(), "ota_manifest_vectors.json not found");
    TEST_ASSERT_EQUAL_STRING("sporeprint.ota.manifest.v1",
                             g_vectors["schema"].as<const char*>());
    const char* b64 = g_vectors["public_key_b64"].as<const char*>();
    size_t n = 0;
    TEST_ASSERT_TRUE(sp::base64_decode(b64, strlen(b64), g_pub, sizeof(g_pub), &n));
    TEST_ASSERT_EQUAL(32, n);

    std::vector<uint8_t> seed = unhex(g_vectors["private_seed_hex"].as<const char*>());
    TEST_ASSERT_EQUAL(32, seed.size());
    uint8_t derived[32];
    crypto_ed25519_key_pair(g_secret, derived, seed.data());  // wipes seed
    TEST_ASSERT_EQUAL_MEMORY(g_pub, derived, 32);
}

// ── Ed25519 (RFC 8032 §7.1) ────────────────────────────────────

void test_ed25519_rfc8032_vectors() {
    struct Case {
        const char* pub;
        const char* msg;
        const char* sig;
    } cases[] = {
        {"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
         "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"},
        {"3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
         "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"},
        {"fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
         "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
         "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"},
    };
    for (const Case& c : cases) {
        std::vector<uint8_t> pub = unhex(c.pub), msg = unhex(c.msg), sig = unhex(c.sig);
        TEST_ASSERT_EQUAL(0, crypto_ed25519_check(sig.data(), pub.data(),
                                                  msg.data(), msg.size()));
        sig[10] ^= 0x01;
        TEST_ASSERT_EQUAL(-1, crypto_ed25519_check(sig.data(), pub.data(),
                                                   msg.data(), msg.size()));
    }
}

// S + L (L = the group order, little-endian): the same curve equation, but a
// non-canonical S. RFC 8032 §5.1.7 requires refusing S >= L, and the Pi's
// verifier (Python cryptography / OpenSSL) does, so node and Pi must agree.
static void add_group_order(uint8_t s[32]) {
    static const uint8_t kL[32] = {
        0xed, 0xd3, 0xf5, 0x5c, 0x1a, 0x63, 0x12, 0x58, 0xd6, 0x9c, 0xf7,
        0xa2, 0xde, 0xf9, 0xde, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10};
    unsigned carry = 0;
    for (int i = 0; i < 32; ++i) {
        const unsigned v = (unsigned)s[i] + kL[i] + carry;
        s[i] = (uint8_t)v;
        carry = v >> 8;
    }
}

void test_ed25519_refuses_a_malleated_signature() {
    // RFC 8032 test 1 with S + L, as Python computes it (S + L < 2^256).
    std::vector<uint8_t> pub = unhex(
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a");
    std::vector<uint8_t> sig = unhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b");
    add_group_order(sig.data() + 32);
    TEST_ASSERT_EQUAL_STRING(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "4c8c7872aa064e049dbb3013fbf29380d25bf5f0595bbe24655141438e7a101b",
        hexs(sig.data(), sig.size()).c_str());
    TEST_ASSERT_EQUAL(-1, crypto_ed25519_check(sig.data(), pub.data(), nullptr, 0));

    // And a genuine release manifest with its S malleated the same way.
    JsonObject c = g_vectors["valid"][0];
    std::vector<uint8_t> bytes = unhex(c["manifest_hex"].as<const char*>());
    std::vector<uint8_t> msig = unhex(c["signature_hex"].as<const char*>());
    TEST_ASSERT_EQUAL(64, msig.size());
    OtaManifest m;
    ASSERT_STATUS(ManifestStatus::Ok, sp::verify_manifest(bytes.data(), bytes.size(),
                                                          msig.data(), g_pub, &m));
    add_group_order(msig.data() + 32);
    ASSERT_STATUS(ManifestStatus::BadSignature,
                  sp::verify_manifest(bytes.data(), bytes.size(), msig.data(),
                                      g_pub, &m));
}

// ── the shared vectors ─────────────────────────────────────────

static ManifestStatus verify_case(JsonObject c, OtaManifest* m) {
    std::vector<uint8_t> bytes = unhex(c["manifest_hex"].as<const char*>());
    std::vector<uint8_t> sig = unhex(c["signature_hex"].as<const char*>());
    if (sig.size() != 64) return ManifestStatus::BadSignature;
    return sp::verify_manifest(bytes.data(), bytes.size(), sig.data(), g_pub, m);
}

void test_valid_vectors_verify() {
    JsonArray valid = g_vectors["valid"].as<JsonArray>();
    TEST_ASSERT_TRUE(valid.size() >= 3);
    for (JsonObject c : valid) {
        OtaManifest m;
        ASSERT_STATUS(ManifestStatus::Ok, verify_case(c, &m));
        JsonObject f = c["fields"];
        TEST_ASSERT_EQUAL_STRING(f["artifact"].as<const char*>(), m.artifact);
        TEST_ASSERT_EQUAL_STRING(f["channel"].as<const char*>(), m.channel);
        TEST_ASSERT_EQUAL_STRING(f["version"].as<const char*>(), m.version);
        TEST_ASSERT_EQUAL_STRING(f["sha256"].as<const char*>(), m.sha256);
        TEST_ASSERT_EQUAL_STRING(f["published_at"].as<const char*>(), m.published_at);
        TEST_ASSERT_EQUAL((uint64_t)f["size"].as<uint64_t>(), m.size);
        // The bundle text hashes to the signed sha256 (the gate's check).
        const char* bundle = c["bundle"].as<const char*>();
        uint8_t d[32];
        sp::sha256_host((const uint8_t*)bundle, strlen(bundle), d);
        TEST_ASSERT_EQUAL_STRING(m.sha256, hexs(d, 32).c_str());
        TEST_ASSERT_EQUAL(strlen(bundle), m.size);
    }
}

void test_tampered_vectors_fail_the_signature() {
    JsonArray tampered = g_vectors["tampered"].as<JsonArray>();
    TEST_ASSERT_TRUE(tampered.size() >= 8);
    for (JsonObject c : tampered) {
        OtaManifest m;
        TEST_ASSERT_EQUAL_MESSAGE((int)ManifestStatus::BadSignature,
                                  (int)verify_case(c, &m),
                                  c["id"].as<const char*>());
    }
}

void test_signed_but_invalid_vectors_are_refused() {
    JsonArray bad = g_vectors["signed_but_invalid"].as<JsonArray>();
    TEST_ASSERT_TRUE(bad.size() >= 15);
    for (JsonObject c : bad) {
        OtaManifest m;
        const ManifestStatus s = verify_case(c, &m);
        // The signature is genuine; the bytes are not a v1 manifest.
        TEST_ASSERT_TRUE_MESSAGE(
            s == ManifestStatus::NotCanonical || s == ManifestStatus::BadField,
            c["id"].as<const char*>());
    }
}

// ── node-signed manifests (test key) ───────────────────────────

static OtaManifest node_manifest(const char* artifact = "node_esp32",
                                 const char* version = "5.1.0") {
    OtaManifest m;
    memset(&m, 0, sizeof(m));
    snprintf(m.artifact, sizeof(m.artifact), "%s", artifact);
    snprintf(m.channel, sizeof(m.channel), "stable");
    snprintf(m.published_at, sizeof(m.published_at), "2026-10-05T12:00:00Z");
    snprintf(m.sha256, sizeof(m.sha256), "%s",
             "f60daaa4795f6c3bf50bfb9ec47a8978cf35216fe9dc1b33bc120feea147990b");
    m.size = 1293136;
    snprintf(m.version, sizeof(m.version), "%s", version);
    return m;
}

static std::string sign_text(const std::string& text, uint8_t sig[64]) {
    crypto_ed25519_sign(sig, g_secret, (const uint8_t*)text.data(), text.size());
    return text;
}

void test_canonical_bytes_match_python() {
    // The Pi's stable vector re-encodes to exactly its signed bytes.
    JsonObject c = g_vectors["valid"][0];
    OtaManifest m;
    ASSERT_STATUS(ManifestStatus::Ok, verify_case(c, &m));
    char out[512];
    const size_t n = sp::manifest_canonical(m, out, sizeof(out));
    TEST_ASSERT_EQUAL_STRING(c["manifest_text"].as<const char*>(), out);
    TEST_ASSERT_EQUAL(strlen(out), n);
    TEST_ASSERT_EQUAL(0, sp::manifest_canonical(m, out, 20));  // too small
}

void test_node_manifest_round_trip() {
    OtaManifest m = node_manifest();
    char text[512];
    sp::manifest_canonical(m, text, sizeof(text));
    uint8_t sig[64];
    sign_text(text, sig);
    OtaManifest got;
    ASSERT_STATUS(ManifestStatus::Ok,
                  sp::verify_manifest((const uint8_t*)text, strlen(text), sig, g_pub, &got));
    TEST_ASSERT_EQUAL_STRING("node_esp32", got.artifact);
    TEST_ASSERT_EQUAL(1293136, got.size);
    // Too large never reaches the curve.
    std::string big(sp::kOtaManifestMaxBytes + 1, ' ');
    ASSERT_STATUS(ManifestStatus::TooLarge,
                  sp::verify_manifest((const uint8_t*)big.data(), big.size(), sig, g_pub, &got));
}

// Field grammar: sign a mutated canonical text and parse it.
static ManifestStatus signed_status(const std::string& text) {
    uint8_t sig[64];
    sign_text(text, sig);
    OtaManifest m;
    return sp::verify_manifest((const uint8_t*)text.data(), text.size(), sig, g_pub, &m);
}

static std::string with_field(const char* key, const char* raw_value) {
    OtaManifest m = node_manifest();
    char text[512];
    sp::manifest_canonical(m, text, sizeof(text));
    std::string s(text);
    std::string k = std::string("\"") + key + "\":";
    size_t at = s.find(k);
    size_t v = at + k.size();
    size_t end = s.find_first_of(",}", v);
    return s.substr(0, v) + raw_value + s.substr(end);
}

void test_field_grammar() {
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("version", "\"v5.1.0\"")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("version", "\"5.2.0-beta.1\"")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("version", "\"5.2.0.dev7\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("version", "\"5.2\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("version", "\"5.2.0-\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("version", "\"5.2.0/x\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("version", "\"V5.2.0\"")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("artifact", "\"cam_xiao_esp32s3\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("artifact", "\"_cam\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("artifact", "\"Cam\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("artifact", "\"\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("channel", "\"nightly\"")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("size", "0")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("size", "9007199254740991")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("size", "9007199254740992")));
    ASSERT_STATUS(ManifestStatus::NotCanonical, signed_status(with_field("size", "012")));
    ASSERT_STATUS(ManifestStatus::NotCanonical, signed_status(with_field("size", "-1")));
    ASSERT_STATUS(ManifestStatus::NotCanonical, signed_status(with_field("size", "1.0")));
    ASSERT_STATUS(ManifestStatus::NotCanonical, signed_status(with_field("size", "\"12\"")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("published_at", "\"2028-02-29T23:59:59Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("published_at", "\"2026-02-29T00:00:00Z\"")));
    ASSERT_STATUS(ManifestStatus::Ok, signed_status(with_field("published_at", "\"2000-02-29T00:00:00Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("published_at", "\"2100-02-29T00:00:00Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("published_at", "\"2026-10-05T24:00:00Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("published_at", "\"2026-10-05T12:00:60Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("published_at", "\"0000-01-01T00:00:00Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("published_at", "\"2026-10-05 12:00:00Z\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("sha256", "\"F60daaa4795f6c3bf50bfb9ec47a8978cf35216fe9dc1b33bc120feea147990b\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("sha256", "\"f60d\"")));
    ASSERT_STATUS(ManifestStatus::BadField, signed_status(with_field("schema", "\"sporeprint.ota.manifest.v2\"")));
    ASSERT_STATUS(ManifestStatus::NotCanonical, signed_status(with_field("version", "\"5.1.\\u0030\"")));
}

// ── policy ─────────────────────────────────────────────────────

void test_policy() {
    OtaManifest m = node_manifest("node_esp32", "5.1.0");
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Ok, (int)sp::manifest_policy(m, "node_esp32", "5.0.0", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Ok, (int)sp::manifest_policy(m, "node_esp32", "5.1.0", ""));  // re-flash
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Ok, (int)sp::manifest_policy(m, "node_esp32", "dev", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Ok, (int)sp::manifest_policy(m, "node_esp32", "5.1.0-rc.1", "5.1.0"));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::WrongArtifact, (int)sp::manifest_policy(m, "cam", "5.0.0", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::WrongArtifact, (int)sp::manifest_policy(m, "node_esp32s3", "5.0.0", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::NoArtifact, (int)sp::manifest_policy(m, "", "5.0.0", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Downgrade, (int)sp::manifest_policy(m, "node_esp32", "5.1.1", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Downgrade, (int)sp::manifest_policy(m, "node_esp32", "v6.0.0", ""));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::BelowFloor, (int)sp::manifest_policy(m, "node_esp32", "dev", "5.2.0"));
    TEST_ASSERT_EQUAL((int)ManifestPolicy::Ok, (int)sp::manifest_policy(m, "node_esp32", "dev", "garbage"));

    sp::FwVersion a, b;
    TEST_ASSERT_TRUE(sp::parse_fw_version("v10.2.33-beta", &a));
    TEST_ASSERT_EQUAL(10, a.major);
    TEST_ASSERT_EQUAL(2, a.minor);
    TEST_ASSERT_EQUAL(33, a.patch);
    TEST_ASSERT_TRUE(sp::parse_fw_version("10.10.0", &b));
    TEST_ASSERT_EQUAL(-1, sp::compare_fw_version(a, b));  // numeric, not lexical
    TEST_ASSERT_FALSE(sp::parse_fw_version("dev", &a));
    TEST_ASSERT_FALSE(sp::parse_fw_version("5.1", &a));
    TEST_ASSERT_FALSE(sp::parse_fw_version("5.1.0x", &a));
    TEST_ASSERT_FALSE(sp::parse_fw_version("1234567890.0.0", &a));
    TEST_ASSERT_FALSE(sp::parse_fw_version(nullptr, &a));
}

// ── gate ───────────────────────────────────────────────────────

static std::string image_bytes(size_t n) {
    std::string s(n, '\0');
    for (size_t i = 0; i < n; ++i) s[i] = (char)(i * 31 + 7);
    return s;
}

static OtaManifest manifest_for(const std::string& image) {
    OtaManifest m = node_manifest();
    uint8_t d[32];
    sp::sha256_host((const uint8_t*)image.data(), image.size(), d);
    snprintf(m.sha256, sizeof(m.sha256), "%s", hexs(d, 32).c_str());
    m.size = image.size();
    return m;
}

void test_gate_unarmed_is_unverified_unless_required() {
    OtaGate g;
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::Unverified, (int)g.begin(0, 0, 1000, false));
    g.update((const uint8_t*)"x", 1);
    TEST_ASSERT_EQUAL((int)OtaGate::End::Unverified, (int)g.finish());
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::RefuseNoManifest, (int)g.begin(0, 0, 1000, true));
    TEST_ASSERT_EQUAL_STRING("manifest_required",
                             sp::ota_gate_begin_str(OtaGate::Begin::RefuseNoManifest));
}

void test_gate_verifies_the_streamed_image() {
    const std::string img = image_bytes(5000);
    OtaGate g;
    g.arm(manifest_for(img), 100);
    TEST_ASSERT_TRUE(g.armed(100));
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::Verified, (int)g.begin(200, 0, 5000, true));
    TEST_ASSERT_FALSE(g.armed(200));  // consumed
    for (size_t off = 0; off < img.size(); off += 1460) {
        size_t n = img.size() - off < 1460 ? img.size() - off : 1460;
        g.update((const uint8_t*)img.data() + off, n);
    }
    TEST_ASSERT_EQUAL((int)OtaGate::End::Match, (int)g.finish());
    // Finished: a second finish is not a verified update any more.
    TEST_ASSERT_EQUAL((int)OtaGate::End::Unverified, (int)g.finish());
    // And the next invitation is unverified (or refused when required).
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::RefuseNoManifest, (int)g.begin(300, 0, 5000, true));
}

void test_gate_refuses_a_different_image() {
    const std::string img = image_bytes(5000);
    std::string evil = img;
    evil[4000] ^= 0x01;
    OtaGate g;
    g.arm(manifest_for(img), 0);
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::Verified, (int)g.begin(1, 0, 5000, false));
    g.update((const uint8_t*)evil.data(), evil.size());
    TEST_ASSERT_EQUAL((int)OtaGate::End::Mismatch, (int)g.finish());

    // Short stream with the right size announced: mismatch, never a match.
    g.arm(manifest_for(img), 0);
    g.begin(1, 0, 5000, false);
    g.update((const uint8_t*)img.data(), 4999);
    TEST_ASSERT_EQUAL((int)OtaGate::End::Mismatch, (int)g.finish());

    // Wrong size or a filesystem image: refused outright, arming consumed.
    g.arm(manifest_for(img), 0);
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::RefuseSize, (int)g.begin(1, 0, 5001, false));
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::Unverified, (int)g.begin(2, 0, 5000, false));
    g.arm(manifest_for(img), 0);
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::RefuseFilesystem, (int)g.begin(1, 100, 5000, false));
}

void test_gate_arming_expires_after_five_minutes() {
    const std::string img = image_bytes(100);
    OtaGate g;
    const uint32_t t0 = 0xFFFFFF00u;  // across the millis() wrap
    g.arm(manifest_for(img), t0);
    TEST_ASSERT_TRUE(g.armed(t0 + OtaGate::kArmMs - 1));
    TEST_ASSERT_FALSE(g.armed(t0 + OtaGate::kArmMs));
    // An expired arming counts as none.
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::Unverified,
                      (int)g.begin(t0 + OtaGate::kArmMs, 0, 100, false));
    g.arm(manifest_for(img), t0);
    TEST_ASSERT_EQUAL((int)OtaGate::Begin::RefuseNoManifest,
                      (int)g.begin(t0 + OtaGate::kArmMs + 5, 0, 100, true));
    g.arm(manifest_for(img), t0);
    g.disarm();
    TEST_ASSERT_FALSE(g.armed(t0));
}

// ── base64 decode ──────────────────────────────────────────────

void test_base64_decode_strict() {
    uint8_t out[16];
    size_t n = 99;
    const char* ok[][2] = {{"", ""}, {"Zg==", "f"}, {"Zm8=", "fo"}, {"Zm9v", "foo"},
                           {"Zm9vYg==", "foob"}, {"Zm9vYmFy", "foobar"}};
    for (auto& c : ok) {
        TEST_ASSERT_TRUE(sp::base64_decode(c[0], strlen(c[0]), out, sizeof(out), &n));
        TEST_ASSERT_EQUAL(strlen(c[1]), n);
        if (n > 0) TEST_ASSERT_EQUAL_MEMORY(c[1], out, n);
    }
    const char* bad[] = {"Zg=", "Zg", "Zh==", "Zm9=", "Z===", "====", "Zg==Zg==",
                         "Zm9v!", "Zm 9", "Zm9vYmFy\n"};
    for (const char* b : bad)
        TEST_ASSERT_FALSE_MESSAGE(sp::base64_decode(b, strlen(b), out, sizeof(out), &n), b);
    // Output too small.
    TEST_ASSERT_FALSE(sp::base64_decode("Zm9vYmFy", 8, out, 5, &n));
    // Round trip through the encoder, every length 0..40.
    uint8_t raw[40];
    for (size_t i = 0; i < sizeof(raw); ++i) raw[i] = (uint8_t)(255 - i * 13);
    for (size_t len = 0; len <= sizeof(raw); ++len) {
        char enc[64];
        sp::base64_encode(raw, len, enc, sizeof(enc));
        uint8_t dec[40];
        TEST_ASSERT_TRUE(sp::base64_decode(enc, strlen(enc), dec, sizeof(dec), &n));
        TEST_ASSERT_EQUAL(len, n);
        if (len > 0) TEST_ASSERT_EQUAL_MEMORY(raw, dec, len);
    }
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_fixture_loads_and_seed_derives_the_pinned_key);
    RUN_TEST(test_ed25519_rfc8032_vectors);
    RUN_TEST(test_ed25519_refuses_a_malleated_signature);
    RUN_TEST(test_valid_vectors_verify);
    RUN_TEST(test_tampered_vectors_fail_the_signature);
    RUN_TEST(test_signed_but_invalid_vectors_are_refused);
    RUN_TEST(test_canonical_bytes_match_python);
    RUN_TEST(test_node_manifest_round_trip);
    RUN_TEST(test_field_grammar);
    RUN_TEST(test_policy);
    RUN_TEST(test_gate_unarmed_is_unverified_unless_required);
    RUN_TEST(test_gate_verifies_the_streamed_image);
    RUN_TEST(test_gate_refuses_a_different_image);
    RUN_TEST(test_gate_arming_expires_after_five_minutes);
    RUN_TEST(test_base64_decode_strict);
    return UNITY_END();
}
