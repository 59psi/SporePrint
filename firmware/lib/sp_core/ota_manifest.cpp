#include "ota_manifest.h"

#include <stdio.h>
#include <string.h>

#include "vendor/monocypher/monocypher-ed25519.h"

namespace sp {

namespace {

bool is_digit(char c) { return c >= '0' && c <= '9'; }
bool is_lower_hex(char c) { return is_digit(c) || (c >= 'a' && c <= 'f'); }
bool is_alnum(char c) {
    return is_digit(c) || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

// Cursor over the manifest bytes.
struct Reader {
    const char* p;
    const char* end;

    bool literal(const char* lit) {
        const size_t n = strlen(lit);
        if ((size_t)(end - p) < n || memcmp(p, lit, n) != 0) return false;
        p += n;
        return true;
    }
    // A JSON string body up to the closing quote: printable ASCII only, no
    // escapes (no grammar below allows a character that would need one).
    bool string_body(char* out, size_t cap) {
        size_t n = 0;
        while (p < end && *p != '"') {
            const char c = *p;
            if (c < 0x20 || c > 0x7E || c == '\\') return false;
            if (n + 1 >= cap) return false;
            out[n++] = c;
            ++p;
        }
        if (p >= end) return false;
        ++p;  // closing quote
        out[n] = '\0';
        return true;
    }
    // A JSON integer as Python writes one: no sign, no leading zero.
    bool integer(uint64_t* out) {
        const char* start = p;
        uint64_t v = 0;
        while (p < end && is_digit(*p)) {
            if (p - start >= 16) return false;  // 2^53 has 16 digits
            v = v * 10 + (uint64_t)(*p - '0');
            ++p;
        }
        const size_t n = (size_t)(p - start);
        if (n == 0 || (n > 1 && *start == '0')) return false;
        *out = v;
        return true;
    }
};

// ota_manifest.py _ARTIFACT_RE: [a-z0-9][a-z0-9._-]{0,63}
bool artifact_ok(const char* s) {
    const size_t n = strlen(s);
    if (n == 0 || n > kOtaArtifactMaxLen) return false;
    for (size_t i = 0; i < n; ++i) {
        const char c = s[i];
        const bool base = is_digit(c) || (c >= 'a' && c <= 'z');
        if (i == 0 ? !base : !(base || c == '.' || c == '_' || c == '-'))
            return false;
    }
    return true;
}

// ota_manifest.py VERSION_RE: v?\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.-]+)?
bool version_ok(const char* s) {
    if (strlen(s) > kOtaVersionMaxLen) return false;
    const char* p = s;
    if (*p == 'v') ++p;
    for (int part = 0; part < 3; ++part) {
        if (!is_digit(*p)) return false;
        while (is_digit(*p)) ++p;
        if (part < 2) {
            if (*p != '.') return false;
            ++p;
        }
    }
    if (*p == '\0') return true;
    if (*p != '-' && *p != '.') return false;
    ++p;
    if (*p == '\0') return false;
    for (; *p != '\0'; ++p)
        if (!(is_alnum(*p) || *p == '.' || *p == '-')) return false;
    return true;
}

bool channel_ok(const char* s) {
    return strcmp(s, "stable") == 0 || strcmp(s, "beta") == 0 ||
           strcmp(s, "dev") == 0;
}

bool sha256_ok(const char* s) {
    if (strlen(s) != 64) return false;
    for (size_t i = 0; i < 64; ++i)
        if (!is_lower_hex(s[i])) return false;
    return true;
}

bool leap(unsigned y) { return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0; }

unsigned two(const char* s) { return (unsigned)(s[0] - '0') * 10u + (unsigned)(s[1] - '0'); }

// YYYY-MM-DDTHH:MM:SSZ and a real UTC time (Python's datetime rules:
// year 1-9999, no leap second).
bool published_at_ok(const char* s) {
    if (strlen(s) != 20) return false;
    static const char kShape[] = "dddd-dd-ddTdd:dd:ddZ";
    for (size_t i = 0; i < 20; ++i) {
        if (kShape[i] == 'd' ? !is_digit(s[i]) : s[i] != kShape[i]) return false;
    }
    const unsigned year = two(s) * 100u + two(s + 2);
    const unsigned month = two(s + 5), day = two(s + 8);
    const unsigned hour = two(s + 11), minute = two(s + 14), second = two(s + 17);
    static const unsigned kDays[12] = {31, 28, 31, 30, 31, 30,
                                       31, 31, 30, 31, 30, 31};
    if (year < 1 || month < 1 || month > 12 || day < 1) return false;
    unsigned dim = kDays[month - 1];
    if (month == 2 && leap(year)) dim = 29;
    return day <= dim && hour <= 23 && minute <= 59 && second <= 59;
}

}  // namespace

const char* manifest_status_str(ManifestStatus s) {
    switch (s) {
        case ManifestStatus::Ok: return "ok";
        case ManifestStatus::TooLarge: return "manifest_too_large";
        case ManifestStatus::BadSignature: return "manifest_signature";
        case ManifestStatus::NotCanonical: return "manifest_not_canonical";
        case ManifestStatus::BadField: return "manifest_bad_field";
    }
    return "manifest_invalid";
}

const char* manifest_policy_str(ManifestPolicy p) {
    switch (p) {
        case ManifestPolicy::Ok: return "ok";
        case ManifestPolicy::NoArtifact: return "manifest_no_artifact";
        case ManifestPolicy::WrongArtifact: return "manifest_wrong_artifact";
        case ManifestPolicy::Downgrade: return "manifest_downgrade";
        case ManifestPolicy::BelowFloor: return "manifest_below_floor";
    }
    return "manifest_policy";
}

size_t manifest_canonical(const OtaManifest& m, char* out, size_t cap) {
    if (out == nullptr || cap == 0) return 0;
    const int n = snprintf(
        out, cap,
        "{\"artifact\":\"%s\",\"channel\":\"%s\",\"published_at\":\"%s\","
        "\"schema\":\"%s\",\"sha256\":\"%s\",\"size\":%llu,"
        "\"version\":\"%s\"}",
        m.artifact, m.channel, m.published_at, kOtaManifestSchema, m.sha256,
        (unsigned long long)m.size, m.version);
    if (n < 0 || (size_t)n >= cap) return 0;
    return (size_t)n;
}

ManifestStatus parse_manifest(const uint8_t* bytes, size_t len,
                              OtaManifest* out) {
    if (bytes == nullptr || out == nullptr) return ManifestStatus::NotCanonical;
    if (len > kOtaManifestMaxBytes) return ManifestStatus::TooLarge;
    OtaManifest m;
    memset(&m, 0, sizeof(m));
    char schema[32];
    Reader r{(const char*)bytes, (const char*)bytes + len};
    if (!(r.literal("{\"artifact\":\"") &&
          r.string_body(m.artifact, sizeof(m.artifact)) &&
          r.literal(",\"channel\":\"") &&
          r.string_body(m.channel, sizeof(m.channel)) &&
          r.literal(",\"published_at\":\"") &&
          r.string_body(m.published_at, sizeof(m.published_at)) &&
          r.literal(",\"schema\":\"") &&
          r.string_body(schema, sizeof(schema)) &&
          r.literal(",\"sha256\":\"") &&
          r.string_body(m.sha256, sizeof(m.sha256)) &&
          r.literal(",\"size\":") && r.integer(&m.size) &&
          r.literal(",\"version\":\"") &&
          r.string_body(m.version, sizeof(m.version)) && r.literal("}") &&
          r.p == r.end))
        return ManifestStatus::NotCanonical;

    if (strcmp(schema, kOtaManifestSchema) != 0 || !artifact_ok(m.artifact) ||
        !version_ok(m.version) || !channel_ok(m.channel) ||
        !sha256_ok(m.sha256) || m.size > kOtaMaxSize ||
        !published_at_ok(m.published_at))
        return ManifestStatus::BadField;

    // The exact-literal walk above admits only the canonical form; rebuilding
    // it and comparing keeps that true if the walk is ever loosened.
    char canon[kOtaManifestMaxBytes / 8];
    const size_t n = manifest_canonical(m, canon, sizeof(canon));
    if (n != len || memcmp(canon, bytes, len) != 0)
        return ManifestStatus::NotCanonical;
    *out = m;
    return ManifestStatus::Ok;
}

ManifestStatus verify_manifest(const uint8_t* bytes, size_t len,
                               const uint8_t sig[kOtaSignatureBytes],
                               const uint8_t pubkey[kOtaPubkeyBytes],
                               OtaManifest* out) {
    if (bytes == nullptr || sig == nullptr || pubkey == nullptr)
        return ManifestStatus::BadSignature;
    if (len > kOtaManifestMaxBytes) return ManifestStatus::TooLarge;
    if (crypto_ed25519_check(sig, pubkey, bytes, len) != 0)
        return ManifestStatus::BadSignature;
    return parse_manifest(bytes, len, out);
}

bool parse_fw_version(const char* s, FwVersion* out) {
    if (s == nullptr || out == nullptr) return false;
    const char* p = s;
    if (*p == 'v') ++p;
    uint32_t parts[3];
    for (int i = 0; i < 3; ++i) {
        if (!is_digit(*p)) return false;
        uint32_t v = 0;
        int digits = 0;
        while (is_digit(*p)) {
            if (++digits > 9) return false;
            v = v * 10u + (uint32_t)(*p - '0');
            ++p;
        }
        parts[i] = v;
        if (i < 2) {
            if (*p != '.') return false;
            ++p;
        }
    }
    // Anything after X.Y.Z must be a suffix, not more digits glued on.
    if (*p != '\0' && *p != '-' && *p != '.' && *p != '+') return false;
    out->major = parts[0];
    out->minor = parts[1];
    out->patch = parts[2];
    return true;
}

int compare_fw_version(const FwVersion& a, const FwVersion& b) {
    if (a.major != b.major) return a.major < b.major ? -1 : 1;
    if (a.minor != b.minor) return a.minor < b.minor ? -1 : 1;
    if (a.patch != b.patch) return a.patch < b.patch ? -1 : 1;
    return 0;
}

ManifestPolicy manifest_policy(const OtaManifest& m, const char* my_artifact,
                               const char* running_version,
                               const char* floor_version) {
    if (my_artifact == nullptr || my_artifact[0] == '\0')
        return ManifestPolicy::NoArtifact;
    if (strcmp(m.artifact, my_artifact) != 0)
        return ManifestPolicy::WrongArtifact;
    FwVersion want;
    if (!parse_fw_version(m.version, &want)) return ManifestPolicy::Downgrade;
    FwVersion have;
    if (parse_fw_version(running_version, &have) &&
        compare_fw_version(want, have) < 0)
        return ManifestPolicy::Downgrade;
    FwVersion floor;
    if (floor_version != nullptr && floor_version[0] != '\0' &&
        parse_fw_version(floor_version, &floor) &&
        compare_fw_version(want, floor) < 0)
        return ManifestPolicy::BelowFloor;
    return ManifestPolicy::Ok;
}

}  // namespace sp
