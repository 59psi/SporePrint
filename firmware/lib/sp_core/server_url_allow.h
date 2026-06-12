#pragma once
//
// server_url_allow — validation for the cam node's `server_url` command.
//
// A LAN actor with broker credentials must not be able to point frame
// uploads at an attacker host. Allow only:
//   * http:// or https:// scheme
//   * no userinfo, no query string, no fragment, length <= 128
//   * host ∈ { sporeprint.local, sporeprint.ai, <paired_pi_host> } OR an
//     RFC1918 IPv4 LITERAL — v1 checked `startsWith("10.")` on the raw
//     host, so "10.attacker.com" passed; v2 requires a valid dotted quad
//     before any private-range check.
//
// Native-safe; covered in test_core_channel's suite neighbor (test_cam_url).

#include <stdint.h>
#include <string.h>

namespace sp {

// Parse a strict dotted-quad IPv4 (no leading +/-, values 0-255).
// Returns true and fills octets on success.
inline bool parse_ipv4(const char* s, size_t len, uint8_t octets[4]) {
    int oct = 0;
    uint32_t val = 0;
    int digits = 0;
    for (size_t i = 0; i <= len; ++i) {
        char ch = (i < len) ? s[i] : '.';  // virtual trailing dot
        if (ch >= '0' && ch <= '9') {
            val = val * 10 + (uint32_t)(ch - '0');
            if (++digits > 3 || val > 255) return false;
        } else if (ch == '.') {
            if (digits == 0 || oct >= 4) return false;
            octets[oct++] = (uint8_t)val;
            val = 0;
            digits = 0;
        } else {
            return false;
        }
    }
    return oct == 4;
}

inline bool is_rfc1918(const uint8_t o[4]) {
    if (o[0] == 10) return true;
    if (o[0] == 192 && o[1] == 168) return true;
    if (o[0] == 172 && o[1] >= 16 && o[1] <= 31) return true;
    return false;
}

// `paired_pi_host` may be empty. Case-insensitive host compare is the
// caller's job — pass lowercased inputs.
inline bool server_url_allowed(const char* url, const char* paired_pi_host) {
    if (url == nullptr) return false;
    size_t len = strlen(url);
    if (len == 0 || len > 128) return false;

    const char* rest = nullptr;
    if (strncmp(url, "https://", 8) == 0) rest = url + 8;
    else if (strncmp(url, "http://", 7) == 0) rest = url + 7;
    else return false;

    // No query/fragment anywhere.
    if (strchr(url, '?') != nullptr || strchr(url, '#') != nullptr) return false;

    // Host part = up to the first '/' (or end).
    const char* slash = strchr(rest, '/');
    size_t hostport_len = slash ? (size_t)(slash - rest) : strlen(rest);
    if (hostport_len == 0) return false;

    // No userinfo.
    for (size_t i = 0; i < hostport_len; ++i)
        if (rest[i] == '@') return false;

    // Strip :port.
    size_t host_len = hostport_len;
    for (size_t i = 0; i < hostport_len; ++i) {
        if (rest[i] == ':') {
            host_len = i;
            // Port must be digits only.
            for (size_t j = i + 1; j < hostport_len; ++j)
                if (rest[j] < '0' || rest[j] > '9') return false;
            break;
        }
    }
    if (host_len == 0 || host_len > 63) return false;

    char host[64];
    memcpy(host, rest, host_len);
    host[host_len] = '\0';

    if (strcmp(host, "sporeprint.local") == 0) return true;
    if (strcmp(host, "sporeprint.ai") == 0) return true;
    if (paired_pi_host != nullptr && paired_pi_host[0] != '\0' &&
        strcmp(host, paired_pi_host) == 0)
        return true;

    // Private-range check ONLY for genuine IPv4 literals.
    uint8_t octets[4];
    if (parse_ipv4(host, host_len, octets)) return is_rfc1918(octets);
    return false;
}

}  // namespace sp
