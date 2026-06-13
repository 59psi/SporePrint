#pragma once
//
// sha256 — minimal interface sp_core modules depend on, so the same
// verification code runs on-device (bound to mbedTLS, zero extra flash —
// it ships in ESP-IDF anyway) and on the host (bound to the vendored
// implementation in sha256_host.cpp).
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

namespace sp {

using HmacSha256Fn = void (*)(const uint8_t* key, size_t key_len,
                              const uint8_t* msg, size_t msg_len,
                              uint8_t out[32]);

// Host (vendored) implementation — always available; device builds may
// prefer the mbedTLS binding from sp_device but CAN use this one too.
void hmac_sha256_host(const uint8_t* key, size_t key_len,
                      const uint8_t* msg, size_t msg_len, uint8_t out[32]);

void sha256_host(const uint8_t* msg, size_t msg_len, uint8_t out[32]);

}  // namespace sp
