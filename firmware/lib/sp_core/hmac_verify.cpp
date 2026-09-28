#include "hmac_verify.h"

#include <stdlib.h>
#include <string.h>

#include <string>

#include "canonical_json.h"

namespace sp {

const char* verify_status_str(VerifyStatus s) {
    switch (s) {
        case VerifyStatus::Ok:              return "ok";
        case VerifyStatus::NoKey:           return "no signing key configured";
        case VerifyStatus::BadFrame:        return "unparseable frame";
        case VerifyStatus::NoSignature:     return "missing signature field";
        case VerifyStatus::BadSignatureLen: return "signature length != 64 hex chars";
        case VerifyStatus::NoTimestamp:     return "missing or non-numeric ts";
        case VerifyStatus::StaleTimestamp:  return "ts outside replay window";
        case VerifyStatus::Mismatch:        return "signature mismatch";
        case VerifyStatus::TopicMismatch:   return "signed topic does not match";
        case VerifyStatus::Replayed:        return "replayed frame";
    }
    return "unknown";
}

bool const_time_eq(const uint8_t* a, const uint8_t* b, size_t len) {
    uint8_t diff = 0;
    for (size_t i = 0; i < len; ++i) diff |= (uint8_t)(a[i] ^ b[i]);
    return diff == 0;
}

void to_hex_lower(const uint8_t* bytes, size_t len, char* out) {
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < len; ++i) {
        out[2 * i]     = hex[(bytes[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[bytes[i] & 0xF];
    }
    out[2 * len] = '\0';
}

uint32_t topic_hash(const char* topic) {
    uint32_t h = 2166136261u;
    if (topic == nullptr) return 0;
    for (const char* p = topic; *p; ++p) {
        h ^= (uint8_t)*p;
        h *= 16777619u;
    }
    return h;
}

bool ReplayGuard::seen(uint32_t topic, const uint8_t mac[32],
                       uint64_t now_epoch_s) const {
    for (const Entry& e : slots_) {
        if (e.used && e.topic == topic && now_epoch_s <= e.expires_s &&
            memcmp(e.mac, mac, sizeof(e.mac)) == 0)
            return true;
    }
    return false;
}

void ReplayGuard::remember(uint32_t topic, const uint8_t mac[32],
                           uint64_t now_epoch_s) {
    // Reuse a free / expired slot first; otherwise evict the oldest entry.
    Entry* slot = nullptr;
    for (Entry& e : slots_) {
        if (!e.used || now_epoch_s > e.expires_s) {
            slot = &e;
            break;
        }
        if (slot == nullptr || e.seq < slot->seq) slot = &e;
    }
    slot->used = true;
    slot->seq = next_seq_++;
    slot->topic = topic;
    slot->expires_s = now_epoch_s + kRememberSeconds;
    memcpy(slot->mac, mac, sizeof(slot->mac));
}

namespace {

// Signature + timestamp + MAC check. On Ok, `mac_out` holds the verified MAC.
VerifyStatus verify_mac(const char* payload, size_t len, const char* key,
                        size_t key_len, uint64_t now_epoch_s,
                        HmacSha256Fn hmac, uint8_t mac_out[32]) {
    if (key == nullptr || key_len == 0) return VerifyStatus::NoKey;

    // signature — must be a string member of exactly 64 hex chars.
    const char* sig_span;
    size_t sig_span_len;
    if (!find_member_span(payload, len, "signature", &sig_span, &sig_span_len))
        return VerifyStatus::NoSignature;
    if (sig_span_len < 2 || sig_span[0] != '"' || sig_span[sig_span_len - 1] != '"')
        return VerifyStatus::NoSignature;
    const char* sig_hex = sig_span + 1;
    size_t sig_hex_len = sig_span_len - 2;
    if (sig_hex_len != 64) return VerifyStatus::BadSignatureLen;
    for (size_t i = 0; i < 64; ++i) {
        char ch = sig_hex[i];
        bool ok = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') ||
                  (ch >= 'A' && ch <= 'F');
        if (!ok) return VerifyStatus::BadSignatureLen;
    }

    // ts — numeric lexeme; Pi sends int seconds, cloud vectors use floats.
    const char* ts_span;
    size_t ts_span_len;
    if (!find_member_span(payload, len, "ts", &ts_span, &ts_span_len))
        return VerifyStatus::NoTimestamp;
    if (ts_span_len == 0 ||
        !((ts_span[0] >= '0' && ts_span[0] <= '9') || ts_span[0] == '-'))
        return VerifyStatus::NoTimestamp;
    char ts_buf[32];
    if (ts_span_len >= sizeof(ts_buf)) return VerifyStatus::NoTimestamp;
    memcpy(ts_buf, ts_span, ts_span_len);
    ts_buf[ts_span_len] = '\0';
    char* endp = nullptr;
    double ts = strtod(ts_buf, &endp);
    if (endp == ts_buf) return VerifyStatus::NoTimestamp;
    double now = (double)now_epoch_s;
    double delta = now > ts ? now - ts : ts - now;
    if (delta > (double)kReplayWindowSeconds) return VerifyStatus::StaleTimestamp;

    // Canonical body = frame minus top-level signature, sorted, compact.
    std::string canonical;
    if (canonicalize(payload, len, canonical, "signature") != CanonStatus::Ok)
        return VerifyStatus::BadFrame;

    uint8_t* mac = mac_out;
    hmac((const uint8_t*)key, key_len,
         (const uint8_t*)canonical.data(), canonical.size(), mac);

    char computed[65];
    to_hex_lower(mac, 32, computed);

    // Normalize incoming hex to lowercase for the constant-time compare.
    uint8_t theirs[64];
    for (size_t i = 0; i < 64; ++i) {
        char ch = sig_hex[i];
        if (ch >= 'A' && ch <= 'F') ch = (char)(ch - 'A' + 'a');
        theirs[i] = (uint8_t)ch;
    }
    if (!const_time_eq((const uint8_t*)computed, theirs, 64))
        return VerifyStatus::Mismatch;
    return VerifyStatus::Ok;
}

// A signed "topic" member, when present, must be exactly the arrival topic.
bool topic_member_matches(const char* payload, size_t len, const char* topic) {
    const char* span;
    size_t span_len;
    if (!find_member_span(payload, len, "topic", &span, &span_len))
        return true;  // unbound (legacy) frame
    size_t tl = strlen(topic);
    return span_len == tl + 2 && span[0] == '"' && span[span_len - 1] == '"' &&
           memcmp(span + 1, topic, tl) == 0;
}

}  // namespace

VerifyStatus verify_frame(const char* payload, size_t len,
                          const char* key, size_t key_len,
                          uint64_t now_epoch_s, HmacSha256Fn hmac,
                          const char* topic, ReplayGuard* replay) {
    uint8_t mac[32];
    VerifyStatus st =
        verify_mac(payload, len, key, key_len, now_epoch_s, hmac, mac);
    if (st != VerifyStatus::Ok) return st;
    // Checked only after the MAC verifies: the member is authentic.
    if (topic != nullptr && !topic_member_matches(payload, len, topic))
        return VerifyStatus::TopicMismatch;
    if (replay != nullptr) {
        uint32_t th = topic_hash(topic);
        if (replay->seen(th, mac, now_epoch_s)) return VerifyStatus::Replayed;
        replay->remember(th, mac, now_epoch_s);
    }
    return VerifyStatus::Ok;
}

CmdAuthResult command_auth_decision(const char* payload, size_t len,
                                    const char* key, size_t key_len,
                                    uint64_t now_epoch_s, HmacSha256Fn hmac,
                                    const char* topic, ReplayGuard* replay) {
    // No provisioned key: accept unsigned (fail-open migration posture). An
    // empty std::string yields key_len 0 here.
    if (key == nullptr || key_len == 0)
        return {CmdAuthDecision::AcceptUnsigned, VerifyStatus::NoKey};
    // Key present but clock not synced — a fresh signature can't be replay-
    // gated, so refuse rather than trust an unbounded timestamp window.
    if (now_epoch_s < kMinValidEpoch)
        return {CmdAuthDecision::RejectClockUnsynced, VerifyStatus::StaleTimestamp};
    VerifyStatus st = verify_frame(payload, len, key, key_len, now_epoch_s,
                                   hmac, topic, replay);
    return {st == VerifyStatus::Ok ? CmdAuthDecision::Accept
                                   : CmdAuthDecision::Reject,
            st};
}

}  // namespace sp
