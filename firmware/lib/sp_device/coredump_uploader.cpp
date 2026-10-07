#include "coredump_uploader.h"

#include <esp_core_dump.h>
#include <esp_partition.h>

#include <string>

#include "coredump_drain.h"
#include "log_forward.h"
#include "sha256.h"

namespace sp_device {
namespace coredump {

namespace {

MqttLink* g_link = nullptr;
sp::KvStore* g_kv = nullptr;
const esp_partition_t* g_part = nullptr;
sp::CoredumpDrain g_drain;
std::string g_topic;

// One chunk: read it from flash, base64 it, stream it out.
bool publish_chunk(uint32_t seq) {
    uint8_t buf[sp::kCoredumpChunkBytes];
    char b64[((sp::kCoredumpChunkBytes + 2) / 3) * 4 + 1];
    const uint32_t len = g_drain.chunk_len(seq);
    if (len == 0) return false;
    if (esp_partition_read(g_part, g_drain.chunk_offset(seq), buf, len) !=
        ESP_OK)
        return false;
    if (sp::base64_encode(buf, len, b64, sizeof(b64)) == 0) return false;
    JsonDocument doc;
    sp::build_coredump_chunk(seq, g_drain.total_chunks(), len, b64,
                             g_drain.id(), doc);
    return g_link->connected() && g_link->publish(g_topic.c_str(), doc);
}

}  // namespace

void begin(MqttLink& link, sp::KvStore& kv) {
    g_link = &link;
    g_kv = &kv;
    g_topic = link.topic("coredump/chunk");

    size_t addr = 0;
    size_t img_size = 0;
    if (esp_core_dump_image_get(&addr, &img_size) != ESP_OK || img_size == 0) {
        sp::coredump_forget(kv);  // nothing held: drop any stale counter
        return;
    }
    g_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                      ESP_PARTITION_SUBTYPE_DATA_COREDUMP,
                                      nullptr);
    if (g_part == nullptr || img_size > g_part->size) {
        SP_LOG(LOG_ERROR, "[COREDUMP] %u-byte dump does not fit its partition "
                          "- not uploaded", (unsigned)img_size);
        return;
    }

    // The id: SHA-256 over exactly the bytes the chunks will carry. Runs in
    // setup(), before the loop WDT is armed (128 KB at most: a few ms).
    sp::Sha256 sha;
    uint8_t buf[sp::kCoredumpChunkBytes];
    for (size_t off = 0; off < img_size; off += sizeof(buf)) {
        size_t n = img_size - off;
        if (n > sizeof(buf)) n = sizeof(buf);
        if (esp_partition_read(g_part, off, buf, n) != ESP_OK) {
            SP_LOG(LOG_ERROR, "[COREDUMP] flash read failed at %u - dump kept, "
                              "not uploaded", (unsigned)off);
            return;
        }
        sha.update(buf, n);
    }
    uint8_t digest[32];
    sha.finish(digest);
    char id[sp::kCoredumpIdLen + 1];
    sp::coredump_id_hex(digest, id);

    const uint32_t prior = sp::coredump_prior_uploads(kv, id);
    g_drain.begin((uint32_t)img_size, id, prior, millis());
    if (g_drain.state() == sp::CoredumpDrain::State::Kept) {
        SP_LOG(LOG_WARN,
               "[COREDUMP] %u-byte dump %.16s kept in flash: uploaded %u "
               "times and never acknowledged (Pi server without coredump "
               "acks?) - not uploading again",
               (unsigned)img_size, id, (unsigned)prior);
    } else {
        SP_LOG(LOG_WARN,
               "[COREDUMP] previous run panicked: %u-byte dump %.16s queued "
               "for upload (%u chunks)",
               (unsigned)img_size, id, (unsigned)g_drain.total_chunks());
    }
}

void loop(uint32_t now_ms, bool ack_verifiable) {
    if (g_link == nullptr || !g_drain.holds_dump()) return;
    using State = sp::CoredumpDrain::State;
    const State before = g_drain.state();
    uint32_t n = g_drain.poll(now_ms, g_link->connected(), ack_verifiable);
    for (; n > 0; --n) {
        const sp::CoredumpDrain::Sent sent =
            g_drain.chunk_sent(millis(), publish_chunk(g_drain.next_seq()));
        if (sent == sp::CoredumpDrain::Sent::Next) continue;
        if (sent == sp::CoredumpDrain::Sent::Complete) {
            sp::coredump_note_uploads(*g_kv, g_drain.id(),
                                      g_drain.uploads_total());
            SP_LOG(LOG_INFO,
                   "[COREDUMP] dump %.16s uploaded (try %u) - kept in flash "
                   "until the Pi acknowledges it",
                   g_drain.id(), (unsigned)g_drain.uploads_total());
        }
        break;
    }
    const State after = g_drain.state();
    if (after == before) return;
    if (after == State::Kept) {
        SP_LOG(LOG_WARN,
               "[COREDUMP] dump %.16s: no acknowledgement after %u uploads "
               "(%u interrupted) - kept in flash, no more uploads this boot",
               g_drain.id(), (unsigned)g_drain.uploads_this_boot(),
               (unsigned)g_drain.interrupted_this_boot());
    } else if (after == State::Waiting) {
        SP_LOG(LOG_WARN,
               "[COREDUMP] dump %.16s: %s - retrying later",
               g_drain.id(),
               before == State::AwaitAck ? "no acknowledgement from the Pi"
                                         : "upload interrupted");
    }
}

void on_ack(JsonDocument& doc) {
    const char* id = sp::coredump_ack_id(doc);
    if (id == nullptr) {
        SP_LOG(LOG_WARN, "[COREDUMP] cmd/%s without a valid coredump_id - "
                         "ignored", sp::kCoredumpAckSuffix);
        return;
    }
    if (!g_drain.ack(id)) {
        SP_LOG(LOG_INFO, "[COREDUMP] ack for %.16s ignored - not the dump held",
               id);
        return;
    }
    const esp_err_t err = esp_core_dump_image_erase();
    // Forget the upload count either way: if the erase failed, the next boot
    // uploads the same dump again, the Pi re-acknowledges it without storing
    // a second copy, and the erase is retried.
    if (g_kv != nullptr) sp::coredump_forget(*g_kv);
    if (err != ESP_OK) {
        SP_LOG(LOG_ERROR, "[COREDUMP] Pi stored dump %.16s but the erase "
                          "failed (%s) - retried next boot",
               g_drain.id(), esp_err_to_name(err));
        return;
    }
    SP_LOG(LOG_INFO, "[COREDUMP] Pi stored dump %.16s - erased from flash",
           g_drain.id());
}

bool pending() { return g_drain.holds_dump(); }

}  // namespace coredump
}  // namespace sp_device
