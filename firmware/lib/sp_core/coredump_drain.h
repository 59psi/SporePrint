#pragma once
//
// coredump_drain — the node half of the coredump store-then-ack protocol.
// Pure and host-tested (test_core_coredump); sp_device/coredump_uploader.cpp
// is the flash + MQTT adapter around it.
//
// Wire contract (additive to the v4.2 chunk upload):
//
//   node → Pi  sporeprint/<id>/coredump/chunk
//              {seq, total, size, b64_data, coredump_id}
//              coredump_id: lowercase hex SHA-256 of the whole dump — exactly
//              the bytes the chunks carry, in seq order. A Pi without ack
//              support ignores the key.
//   Pi → node  sporeprint/<id>/cmd/coredump_ack  {"coredump_id": "<same id>"}
//              signed and topic/nonce-bound like every cmd/* frame. The Pi
//              sends it only after the reassembled dump hashed to the id AND
//              the file is durably on disk; a re-upload of a dump it already
//              stored is acknowledged again, never stored twice.
//
// The node erases the flash dump ONLY on an authenticated ack naming the
// exact id of the dump it holds. Before this, the uploader erased as soon as
// the last QoS 0 chunk left the node — a Pi restart, a full disk or a lost
// chunk destroyed the only copy of the crash.
//
// Retries are bounded so a Pi too old to acknowledge (it still stores every
// upload as a new file) gets a handful of copies, not one per boot forever:
//   * an upload whose ack does not arrive within ack_timeout_ms, or that is
//     cut short (link loss, failed publish), is retried after a backoff of
//     retry_base_ms doubling to retry_max_ms;
//   * at most uploads_per_boot complete uploads per boot, and
//     uploads_per_dump per dump across boots (counted in NVS by id);
//   * then the dump is KEPT in flash, unacknowledged, with no more uploads.
//     The next panic overwrites it; nothing else is lost.
// The upload never blocks the loop: poll() hands out at most chunks_per_pass
// chunks per pass, and only while MQTT is connected.
//
// Native-safe: no Arduino headers (ArduinoJson is header-only).

#include <ArduinoJson.h>

#include <stddef.h>
#include <stdint.h>

#include "base64_codec.h"  // the chunk's b64_data
#include "kv_store.h"

namespace sp {

// cmd/<suffix> the Pi acknowledges a stored dump on.
constexpr const char* kCoredumpAckSuffix = "coredump_ack";
// Raw bytes per chunk (base64 → 684 chars; the chunk document stays well
// under 1 KB, and MqttLink streams it, so no client buffer bounds it).
constexpr uint32_t kCoredumpChunkBytes = 512;
// Lowercase hex SHA-256.
constexpr size_t kCoredumpIdLen = 64;
// NVS keys: the id of the dump the counter belongs to, and its complete
// un-acknowledged uploads on earlier boots.
constexpr const char* kCoredumpNvsId = "cd_id";
constexpr const char* kCoredumpNvsUploads = "cd_up";

struct CoredumpPolicy {
    uint32_t ack_timeout_ms = 30000;
    uint32_t retry_base_ms = 60000;
    uint32_t retry_max_ms = 15UL * 60UL * 1000UL;
    // With a signing key provisioned the node rejects every command until
    // NTP has synced — the ack too. The first upload waits up to this long
    // for the clock, then goes anyway (the Pi stores it regardless).
    uint32_t clock_wait_ms = 120000;
    uint8_t uploads_per_boot = 3;
    uint8_t uploads_per_dump = 6;
    uint8_t interrupted_per_boot = 8;
    uint8_t chunks_per_pass = 4;
};

class CoredumpDrain {
public:
    enum class State : uint8_t {
        NoDump,     // nothing in flash
        Waiting,    // dump held; next upload not due (link down, clock, backoff)
        Uploading,  // chunks going out, next_seq() is next
        AwaitAck,   // every chunk published; waiting for cmd/coredump_ack
        Kept,       // retries exhausted: the dump stays in flash, no uploads
        Erased,     // acknowledged — the caller erased the flash dump
    };

    explicit CoredumpDrain(const CoredumpPolicy& policy = CoredumpPolicy())
        : policy_(policy) {}

    // A dump of `size` bytes whose SHA-256 is `id_hex` is in flash.
    // `prior_uploads` = complete un-acknowledged uploads of this same dump on
    // earlier boots (coredump_prior_uploads()). size 0 or a malformed id
    // leaves the drain idle (NoDump).
    void begin(uint32_t size, const char* id_hex, uint32_t prior_uploads,
               uint32_t now_ms);

    // One loop pass. `link_up`: MQTT connected. `ack_verifiable`: an ack
    // would pass command verification now (no signing key, or the clock is
    // synced). Returns how many chunks to publish this pass, starting at
    // next_seq(); report each with chunk_sent(), in order.
    uint32_t poll(uint32_t now_ms, bool link_up, bool ack_verifiable);

    enum class Sent : uint8_t {
        Next,         // published; carry on
        Complete,     // that was the last chunk: persist uploads_total()
        Interrupted,  // the publish failed: stop this pass, retry later
    };
    Sent chunk_sent(uint32_t now_ms, bool ok);

    // An authenticated cmd/coredump_ack named `id_hex`. True = it names the
    // dump held: erase the flash dump now (the drain is then Erased).
    bool ack(const char* id_hex);

    State state() const { return state_; }
    bool holds_dump() const {
        return state_ == State::Waiting || state_ == State::Uploading ||
               state_ == State::AwaitAck || state_ == State::Kept;
    }
    const char* id() const { return id_; }
    uint32_t size() const { return size_; }
    uint32_t total_chunks() const { return total_; }
    uint32_t next_seq() const { return seq_; }
    uint32_t chunk_offset(uint32_t seq) const {
        return seq * kCoredumpChunkBytes;
    }
    uint32_t chunk_len(uint32_t seq) const;
    // Complete uploads of this dump, earlier boots included (persist it).
    uint32_t uploads_total() const { return uploads_total_; }
    uint32_t uploads_this_boot() const { return uploads_boot_; }
    uint32_t interrupted_this_boot() const { return interrupted_; }

private:
    void retry_later(uint32_t now_ms);

    CoredumpPolicy policy_;
    State state_ = State::NoDump;
    char id_[kCoredumpIdLen + 1] = {0};
    uint32_t size_ = 0;
    uint32_t total_ = 0;
    uint32_t seq_ = 0;
    uint32_t begin_ms_ = 0;
    uint32_t wait_from_ms_ = 0;
    uint32_t wait_ms_ = 0;
    uint32_t ack_from_ms_ = 0;
    uint32_t uploads_total_ = 0;
    uint32_t uploads_boot_ = 0;
    uint32_t interrupted_ = 0;
    uint32_t failures_ = 0;  // missed acks + interrupted uploads this boot
};

// 64 lowercase hex characters, nothing else.
bool coredump_id_valid(const char* id_hex);
// `out` gets 64 lowercase hex characters + NUL.
void coredump_id_hex(const uint8_t digest[32], char out[kCoredumpIdLen + 1]);

// The chunk document. `b64` and `coredump_id` must outlive `doc`'s publish.
inline void build_coredump_chunk(uint32_t seq, uint32_t total, uint32_t size,
                                 const char* b64, const char* coredump_id,
                                 JsonDocument& doc) {
    doc["seq"] = seq;
    doc["total"] = total;
    doc["size"] = size;
    doc["b64_data"] = b64;
    doc["coredump_id"] = coredump_id;
}

// The id a cmd/coredump_ack names, or nullptr when the frame has none / a
// malformed one.
const char* coredump_ack_id(JsonDocument& doc);

// NVS bookkeeping for the per-dump upload cap.
uint32_t coredump_prior_uploads(KvStore& kv, const char* id_hex);
void coredump_note_uploads(KvStore& kv, const char* id_hex, uint32_t uploads);
void coredump_forget(KvStore& kv);

}  // namespace sp
