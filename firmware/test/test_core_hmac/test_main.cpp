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

// ── destination binding + replay guard (fw-node#11) ────────────
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

// Sign an already-canonical body (sorted keys, compact) with kKey.
static std::string sign_body(const std::string& canonical) {
    uint8_t mac[32];
    sp::hmac_sha256_host((const uint8_t*)kKey, strlen(kKey),
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
    guard.remember(topic, mac, kNow);
    TEST_ASSERT_TRUE(guard.seen(topic, mac, kNow));
    TEST_ASSERT_TRUE(guard.seen(topic, mac, kNow + 2 * sp::kReplayWindowSeconds));
    // Past any ts that could still pass the ±30 s window: forgotten.
    TEST_ASSERT_FALSE(
        guard.seen(topic, mac, kNow + 2 * sp::kReplayWindowSeconds + 1));
    TEST_ASSERT_FALSE(guard.seen(topic + 1, mac, kNow));

    // Ring: the oldest entry is evicted once every slot is taken.
    sp::ReplayGuard ring;
    for (size_t i = 0; i < sp::ReplayGuard::kSlots + 1; ++i) {
        uint8_t m[32] = {0};
        m[0] = (uint8_t)i;
        m[1] = (uint8_t)(i >> 8);
        ring.remember(topic, m, kNow);
    }
    uint8_t first[32] = {0};
    TEST_ASSERT_FALSE(ring.seen(topic, first, kNow));
    uint8_t second[32] = {0};
    second[0] = 1;
    TEST_ASSERT_TRUE(ring.seen(topic, second, kNow));
    TEST_ASSERT_TRUE(sp::topic_hash("a") != sp::topic_hash("b"));
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
    RUN_TEST(test_command_auth_threads_topic_and_replay_guard);
    return UNITY_END();
}
