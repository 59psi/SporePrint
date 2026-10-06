#pragma once
//
// espota — the network-OTA handshake every SporePrint node has spoken since
// v1 (arduino-esp32 2.x ArduinoOTA), as pure, host-tested functions.
// sp_device/ota_service.cpp owns the sockets and the flash writes; what a
// datagram means and whether an answer authenticates is decided here.
//
// Wire (byte-for-byte the 2.x ArduinoOTA exchange; clients: the Pi's OTA push
// server/app/hardware/ota_push.py, and espota.py):
//   1. client -> node, UDP :3232   "<cmd> <port> <size> <md5>\n"
//        cmd 0 = application image, 100 = filesystem image; <md5> = the 32
//        hex chars of the image's MD5 (the node's Update checks it at the end)
//   2. node -> client              "AUTH <nonce>"           (32 lowercase hex)
//      client -> node              "200 <cnonce> <response>\n"
//        response = md5_hex(md5_hex(password) ":" nonce ":" cnonce)
//      node -> client              "OK" | "Authentication Failed"
//   3. the node connects BACK over TCP to <client ip>:<port>, pulls <size>
//      bytes, acks each chunk with the decimal count it wrote, sends "OK" once
//      the image verified and is the next boot image, and reboots into it.
//
// Why the node no longer uses the core's ArduinoOTA: arduino-esp32 3.3
// replaced step 2 with a PBKDF2-HMAC-SHA256 exchange (64-hex nonce, cnonce and
// response) and dropped the MD5 one. Every deployed Pi answers with MD5, so a
// node on the stock 3.x library would refuse every Pi push after its first
// 3.x OTA. Speaking the 2.x handshake keeps the Pi <-> node contract
// unchanged; espota.py from the 3.x platform (pio -t upload over the network)
// still speaks it too — a 32-hex nonce selects its MD5 path. Moving to the
// PBKDF2 exchange is a coordinated change: the Pi push must answer both
// (choosing by nonce length, as espota.py does) before a node stops offering
// MD5. ota_push.py does from 2026-10; Pis older than that still answer only
// MD5.
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>

#include "md5.h"

namespace sp {
namespace espota {

constexpr uint16_t kPort = 3232;
constexpr int kCmdFlash = 0;         // U_FLASH
constexpr int kCmdFilesystem = 100;  // U_SPIFFS on 2.x, U_FLASHFS on 3.x
constexpr int kCmdAuth = 200;        // U_AUTH
constexpr size_t kHexLen = kMd5HexLen;
constexpr size_t kNonceBytes = 16;
// Longest valid datagram: "200 " + 32 + " " + 32 + "\n" = 70 bytes.
constexpr size_t kMaxDatagram = 128;

struct Invitation {
    int cmd = -1;
    uint16_t port = 0;
    uint32_t size = 0;
    char md5[kHexLen + 1] = {0};
};

// Step 1. False for anything that is not a well-formed invitation (an auth
// answer, a truncated or garbled datagram, port 0, size 0, a non-hex MD5).
bool parse_invitation(const char* data, size_t len, Invitation* out);

struct AuthReply {
    char cnonce[kHexLen + 1] = {0};
    char response[kHexLen + 1] = {0};
};

enum class AuthParse : uint8_t {
    Ok,
    NotAuth,    // the datagram does not start with command 200
    BadParams,  // 200, but cnonce / response are not 32 characters each
};

// Step 2, the client's answer.
AuthParse parse_auth_reply(const char* data, size_t len, AuthReply* out);

// md5_hex(password): what the node keeps instead of the password.
void password_digest(const char* password, char out[kHexLen + 1]);

// The challenge sent in "AUTH <nonce>": lowercase hex of kNonceBytes random
// bytes (the device draws them from the hardware RNG).
void nonce_hex(const uint8_t random[kNonceBytes], char out[kHexLen + 1]);

// md5_hex(pass_digest ":" nonce ":" cnonce) — the answer a client holding the
// password sends.
void expected_response(const char* pass_digest, const char* nonce,
                       const char* cnonce, char out[kHexLen + 1]);

// Constant-time check of a parsed answer against the challenge.
bool response_matches(const char* pass_digest, const char* nonce,
                      const AuthReply& reply);

}  // namespace espota
}  // namespace sp
