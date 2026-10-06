// test_core_coredump — the node half of the coredump store-then-ack protocol
// (sp_core/coredump_drain.h) and the pieces it is built from.
//
// Pinned here:
//   * the dump id: lowercase hex SHA-256 (streamed in 512-byte reads) — the
//     FIPS 180-4 vectors, and streaming == one-shot at every split point, so
//     it equals the Pi's hashlib.sha256(dump).hexdigest()
//   * RFC 4648 base64 (the chunk payload) and the exact chunk key set
//   * the drain: no upload while MQTT is down, a bounded wait for NTP when an
//     ack could not verify yet, a few chunks per pass, the dump erased ONLY on
//     an ack naming its exact id (also a late one), missed-ack and
//     interrupted-upload backoff (1, 2, 4 ... 15 min), the per-boot and
//     per-dump (NVS) upload caps after which the dump is kept, millis() wrap
//   * the NVS bookkeeping: counts follow the id, no write on a clean boot

#include <unity.h>

#include <stdio.h>
#include <string.h>

#include <string>

#include "coredump_drain.h"
#include "kv_store.h"
#include "sha256.h"

using sp::CoredumpDrain;
using State = sp::CoredumpDrain::State;
using Sent = sp::CoredumpDrain::Sent;

void setUp() {}
void tearDown() {}

#define ASSERT_STATE(want, drain) \
    TEST_ASSERT_EQUAL((int)(want), (int)(drain).state())

static const char kId[] =
    "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1";
static const char kOtherId[] =
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

// Publish every chunk poll() hands out this pass; returns how many went.
static uint32_t send_pass(CoredumpDrain& d, uint32_t now, bool link_up = true,
                          bool verifiable = true) {
    uint32_t n = d.poll(now, link_up, verifiable);
    uint32_t sent = 0;
    for (; n > 0; --n) {
        ++sent;
        if (d.chunk_sent(now, true) != Sent::Next) break;
    }
    return sent;
}

// Run passes until the upload completes (AwaitAck); returns the pass count.
static uint32_t upload_all(CoredumpDrain& d, uint32_t now) {
    uint32_t passes = 0;
    while (d.state() != State::AwaitAck && passes < 1000) {
        send_pass(d, now);
        ++passes;
        if (d.state() != State::Uploading && d.state() != State::AwaitAck)
            break;
    }
    return passes;
}

// ── SHA-256 (the dump id) ──────────────────────────────────────

static void hex_of(const uint8_t d[32], char out[65]) {
    sp::coredump_id_hex(d, out);
}

void test_sha256_stream_matches_fips_vectors() {
    uint8_t d[32];
    char hex[65];
    {
        sp::Sha256 s;
        s.update((const uint8_t*)"abc", 3);
        s.finish(d);
        hex_of(d, hex);
        TEST_ASSERT_EQUAL_STRING(kOtherId, hex);
    }
    {
        const char* m =
            "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
        sp::Sha256 s;
        s.update((const uint8_t*)m, strlen(m));
        s.finish(d);
        hex_of(d, hex);
        TEST_ASSERT_EQUAL_STRING(kId, hex);
    }
    {
        sp::Sha256 s;
        s.finish(d);
        hex_of(d, hex);
        TEST_ASSERT_EQUAL_STRING(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            hex);
    }
    {
        // One million 'a' fed in 512-byte reads, like the partition drain.
        uint8_t block[512];
        memset(block, 'a', sizeof(block));
        sp::Sha256 s;
        size_t left = 1000000;
        while (left > 0) {
            size_t n = left < sizeof(block) ? left : sizeof(block);
            s.update(block, n);
            left -= n;
        }
        s.finish(d);
        hex_of(d, hex);
        TEST_ASSERT_EQUAL_STRING(
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
            hex);
    }
}

void test_sha256_stream_equals_one_shot_at_every_split() {
    uint8_t msg[200];
    for (size_t i = 0; i < sizeof(msg); ++i) msg[i] = (uint8_t)(i * 7 + 3);
    uint8_t want[32];
    sp::sha256_host(msg, sizeof(msg), want);
    for (size_t split = 0; split <= sizeof(msg); ++split) {
        sp::Sha256 s;
        s.update(msg, split);
        s.update(msg + split, sizeof(msg) - split);
        uint8_t got[32];
        s.finish(got);
        TEST_ASSERT_EQUAL_MEMORY(want, got, 32);
    }
}

// ── ids, base64, the chunk document ────────────────────────────

void test_coredump_id_validation() {
    TEST_ASSERT_TRUE(sp::coredump_id_valid(kId));
    TEST_ASSERT_FALSE(sp::coredump_id_valid(nullptr));
    TEST_ASSERT_FALSE(sp::coredump_id_valid(""));
    std::string upper(kId);
    upper[0] = 'A';  // the Pi sends lowercase; anything else is not the id
    TEST_ASSERT_FALSE(sp::coredump_id_valid(upper.c_str()));
    std::string short_id(kId, 63);
    TEST_ASSERT_FALSE(sp::coredump_id_valid(short_id.c_str()));
    std::string long_id = std::string(kId) + "0";
    TEST_ASSERT_FALSE(sp::coredump_id_valid(long_id.c_str()));
    std::string bad(kId);
    bad[10] = 'g';
    TEST_ASSERT_FALSE(sp::coredump_id_valid(bad.c_str()));
}

void test_base64_rfc4648_vectors() {
    const char* in[] = {"", "f", "fo", "foo", "foob", "fooba", "foobar"};
    const char* out[] = {"",         "Zg==",     "Zm8=",    "Zm9v",
                         "Zm9vYg==", "Zm9vYmE=", "Zm9vYmFy"};
    char buf[16];
    for (size_t i = 0; i < 7; ++i) {
        size_t n = sp::base64_encode((const uint8_t*)in[i], strlen(in[i]), buf,
                                     sizeof(buf));
        TEST_ASSERT_EQUAL_STRING(out[i], buf);
        TEST_ASSERT_EQUAL(strlen(out[i]), n);
    }
    // Every byte value + the alphabet's last two characters.
    const uint8_t hi[] = {0xFB, 0xFF, 0xBF};
    sp::base64_encode(hi, 3, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_STRING("+/+/", buf);
    // Too small (needs 9 incl. NUL for 6 bytes) → 0, nothing claimed.
    TEST_ASSERT_EQUAL(0, sp::base64_encode((const uint8_t*)"foobar", 6, buf, 8));
    TEST_ASSERT_EQUAL(8, sp::base64_encode((const uint8_t*)"foobar", 6, buf, 9));
}

void test_full_chunk_encodes_to_684_chars() {
    uint8_t raw[sp::kCoredumpChunkBytes];
    for (size_t i = 0; i < sizeof(raw); ++i) raw[i] = (uint8_t)i;
    char b64[((sp::kCoredumpChunkBytes + 2) / 3) * 4 + 1];
    TEST_ASSERT_EQUAL(684, sp::base64_encode(raw, sizeof(raw), b64, sizeof(b64)));
}

void test_chunk_document_key_set() {
    JsonDocument doc;
    sp::build_coredump_chunk(2, 3, 276, "QUJD", kId, doc);
    JsonObject o = doc.as<JsonObject>();
    const char* want[] = {"seq", "total", "size", "b64_data", "coredump_id"};
    size_t n = 0;
    for (JsonPair kv : o) {
        bool known = false;
        for (const char* k : want) known = known || strcmp(kv.key().c_str(), k) == 0;
        TEST_ASSERT_TRUE_MESSAGE(known, kv.key().c_str());
        ++n;
    }
    TEST_ASSERT_EQUAL(5, n);
    TEST_ASSERT_EQUAL(2, doc["seq"].as<int>());
    TEST_ASSERT_EQUAL(3, doc["total"].as<int>());
    TEST_ASSERT_EQUAL(276, doc["size"].as<int>());
    TEST_ASSERT_EQUAL_STRING("QUJD", doc["b64_data"].as<const char*>());
    TEST_ASSERT_EQUAL_STRING(kId, doc["coredump_id"].as<const char*>());
    // Integers on the wire (the Pi int()s them; a float would still parse,
    // but the v4.2 contract has always been integers).
    char out[200];
    serializeJson(doc, out, sizeof(out));
    TEST_ASSERT_NOT_NULL(strstr(out, "\"seq\":2,\"total\":3,\"size\":276"));
}

void test_ack_id_parsing() {
    JsonDocument doc;
    char frame[300];
    snprintf(frame, sizeof(frame),
             "{\"coredump_id\":\"%s\",\"topic\":\"sporeprint/n1/cmd/"
             "coredump_ack\",\"nonce\":\"00ff\",\"ts\":1790000000}",
             kId);
    deserializeJson(doc, frame);
    TEST_ASSERT_EQUAL_STRING(kId, sp::coredump_ack_id(doc));

    deserializeJson(doc, "{}");
    TEST_ASSERT_NULL(sp::coredump_ack_id(doc));
    deserializeJson(doc, "{\"coredump_id\":42}");
    TEST_ASSERT_NULL(sp::coredump_ack_id(doc));
    deserializeJson(doc, "{\"coredump_id\":\"abc\"}");
    TEST_ASSERT_NULL(sp::coredump_ack_id(doc));
    TEST_ASSERT_EQUAL_STRING("coredump_ack", sp::kCoredumpAckSuffix);
}

// ── the drain ──────────────────────────────────────────────────

void test_no_dump_stays_idle() {
    CoredumpDrain d;
    ASSERT_STATE(State::NoDump, d);
    TEST_ASSERT_EQUAL(0, d.poll(0, true, true));
    TEST_ASSERT_FALSE(d.ack(kId));
    d.begin(0, kId, 0, 0);  // empty
    ASSERT_STATE(State::NoDump, d);
    d.begin(1000, "not-an-id", 0, 0);
    ASSERT_STATE(State::NoDump, d);
    TEST_ASSERT_FALSE(d.holds_dump());
    TEST_ASSERT_EQUAL(Sent::Interrupted, d.chunk_sent(0, true));
}

void test_chunk_geometry() {
    CoredumpDrain d;
    d.begin(1300, kId, 0, 0);
    TEST_ASSERT_EQUAL(3, d.total_chunks());
    TEST_ASSERT_EQUAL(512, d.chunk_len(0));
    TEST_ASSERT_EQUAL(512, d.chunk_len(1));
    TEST_ASSERT_EQUAL(276, d.chunk_len(2));
    TEST_ASSERT_EQUAL(0, d.chunk_len(3));
    TEST_ASSERT_EQUAL(1024, d.chunk_offset(2));
    d.begin(1024, kId, 0, 0);
    TEST_ASSERT_EQUAL(2, d.total_chunks());
    TEST_ASSERT_EQUAL(512, d.chunk_len(1));
    // The largest partition (128 KB) is 256 chunks.
    d.begin(128 * 1024, kId, 0, 0);
    TEST_ASSERT_EQUAL(256, d.total_chunks());
}

void test_uploads_only_while_mqtt_is_up_and_erases_on_matching_ack() {
    CoredumpDrain d;
    d.begin(1300, kId, 0, 1000);
    ASSERT_STATE(State::Waiting, d);
    TEST_ASSERT_TRUE(d.holds_dump());
    TEST_ASSERT_EQUAL_STRING(kId, d.id());
    // MQTT down: nothing, however long.
    TEST_ASSERT_EQUAL(0, d.poll(1000, false, true));
    TEST_ASSERT_EQUAL(0, d.poll(900000, false, true));
    ASSERT_STATE(State::Waiting, d);
    // Up: all three chunks fit in one pass (4 per pass).
    TEST_ASSERT_EQUAL(3, d.poll(900001, true, true));
    ASSERT_STATE(State::Uploading, d);
    TEST_ASSERT_EQUAL(0, d.next_seq());
    TEST_ASSERT_EQUAL(Sent::Next, d.chunk_sent(900001, true));
    TEST_ASSERT_EQUAL(1, d.next_seq());
    TEST_ASSERT_EQUAL(Sent::Next, d.chunk_sent(900001, true));
    TEST_ASSERT_EQUAL(Sent::Complete, d.chunk_sent(900001, true));
    ASSERT_STATE(State::AwaitAck, d);
    TEST_ASSERT_EQUAL(1, d.uploads_total());
    TEST_ASSERT_EQUAL(0, d.poll(900002, true, true));  // nothing more to send
    // Only the exact id erases.
    TEST_ASSERT_FALSE(d.ack(kOtherId));
    TEST_ASSERT_FALSE(d.ack(nullptr));
    TEST_ASSERT_FALSE(d.ack("248d6a61"));
    ASSERT_STATE(State::AwaitAck, d);
    TEST_ASSERT_TRUE(d.ack(kId));
    ASSERT_STATE(State::Erased, d);
    TEST_ASSERT_FALSE(d.holds_dump());
    // Done for good: no more uploads, a repeated ack is a no-op.
    TEST_ASSERT_EQUAL(0, d.poll(2000000, true, true));
    TEST_ASSERT_FALSE(d.ack(kId));
}

void test_chunks_per_pass_bound_the_loop_pass() {
    CoredumpDrain d;
    d.begin(10 * 512, kId, 0, 0);
    TEST_ASSERT_EQUAL(4, send_pass(d, 0));
    TEST_ASSERT_EQUAL(4, send_pass(d, 1));
    TEST_ASSERT_EQUAL(8, d.next_seq());
    TEST_ASSERT_EQUAL(2, send_pass(d, 2));
    ASSERT_STATE(State::AwaitAck, d);
}

void test_waits_for_the_clock_when_an_ack_could_not_verify() {
    CoredumpDrain d;  // clock_wait_ms = 120 s
    d.begin(512, kId, 0, 5000);
    TEST_ASSERT_EQUAL(0, d.poll(5000, true, false));
    TEST_ASSERT_EQUAL(0, d.poll(5000 + 119999, true, false));
    // NTP synced → go at once.
    TEST_ASSERT_EQUAL(1, d.poll(5000 + 30000, true, true));

    // Never synced → go anyway after the wait (the Pi stores it regardless).
    CoredumpDrain e;
    e.begin(512, kId, 0, 5000);
    TEST_ASSERT_EQUAL(0, e.poll(5000 + 119999, true, false));
    TEST_ASSERT_EQUAL(1, e.poll(5000 + 120000, true, false));
}

void test_missed_ack_backs_off_then_keeps_the_dump() {
    CoredumpDrain d;  // 30 s ack wait, 1 min base backoff, 3 uploads per boot
    uint32_t t = 0;
    d.begin(1024, kId, 0, t);
    upload_all(d, t);
    ASSERT_STATE(State::AwaitAck, d);
    TEST_ASSERT_EQUAL(0, d.poll(t + 29999, true, true));
    ASSERT_STATE(State::AwaitAck, d);
    t += 30000;
    TEST_ASSERT_EQUAL(0, d.poll(t, true, true));  // ack wait over
    ASSERT_STATE(State::Waiting, d);
    // Retry 1 after 60 s, from seq 0 (the Pi restarts its assembly there).
    TEST_ASSERT_EQUAL(0, d.poll(t + 59999, true, true));
    t += 60000;
    TEST_ASSERT_EQUAL(2, d.poll(t, true, true));
    TEST_ASSERT_EQUAL(0, d.next_seq());
    d.chunk_sent(t, true);
    TEST_ASSERT_EQUAL(Sent::Complete, d.chunk_sent(t, true));
    TEST_ASSERT_EQUAL(2, d.uploads_this_boot());
    t += 30000;
    d.poll(t, true, true);
    ASSERT_STATE(State::Waiting, d);
    // Retry 2 after 120 s.
    TEST_ASSERT_EQUAL(0, d.poll(t + 119999, true, true));
    t += 120000;
    upload_all(d, t);
    ASSERT_STATE(State::AwaitAck, d);
    TEST_ASSERT_EQUAL(3, d.uploads_total());
    // Third miss: the per-boot cap — kept in flash, no more uploads.
    t += 30000;
    d.poll(t, true, true);
    ASSERT_STATE(State::Kept, d);
    TEST_ASSERT_TRUE(d.holds_dump());
    TEST_ASSERT_EQUAL(0, d.poll(t + 3600000, true, true));
    // A late ack still proves the Pi has it: erase.
    TEST_ASSERT_TRUE(d.ack(kId));
    ASSERT_STATE(State::Erased, d);
}

void test_per_dump_cap_spans_boots() {
    // Five complete un-acked uploads on earlier boots: one more, then keep.
    CoredumpDrain d;
    d.begin(512, kId, 5, 0);
    ASSERT_STATE(State::Waiting, d);
    upload_all(d, 0);
    TEST_ASSERT_EQUAL(6, d.uploads_total());
    d.poll(30000, true, true);
    ASSERT_STATE(State::Kept, d);

    // Six already: kept from boot, nothing goes out.
    CoredumpDrain e;
    e.begin(512, kId, 6, 0);
    ASSERT_STATE(State::Kept, e);
    TEST_ASSERT_TRUE(e.holds_dump());
    TEST_ASSERT_EQUAL(0, e.poll(0, true, true));
    TEST_ASSERT_EQUAL(0, e.poll(10000000, true, true));
}

void test_link_loss_mid_upload_restarts_from_seq_zero_after_backoff() {
    CoredumpDrain d;
    d.begin(10 * 512, kId, 0, 0);
    TEST_ASSERT_EQUAL(4, send_pass(d, 0));
    TEST_ASSERT_EQUAL(0, d.poll(10, false, true));  // MQTT dropped
    ASSERT_STATE(State::Waiting, d);
    TEST_ASSERT_EQUAL(1, d.interrupted_this_boot());
    TEST_ASSERT_EQUAL(0, d.uploads_total());  // an interrupted upload is not one
    TEST_ASSERT_EQUAL(0, d.poll(10 + 59999, true, true));
    TEST_ASSERT_EQUAL(4, d.poll(10 + 60000, true, true));
    TEST_ASSERT_EQUAL(0, d.next_seq());
}

void test_failed_publish_interrupts_and_is_bounded() {
    sp::CoredumpPolicy p;
    p.interrupted_per_boot = 3;
    CoredumpDrain d(p);
    d.begin(2048, kId, 0, 0);
    uint32_t t = 0;
    TEST_ASSERT_EQUAL(4, d.poll(t, true, true));
    TEST_ASSERT_EQUAL(Sent::Next, d.chunk_sent(t, true));
    TEST_ASSERT_EQUAL(Sent::Interrupted, d.chunk_sent(t, false));
    ASSERT_STATE(State::Waiting, d);
    // Second failure: backoff doubles (1 min, then 2 min).
    t += 60000;
    TEST_ASSERT_EQUAL(4, d.poll(t, true, true));
    TEST_ASSERT_EQUAL(Sent::Interrupted, d.chunk_sent(t, false));
    TEST_ASSERT_EQUAL(0, d.poll(t + 119999, true, true));
    t += 120000;
    TEST_ASSERT_EQUAL(4, d.poll(t, true, true));
    TEST_ASSERT_EQUAL(Sent::Interrupted, d.chunk_sent(t, false));
    ASSERT_STATE(State::Kept, d);  // third: give up for this boot
    TEST_ASSERT_EQUAL(0, d.poll(t + 100000000, true, true));
}

void test_backoff_is_capped_at_15_minutes() {
    sp::CoredumpPolicy p;
    p.uploads_per_boot = 50;
    p.uploads_per_dump = 50;
    CoredumpDrain d(p);
    d.begin(512, kId, 0, 0);
    uint32_t t = 0;
    const uint32_t want[] = {60000, 120000, 240000, 480000, 900000, 900000,
                             900000};
    for (uint32_t w : want) {
        upload_all(d, t);
        ASSERT_STATE(State::AwaitAck, d);
        t += 30000;
        d.poll(t, true, true);
        ASSERT_STATE(State::Waiting, d);
        TEST_ASSERT_EQUAL(0, d.poll(t + w - 1, true, true));
        t += w;
        TEST_ASSERT_EQUAL(1, d.poll(t, true, true));
        // The one-chunk retry completes at once: next round.
        TEST_ASSERT_EQUAL(Sent::Complete, d.chunk_sent(t, true));
    }
}

void test_ack_during_upload_stops_it() {
    // A re-upload of a dump the Pi already has (its earlier ack was lost):
    // the Pi re-acks; the node erases even mid-stream.
    CoredumpDrain d;
    d.begin(10 * 512, kId, 1, 0);
    send_pass(d, 0);
    ASSERT_STATE(State::Uploading, d);
    TEST_ASSERT_TRUE(d.ack(kId));
    ASSERT_STATE(State::Erased, d);
    TEST_ASSERT_EQUAL(0, d.poll(1, true, true));
    TEST_ASSERT_EQUAL(Sent::Interrupted, d.chunk_sent(1, true));
}

void test_timers_survive_millis_wrap() {
    CoredumpDrain d;
    const uint32_t t0 = 0xFFFFF000u;  // 4 s before the 49.7-day wrap
    d.begin(512, kId, 0, t0);
    TEST_ASSERT_EQUAL(0, d.poll(t0, true, false));
    TEST_ASSERT_EQUAL(0, d.poll(t0 + 100000, true, false));  // wrapped, 100 s
    TEST_ASSERT_EQUAL(1, d.poll(t0 + 120000, true, false));
    uint32_t t = t0 + 120000;
    TEST_ASSERT_EQUAL(Sent::Complete, d.chunk_sent(t, true));
    TEST_ASSERT_EQUAL(0, d.poll(t + 29999, true, true));
    ASSERT_STATE(State::AwaitAck, d);
    d.poll(t + 30000, true, true);
    ASSERT_STATE(State::Waiting, d);
}

// ── NVS bookkeeping ────────────────────────────────────────────

class CountingKv : public sp::MemKvStore {
public:
    void set_string(const char* key, const std::string& value) override {
        ++writes;
        sp::MemKvStore::set_string(key, value);
    }
    void set_int(const char* key, int32_t value) override {
        ++writes;
        sp::MemKvStore::set_int(key, value);
    }
    int writes = 0;
};

void test_nvs_upload_count_follows_the_dump_id() {
    CountingKv kv;
    TEST_ASSERT_EQUAL(0, sp::coredump_prior_uploads(kv, kId));
    sp::coredump_forget(kv);  // a clean boot never writes NVS
    TEST_ASSERT_EQUAL(0, kv.writes);

    sp::coredump_note_uploads(kv, kId, 1);
    sp::coredump_note_uploads(kv, kId, 2);
    TEST_ASSERT_EQUAL(2, sp::coredump_prior_uploads(kv, kId));
    TEST_ASSERT_EQUAL_STRING(kId, kv.get_string(sp::kCoredumpNvsId, "").c_str());
    // A different (newer) dump starts from zero and takes the slot over.
    TEST_ASSERT_EQUAL(0, sp::coredump_prior_uploads(kv, kOtherId));
    sp::coredump_note_uploads(kv, kOtherId, 1);
    TEST_ASSERT_EQUAL(0, sp::coredump_prior_uploads(kv, kId));
    TEST_ASSERT_EQUAL(1, sp::coredump_prior_uploads(kv, kOtherId));
    // A malformed id is never recorded.
    sp::coredump_note_uploads(kv, "zz", 9);
    TEST_ASSERT_EQUAL(1, sp::coredump_prior_uploads(kv, kOtherId));
    // Erased → forgotten.
    sp::coredump_forget(kv);
    TEST_ASSERT_EQUAL(0, sp::coredump_prior_uploads(kv, kOtherId));
    TEST_ASSERT_EQUAL_STRING("", kv.get_string(sp::kCoredumpNvsId, "").c_str());
    // A negative stored count (corrupt NVS) reads as zero.
    kv.set_string(sp::kCoredumpNvsId, kId);
    kv.set_int(sp::kCoredumpNvsUploads, -4);
    TEST_ASSERT_EQUAL(0, sp::coredump_prior_uploads(kv, kId));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_sha256_stream_matches_fips_vectors);
    RUN_TEST(test_sha256_stream_equals_one_shot_at_every_split);
    RUN_TEST(test_coredump_id_validation);
    RUN_TEST(test_base64_rfc4648_vectors);
    RUN_TEST(test_full_chunk_encodes_to_684_chars);
    RUN_TEST(test_chunk_document_key_set);
    RUN_TEST(test_ack_id_parsing);
    RUN_TEST(test_no_dump_stays_idle);
    RUN_TEST(test_chunk_geometry);
    RUN_TEST(test_uploads_only_while_mqtt_is_up_and_erases_on_matching_ack);
    RUN_TEST(test_chunks_per_pass_bound_the_loop_pass);
    RUN_TEST(test_waits_for_the_clock_when_an_ack_could_not_verify);
    RUN_TEST(test_missed_ack_backs_off_then_keeps_the_dump);
    RUN_TEST(test_per_dump_cap_spans_boots);
    RUN_TEST(test_link_loss_mid_upload_restarts_from_seq_zero_after_backoff);
    RUN_TEST(test_failed_publish_interrupts_and_is_bounded);
    RUN_TEST(test_backoff_is_capped_at_15_minutes);
    RUN_TEST(test_ack_during_upload_stops_it);
    RUN_TEST(test_timers_survive_millis_wrap);
    RUN_TEST(test_nvs_upload_count_follows_the_dump_id);
    return UNITY_END();
}
