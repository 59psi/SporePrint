// test_core_espota — the network-OTA handshake (sp_core/espota.h) and the
// vendored MD5 behind it.
//
// Pinned here:
//   * MD5 against the RFC 1321 appendix A.5 suite plus the 55/56/64-byte
//     padding edges (one vs two final blocks), the same edges one block in,
//     all 256 byte values, and one million 'a'
//   * the auth answer against the Pi's OWN espota client
//     (server/app/hardware/ota_push.py auth_response(), vectors generated
//     from it, incl. a non-ASCII UTF-8 password) — a node that computes
//     anything else rejects every Pi push
//   * invitation / answer parsing for the exact datagrams the Pi and espota.py
//     send, and the garbage arduino-esp32 2.x ArduinoOTA silently read as
//     zeros (a missing number parsed as command 0 = flash)

#include <unity.h>

#include <stdio.h>
#include <string.h>

#include "espota.h"
#include "md5.h"

using sp::espota::AuthParse;
using sp::espota::AuthReply;
using sp::espota::Invitation;

void setUp() {}
void tearDown() {}

#define ASSERT_PARSE(want, got) TEST_ASSERT_EQUAL((int)(want), (int)(got))

static void assert_md5(const char* msg, size_t len, const char* want) {
    char hex[sp::kMd5HexLen + 1];
    sp::md5_hex(msg, len, hex);
    TEST_ASSERT_EQUAL_STRING(want, hex);
}

// ── MD5 ────────────────────────────────────────────────────────

void test_md5_rfc1321_suite() {
    assert_md5("", 0, "d41d8cd98f00b204e9800998ecf8427e");
    assert_md5("a", 1, "0cc175b9c0f1b6a831c399e269772661");
    assert_md5("abc", 3, "900150983cd24fb0d6963f7d28e17f72");
    assert_md5("message digest", 14, "f96b697d7cb7938d525a2f31aaf161d0");
    assert_md5("abcdefghijklmnopqrstuvwxyz", 26,
               "c3fcd3d76192e4007dfb496cca67e13b");
    const char* alnum =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    assert_md5(alnum, strlen(alnum), "d174ab98d277d9f5a5611c2c9f419d9f");
    const char* digits80 =
        "1234567890123456789012345678901234567890"
        "1234567890123456789012345678901234567890";
    assert_md5(digits80, 80, "57edf4a22be3c955ac49da2e2107b67a");
}

void test_md5_padding_edges() {
    char buf[64];
    memset(buf, 'x', sizeof(buf));
    // 55 bytes: the length still fits the final block. 56: it spills into a
    // second padding block. 64: a full block, then a padding-only block.
    assert_md5(buf, 55, "04364420e25c512fd958a70738aa8f72");
    assert_md5(buf, 56, "668a72d5ba17f08e62dabcafad6db14b");
    assert_md5(buf, 64, "c1bb4f81d892b2d57947682aeb252456");
}

void test_md5_binary_and_multiblock() {
    // The RFC 1321 suite is all 7-bit ASCII; every byte value 0x00-0xFF
    // pins the message loading for bytes >= 0x80 (a UTF-8 password).
    uint8_t all[256];
    for (int i = 0; i < 256; ++i) all[i] = (uint8_t)i;
    assert_md5((const char*)all, sizeof(all), "e2c865db4162bed963bfaa9ef6ac18f0");

    // The padding edges again one block in (63/65, 119/120) and a 2-block
    // message plus a padding-only block (128). Pattern byte i = 131i + 7.
    uint8_t pat[128];
    for (int i = 0; i < 128; ++i) pat[i] = (uint8_t)(i * 131 + 7);
    assert_md5((const char*)pat, 63, "c9803ddca3b148d91d5f214be64197d4");
    assert_md5((const char*)pat, 65, "4e114d3e0baf5ace365e0552a3273291");
    assert_md5((const char*)pat, 119, "e0c0cb3cbc027ba4d5a6c983754f2dc1");
    assert_md5((const char*)pat, 120, "3d7a96a57e721a4e2c2cbe55937e10e2");
    assert_md5((const char*)pat, 128, "154b8c17cfb174384edd9557e3e64e2b");

    // One million 'a' (15,625 blocks; the bit length needs 23 bits).
    static char million[1000000];
    memset(million, 'a', sizeof(million));
    assert_md5(million, sizeof(million), "7707d6ae4e027c70eea2a935c2296f21");
}

// ── the auth answer ────────────────────────────────────────────

static const char* kPassword = "correct-horse-battery";
static const char* kNonce = "0123456789abcdef0123456789abcdef";
static const char* kCnonce = "fedcba9876543210fedcba9876543210";
// auth_response("correct-horse-battery", kNonce, kCnonce) from
// server/app/hardware/ota_push.py.
static const char* kPiResponse = "0e519f38e27e3c52eee1199f07c3c13e";

void test_password_digest_is_md5_hex() {
    char digest[sp::espota::kHexLen + 1];
    sp::espota::password_digest(kPassword, digest);
    TEST_ASSERT_EQUAL_STRING("09f31f46f81f8fab873fbc0420173519", digest);
}

void test_expected_response_matches_the_pi_push() {
    char digest[sp::espota::kHexLen + 1];
    char want[sp::espota::kHexLen + 1];
    sp::espota::password_digest(kPassword, digest);
    sp::espota::expected_response(digest, kNonce, kCnonce, want);
    TEST_ASSERT_EQUAL_STRING(kPiResponse, want);
}

void test_utf8_password_matches_the_pi_push() {
    // The portal stores the password's UTF-8 bytes and the Pi hashes
    // password.encode(): "grüne-pilze-ö-2026" (20 bytes), vectors from
    // ota_push.py auth_response().
    const char* pw = "gr\xc3\xbcne-pilze-\xc3\xb6-2026";
    TEST_ASSERT_EQUAL(20, (int)strlen(pw));
    char digest[sp::espota::kHexLen + 1];
    char want[sp::espota::kHexLen + 1];
    sp::espota::password_digest(pw, digest);
    TEST_ASSERT_EQUAL_STRING("eb0ebb09ddf47a3443d0cafb61181b54", digest);
    sp::espota::expected_response(digest, kNonce, kCnonce, want);
    TEST_ASSERT_EQUAL_STRING("a9bc5999366ff53c3c286545a50649ad", want);
}

void test_response_matches_accepts_only_the_right_answer() {
    char digest[sp::espota::kHexLen + 1];
    sp::espota::password_digest(kPassword, digest);
    AuthReply r;
    strcpy(r.cnonce, kCnonce);
    strcpy(r.response, kPiResponse);
    TEST_ASSERT_TRUE(sp::espota::response_matches(digest, kNonce, r));

    // Another nonce (a stale challenge) — rejected.
    TEST_ASSERT_FALSE(sp::espota::response_matches(
        digest, "ffffffffffffffffffffffffffffffff", r));
    // Wrong password.
    char other[sp::espota::kHexLen + 1];
    sp::espota::password_digest("correct-horse-batterz", other);
    TEST_ASSERT_FALSE(sp::espota::response_matches(other, kNonce, r));
    // Case matters: the node compares lowercase hex exactly (as 2.x did).
    AuthReply upper = r;
    for (char* p = upper.response; *p; ++p)
        if (*p >= 'a' && *p <= 'f') *p = (char)(*p - 'a' + 'A');
    TEST_ASSERT_FALSE(sp::espota::response_matches(digest, kNonce, upper));
}

void test_nonce_is_32_lowercase_hex() {
    const uint8_t rnd[sp::espota::kNonceBytes] = {
        0x00, 0x01, 0xAB, 0xCD, 0xEF, 0x10, 0x20, 0x30,
        0x40, 0x50, 0x60, 0x70, 0x80, 0x90, 0xA0, 0xFF};
    char nonce[sp::espota::kHexLen + 1];
    sp::espota::nonce_hex(rnd, nonce);
    TEST_ASSERT_EQUAL_STRING("0001abcdef102030405060708090a0ff", nonce);
    TEST_ASSERT_EQUAL(32, (int)strlen(nonce));
}

// ── invitation parsing ─────────────────────────────────────────

static bool parse_inv(const char* s, Invitation* inv) {
    return sp::espota::parse_invitation(s, strlen(s), inv);
}

void test_parses_the_pi_push_invitation() {
    // f"{FLASH_CMD} {host_port} {size} {file_md5}\n" (ota_push.py)
    Invitation inv;
    TEST_ASSERT_TRUE(
        parse_inv("0 3233 1294752 0123456789abcdef0123456789abcdef\n", &inv));
    TEST_ASSERT_EQUAL(sp::espota::kCmdFlash, inv.cmd);
    TEST_ASSERT_EQUAL(3233, inv.port);
    TEST_ASSERT_EQUAL_UINT32(1294752u, inv.size);
    TEST_ASSERT_EQUAL_STRING("0123456789abcdef0123456789abcdef", inv.md5);
}

void test_parses_espota_filesystem_invitation_and_trims_the_md5() {
    Invitation inv;
    TEST_ASSERT_TRUE(parse_inv(
        "100 51234 917504  FEDCBA9876543210FEDCBA9876543210 \r\n", &inv));
    TEST_ASSERT_EQUAL(sp::espota::kCmdFilesystem, inv.cmd);
    TEST_ASSERT_EQUAL(51234, inv.port);
    TEST_ASSERT_EQUAL_UINT32(917504u, inv.size);
    TEST_ASSERT_EQUAL_STRING("FEDCBA9876543210FEDCBA9876543210", inv.md5);
    // No trailing newline at all (a client that omits it).
    TEST_ASSERT_TRUE(
        parse_inv("0 3233 10 0123456789abcdef0123456789abcdef", &inv));
}

void test_rejects_malformed_invitations() {
    Invitation inv;
    const char* md5 = "0123456789abcdef0123456789abcdef";
    char buf[96];
    // An auth answer is not an invitation (2.x read its 200 as "not flash").
    snprintf(buf, sizeof(buf), "200 %s %s\n", md5, md5);
    TEST_ASSERT_FALSE(parse_inv(buf, &inv));
    // Unknown command.
    snprintf(buf, sizeof(buf), "1 3233 10 %s\n", md5);
    TEST_ASSERT_FALSE(parse_inv(buf, &inv));
    // Garbage where a number belongs — 2.x parsed this as command 0 (flash).
    snprintf(buf, sizeof(buf), "AUTH 3233 10 %s\n", md5);
    TEST_ASSERT_FALSE(parse_inv(buf, &inv));
    // Port 0 / out of range, size 0, missing fields.
    snprintf(buf, sizeof(buf), "0 0 10 %s\n", md5);
    TEST_ASSERT_FALSE(parse_inv(buf, &inv));
    snprintf(buf, sizeof(buf), "0 65536 10 %s\n", md5);
    TEST_ASSERT_FALSE(parse_inv(buf, &inv));
    snprintf(buf, sizeof(buf), "0 3233 0 %s\n", md5);
    TEST_ASSERT_FALSE(parse_inv(buf, &inv));
    TEST_ASSERT_FALSE(parse_inv("0 3233\n", &inv));
    TEST_ASSERT_FALSE(parse_inv("", &inv));
    // MD5 the wrong length or not hex.
    TEST_ASSERT_FALSE(parse_inv("0 3233 10 0123456789abcdef\n", &inv));
    TEST_ASSERT_FALSE(
        parse_inv("0 3233 10 0123456789abcdef0123456789abcdeff\n", &inv));
    TEST_ASSERT_FALSE(
        parse_inv("0 3233 10 0123456789abcdef0123456789abcdeg\n", &inv));
}

// ── auth answer parsing ────────────────────────────────────────

void test_parses_the_pi_push_auth_answer() {
    // f"{AUTH_CMD} {cnonce} {auth_response(...)}\n" (ota_push.py)
    char buf[96];
    snprintf(buf, sizeof(buf), "200 %s %s\n", kCnonce, kPiResponse);
    AuthReply r;
    ASSERT_PARSE(AuthParse::Ok,
                      sp::espota::parse_auth_reply(buf, strlen(buf), &r));
    TEST_ASSERT_EQUAL_STRING(kCnonce, r.cnonce);
    TEST_ASSERT_EQUAL_STRING(kPiResponse, r.response);
}

void test_auth_answer_rejections() {
    AuthReply r;
    char buf[128];
    // A re-sent invitation while waiting for the answer: not an answer (the
    // receiver drops back to idle, exactly as 2.x ArduinoOTA did).
    const char* inv = "0 3233 10 0123456789abcdef0123456789abcdef\n";
    ASSERT_PARSE(AuthParse::NotAuth,
                      sp::espota::parse_auth_reply(inv, strlen(inv), &r));
    // 3.3's PBKDF2 answer (64-hex fields) — not ours.
    snprintf(buf, sizeof(buf), "200 %s%s %s%s\n", kCnonce, kCnonce,
             kPiResponse, kPiResponse);
    ASSERT_PARSE(AuthParse::BadParams,
                      sp::espota::parse_auth_reply(buf, strlen(buf), &r));
    // A trailing CR makes the response 33 characters (2.x rejected it too).
    snprintf(buf, sizeof(buf), "200 %s %s\r\n", kCnonce, kPiResponse);
    ASSERT_PARSE(AuthParse::BadParams,
                      sp::espota::parse_auth_reply(buf, strlen(buf), &r));
    // Missing response.
    snprintf(buf, sizeof(buf), "200 %s\n", kCnonce);
    ASSERT_PARSE(AuthParse::BadParams,
                      sp::espota::parse_auth_reply(buf, strlen(buf), &r));
    ASSERT_PARSE(AuthParse::NotAuth,
                      sp::espota::parse_auth_reply("", 0, &r));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_md5_rfc1321_suite);
    RUN_TEST(test_md5_padding_edges);
    RUN_TEST(test_md5_binary_and_multiblock);
    RUN_TEST(test_password_digest_is_md5_hex);
    RUN_TEST(test_expected_response_matches_the_pi_push);
    RUN_TEST(test_utf8_password_matches_the_pi_push);
    RUN_TEST(test_response_matches_accepts_only_the_right_answer);
    RUN_TEST(test_nonce_is_32_lowercase_hex);
    RUN_TEST(test_parses_the_pi_push_invitation);
    RUN_TEST(test_parses_espota_filesystem_invitation_and_trims_the_md5);
    RUN_TEST(test_rejects_malformed_invitations);
    RUN_TEST(test_parses_the_pi_push_auth_answer);
    RUN_TEST(test_auth_answer_rejections);
    return UNITY_END();
}
