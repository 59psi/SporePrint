// espota — see espota.h. Parsing follows what arduino-esp32 2.x ArduinoOTA
// accepted from the same clients (space-separated decimal fields, the MD5
// token trimmed, the auth answer split on the single spaces), but rejects the
// garbage it silently read as zeros (a missing number used to parse as
// command 0 = flash).

#include "espota.h"

#include <string.h>

#include "hmac_verify.h"  // sp::const_time_eq, sp::to_hex_lower

namespace sp {
namespace espota {

namespace {

struct Cursor {
    const char* p;
    const char* end;

    bool done() const { return p >= end; }
    void skip_spaces() {
        while (p < end && *p == ' ') ++p;
    }
    // 1..max_digits decimal digits into *out; false when none.
    bool number(uint32_t max_digits, uint64_t* out) {
        uint64_t v = 0;
        uint32_t n = 0;
        while (p < end && *p >= '0' && *p <= '9') {
            if (++n > max_digits) return false;
            v = v * 10u + (uint64_t)(*p - '0');
            ++p;
        }
        if (n == 0) return false;
        *out = v;
        return true;
    }
    // Characters up to (not including) `stop`, a NUL or the end.
    size_t token(char stop, const char** start) {
        *start = p;
        while (p < end && *p != stop && *p != '\0') ++p;
        return (size_t)(p - *start);
    }
};

bool is_hex(const char* s, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        const char c = s[i];
        const bool digit = c >= '0' && c <= '9';
        const bool lower = c >= 'a' && c <= 'f';
        const bool upper = c >= 'A' && c <= 'F';
        if (!digit && !lower && !upper) return false;
    }
    return true;
}

bool is_trailing_space(char c) {
    return c == ' ' || c == '\r' || c == '\t';
}

}  // namespace

bool parse_invitation(const char* data, size_t len, Invitation* out) {
    if (data == nullptr || out == nullptr) return false;
    Cursor c{data, data + len};
    uint64_t cmd = 0, port = 0, size = 0;
    c.skip_spaces();
    if (!c.number(3, &cmd)) return false;
    if (cmd != (uint64_t)kCmdFlash && cmd != (uint64_t)kCmdFilesystem)
        return false;
    c.skip_spaces();
    if (!c.number(5, &port) || port == 0 || port > 65535) return false;
    c.skip_spaces();
    if (!c.number(10, &size) || size == 0 || size > 0xFFFFFFFFull) return false;
    c.skip_spaces();
    const char* md5 = nullptr;
    size_t n = c.token('\n', &md5);
    while (n > 0 && is_trailing_space(md5[n - 1])) --n;
    if (n != kHexLen || !is_hex(md5, n)) return false;

    out->cmd = (int)cmd;
    out->port = (uint16_t)port;
    out->size = (uint32_t)size;
    memcpy(out->md5, md5, kHexLen);
    out->md5[kHexLen] = '\0';
    return true;
}

AuthParse parse_auth_reply(const char* data, size_t len, AuthReply* out) {
    if (data == nullptr || out == nullptr) return AuthParse::NotAuth;
    Cursor c{data, data + len};
    uint64_t cmd = 0;
    c.skip_spaces();
    if (!c.number(3, &cmd) || cmd != (uint64_t)kCmdAuth)
        return AuthParse::NotAuth;
    if (c.done() || *c.p != ' ') return AuthParse::BadParams;
    ++c.p;
    const char* cnonce = nullptr;
    const size_t cn = c.token(' ', &cnonce);
    if (c.done() || *c.p != ' ') return AuthParse::BadParams;
    ++c.p;
    const char* response = nullptr;
    const size_t rn = c.token('\n', &response);
    if (cn != kHexLen || rn != kHexLen) return AuthParse::BadParams;

    memcpy(out->cnonce, cnonce, kHexLen);
    out->cnonce[kHexLen] = '\0';
    memcpy(out->response, response, kHexLen);
    out->response[kHexLen] = '\0';
    return AuthParse::Ok;
}

void password_digest(const char* password, char out[kHexLen + 1]) {
    md5_hex(password, password ? strlen(password) : 0, out);
}

void nonce_hex(const uint8_t random[kNonceBytes], char out[kHexLen + 1]) {
    to_hex_lower(random, kNonceBytes, out);
}

void expected_response(const char* pass_digest, const char* nonce,
                       const char* cnonce, char out[kHexLen + 1]) {
    // "<32>:<nonce>:<cnonce>" — every piece is a 32-char token on the wire,
    // but size the buffer for whatever the caller hands in.
    const size_t a = strlen(pass_digest), b = strlen(nonce),
                 c = strlen(cnonce);
    char buf[3 * kMaxDatagram];
    if (a + b + c + 2 >= sizeof(buf)) {
        out[0] = '\0';
        return;
    }
    size_t n = 0;
    memcpy(buf + n, pass_digest, a);
    n += a;
    buf[n++] = ':';
    memcpy(buf + n, nonce, b);
    n += b;
    buf[n++] = ':';
    memcpy(buf + n, cnonce, c);
    n += c;
    md5_hex(buf, n, out);
}

bool response_matches(const char* pass_digest, const char* nonce,
                      const AuthReply& reply) {
    char want[kHexLen + 1];
    expected_response(pass_digest, nonce, reply.cnonce, want);
    if (want[0] == '\0') return false;
    return const_time_eq((const uint8_t*)want, (const uint8_t*)reply.response,
                         kHexLen);
}

}  // namespace espota
}  // namespace sp
