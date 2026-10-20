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

// ── call-site signing policy (verify_command in node + cam) ────
// Pins the security hinge of the HMAC migration: fail-OPEN with no key,
// clock-gate, strict verify with a key. A regression flipping the empty-key
// early-return (accept-everything for keyed nodes, or reject for
// unprovisioned ones) must fail here — it can't in the two Arduino main.cpp
// copies, which are host-untestable.
void test_command_auth_unprovisioned_key_fails_open() {
    // No key ⇒ AcceptUnsigned regardless of payload or clock (the migration
    // posture). Even total garbage and an unsynced clock accept.
    sp::CmdAuthResult r = sp::command_auth_decision(
        "not even json", 13, "", 0, 0 /*unsynced*/, sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::AcceptUnsigned,
                          (int)r.decision);
    // nullptr key is also treated as unprovisioned.
    r = sp::command_auth_decision("{}", 2, nullptr, 0, 1700000000ULL,
                                  sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::AcceptUnsigned,
                          (int)r.decision);
}

void test_command_auth_provisioned_key_accepts_valid_frame() {
    auto vectors = load_vectors();
    const Vector& v = vectors[0];
    std::string wire = wire_with_signature(v);
    uint64_t now = (uint64_t)v.ts + 5;  // in window AND > kMinValidEpoch
    TEST_ASSERT_TRUE(now >= sp::kMinValidEpoch);
    sp::CmdAuthResult r = sp::command_auth_decision(
        wire.data(), wire.size(), kKey, strlen(kKey), now, sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok, (int)r.status);
}

void test_command_auth_provisioned_key_rejects_bad_signature() {
    auto vectors = load_vectors();
    const Vector& v = vectors[0];
    std::string wire = wire_with_signature(v);
    uint64_t now = (uint64_t)v.ts;
    // A DIFFERENT key ⇒ the golden signature no longer matches ⇒ Reject. Using
    // a distinct key (not a tampered byte) avoids any canonical-id masking.
    sp::CmdAuthResult r = sp::command_auth_decision(
        wire.data(), wire.size(), "some-other-key", 14, now,
        sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Mismatch, (int)r.status);
}

void test_command_auth_rejects_unsynced_clock_before_verifying() {
    auto vectors = load_vectors();
    const Vector& v = vectors[0];
    std::string wire = wire_with_signature(v);
    // Key IS provisioned and the frame is perfectly valid, but the clock has
    // not synced (now < 2020) ⇒ refuse without even reaching verify_frame.
    sp::CmdAuthResult r = sp::command_auth_decision(
        wire.data(), wire.size(), kKey, strlen(kKey),
        sp::kMinValidEpoch - 1, sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::RejectClockUnsynced,
                          (int)r.decision);
    // A now of 0 (boot, no NTP) is the real-world case.
    r = sp::command_auth_decision(wire.data(), wire.size(), kKey, strlen(kKey),
                                  0, sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::RejectClockUnsynced,
                          (int)r.decision);
    // At exactly kMinValidEpoch the clock gate opens (boundary is <, not <=):
    // the golden ts (~1.7e9) is now far outside the window ⇒ falls through to a
    // verify-level Reject, NOT a clock reject.
    r = sp::command_auth_decision(wire.data(), wire.size(), kKey, strlen(kKey),
                                  sp::kMinValidEpoch, sp::hmac_sha256_host);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::StaleTimestamp, (int)r.status);
}

// ── destination binding + replay guard ─────────────────────────
// The MAC covers only the payload, so a captured signed frame could be
// re-published verbatim to another channel/node, or replayed repeatedly,
// inside the ±30 s window. Two backward-compatible defenses:
//   * a signer MAY add "topic": "<full topic>" to the signed body; when
//     present the node rejects it anywhere but that topic (legacy frames
//     without the member still verify — no signer change is required)
//   * every accepted (topic, MAC) is remembered for the replay window and a
//     second delivery is rejected

static const char* kExhaust = "sporeprint/relay-01/cmd/exhaust";
static const uint64_t kNow = 1700000000ULL;

// Sign an already-canonical body (sorted keys, compact) with `key`.
static std::string sign_body_with(const char* key,
                                  const std::string& canonical) {
    uint8_t mac[32];
    sp::hmac_sha256_host((const uint8_t*)key, strlen(key),
                         (const uint8_t*)canonical.data(), canonical.size(),
                         mac);
    char hex[65];
    sp::to_hex_lower(mac, 32, hex);
    std::string wire = "{\"signature\":\"";
    wire += hex;
    wire += "\",";
    wire.append(canonical.begin() + 1, canonical.end());
    return wire;
}

// ...with kKey.
static std::string sign_body(const std::string& canonical) {
    return sign_body_with(kKey, canonical);
}

static sp::VerifyStatus verify_at(const std::string& wire, const char* topic,
                                  sp::ReplayGuard* guard,
                                  uint64_t now = kNow) {
    return sp::verify_frame(wire.data(), wire.size(), kKey, strlen(kKey), now,
                            sp::hmac_sha256_host, topic, guard);
}

void test_topic_member_binds_frame_to_its_destination() {
    std::string wire = sign_body(
        "{\"duration_sec\":600,\"pwm\":255,\"state\":\"on\","
        "\"topic\":\"sporeprint/relay-01/cmd/exhaust\",\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(wire, kExhaust, nullptr));
    // Same signed bytes re-published to the misting pump channel…
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::TopicMismatch,
        (int)verify_at(wire, "sporeprint/relay-01/cmd/aux", nullptr));
    // …or to a sibling node.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::TopicMismatch,
        (int)verify_at(wire, "sporeprint/relay-02/cmd/exhaust", nullptr));
    // A prefix of the bound topic is not a match either.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::TopicMismatch,
        (int)verify_at(wire, "sporeprint/relay-01/cmd/exhaus", nullptr));
    TEST_ASSERT_NOT_NULL(sp::verify_status_str(sp::VerifyStatus::TopicMismatch));
}

void test_non_string_topic_member_is_a_mismatch() {
    std::string wire = sign_body(
        "{\"state\":\"on\",\"topic\":null,\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::TopicMismatch,
                          (int)verify_at(wire, kExhaust, nullptr));
}

void test_frames_without_topic_member_still_verify() {
    // Today's Pi signer (server/app/mqtt.py::_sign_cmd_payload) signs
    // {state,pwm,duration_sec,ts} only — it must keep working unchanged.
    std::string wire = sign_body(
        "{\"duration_sec\":600,\"pwm\":255,\"state\":\"on\",\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(wire, kExhaust, nullptr));
    // And the golden vectors (no topic member) still verify with a topic.
    for (const Vector& v : load_vectors()) {
        std::string w = wire_with_signature(v);
        TEST_ASSERT_EQUAL_INT(
            (int)sp::VerifyStatus::Ok,
            (int)verify_at(w, kExhaust, nullptr, (uint64_t)v.ts + 1));
    }
}

void test_no_topic_argument_skips_binding() {
    // Callers that don't pass the received topic (the cam image) keep the
    // pre-binding behavior.
    std::string wire = sign_body(
        "{\"state\":\"on\",\"topic\":\"sporeprint/other/cmd/x\","
        "\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(wire, nullptr, nullptr));
}

void test_replay_guard_rejects_second_delivery() {
    sp::ReplayGuard guard;
    std::string wire = sign_body(
        "{\"duration_sec\":600,\"pwm\":255,\"state\":\"on\",\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(wire, kExhaust, &guard));
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed,
                          (int)verify_at(wire, kExhaust, &guard, kNow + 5));
    TEST_ASSERT_NOT_NULL(sp::verify_status_str(sp::VerifyStatus::Replayed));

    // Uppercase-hex re-encoding of the same signature is the same frame.
    std::string upper = wire;
    size_t at = upper.find("\"signature\":\"") + 13;
    for (size_t i = at; i < at + 64; ++i)
        upper[i] = (char)toupper((unsigned char)upper[i]);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed,
                          (int)verify_at(upper, kExhaust, &guard, kNow + 6));
}

void test_replay_guard_allows_identical_legacy_body_on_another_channel() {
    // Legacy (unbound) frames: the Pi can legitimately send the identical
    // body to two channels in the same second (e.g. fae + exhaust on) — the
    // second channel's command must not be mistaken for a replay.
    sp::ReplayGuard guard;
    std::string wire = sign_body(
        "{\"pwm\":255,\"state\":\"on\",\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(wire, kExhaust, &guard));
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::Ok,
        (int)verify_at(wire, "sporeprint/relay-01/cmd/fae", &guard));
    // …but each channel still only once.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::Replayed,
        (int)verify_at(wire, "sporeprint/relay-01/cmd/fae", &guard));
}

void test_rejected_frames_are_not_remembered() {
    sp::ReplayGuard guard;
    std::string wire = sign_body(
        "{\"state\":\"on\",\"topic\":\"sporeprint/relay-01/cmd/exhaust\","
        "\"ts\":1700000000}");
    // Misdirected copy arrives first: rejected, and must not poison the
    // cache for the genuine delivery.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::TopicMismatch,
        (int)verify_at(wire, "sporeprint/relay-01/cmd/aux", &guard));
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(wire, kExhaust, &guard));
    // Stale frames are rejected before the cache is consulted.
    TEST_ASSERT_EQUAL_INT(
        (int)sp::VerifyStatus::StaleTimestamp,
        (int)verify_at(wire, kExhaust, &guard, kNow + 31));
}

void test_replay_guard_expiry_and_capacity() {
    sp::ReplayGuard guard;
    uint8_t mac[32] = {0};
    const uint32_t topic = sp::topic_hash(kExhaust);
    guard.remember(topic, mac, kNow, (double)kNow);
    TEST_ASSERT_TRUE(guard.seen(topic, mac, kNow));
    TEST_ASSERT_TRUE(guard.seen(topic, mac, kNow + 2 * sp::kReplayWindowSeconds));
    // Past any ts that could still pass the ±30 s window: forgotten.
    TEST_ASSERT_FALSE(
        guard.seen(topic, mac, kNow + 2 * sp::kReplayWindowSeconds + 1));
    TEST_ASSERT_FALSE(guard.seen(topic + 1, mac, kNow));
    // Expired slots are reused without raising the floor.
    for (size_t i = 0; i < sp::ReplayGuard::kSlots + 1; ++i) {
        uint8_t m[32] = {0};
        m[0] = (uint8_t)i;
        guard.remember(topic, m, kNow + 100 + i * 61, (double)(kNow + 100 + i * 61));
    }
    TEST_ASSERT_FALSE(guard.below_floor((double)kNow));

    // Full of live entries: the oldest frame ts is evicted and the floor
    // rises to it.
    sp::ReplayGuard ring;
    for (size_t i = 0; i < sp::ReplayGuard::kSlots + 1; ++i) {
        uint8_t m[32] = {0};
        m[0] = (uint8_t)i;
        m[1] = (uint8_t)(i >> 8);
        ring.remember(topic, m, kNow, (double)(kNow - 20 + i / 2));
    }
    uint8_t first[32] = {0};
    TEST_ASSERT_FALSE(ring.seen(topic, first, kNow));
    TEST_ASSERT_TRUE(ring.below_floor((double)(kNow - 20)));
    TEST_ASSERT_FALSE(ring.below_floor((double)(kNow - 19)));
    uint8_t second[32] = {0};
    second[0] = 1;
    TEST_ASSERT_TRUE(ring.seen(topic, second, kNow));
    TEST_ASSERT_TRUE(sp::topic_hash("a") != sp::topic_hash("b"));
}

void test_replay_guard_eviction_never_reopens_a_replay() {
    // More accepted frames inside one window than the table holds: the
    // frame evicted to make room must stay refused, and so must every other
    // frame of that window (each accepted replay used to evict the next
    // oldest entry, so all of them could be cycled through).
    sp::ReplayGuard guard;
    const size_t n = sp::ReplayGuard::kSlots + 1;
    std::vector<std::string> frames;
    for (size_t i = 0; i < n; ++i) {
        // Unbound, distinct bodies signed in the same second (the Pi's
        // fallback when a bound frame would be too large).
        std::string body = "{\"pwm\":" + std::to_string(i) +
                           ",\"state\":\"on\",\"ts\":1700000000}";
        frames.push_back(sign_body(body));
        TEST_ASSERT_EQUAL_INT_MESSAGE((int)sp::VerifyStatus::Ok,
                                      (int)verify_at(frames[i], kExhaust, &guard),
                                      body.c_str());
    }
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed,
                          (int)verify_at(frames[0], kExhaust, &guard, kNow + 1));
    for (int round = 0; round < 3; ++round) {
        for (size_t i = 0; i < n; ++i) {
            TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed,
                                  (int)verify_at(frames[i], kExhaust, &guard,
                                                 kNow + 2));
        }
    }
    // The cost, pinned: a new frame signed in that same full second is
    // refused too (a burst of more than kSlots frames in one second)...
    std::string late = sign_body(
        "{\"pwm\":99,\"state\":\"on\",\"ts\":1700000000}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed,
                          (int)verify_at(late, kExhaust, &guard, kNow + 2));
    // ...while the next second's frames go through.
    std::string next = sign_body(
        "{\"pwm\":99,\"state\":\"on\",\"ts\":1700000001}");
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok,
                          (int)verify_at(next, kExhaust, &guard, kNow + 2));
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed,
                          (int)verify_at(next, kExhaust, &guard, kNow + 3));
}

void test_command_auth_threads_topic_and_replay_guard() {
    sp::ReplayGuard guard;
    std::string wire = sign_body(
        "{\"state\":\"off\",\"topic\":\"sporeprint/relay-01/cmd/exhaust\","
        "\"ts\":1700000000}");
    sp::CmdAuthResult r = sp::command_auth_decision(
        wire.data(), wire.size(), kKey, strlen(kKey), kNow,
        sp::hmac_sha256_host, kExhaust, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    r = sp::command_auth_decision(wire.data(), wire.size(), kKey, strlen(kKey),
                                  kNow, sp::hmac_sha256_host, kExhaust, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed, (int)r.status);
    r = sp::command_auth_decision(wire.data(), wire.size(), kKey, strlen(kKey),
                                  kNow, sp::hmac_sha256_host,
                                  "sporeprint/relay-01/cmd/aux", &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::TopicMismatch, (int)r.status);
    // Unprovisioned key: still the fail-open migration posture.
    r = sp::command_auth_decision(wire.data(), wire.size(), "", 0, kNow,
                                  sp::hmac_sha256_host, kExhaust, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::AcceptUnsigned,
                          (int)r.decision);
}

// ── command-signing key rotation ───────────────────────────────
// The setup portal keeps the key a new one replaces (NVS hmac_key_prev). A
// frame the current key does not verify is tried with it, through the same
// window, binding and replay checks, until a frame verifies with the
// current key: that one retires the old key, in memory and in NVS. A node
// that held one key used to reject every command from the moment the Pi
// signed with a new key until the node itself was re-keyed.

static const char* kNewKey = "golden-file-signing-key-v2";

static sp::CmdAuthResult auth_with(const std::string& wire,
                                   const std::string& key,
                                   const std::string& prev,
                                   sp::ReplayGuard* guard,
                                   uint64_t now = kNow,
                                   const char* topic = kExhaust) {
    return sp::command_auth_decision(wire.data(), wire.size(), key.data(),
                                     key.size(), now, sp::hmac_sha256_host,
                                     topic, guard, prev.data(), prev.size());
}

// The exhaust command the Pi signs with `key` at `ts` (topic-bound).
static std::string exhaust_cmd(const char* key, uint64_t ts,
                               const char* state = "on") {
    return sign_body_with(
        key, std::string("{\"state\":\"") + state +
                 "\",\"topic\":\"sporeprint/relay-01/cmd/exhaust\",\"ts\":" +
                 std::to_string(ts) + "}");
}

void test_rotation_accepts_the_old_key_until_the_new_one_verifies() {
    sp::MemKvStore kv;
    sp::ReplayGuard guard;
    // The portal stored kNewKey over kKey: kKey is kept as the previous key.
    const std::string key = kNewKey;
    std::string prev = sp::prev_key_after_rekey(kKey, "", kNewKey);
    TEST_ASSERT_EQUAL_STRING(kKey, prev.c_str());
    kv.set_string(sp::kHmacPrevKeyNvsKey, prev);

    // The Pi still signs with the old key: accepted (said so), and the old
    // key stays for the next one.
    sp::CmdAuthResult r = auth_with(exhaust_cmd(kKey, kNow), key, prev, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Ok, (int)r.status);
    TEST_ASSERT_TRUE(r.with_prev_key);
    TEST_ASSERT_FALSE(sp::retire_prev_key(r, prev, kv));
    TEST_ASSERT_EQUAL_STRING(kKey, prev.c_str());
    TEST_ASSERT_EQUAL_STRING(kKey,
                             kv.get_string(sp::kHmacPrevKeyNvsKey, "").c_str());
    r = auth_with(exhaust_cmd(kKey, kNow + 1, "off"), key, prev, &guard,
                  kNow + 1);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    TEST_ASSERT_TRUE(r.with_prev_key);
    TEST_ASSERT_FALSE(sp::retire_prev_key(r, prev, kv));

    // The Pi switched keys: the first frame the new key verifies is accepted
    // and retires the old key, in memory and in NVS.
    r = auth_with(exhaust_cmd(kNewKey, kNow + 2), key, prev, &guard, kNow + 2);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    TEST_ASSERT_FALSE(r.with_prev_key);
    TEST_ASSERT_TRUE(sp::retire_prev_key(r, prev, kv));
    TEST_ASSERT_TRUE(prev.empty());
    TEST_ASSERT_EQUAL_STRING(
        "", kv.get_string(sp::kHmacPrevKeyNvsKey, "unset").c_str());

    // From then on a frame the old key signed is refused, however fresh.
    r = auth_with(exhaust_cmd(kKey, kNow + 3, "off"), key, prev, &guard,
                  kNow + 3);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Mismatch, (int)r.status);
    TEST_ASSERT_FALSE(sp::retire_prev_key(r, prev, kv));
    // The new key keeps working, with nothing left to retire.
    r = auth_with(exhaust_cmd(kNewKey, kNow + 4, "off"), key, prev, &guard,
                  kNow + 4);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    TEST_ASSERT_FALSE(r.with_prev_key);
    TEST_ASSERT_FALSE(sp::retire_prev_key(r, prev, kv));
}

void test_rotation_keeps_every_check_for_the_old_key() {
    sp::ReplayGuard guard;
    const std::string key = kNewKey;
    const std::string prev = kKey;
    const std::string old = exhaust_cmd(kKey, kNow);

    // Never an unsigned frame, rotation or not...
    const std::string bare = "{\"state\":\"on\",\"ts\":1700000000}";
    sp::CmdAuthResult r = auth_with(bare, key, prev, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::NoSignature, (int)r.status);
    // ...nor one that neither key signed.
    r = auth_with(exhaust_cmd("some-other-key", kNow), key, prev, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Mismatch, (int)r.status);
    // The old key gets the same ±30 s window...
    r = auth_with(old, key, prev, &guard, kNow + 31);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::StaleTimestamp, (int)r.status);
    // ...the same destination binding...
    r = auth_with(old, key, prev, &guard, kNow, "sporeprint/relay-01/cmd/aux");
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::TopicMismatch, (int)r.status);
    // ...the same replay guard...
    r = auth_with(old, key, prev, &guard);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Accept, (int)r.decision);
    TEST_ASSERT_TRUE(r.with_prev_key);
    r = auth_with(old, key, prev, &guard, kNow + 5);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::Replayed, (int)r.status);
    // ...and the same clock gate.
    r = auth_with(exhaust_cmd(kKey, kNow + 6, "off"), key, prev, &guard,
                  sp::kMinValidEpoch - 1);
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::RejectClockUnsynced,
                          (int)r.decision);

    // A new-key frame that fails a check retires nothing.
    sp::MemKvStore kv;
    std::string held = prev;
    kv.set_string(sp::kHmacPrevKeyNvsKey, held);
    r = auth_with(exhaust_cmd(kNewKey, kNow + 7), key, held, &guard, kNow + 7,
                  "sporeprint/relay-01/cmd/aux");
    TEST_ASSERT_EQUAL_INT((int)sp::CmdAuthDecision::Reject, (int)r.decision);
    TEST_ASSERT_EQUAL_INT((int)sp::VerifyStatus::TopicMismatch, (int)r.status);
    TEST_ASSERT_FALSE(sp::retire_prev_key(r, held, kv));
    TEST_ASSERT_EQUAL_STRING(kKey, held.c_str());
    TEST_ASSERT_EQUAL_STRING(kKey,
                             kv.get_string(sp::kHmacPrevKeyNvsKey, "").c_str());
}

void test_portal_rekey_keeps_the_replaced_key() {
    // A first key: no previous key, so a keyed node never accepts unsigned.
    TEST_ASSERT_EQUAL_STRING("", sp::prev_key_after_rekey("", "", "k1").c_str());
    // A blank field, or the key it already holds, changes nothing.
    TEST_ASSERT_EQUAL_STRING("", sp::prev_key_after_rekey("k1", "", "").c_str());
    TEST_ASSERT_EQUAL_STRING("", sp::prev_key_after_rekey("k1", "", "k1").c_str());
    TEST_ASSERT_EQUAL_STRING("k1",
                             sp::prev_key_after_rekey("k2", "k1", "").c_str());
    TEST_ASSERT_EQUAL_STRING("k1",
                             sp::prev_key_after_rekey("k2", "k1", "k2").c_str());
    // A new key keeps the key it replaces.
    TEST_ASSERT_EQUAL_STRING("k1",
                             sp::prev_key_after_rekey("k1", "", "k2").c_str());
    // One previous key at most: re-keying again before the new key verified
    // a frame keeps the key that save replaced, and going back to the old
    // key keeps the newer one meanwhile.
    TEST_ASSERT_EQUAL_STRING("k2",
                             sp::prev_key_after_rekey("k2", "k1", "k3").c_str());
    TEST_ASSERT_EQUAL_STRING("k2",
                             sp::prev_key_after_rekey("k2", "k1", "k1").c_str());
    // NVS key names are at most 15 characters.
    TEST_ASSERT_TRUE(strlen(sp::kHmacPrevKeyNvsKey) <= 15);
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
    RUN_TEST(test_command_auth_unprovisioned_key_fails_open);
    RUN_TEST(test_command_auth_provisioned_key_accepts_valid_frame);
    RUN_TEST(test_command_auth_provisioned_key_rejects_bad_signature);
    RUN_TEST(test_command_auth_rejects_unsynced_clock_before_verifying);
    RUN_TEST(test_topic_member_binds_frame_to_its_destination);
    RUN_TEST(test_non_string_topic_member_is_a_mismatch);
    RUN_TEST(test_frames_without_topic_member_still_verify);
    RUN_TEST(test_no_topic_argument_skips_binding);
    RUN_TEST(test_replay_guard_rejects_second_delivery);
    RUN_TEST(test_replay_guard_allows_identical_legacy_body_on_another_channel);
    RUN_TEST(test_rejected_frames_are_not_remembered);
    RUN_TEST(test_replay_guard_expiry_and_capacity);
    RUN_TEST(test_replay_guard_eviction_never_reopens_a_replay);
    RUN_TEST(test_command_auth_threads_topic_and_replay_guard);
    RUN_TEST(test_rotation_accepts_the_old_key_until_the_new_one_verifies);
    RUN_TEST(test_rotation_keeps_every_check_for_the_old_key);
    RUN_TEST(test_portal_rekey_keeps_the_replaced_key);
    return UNITY_END();
}
