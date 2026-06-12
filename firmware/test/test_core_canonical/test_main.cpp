// test_core_canonical — golden-vector parity for the raw-token canonicalizer
// plus its fail-closed edges.
//
// Strategy: every vector's `expected_canonical` (decoded from the fixture)
// IS a valid compact wire body. We inject a `"signature":"…"` member and a
// layer of cosmetic whitespace, run canonicalize(), and require the output
// byte-equal to `expected_canonical`. That proves member sort, whitespace
// stripping, top-level signature drop, and verbatim scalar lexeme copy
// (incl. Python's "1700000000.0" float formatting and \uXXXX escapes) in
// one assertion per vector — against the SAME fixture file the Python
// signers test against (byte-identical copy; bump.sh parity gate).

#include <unity.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "canonical_json.h"

void setUp() {}
void tearDown() {}

// ── fixture loading ────────────────────────────────────────────

static std::string g_fixture;

static bool load_fixture() {
    const char* candidates[] = {
        "test/fixtures/signing_vectors.json",
        "fixtures/signing_vectors.json",
        "../fixtures/signing_vectors.json",
    };
    for (const char* path : candidates) {
        FILE* f = fopen(path, "rb");
        if (!f) continue;
        fseek(f, 0, SEEK_END);
        long n = ftell(f);
        fseek(f, 0, SEEK_SET);
        g_fixture.resize((size_t)n);
        size_t got = fread(&g_fixture[0], 1, (size_t)n, f);
        fclose(f);
        return got == (size_t)n;
    }
    return false;
}

// Decode a JSON string literal span (with quotes) into raw bytes. Handles
// the escapes the fixture uses (\" \\ \/ \uXXXX with BMP codepoints).
static std::string decode_json_string(const char* span, size_t len) {
    std::string out;
    TEST_ASSERT_TRUE(len >= 2 && span[0] == '"' && span[len - 1] == '"');
    for (size_t i = 1; i + 1 < len; ++i) {
        char ch = span[i];
        if (ch != '\\') {
            out.push_back(ch);
            continue;
        }
        ++i;
        char e = span[i];
        switch (e) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'b': out.push_back('\b'); break;
            case 'f': out.push_back('\f'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            case 'u': {
                char hex[5] = {span[i + 1], span[i + 2], span[i + 3], span[i + 4], 0};
                i += 4;
                unsigned cp = (unsigned)strtoul(hex, nullptr, 16);
                // Fixture-level \u only appears for ASCII in our vectors;
                // encode BMP as UTF-8 to be safe.
                if (cp < 0x80) {
                    out.push_back((char)cp);
                } else if (cp < 0x800) {
                    out.push_back((char)(0xC0 | (cp >> 6)));
                    out.push_back((char)(0x80 | (cp & 0x3F)));
                } else {
                    out.push_back((char)(0xE0 | (cp >> 12)));
                    out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
                    out.push_back((char)(0x80 | (cp & 0x3F)));
                }
                break;
            }
            default: TEST_FAIL_MESSAGE("unexpected escape in fixture string");
        }
    }
    return out;
}

// Walk the top-level elements of a JSON array span (depth/quote aware).
static std::vector<std::pair<const char*, size_t>> array_elements(
    const char* span, size_t len) {
    std::vector<std::pair<const char*, size_t>> out;
    size_t i = 0;
    while (i < len && span[i] != '[') ++i;
    TEST_ASSERT_TRUE(i < len);
    ++i;
    int depth = 0;
    bool in_str = false;
    const char* start = nullptr;
    for (; i < len; ++i) {
        char ch = span[i];
        if (in_str) {
            if (ch == '\\') ++i;
            else if (ch == '"') in_str = false;
            continue;
        }
        if (ch == '"') { in_str = true; if (!start) start = span + i; continue; }
        if (ch == '{' || ch == '[') {
            if (depth == 0 && !start) start = span + i;
            ++depth;
            continue;
        }
        if (ch == '}' || ch == ']') {
            if (depth == 0 && ch == ']') break;  // array end
            --depth;
            continue;
        }
        if (depth == 0 && (ch == ',')) {
            if (start) out.emplace_back(start, (size_t)(span + i - start));
            start = nullptr;
            continue;
        }
        if (depth == 0 && !start && ch != ' ' && ch != '\n' && ch != '\r' &&
            ch != '\t') {
            start = span + i;
        }
    }
    if (start) {
        // Trim trailing whitespace before the closing bracket.
        const char* e = span + i;
        while (e > start && (e[-1] == ' ' || e[-1] == '\n' || e[-1] == '\r' ||
                             e[-1] == '\t')) --e;
        out.emplace_back(start, (size_t)(e - start));
    }
    return out;
}

struct Vector {
    std::string id;
    std::string canonical;   // decoded expected_canonical (wire-form body)
    std::string signature;   // decoded expected_signature (64 hex)
};

static std::vector<Vector> load_vectors() {
    std::vector<Vector> out;
    TEST_ASSERT_TRUE_MESSAGE(load_fixture(), "fixture file not found");
    const char* arr;
    size_t arr_len;
    TEST_ASSERT_TRUE(sp::find_member_span(g_fixture.data(), g_fixture.size(),
                                          "vectors", &arr, &arr_len));
    for (auto& el : array_elements(arr, arr_len)) {
        Vector v;
        const char* s;
        size_t sl;
        TEST_ASSERT_TRUE(sp::find_member_span(el.first, el.second, "id", &s, &sl));
        v.id = decode_json_string(s, sl);
        TEST_ASSERT_TRUE(sp::find_member_span(el.first, el.second,
                                              "expected_canonical", &s, &sl));
        v.canonical = decode_json_string(s, sl);
        TEST_ASSERT_TRUE(sp::find_member_span(el.first, el.second,
                                              "expected_signature", &s, &sl));
        v.signature = decode_json_string(s, sl);
        out.push_back(v);
    }
    return out;
}

// Build a wire frame: canonical body + injected signature member + cosmetic
// whitespace, so canonicalize() has real work to do.
static std::string wire_with_signature(const Vector& v) {
    std::string wire = "{ \"signature\" : \"";
    wire += v.signature;
    wire += "\" , ";
    wire.append(v.canonical.begin() + 1, v.canonical.end());  // skip '{'
    return wire;
}

// ── tests ──────────────────────────────────────────────────────

void test_golden_vectors_canonicalize() {
    auto vectors = load_vectors();
    TEST_ASSERT_EQUAL_INT_MESSAGE(6, (int)vectors.size(),
                                  "fixture vector count changed — update tests");
    for (const Vector& v : vectors) {
        std::string wire = wire_with_signature(v);
        std::string out;
        sp::CanonStatus st =
            sp::canonicalize(wire.data(), wire.size(), out, "signature");
        char msg[128];
        snprintf(msg, sizeof(msg), "vector '%s': status %s", v.id.c_str(),
                 sp::canon_status_str(st));
        TEST_ASSERT_EQUAL_INT_MESSAGE((int)sp::CanonStatus::Ok, (int)st, msg);
        snprintf(msg, sizeof(msg), "vector '%s': canonical bytes diverge",
                 v.id.c_str());
        TEST_ASSERT_EQUAL_STRING_MESSAGE(v.canonical.c_str(), out.c_str(), msg);
    }
}

void test_unsorted_pretty_input_sorts() {
    const char* wire =
        "{\n  \"ts\": 1700000000.5,\n  \"channel\": \"fae\",\n"
        "  \"target\": \"relay-01\",\n  \"tier\": \"premium\",\n"
        "  \"id\": \"cmd-2\"\n}";
    std::string out;
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::Ok,
                          (int)sp::canonicalize(wire, strlen(wire), out, nullptr));
    TEST_ASSERT_EQUAL_STRING(
        "{\"channel\":\"fae\",\"id\":\"cmd-2\",\"target\":\"relay-01\","
        "\"tier\":\"premium\",\"ts\":1700000000.5}",
        out.c_str());
}

void test_float_lexeme_preserved_verbatim() {
    const char* wire = "{\"ts\":1700000000.0}";
    std::string out;
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::Ok,
                          (int)sp::canonicalize(wire, strlen(wire), out, nullptr));
    // A parse→reserialize canonicalizer would emit 1700000000 here.
    TEST_ASSERT_EQUAL_STRING("{\"ts\":1700000000.0}", out.c_str());
}

void test_nested_objects_sort_recursively() {
    const char* wire = "{\"b\":{\"z\":1,\"a\":2},\"a\":[{\"y\":1,\"x\":2}]}";
    std::string out;
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::Ok,
                          (int)sp::canonicalize(wire, strlen(wire), out, nullptr));
    TEST_ASSERT_EQUAL_STRING("{\"a\":[{\"x\":2,\"y\":1}],\"b\":{\"a\":2,\"z\":1}}",
                             out.c_str());
}

void test_signature_dropped_top_level_only() {
    const char* wire = "{\"a\":{\"signature\":\"keep\"},\"signature\":\"drop\"}";
    std::string out;
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::Ok,
                          (int)sp::canonicalize(wire, strlen(wire), out, "signature"));
    TEST_ASSERT_EQUAL_STRING("{\"a\":{\"signature\":\"keep\"}}", out.c_str());
}

void test_fail_closed_edges() {
    std::string out;
    // Raw non-ASCII (compliant peers always escape) — reject.
    const char raw_utf8[] = "{\"scene\":\"daylight \xE2\x98\x80\"}";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::NonAscii,
                          (int)sp::canonicalize(raw_utf8, sizeof(raw_utf8) - 1,
                                                out, nullptr));
    // Duplicate keys — reject.
    const char* dup = "{\"a\":1,\"a\":2}";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::DupKey,
                          (int)sp::canonicalize(dup, strlen(dup), out, nullptr));
    // Escaped key — raw-byte sort would diverge from Python — reject.
    const char* esc = "{\"a\\u0041\":1}";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::EscapedKey,
                          (int)sp::canonicalize(esc, strlen(esc), out, nullptr));
    // Trailing garbage — reject.
    const char* trail = "{\"a\":1} x";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::BadJson,
                          (int)sp::canonicalize(trail, strlen(trail), out, nullptr));
    // Top level must be an object.
    const char* arr = "[1,2]";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::NotObject,
                          (int)sp::canonicalize(arr, strlen(arr), out, nullptr));
    // Depth bomb.
    std::string deep;
    for (int i = 0; i < 12; ++i) deep += "{\"a\":";
    deep += "1";
    for (int i = 0; i < 12; ++i) deep += "}";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::TooDeep,
                          (int)sp::canonicalize(deep.data(), deep.size(), out,
                                                nullptr));
    // Unterminated string.
    const char* unterm = "{\"a\":\"x";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::BadJson,
                          (int)sp::canonicalize(unterm, strlen(unterm), out,
                                                nullptr));
}

void test_find_member_span() {
    const char* json = "{\"ts\": 1700000000.5, \"signature\":\"abc\"}";
    const char* span;
    size_t len;
    TEST_ASSERT_TRUE(sp::find_member_span(json, strlen(json), "ts", &span, &len));
    TEST_ASSERT_EQUAL_INT(12, (int)len);
    TEST_ASSERT_EQUAL_MEMORY("1700000000.5", span, 12);
    TEST_ASSERT_TRUE(
        sp::find_member_span(json, strlen(json), "signature", &span, &len));
    TEST_ASSERT_EQUAL_MEMORY("\"abc\"", span, 5);
    TEST_ASSERT_FALSE(
        sp::find_member_span(json, strlen(json), "missing", &span, &len));
}

void test_empty_and_minimal_objects() {
    std::string out;
    const char* empty = "  { }  ";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::Ok,
                          (int)sp::canonicalize(empty, strlen(empty), out, nullptr));
    TEST_ASSERT_EQUAL_STRING("{}", out.c_str());
    // Dropping the only member yields {} — matches Python's dict-comp.
    const char* only_sig = "{\"signature\":\"x\"}";
    TEST_ASSERT_EQUAL_INT((int)sp::CanonStatus::Ok,
                          (int)sp::canonicalize(only_sig, strlen(only_sig), out,
                                                "signature"));
    TEST_ASSERT_EQUAL_STRING("{}", out.c_str());
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_golden_vectors_canonicalize);
    RUN_TEST(test_unsorted_pretty_input_sorts);
    RUN_TEST(test_float_lexeme_preserved_verbatim);
    RUN_TEST(test_nested_objects_sort_recursively);
    RUN_TEST(test_signature_dropped_top_level_only);
    RUN_TEST(test_fail_closed_edges);
    RUN_TEST(test_find_member_span);
    RUN_TEST(test_empty_and_minimal_objects);
    return UNITY_END();
}
