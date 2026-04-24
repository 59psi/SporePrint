// Placeholder native test — proves pio test -e native is wired.
// Replace with frame_verify::canonicalize byte-equality tests,
// OfflineBuffer FIFO tests, clamp-boundary tests as they land.
//
// Unity is included automatically by PlatformIO when this file compiles
// under the native env.

#include <unity.h>

void setUp() {}
void tearDown() {}

void test_harness_boot(void) {
    // Sanity: 2+2=4. When the real tests land this file will be deleted
    // and the canonicalize+eviction+clamp tests will replace it.
    TEST_ASSERT_EQUAL_INT(4, 2 + 2);
}

int main(int argc, char** argv) {
    UNITY_BEGIN();
    RUN_TEST(test_harness_boot);
    return UNITY_END();
}
