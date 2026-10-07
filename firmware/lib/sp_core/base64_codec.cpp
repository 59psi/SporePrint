#include "base64_codec.h"

namespace sp {

namespace {

const char kB64[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

int b64_value(char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

}  // namespace

size_t base64_encode(const uint8_t* in, size_t in_len, char* out,
                     size_t out_cap) {
    const size_t needed = base64_encoded_len(in_len) + 1;
    if (out == nullptr || out_cap < needed) return 0;
    size_t i = 0, o = 0;
    while (i + 3 <= in_len) {
        const uint32_t v = ((uint32_t)in[i] << 16) |
                           ((uint32_t)in[i + 1] << 8) | in[i + 2];
        out[o++] = kB64[(v >> 18) & 0x3F];
        out[o++] = kB64[(v >> 12) & 0x3F];
        out[o++] = kB64[(v >> 6) & 0x3F];
        out[o++] = kB64[v & 0x3F];
        i += 3;
    }
    if (i < in_len) {
        uint32_t v = (uint32_t)in[i] << 16;
        if (i + 1 < in_len) v |= (uint32_t)in[i + 1] << 8;
        out[o++] = kB64[(v >> 18) & 0x3F];
        out[o++] = kB64[(v >> 12) & 0x3F];
        out[o++] = (i + 1 < in_len) ? kB64[(v >> 6) & 0x3F] : '=';
        out[o++] = '=';
    }
    out[o] = '\0';
    return o;
}

bool base64_decode(const char* in, size_t in_len, uint8_t* out,
                   size_t out_cap, size_t* out_len) {
    if (in == nullptr || out_len == nullptr || in_len % 4 != 0) return false;
    size_t pad = 0;
    if (in_len >= 4 && in[in_len - 1] == '=') pad = (in[in_len - 2] == '=') ? 2 : 1;
    const size_t n = (in_len / 4) * 3 - pad;
    if (n > out_cap || (n > 0 && out == nullptr)) return false;
    size_t o = 0;
    for (size_t i = 0; i < in_len; i += 4) {
        const bool last = (i + 4 == in_len);
        int v[4];
        for (size_t k = 0; k < 4; ++k) {
            const char c = in[i + k];
            if (c == '=' && last && k >= 4 - pad) {
                v[k] = 0;
                continue;
            }
            v[k] = b64_value(c);
            if (v[k] < 0) return false;
        }
        const uint32_t word = ((uint32_t)v[0] << 18) | ((uint32_t)v[1] << 12) |
                              ((uint32_t)v[2] << 6) | (uint32_t)v[3];
        if (last && pad == 2) {
            if ((word & 0xFFFF) != 0) return false;  // non-zero pad bits
            out[o++] = (uint8_t)(word >> 16);
        } else if (last && pad == 1) {
            if ((word & 0xFF) != 0) return false;
            out[o++] = (uint8_t)(word >> 16);
            out[o++] = (uint8_t)(word >> 8);
        } else {
            out[o++] = (uint8_t)(word >> 16);
            out[o++] = (uint8_t)(word >> 8);
            out[o++] = (uint8_t)word;
        }
    }
    *out_len = o;
    return true;
}

}  // namespace sp
