// test_cam_url — server_url allowlist, including the v1 hole where
// "10.attacker.com" passed the RFC1918 check via startsWith("10.").

#include <unity.h>

#include "server_url_allow.h"

void setUp() {}
void tearDown() {}

void test_allowed_hosts() {
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://sporeprint.local:8000", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("https://sporeprint.ai", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://sporeprint.local/api", ""));
    TEST_ASSERT_TRUE(
        sp::server_url_allowed("http://mypi.lan:8000", "mypi.lan"));
}

void test_rfc1918_literals() {
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://10.0.0.5:8000", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://192.168.1.7", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://172.16.0.1", ""));
    TEST_ASSERT_TRUE(sp::server_url_allowed("http://172.31.255.254:8000", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://172.32.0.1", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://172.15.0.1", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://8.8.8.8", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://11.0.0.1", ""));
}

void test_v1_hole_closed() {
    // The exact v1 bypass: a HOSTNAME starting with "10.".
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.attacker.com/x", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://192.168.evil.io", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5.evil.com", ""));
    // Malformed quads are hostnames, not IPs.
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.999", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5.6", ""));
}

void test_structure_rules() {
    TEST_ASSERT_FALSE(sp::server_url_allowed("ftp://10.0.0.5", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://user@10.0.0.5/", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5/?q=1", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5/#frag", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://10.0.0.5:80x", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("", ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed(nullptr, ""));
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://", ""));
    // Length cap.
    char big[160];
    memset(big, 'a', sizeof(big));
    memcpy(big, "http://10.0.0.5/", 16);
    big[sizeof(big) - 1] = '\0';
    TEST_ASSERT_FALSE(sp::server_url_allowed(big, ""));
    // Empty paired host must not match an empty-host comparison trick.
    TEST_ASSERT_FALSE(sp::server_url_allowed("http://evil.com", ""));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_allowed_hosts);
    RUN_TEST(test_rfc1918_literals);
    RUN_TEST(test_v1_hole_closed);
    RUN_TEST(test_structure_rules);
    return UNITY_END();
}
