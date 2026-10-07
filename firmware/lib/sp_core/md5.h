#pragma once
//
// md5 — clean-room RFC 1321 MD5, for the espota OTA handshake (espota.h).
//
// MD5 is not used for anything security-bearing on its own here: the espota
// wire protocol (what every SporePrint node has spoken since v1, and what the
// Pi's OTA push sends) is an MD5 challenge-response, and the image integrity
// check it carries is an MD5 of the upload. Vendored, like sha256_host.cpp,
// so the native suite runs the exact code the device runs.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

namespace sp {

constexpr size_t kMd5Len = 16;
constexpr size_t kMd5HexLen = 32;

void md5(const uint8_t* msg, size_t len, uint8_t out[kMd5Len]);

// Lowercase hex digest of `len` bytes; `out` gets kMd5HexLen chars + NUL.
void md5_hex(const void* msg, size_t len, char out[kMd5HexLen + 1]);

}  // namespace sp
