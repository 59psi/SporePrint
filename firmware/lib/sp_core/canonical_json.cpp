#include "canonical_json.h"

#include <string.h>
#include <vector>

namespace sp {

const char* canon_status_str(CanonStatus s) {
    switch (s) {
        case CanonStatus::Ok:         return "ok";
        case CanonStatus::NonAscii:   return "non-ascii input";
        case CanonStatus::BadJson:    return "malformed json";
        case CanonStatus::EscapedKey: return "escape in object key";
        case CanonStatus::DupKey:     return "duplicate object key";
        case CanonStatus::TooDeep:    return "nesting too deep";
        case CanonStatus::NotObject:  return "top level not an object";
        case CanonStatus::TooLarge:   return "input too large";
    }
    return "unknown";
}

namespace {

struct Cursor {
    const char* p;
    const char* end;
    CanonStatus err = CanonStatus::Ok;

    bool done() const { return p >= end; }
    char peek() const { return *p; }

    void skip_ws() {
        while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) ++p;
    }

    bool fail(CanonStatus s) {
        if (err == CanonStatus::Ok) err = s;
        return false;
    }
};

bool scan_value(Cursor& c, int depth, const char** start, size_t* len);

// Scan a string lexeme starting at '"'. Sets *had_escape. Span includes quotes.
bool scan_string(Cursor& c, const char** start, size_t* len, bool* had_escape) {
    const char* s = c.p;
    if (c.done() || *c.p != '"') return c.fail(CanonStatus::BadJson);
    ++c.p;
    bool esc_seen = false;
    while (!c.done()) {
        char ch = *c.p;
        if (ch == '\\') {
            esc_seen = true;
            ++c.p;
            if (c.done()) return c.fail(CanonStatus::BadJson);
            char e = *c.p;
            if (e == '"' || e == '\\' || e == '/' || e == 'b' || e == 'f' ||
                e == 'n' || e == 'r' || e == 't') {
                ++c.p;
            } else if (e == 'u') {
                ++c.p;
                for (int i = 0; i < 4; ++i) {
                    if (c.done()) return c.fail(CanonStatus::BadJson);
                    char h = *c.p;
                    bool hex = (h >= '0' && h <= '9') || (h >= 'a' && h <= 'f') ||
                               (h >= 'A' && h <= 'F');
                    if (!hex) return c.fail(CanonStatus::BadJson);
                    ++c.p;
                }
            } else {
                return c.fail(CanonStatus::BadJson);
            }
        } else if (ch == '"') {
            ++c.p;
            *start = s;
            *len = (size_t)(c.p - s);
            if (had_escape) *had_escape = esc_seen;
            return true;
        } else if ((unsigned char)ch < 0x20) {
            // Raw control characters are not valid inside JSON strings.
            return c.fail(CanonStatus::BadJson);
        } else {
            ++c.p;
        }
    }
    return c.fail(CanonStatus::BadJson);
}

// Scan a number lexeme per JSON grammar; span copied verbatim by callers.
bool scan_number(Cursor& c, const char** start, size_t* len) {
    const char* s = c.p;
    if (!c.done() && *c.p == '-') ++c.p;
    if (c.done()) return c.fail(CanonStatus::BadJson);
    if (*c.p == '0') {
        ++c.p;
    } else if (*c.p >= '1' && *c.p <= '9') {
        while (!c.done() && *c.p >= '0' && *c.p <= '9') ++c.p;
    } else {
        return c.fail(CanonStatus::BadJson);
    }
    if (!c.done() && *c.p == '.') {
        ++c.p;
        if (c.done() || *c.p < '0' || *c.p > '9') return c.fail(CanonStatus::BadJson);
        while (!c.done() && *c.p >= '0' && *c.p <= '9') ++c.p;
    }
    if (!c.done() && (*c.p == 'e' || *c.p == 'E')) {
        ++c.p;
        if (!c.done() && (*c.p == '+' || *c.p == '-')) ++c.p;
        if (c.done() || *c.p < '0' || *c.p > '9') return c.fail(CanonStatus::BadJson);
        while (!c.done() && *c.p >= '0' && *c.p <= '9') ++c.p;
    }
    *start = s;
    *len = (size_t)(c.p - s);
    return true;
}

bool scan_literal(Cursor& c, const char* lit, const char** start, size_t* len) {
    size_t n = strlen(lit);
    if ((size_t)(c.end - c.p) < n || strncmp(c.p, lit, n) != 0)
        return c.fail(CanonStatus::BadJson);
    *start = c.p;
    *len = n;
    c.p += n;
    return true;
}

struct Member {
    const char* key;      // key content (inside the quotes)
    size_t key_len;
    const char* val;      // raw value span
    size_t val_len;
};

// Scan an object; returns its members (unsorted) and the full span.
bool scan_object(Cursor& c, int depth, std::vector<Member>& members,
                 const char** start, size_t* len) {
    if (depth > kMaxDepth) return c.fail(CanonStatus::TooDeep);
    const char* s = c.p;
    if (c.done() || *c.p != '{') return c.fail(CanonStatus::BadJson);
    ++c.p;
    c.skip_ws();
    if (!c.done() && *c.p == '}') {
        ++c.p;
        *start = s;
        *len = (size_t)(c.p - s);
        return true;
    }
    while (true) {
        c.skip_ws();
        const char* kspan;
        size_t kspan_len;
        bool kesc = false;
        if (!scan_string(c, &kspan, &kspan_len, &kesc)) return false;
        if (kesc) return c.fail(CanonStatus::EscapedKey);
        c.skip_ws();
        if (c.done() || *c.p != ':') return c.fail(CanonStatus::BadJson);
        ++c.p;
        c.skip_ws();
        const char* vspan;
        size_t vspan_len;
        if (!scan_value(c, depth + 1, &vspan, &vspan_len)) return false;
        Member m;
        m.key = kspan + 1;             // strip quotes
        m.key_len = kspan_len - 2;
        m.val = vspan;
        m.val_len = vspan_len;
        members.push_back(m);
        c.skip_ws();
        if (c.done()) return c.fail(CanonStatus::BadJson);
        if (*c.p == ',') {
            ++c.p;
            continue;
        }
        if (*c.p == '}') {
            ++c.p;
            *start = s;
            *len = (size_t)(c.p - s);
            return true;
        }
        return c.fail(CanonStatus::BadJson);
    }
}

bool scan_array(Cursor& c, int depth, const char** start, size_t* len) {
    if (depth > kMaxDepth) return c.fail(CanonStatus::TooDeep);
    const char* s = c.p;
    if (c.done() || *c.p != '[') return c.fail(CanonStatus::BadJson);
    ++c.p;
    c.skip_ws();
    if (!c.done() && *c.p == ']') {
        ++c.p;
        *start = s;
        *len = (size_t)(c.p - s);
        return true;
    }
    while (true) {
        c.skip_ws();
        const char* vspan;
        size_t vspan_len;
        if (!scan_value(c, depth + 1, &vspan, &vspan_len)) return false;
        c.skip_ws();
        if (c.done()) return c.fail(CanonStatus::BadJson);
        if (*c.p == ',') {
            ++c.p;
            continue;
        }
        if (*c.p == ']') {
            ++c.p;
            *start = s;
            *len = (size_t)(c.p - s);
            return true;
        }
        return c.fail(CanonStatus::BadJson);
    }
}

bool scan_value(Cursor& c, int depth, const char** start, size_t* len) {
    if (depth > kMaxDepth) return c.fail(CanonStatus::TooDeep);
    if (c.done()) return c.fail(CanonStatus::BadJson);
    char ch = *c.p;
    if (ch == '{') {
        std::vector<Member> ignored;
        return scan_object(c, depth, ignored, start, len);
    }
    if (ch == '[') return scan_array(c, depth, start, len);
    if (ch == '"') return scan_string(c, start, len, nullptr);
    if (ch == 't') return scan_literal(c, "true", start, len);
    if (ch == 'f') return scan_literal(c, "false", start, len);
    if (ch == 'n') return scan_literal(c, "null", start, len);
    if (ch == '-' || (ch >= '0' && ch <= '9')) return scan_number(c, start, len);
    return c.fail(CanonStatus::BadJson);
}

bool key_less(const Member& a, const Member& b) {
    size_t n = a.key_len < b.key_len ? a.key_len : b.key_len;
    int cmp = memcmp(a.key, b.key, n);
    if (cmp != 0) return cmp < 0;
    return a.key_len < b.key_len;
}

// Emit a raw value span in canonical form: scalars verbatim, containers
// re-walked so nested objects sort and nested whitespace dies.
CanonStatus emit_value(const char* span, size_t len, int depth, std::string& out);

CanonStatus emit_object(const char* span, size_t len, int depth, std::string& out,
                        const char* drop_key) {
    Cursor c{span, span + len};
    std::vector<Member> members;
    const char* s;
    size_t sl;
    if (!scan_object(c, depth, members, &s, &sl)) return c.err;

    // Insertion sort by raw key bytes (member counts are small).
    for (size_t i = 1; i < members.size(); ++i) {
        Member cur = members[i];
        size_t j = i;
        while (j > 0 && key_less(cur, members[j - 1])) {
            members[j] = members[j - 1];
            --j;
        }
        members[j] = cur;
    }
    for (size_t i = 1; i < members.size(); ++i) {
        if (members[i].key_len == members[i - 1].key_len &&
            memcmp(members[i].key, members[i - 1].key, members[i].key_len) == 0)
            return CanonStatus::DupKey;
    }

    out.push_back('{');
    bool first = true;
    for (const Member& m : members) {
        if (drop_key != nullptr && m.key_len == strlen(drop_key) &&
            memcmp(m.key, drop_key, m.key_len) == 0)
            continue;
        if (!first) out.push_back(',');
        first = false;
        out.push_back('"');
        out.append(m.key, m.key_len);
        out.append("\":", 2);
        CanonStatus st = emit_value(m.val, m.val_len, depth + 1, out);
        if (st != CanonStatus::Ok) return st;
    }
    out.push_back('}');
    return CanonStatus::Ok;
}

CanonStatus emit_array(const char* span, size_t len, int depth, std::string& out) {
    Cursor c{span, span + len};
    if (c.done() || *c.p != '[') return CanonStatus::BadJson;
    ++c.p;
    out.push_back('[');
    c.skip_ws();
    bool first = true;
    while (!c.done() && *c.p != ']') {
        if (!first) {
            if (*c.p != ',') return CanonStatus::BadJson;
            ++c.p;
            c.skip_ws();
        }
        const char* vspan;
        size_t vspan_len;
        if (!scan_value(c, depth + 1, &vspan, &vspan_len)) return c.err;
        if (!first) out.push_back(',');
        first = false;
        CanonStatus st = emit_value(vspan, vspan_len, depth + 1, out);
        if (st != CanonStatus::Ok) return st;
        c.skip_ws();
    }
    if (c.done()) return CanonStatus::BadJson;
    out.push_back(']');
    return CanonStatus::Ok;
}

CanonStatus emit_value(const char* span, size_t len, int depth, std::string& out) {
    if (depth > kMaxDepth) return CanonStatus::TooDeep;
    if (len == 0) return CanonStatus::BadJson;
    char ch = span[0];
    if (ch == '{') return emit_object(span, len, depth, out, nullptr);
    if (ch == '[') return emit_array(span, len, depth, out);
    // Scalar: copy the lexeme verbatim.
    out.append(span, len);
    return CanonStatus::Ok;
}

}  // namespace

CanonStatus canonicalize(const char* json, size_t len, std::string& out,
                         const char* drop_top_key) {
    out.clear();
    if (len > kMaxInput) return CanonStatus::TooLarge;
    for (size_t i = 0; i < len; ++i) {
        if ((unsigned char)json[i] & 0x80) return CanonStatus::NonAscii;
    }
    Cursor c{json, json + len};
    c.skip_ws();
    if (c.done() || *c.p != '{') return CanonStatus::NotObject;

    const char* span = c.p;
    // Validate the whole object first (also finds its true extent).
    {
        Cursor v{c.p, c.end};
        std::vector<Member> ignored;
        const char* s;
        size_t sl;
        if (!scan_object(v, 0, ignored, &s, &sl)) return v.err;
        // Trailing garbage after the top-level object is malformed.
        v.skip_ws();
        if (!v.done()) return CanonStatus::BadJson;
        len = sl;
    }
    out.reserve(len);
    return emit_object(span, len, 0, out, drop_top_key);
}

bool find_member_span(const char* json, size_t len, const char* key,
                      const char** span, size_t* span_len) {
    if (len > kMaxInput) return false;
    Cursor c{json, json + len};
    c.skip_ws();
    std::vector<Member> members;
    const char* s;
    size_t sl;
    if (c.done() || *c.p != '{') return false;
    if (!scan_object(c, 0, members, &s, &sl)) return false;
    size_t klen = strlen(key);
    for (const Member& m : members) {
        if (m.key_len == klen && memcmp(m.key, key, klen) == 0) {
            *span = m.val;
            *span_len = m.val_len;
            return true;
        }
    }
    return false;
}

}  // namespace sp
