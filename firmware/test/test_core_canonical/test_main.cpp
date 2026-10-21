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

// Canonical form: members sorted by raw key bytes at every depth, all
// insignificant whitespace gone, the top-level drop key (only) removed, and
// every scalar lexeme copied verbatim (a parse→reserialize canonicalizer
// would turn 1700000000.0 into 1700000000 and break parity with Python).
void test_canonical_form() {
    struct {
        const char* label;
        const char* in;
        const char* drop;
        const char* want;
    } cases[] = {
        {"pretty, unsorted",
         "{\n  \"ts\": 1700000000.5,\n  \"channel\": \"fae\",\n"
         "  \"target\": \"relay-01\",\n  \"tier\": \"premium\",\n"
         "  \"id\": \"cmd-2\"\n}",
         nullptr,
         "{\"channel\":\"fae\",\"id\":\"cmd-2\",\"target\":\"relay-01\","
         "\"tier\":\"premium\",\"ts\":1700000000.5}"},
        {"float lexeme verbatim", "{\"ts\":1700000000.0}", nullptr,
         "{\"ts\":1700000000.0}"},
        {"every scalar verbatim",
         "{\"z\":-0.5e-3,\"y\":1E+2,\"x\":0,\"w\":true,\"v\":false,\"u\":null,"
         "\"t\":\"a\\\"b\\\\c\\u00e9\\n\"}",
         nullptr,
         "{\"t\":\"a\\\"b\\\\c\\u00e9\\n\",\"u\":null,\"v\":false,\"w\":true,"
         "\"x\":0,\"y\":1E+2,\"z\":-0.5e-3}"},
        {"raw byte order: upper case first, prefix first",
         "{\"ab\":1,\"a\":2,\"B\":3}", nullptr, "{\"B\":3,\"a\":2,\"ab\":1}"},
        {"nested objects sort, arrays keep order",
         "{\"b\":{\"z\":1,\"a\":2},\"a\":[ {\"y\":1,\"x\":2} , [ ] , 3 ]}", nullptr,
         "{\"a\":[{\"x\":2,\"y\":1},[],3],\"b\":{\"a\":2,\"z\":1}}"},
        {"signature dropped at the top level only",
         "{\"a\":{\"signature\":\"keep\"},\"signature\":\"drop\"}", "signature",
         "{\"a\":{\"signature\":\"keep\"}}"},
        {"empty object", "  { }  ", nullptr, "{}"},
        // Dropping the only member yields {}, as Python's dict-comp does.
        {"only the dropped member", "{\"signature\":\"x\"}", "signature", "{}"},
    };
    for (auto& c : cases) {
        std::string out;
        TEST_ASSERT_EQUAL_INT_MESSAGE(
            (int)sp::CanonStatus::Ok,
            (int)sp::canonicalize(c.in, strlen(c.in), out, c.drop), c.label);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(c.want, out.c_str(), c.label);
    }
}

// Anything the Python signer could not have produced is refused, never
// guessed at: the MAC must cover exactly the document the node acts on.
void test_fail_closed_edges() {
    std::string deep;
    for (int i = 0; i < 12; ++i) deep += "{\"a\":";
    deep += "1";
    for (int i = 0; i < 12; ++i) deep += "}";
    std::string deep_array = "{\"a\":";
    for (int i = 0; i < 12; ++i) deep_array += "[";
    for (int i = 0; i < 12; ++i) deep_array += "]";
    deep_array += "}";
    std::string huge = "{\"a\":\"" + std::string(sp::kMaxInput, 'x') + "\"}";
    // Raw non-ASCII: compliant peers always escape.
    const std::string raw_utf8 = "{\"scene\":\"daylight \xE2\x98\x80\"}";
    struct {
        const char* label;
        std::string in;
        sp::CanonStatus want;
    } cases[] = {
        {"raw non-ASCII", raw_utf8, sp::CanonStatus::NonAscii},
        {"duplicate key", "{\"a\":1,\"a\":2}", sp::CanonStatus::DupKey},
        // Escaped key: a raw-byte sort would diverge from Python's.
        {"escaped key", "{\"a\\u0041\":1}", sp::CanonStatus::EscapedKey},
        {"trailing garbage", "{\"a\":1} x", sp::CanonStatus::BadJson},
        {"array at the top", "[1,2]", sp::CanonStatus::NotObject},
        {"empty input", "   ", sp::CanonStatus::NotObject},
        {"objects nested past 8", deep, sp::CanonStatus::TooDeep},
        {"arrays nested past 8", deep_array, sp::CanonStatus::TooDeep},
        {"over 4 KB", huge, sp::CanonStatus::TooLarge},
        {"unterminated string", "{\"a\":\"x", sp::CanonStatus::BadJson},
        {"unknown escape", "{\"a\":\"\\x41\"}", sp::CanonStatus::BadJson},
        {"short \\u escape", "{\"a\":\"\\u12g4\"}", sp::CanonStatus::BadJson},
        {"raw control char", "{\"a\":\"x\ty\"}", sp::CanonStatus::BadJson},
        {"leading zero", "{\"a\":01}", sp::CanonStatus::BadJson},
        {"bare minus", "{\"a\":-}", sp::CanonStatus::BadJson},
        {"no fraction digits", "{\"a\":1.}", sp::CanonStatus::BadJson},
        {"no exponent digits", "{\"a\":1e+}", sp::CanonStatus::BadJson},
        {"plus sign", "{\"a\":+1}", sp::CanonStatus::BadJson},
        {"truncated literal", "{\"a\":tru}", sp::CanonStatus::BadJson},
        {"single-quoted string", "{\"a\":'x'}", sp::CanonStatus::BadJson},
        {"missing colon", "{\"a\" 1}", sp::CanonStatus::BadJson},
        {"missing comma", "{\"a\":1 \"b\":2}", sp::CanonStatus::BadJson},
        {"unquoted key", "{a:1}", sp::CanonStatus::BadJson},
        {"trailing comma", "{\"a\":1,}", sp::CanonStatus::BadJson},
        {"unterminated object", "{\"a\":1", sp::CanonStatus::BadJson},
        {"array missing comma", "{\"a\":[1 2]}", sp::CanonStatus::BadJson},
        {"unterminated array", "{\"a\":[1,}", sp::CanonStatus::BadJson},
    };
    for (auto& c : cases) {
        std::string out;
        TEST_ASSERT_EQUAL_INT_MESSAGE(
            (int)c.want,
            (int)sp::canonicalize(c.in.data(), c.in.size(), out, nullptr),
            c.label);
    }
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
    // A nested member is not a top-level one, and a frame that is not one
    // well-formed object has no members at all.
    const char* nested = "{\"a\":{\"ts\":1}}";
    TEST_ASSERT_FALSE(sp::find_member_span(nested, strlen(nested), "ts", &span, &len));
    const char* not_obj = "[{\"ts\":1}]";
    TEST_ASSERT_FALSE(sp::find_member_span(not_obj, strlen(not_obj), "ts", &span, &len));
    const char* broken = "{\"ts\":1,";
    TEST_ASSERT_FALSE(sp::find_member_span(broken, strlen(broken), "ts", &span, &len));
    std::string huge = "{\"ts\":1,\"a\":\"" + std::string(sp::kMaxInput, 'x') + "\"}";
    TEST_ASSERT_FALSE(sp::find_member_span(huge.data(), huge.size(), "ts", &span, &len));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_golden_vectors_canonicalize);
    RUN_TEST(test_canonical_form);
    RUN_TEST(test_fail_closed_edges);
    RUN_TEST(test_find_member_span);
    return UNITY_END();
}
