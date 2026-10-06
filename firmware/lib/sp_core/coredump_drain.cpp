#include "coredump_drain.h"

#include <string.h>

#include "wrap_time.h"

namespace sp {

namespace {

const char kHex[] = "0123456789abcdef";

}  // namespace

bool coredump_id_valid(const char* id_hex) {
    if (id_hex == nullptr) return false;
    size_t i = 0;
    for (; id_hex[i] != '\0'; ++i) {
        if (i >= kCoredumpIdLen) return false;
        const char c = id_hex[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    }
    return i == kCoredumpIdLen;
}

void coredump_id_hex(const uint8_t digest[32], char out[kCoredumpIdLen + 1]) {
    for (size_t i = 0; i < 32; ++i) {
        out[i * 2] = kHex[digest[i] >> 4];
        out[i * 2 + 1] = kHex[digest[i] & 0x0F];
    }
    out[kCoredumpIdLen] = '\0';
}

const char* coredump_ack_id(JsonDocument& doc) {
    JsonVariant v = doc["coredump_id"];
    if (!v.is<const char*>()) return nullptr;
    const char* id = v.as<const char*>();
    return coredump_id_valid(id) ? id : nullptr;
}

uint32_t coredump_prior_uploads(KvStore& kv, const char* id_hex) {
    if (!coredump_id_valid(id_hex)) return 0;
    if (kv.get_string(kCoredumpNvsId, "") != id_hex) return 0;
    const int32_t n = kv.get_int(kCoredumpNvsUploads, 0);
    return n > 0 ? (uint32_t)n : 0;
}

void coredump_note_uploads(KvStore& kv, const char* id_hex,
                           uint32_t uploads) {
    if (!coredump_id_valid(id_hex)) return;
    if (kv.get_string(kCoredumpNvsId, "") != id_hex)
        kv.set_string(kCoredumpNvsId, id_hex);
    kv.set_int(kCoredumpNvsUploads, (int32_t)uploads);
}

void coredump_forget(KvStore& kv) {
    // Only when something is recorded: no NVS write on an ordinary boot.
    if (kv.get_string(kCoredumpNvsId, "").empty()) return;
    kv.set_string(kCoredumpNvsId, "");
    kv.set_int(kCoredumpNvsUploads, 0);
}

void CoredumpDrain::begin(uint32_t size, const char* id_hex,
                          uint32_t prior_uploads, uint32_t now_ms) {
    state_ = State::NoDump;
    id_[0] = '\0';
    size_ = 0;
    total_ = 0;
    seq_ = 0;
    uploads_boot_ = 0;
    interrupted_ = 0;
    failures_ = 0;
    uploads_total_ = 0;
    if (size == 0 || !coredump_id_valid(id_hex)) return;

    memcpy(id_, id_hex, kCoredumpIdLen + 1);
    size_ = size;
    total_ = (size + kCoredumpChunkBytes - 1) / kCoredumpChunkBytes;
    begin_ms_ = now_ms;
    uploads_total_ = prior_uploads;
    if (prior_uploads >= policy_.uploads_per_dump) {
        state_ = State::Kept;
        return;
    }
    state_ = State::Waiting;
    wait_from_ms_ = now_ms;
    wait_ms_ = 0;  // due as soon as the link is up
}

uint32_t CoredumpDrain::chunk_len(uint32_t seq) const {
    if (seq >= total_) return 0;
    const uint32_t remaining = size_ - chunk_offset(seq);
    return remaining < kCoredumpChunkBytes ? remaining : kCoredumpChunkBytes;
}

void CoredumpDrain::retry_later(uint32_t now_ms) {
    ++failures_;
    uint32_t wait = policy_.retry_base_ms;
    for (uint32_t i = 1; i < failures_ && wait < policy_.retry_max_ms; ++i)
        wait *= 2;
    if (wait > policy_.retry_max_ms) wait = policy_.retry_max_ms;
    wait_ms_ = wait;
    wait_from_ms_ = now_ms;
    state_ = State::Waiting;
}

uint32_t CoredumpDrain::poll(uint32_t now_ms, bool link_up,
                             bool ack_verifiable) {
    switch (state_) {
        case State::Waiting:
            if (!link_up) return 0;
            if (elapsed_ms(now_ms, wait_from_ms_) < wait_ms_) return 0;
            // An ack sent now would be rejected (key set, clock unsynced):
            // give NTP a little time first — but never hold the dump back
            // indefinitely, the Pi stores it either way.
            if (!ack_verifiable &&
                elapsed_ms(now_ms, begin_ms_) < policy_.clock_wait_ms)
                return 0;
            state_ = State::Uploading;
            seq_ = 0;
            break;
        case State::Uploading:
            if (!link_up) {
                // The link dropped mid-upload: the Pi's half-built assembly
                // is abandoned and restarts at seq 0 next time.
                ++interrupted_;
                if (interrupted_ >= policy_.interrupted_per_boot)
                    state_ = State::Kept;
                else
                    retry_later(now_ms);
                return 0;
            }
            break;
        case State::AwaitAck:
            if (elapsed_ms(now_ms, ack_from_ms_) < policy_.ack_timeout_ms)
                return 0;
            // No ack: a Pi without ack support, a lost frame, or an ack the
            // node could not verify. A late ack is still honoured (ack()).
            if (uploads_boot_ >= policy_.uploads_per_boot ||
                uploads_total_ >= policy_.uploads_per_dump)
                state_ = State::Kept;
            else
                retry_later(now_ms);
            return 0;
        default:
            return 0;
    }
    const uint32_t remaining = total_ - seq_;
    return remaining < policy_.chunks_per_pass ? remaining
                                               : policy_.chunks_per_pass;
}

CoredumpDrain::Sent CoredumpDrain::chunk_sent(uint32_t now_ms, bool ok) {
    if (state_ != State::Uploading) return Sent::Interrupted;
    if (!ok) {
        ++interrupted_;
        if (interrupted_ >= policy_.interrupted_per_boot)
            state_ = State::Kept;
        else
            retry_later(now_ms);
        return Sent::Interrupted;
    }
    ++seq_;
    if (seq_ < total_) return Sent::Next;
    ++uploads_boot_;
    ++uploads_total_;
    state_ = State::AwaitAck;
    ack_from_ms_ = now_ms;
    return Sent::Complete;
}

bool CoredumpDrain::ack(const char* id_hex) {
    if (!holds_dump() || !coredump_id_valid(id_hex)) return false;
    if (strcmp(id_hex, id_) != 0) return false;
    state_ = State::Erased;
    return true;
}

}  // namespace sp
