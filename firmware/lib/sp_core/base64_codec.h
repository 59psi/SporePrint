#pragma once
//
// base64_codec — RFC 4648 §4 (standard alphabet, '=' padding), the encoding the
// coredump chunks and the signed OTA manifest command carry.
//
// (Not "base64.h": that name is the Arduino core's own header, which
// HTTPClient and WebServer include.)
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

namespace sp {

// Encoded length of `n` bytes, excluding the NUL.
constexpr size_t base64_encoded_len(size_t n) { return ((n + 2) / 3) * 4; }

// Returns the characters written (a NUL follows), or 0 when `out_cap` is
// too small.
size_t base64_encode(const uint8_t* in, size_t in_len, char* out,
                     size_t out_cap);

// Strict decode: length a multiple of 4, only alphabet characters, '='
// only as the final one or two, and zero pad bits (so every byte string has
// exactly one accepted encoding — Python's b64decode(validate=True) also
// rejects the rest). Returns false on any violation or when `out_cap` is too
// small; `*out_len` gets the decoded length.
bool base64_decode(const char* in, size_t in_len, uint8_t* out,
                   size_t out_cap, size_t* out_len);

}  // namespace sp
