#include "coredump_uploader.h"

#include <esp_core_dump.h>
#include <esp_partition.h>
#include <esp_task_wdt.h>

namespace sp_device {
namespace coredump {

namespace {

const char kB64[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

size_t b64_encode(const uint8_t* in, size_t in_len, char* out, size_t out_cap) {
    size_t needed = ((in_len + 2) / 3) * 4 + 1;
    if (out_cap < needed) return 0;
    size_t i = 0, o = 0;
    while (i + 3 <= in_len) {
        uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8) |
                     in[i + 2];
        out[o++] = kB64[(v >> 18) & 0x3F];
        out[o++] = kB64[(v >> 12) & 0x3F];
        out[o++] = kB64[(v >> 6) & 0x3F];
        out[o++] = kB64[v & 0x3F];
        i += 3;
    }
    if (i < in_len) {
        uint32_t v = (uint32_t)in[i] << 16;
        if (i + 1 < in_len) v |= (uint32_t)in[i + 1] << 8;
        out[o++] = kB64[(v >> 18) & 0x3F];
        out[o++] = kB64[(v >> 12) & 0x3F];
        out[o++] = (i + 1 < in_len) ? kB64[(v >> 6) & 0x3F] : '=';
        out[o++] = '=';
    }
    out[o] = '\0';
    return o;
}

}  // namespace

bool upload_if_present(MqttLink& link) {
    size_t addr = 0;
    size_t img_size = 0;
    if (esp_core_dump_image_get(&addr, &img_size) != ESP_OK || img_size == 0) {
        return true;  // nothing to do
    }
    Serial.printf("[COREDUMP] Found %u-byte dump, uploading...\n",
                  (unsigned)img_size);

    const esp_partition_t* part = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_COREDUMP, NULL);
    if (part == nullptr) return false;

    constexpr size_t kChunk = 512;
    const size_t total_chunks = (img_size + kChunk - 1) / kChunk;
    uint8_t buf[kChunk];
    char b64[700];
    std::string topic = link.topic("coredump/chunk");

    size_t offset = 0;
    uint32_t seq = 0;
    while (offset < img_size) {
        // Sanctioned pet site: a large dump's chunk loop can exceed the
        // steady-state WDT budget.
        esp_task_wdt_reset();
        size_t to_read = img_size - offset;
        if (to_read > kChunk) to_read = kChunk;
        if (esp_partition_read(part, offset, buf, to_read) != ESP_OK)
            return false;
        if (b64_encode(buf, to_read, b64, sizeof(b64)) == 0) return false;

        JsonDocument doc;
        doc["seq"] = seq;
        doc["total"] = (uint32_t)total_chunks;
        doc["size"] = (uint32_t)to_read;
        doc["b64_data"] = b64;
        if (!link.connected() || !link.publish(topic.c_str(), doc)) {
            Serial.println("[COREDUMP] Upload interrupted; partition kept for retry");
            return false;
        }
        offset += to_read;
        ++seq;
    }

    Serial.println("[COREDUMP] Upload complete; erasing partition");
    esp_core_dump_image_erase();
    return true;
}

}  // namespace coredump
}  // namespace sp_device
