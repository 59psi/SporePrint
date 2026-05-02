#pragma once
//
// v4 archaeology fix #12 — ESP32 coredump uploader.
//
// On boot, after MQTT is up, each node calls uploadIfPresent(): if the
// previous run left a panic dump in the `coredump` flash partition (see
// firmware/partitions.csv) we read it in 512-byte chunks, base64-encode
// each, and publish to sporeprint/<node_id>/coredump/chunk as
// {seq, total, size, b64_data}. erase() only runs after every chunk
// publishes; a mid-stream broker hiccup leaves the partition intact and
// the next boot retries.
//
// All four functions are no-ops on non-ESP32 builds so unit tests that
// link sporeprint_common don't drag in ESP-IDF symbols.

#include <stdint.h>
#include <stddef.h>
#include <functional>

class MqttManager;  // fwd decl — full include only in the .cpp

namespace sporeprint {
namespace coredump {

bool isPresent(size_t* size);

bool readChunked(size_t chunkBytes,
                 std::function<bool(const uint8_t*, size_t, size_t)> sink);

bool erase();

bool uploadIfPresent(MqttManager& mqtt);

}  // namespace coredump
}  // namespace sporeprint
