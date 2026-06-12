// test_core_hmac — vendored SHA-256/HMAC against standard vectors, then
// full frame verification against every golden signing vector (the same
// fixture the Python signers assert on), then every rejection path.

#include <unity.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "canonical_json.h"
#include "hmac_verify.h"
#include "sha256.h"

void setUp() {}
void tearDown() {}

static const char* kKey = "golden-file-signing-key-v1";

// ── reference vectors ──────────────────────────────────────────

void test_sha256_standard_vectors() {
    uint8_t out[32];
    char hex[65];
    sp::sha256_host((const uint8_t*)"abc", 3, out);
    sp::to_hex_lower(out, 32, hex);
    TEST_ASSERT_EQUAL_STRING(
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", hex);
    sp::sha256_host((const uint8_t*)"", 0, out);
    sp::to_hex_lower(out, 32, hex);
    TEST_ASSERT_EQUAL_STRING(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", hex);
    // 56-byte message exercises the two-block padding path.
    const char* m56 = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    sp::sha256_host((const uint8_t*)m56, strlen(m56), out);
    sp::to_hex_lower(out, 32, hex);
    TEST_ASSERT_EQUAL_STRING(
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1", hex);
}

void test_hmac_standard_vectors() {
    uint8_t out[32];
    char hex[65];
    sp::hmac_sha256_host((const uint8_t*)"key", 3,
                         (const uint8_t*)"The quick brown fox jumps over the lazy dog",
                         43, out);
    sp::to_hex_lower(out, 32, hex);
    TEST_ASSERT_EQUAL_STRING(
        "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8", hex);
    // RFC 4231 test case 2 (short key "Jefe").
    sp::hmac_sha256_host((const uint8_t*)"Jefe", 4,
                         (const uint8_t*)"what do ya want for nothing?", 28, out);
    sp::to_hex_lower(out, 32, hex);
    TEST_ASSERT_EQUAL_STRING(
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843", hex);
}

// ── golden-vector end-to-end verification ──────────────────────

static std::string g_fixture;

static bool load_fixture() {
    const char* candidates[] = {
        "test/fixtures/signing_vectors.json",
        "fixtures/signing_vectors.json",
        "../fixtures/signing_vectors.json",
    };
    for (const char* path : candidates) {
        FILE* f = fopen(path, "rb");
        if (!f) continue;
        fseek(f, 0, SEEK_END);
        long n = ftell(f);
        fseek(f, 0, SEEK_SET);
        g_fixture.resize((size_t)n);
        size_t got = fread(&g_fixture[0], 1, (size_t)n, f);
        fclose(f);
        return got == (size_t)n;
    }
    return false;
}

static std::string decode_json_string(const char* span, size_t len) {
    std::string out;
    for (size_t i = 1; i + 1 < len; ++i) {
        char ch = span[i];
        if (ch != '\\') {
            out.push_back(ch);
            continue;
        }
        ++i;
        char e = span[i];
        switch (e) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'u': {
                char hex[5] = {span[i + 1], span[i + 2], span[i + 3], span[i + 4], 0};
                i += 4;
                unsigned cp = (unsigned)strtoul(hex, nullptr, 16);
                if (cp < 0x80) out.push_back((char)cp);
                else if (cp < 0x800) {
                    out.push_back((char)(0xC0 | (cp >> 6)));
                    out.push_back((char)(0x80 | (cp & 0x3F)));
                } else {
                    out.push_back((char)(0xE0 | (cp >> 12)));
                    out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
                    out.push_back((char)(0x80 | (cp & 0x3F)));
                }
                break;
            }
            default: out.push_back(e); break;
        }
    }
    return out;
}

static std::vector<std::pair<const char*, size_t>> array_elements(
    const char* span, size_t len) {
    std::vector<std::pair<const char*, size_t>> out;
    size_t i = 0;
    while (i < len && span[i] != '[') ++i;
    ++i;
    int depth = 0;
    bool in_str = false;
    const char* start = nullptr;
    for (; i < len; ++i) {
        char ch = span[i];
        if (in_str) {
            if (ch == '\\') ++i;
            else if (ch == '"') in_str = false;
            continue;
        }
        if (ch == '"') { in_str = true; if (!start) start = span + i; continue; }
        if (ch == '{' || ch == '[') {
            if (depth == 0 && !start) start = span + i;
            ++depth;
            continue;
        }
        if (ch == '}' || ch == ']') {
            if (depth == 0 && ch == ']') break;
            --depth;
            continue;
        }
        if (depth == 0 && ch == ',') {
            if (start) out.emplace_back(start, (size_t)(span + i - start));
            start = nullptr;
        }
    }
    if (start) {
        const char* e = span + i;
        while (e > start && (e[-1] == ' ' || e[-1] == '\n' || e[-1] == '\r' ||
                             e[-1] == '\t')) --e;
        out.emplace_back(start, (size_t)(e - start));
    }
    return out;
}

struct Vector {
    std::string id, canonical, signature;
    double ts = 0;
};

static std::vector<Vector> load_vectors() {
    std::vector<Vector> out;
    TEST_ASSERT_TRUE_MESSAGE(load_fixture(), "fixture file not found");
    const char* arr;
    size_t arr_len;
    TEST_ASSERT_TRUE(sp::find_member_span(g_fixture.data(), g_fixture.size(),
                                          "vectors", &arr, &arr_len));
    for (auto& el : array_elements(arr, arr_len)) {
        Vector v;
        const char* s;
        size_t sl;
        TEST_ASSERT_TRUE(sp::find_member_span(el.first, el.second, "id", &s, &sl));
        v.id = decode_json_string(s, sl);
        TEST_ASSERT_TRUE(sp::find_member_span(el.first, el.second,
                                              "expected_canonical", &s, &sl));
        v.canonical = decode_json_string(s, sl);
        TEST_ASSERT_TRUE(sp::find_member_span(el.first, el.second,
                                              "expected_signature", &s, &sl));
        v.signature = decode_json_string(s, sl);
        // ts lives inside the canonical body.
        const char* ts_span;
        size_t ts_len;
        TEST_ASSERT_TRUE(sp::find_member_span(v.canonical.data(),
                                              v.canonical.size(), "ts", &ts_span,
                                              &ts_len));
        char buf[32];
        memcpy(buf, ts_span, ts_len);
        buf[ts_len] = '\0';
        v.ts = strtod(buf, nullptr);
        out.push_back(v);
    }
    return out;
}

static std::string wire_with_signature(const Vector& v) {
    std::string wire = "{\"signature\":\"";
    wire += v.signature;
    wire += "\",";
    wire.append(v.canonical.begin() + 1, v.canonical.end());
    return wire;
}

void test_golden_vectors_signatures() {
    for (const Vector& v : load_vectors()) {
        uint8_t mac[32];
        sp::hmac_sha256_host((const uint8_t*)kKey, strlen(kKey),
                             (const uint8_t*)v.canonical.data(),
                             v.canonical.size(), mac);
        char hex[65];
        sp::to_hex_lower(mac, 32, hex);
        char msg[96];
        snprintf(msg, sizeof(msg), "vector '%s': HMAC diverges", v.id.c_str());
        TEST_ASSERT_EQUAL_STRING_MESSAGE(v.signature.c_str(), hex, msg);
    }
}

void test_golden_vectors_verify_frame() {
    for (const Vector& v : load_vectors()) {
        std::string wire = wire_with_signature(v);
        uint64_t now = (uint64_t)v.ts + 10;  // inside the window
        sp::VerifyStatus st =
            sp::verify_frame(wire.data(), wire.size(), kKey, strlen(kKey), now,
                             sp::hmac_sha256_host);
        char msg[96];
        snprintf(msg, sizeof(msg), "vector '%s': %s", v.id.c_str(),
                 sp::verify_status_str(st));
        TEST_ASSERT_EQUAL_INT_MESSAGE((int)sp::VerifyStatus::Ok, (int)st, msg);

        // Tamper one payload byte (the channel/id value) → Mismatch.
        std::string bad = wire;
        size_t pos = bad.find("cmd-");
        if (pos == std::string::npos) pos = bad.find("\"ts\"") + 6;
        bad[pos] ^= 0x01;
        st = sp::verify_frame(bad.data(), bad.size(), kKey, strlen(kKey), now,
                              sp::hmac_sha256_host);
        TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Mismatch, (int)st);
    }
}

void test_replay_window_edges() {
    auto vectors = load_vectors();
    const Vector& v = vectors[0];
    std::string wire = wire_with_signature(v);
    uint64_t ts = (uint64_t)v.ts;
    // Exactly ±30 s passes; ±31 s rejects.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::Ok,
        (int)sp::verify_frame(wire.data(), wire.size(), kKey, strlen(kKey),
                              ts + 30, sp::hmac_sha256_host));
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::StaleTimestamp,
        (int)sp::verify_frame(wire.data(), wire.size(), kKey, strlen(kKey),
                              ts + 31, sp::hmac_sha256_host));
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::Ok,
        (int)sp::verify_frame(wire.data(), wire.size(), kKey, strlen(kKey),
                              ts - 30, sp::hmac_sha256_host));
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::StaleTimestamp,
        (int)sp::verify_frame(wire.data(), wire.size(), kKey, strlen(kKey),
                              ts - 31, sp::hmac_sha256_host));
}

void test_rejection_paths() {
    auto vectors = load_vectors();
    const Vector& v = vectors[0];
    std::string wire = wire_with_signature(v);
    uint64_t now = (uint64_t)v.ts;

    // Empty key.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::NoKey,
        (int)sp::verify_frame(wire.data(), wire.size(), "", 0, now,
                              sp::hmac_sha256_host));
    // Missing signature.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::NoSignature,
        (int)sp::verify_frame(v.canonical.data(), v.canonical.size(), kKey,
                              strlen(kKey), now, sp::hmac_sha256_host));
    // Wrong signature length.
    std::string short_sig = "{\"signature\":\"abc123\",\"ts\":1700000000}";
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::BadSignatureLen,
        (int)sp::verify_frame(short_sig.data(), short_sig.size(), kKey,
                              strlen(kKey), now, sp::hmac_sha256_host));
    // Missing ts.
    std::string no_ts =
        "{\"signature\":\"" + vectors[0].signature + "\",\"id\":\"x\"}";
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::NoTimestamp,
        (int)sp::verify_frame(no_ts.data(), no_ts.size(), kKey, strlen(kKey),
                              now, sp::hmac_sha256_host));
    // Unparseable frame (raw UTF-8) — fail closed even with a valid-shaped sig.
    std::string bad = wire;
    size_t pos = bad.find("relay-01");
    if (pos != std::string::npos) bad[pos] = (char)0xE2;
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::BadFrame,
        (int)sp::verify_frame(bad.data(), bad.size(), kKey, strlen(kKey), now,
                              sp::hmac_sha256_host));

    // Uppercase hex signature accepted (normalized before compare).
    std::string upper = wire;
    size_t sig_at = upper.find(v.signature);
    for (size_t i = sig_at; i < sig_at + 64; ++i)
        upper[i] = (char)toupper((unsigned char)upper[i]);
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::Ok,
        (int)sp::verify_frame(upper.data(), upper.size(), kKey, strlen(kKey),
                              now, sp::hmac_sha256_host));
}

void test_const_time_eq() {
    const uint8_t a[4] = {1, 2, 3, 4};
    const uint8_t b[4] = {1, 2, 3, 4};
    const uint8_t c[4] = {1, 2, 3, 5};
    TEST_ASSERT_TRUE(sp::const_time_eq(a, b, 4));
    TEST_ASSERT_FALSE(sp::const_time_eq(a, c, 4));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_sha256_standard_vectors);
    RUN_TEST(test_hmac_standard_vectors);
    RUN_TEST(test_golden_vectors_signatures);
    RUN_TEST(test_golden_vectors_verify_frame);
    RUN_TEST(test_replay_window_edges);
    RUN_TEST(test_rejection_paths);
    RUN_TEST(test_const_time_eq);
    return UNITY_END();
}
