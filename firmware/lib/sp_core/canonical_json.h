#pragma once
//
// canonical_json — raw-token JSON canonicalizer for HMAC frame signing.
//
// Produces byte-identical output to Python's
//   json.dumps(obj, sort_keys=True, separators=(",", ":"))
// for the subset of JSON that signed SporePrint frames use, WITHOUT ever
// parsing numbers or unescaping strings. Scalar lexemes (numbers, strings,
// true/false/null) are copied verbatim from the input, so Python's number
// formatting ("1700000000.0" stays "1700000000.0") survives the round trip.
// A parse→re-serialize canonicalizer cannot do this: ArduinoJson renders an
// integral double as "1700000000" and the signature dies.
//
// Canonical transform:
//   * all inter-token whitespace removed
//   * object members sorted by key at EVERY depth (byte order — equal to
//     Python's str sort for the ASCII-only keys we enforce)
//   * one designated top-level member (the signature) dropped
//   * array order and every scalar lexeme preserved verbatim
//
// Fail-closed constraints (any violation rejects the frame):
//   * input must be pure ASCII (compliant peers use json.dumps ensure_ascii,
//     so wire bytes are always ASCII; \uXXXX escapes in VALUES are fine and
//     copied verbatim)
//   * object keys must be escape-free (raw-byte key sort would diverge from
//     Python's decoded-string sort if keys contained escapes)
//   * duplicate keys rejected
//   * nesting depth capped
//
// Native-safe: no Arduino headers, no Arduino String. Mirrors (and must stay
// in lockstep with) the Python signers:
//   sporeprint/server/app/mqtt.py::_sign_cmd_payload
//   sporeprint/server/app/cloud/signing.py
// Golden vectors: test/fixtures/signing_vectors.json (shared 3-way).

#include <stddef.h>
#include <stdint.h>
#include <string>

namespace sp {

enum class CanonStatus : uint8_t {
    Ok = 0,
    NonAscii,     // byte >= 0x80 anywhere in the input
    BadJson,      // tokenizer / grammar error
    EscapedKey,   // object key contains a backslash escape
    DupKey,       // duplicate key inside one object
    TooDeep,      // nesting beyond kMaxDepth
    NotObject,    // top-level value is not an object
    TooLarge,     // input longer than kMaxInput
};

constexpr size_t kMaxInput = 4096;  // signed cmd frames are <= 1024 on the wire
constexpr int kMaxDepth = 8;

const char* canon_status_str(CanonStatus s);

// Canonicalize `json[0..len)` into `out`. If `drop_top_key` is non-null,
// a member with that exact key is removed at the TOP level only (matching
// Python's `{k: v for k, v in frame.items() if k != "signature"}`).
CanonStatus canonicalize(const char* json, size_t len, std::string& out,
                         const char* drop_top_key);

// Locate a top-level member's raw value span (lexeme bytes, untouched).
// For string values the span INCLUDES the surrounding quotes.
// Returns false if the input is not a parseable object or the key is absent.
bool find_member_span(const char* json, size_t len, const char* key,
                      const char** span, size_t* span_len);

}  // namespace sp
