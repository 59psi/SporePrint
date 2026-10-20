#pragma once
//
// chunked_writer — buffers a serializer's byte stream into fixed-size chunks
// before it reaches a transport.
//
// ArduinoJson writes most of a document one character at a time. Streamed
// straight into PubSubClient, every character was its own Client::write: on
// Secure MQTT one TLS record and one TCP segment per byte (tens of times the
// bytes on the wire), and on a stalled plaintext socket up to 10 s per byte
// (the core retries each write for 10 × 1 s), far past the loop watchdog.
// Through this writer a document leaves in kChunk-byte writes.
//
// The first short write marks the writer failed and stops every later
// write: the packet already on the wire is incomplete, so the caller must
// drop the connection (MqttLink::publish does) instead of streaming on into
// a desynced stream.
//
// Sink: any type with `size_t write(const uint8_t* data, size_t len)` that
// returns the bytes it accepted. The writer itself is an ArduinoJson custom
// writer: serializeJson(doc, writer).
//
// Native-safe: no Arduino headers.

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace sp {

template <typename Sink, size_t kChunk = 256>
class ChunkedWriter {
public:
    static_assert(kChunk > 0, "chunk size");

    explicit ChunkedWriter(Sink& sink) : sink_(sink) {}

    size_t write(uint8_t c) {
        if (failed_) return 0;
        buf_[len_++] = c;
        if (len_ == kChunk) send_buffer();
        return 1;
    }

    size_t write(const uint8_t* data, size_t n) {
        size_t taken = 0;
        while (taken < n && !failed_) {
            const size_t room = kChunk - len_;
            const size_t k = n - taken < room ? n - taken : room;
            memcpy(buf_ + len_, data + taken, k);
            len_ += k;
            taken += k;
            if (len_ == kChunk) send_buffer();
        }
        return taken;
    }

    // Send the partial last chunk. False when any write fell short.
    bool flush() {
        if (!failed_ && len_ > 0) send_buffer();
        return !failed_;
    }

    bool failed() const { return failed_; }
    // Bytes the sink accepted.
    size_t written() const { return written_; }

private:
    void send_buffer() {
        const size_t sent = sink_.write(buf_, len_);
        written_ += sent < len_ ? sent : len_;
        if (sent != len_) failed_ = true;
        len_ = 0;
    }

    Sink& sink_;
    uint8_t buf_[kChunk];
    size_t len_ = 0;
    size_t written_ = 0;
    bool failed_ = false;
};

}  // namespace sp
