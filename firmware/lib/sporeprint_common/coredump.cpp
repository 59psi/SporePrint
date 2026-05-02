#include "coredump.h"

#include "mqtt_manager.h"

// v4 archaeology fix #12. ESP-IDF coredump APIs are guarded so this TU
// also compiles for the native (host) test harness, which stubs out
// to "no dump".

#if defined(ARDUINO) || defined(ESP_PLATFORM)
#include <Arduino.h>
#include <ArduinoJson.h>
#include "esp_core_dump.h"
#include "esp_partition.h"
#include "esp_err.h"
#include "esp_log.h"

// Inline encoder — mbedtls would add ~30 KB per image just for base64.
static const char kB64Alphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static size_t b64Encode(const uint8_t* in, size_t inLen, char* out, size_t outCap) {
    size_t needed = ((inLen + 2) / 3) * 4 + 1;
    if (outCap < needed) return 0;
    size_t i = 0, o = 0;
    while (i + 3 <= inLen) {
        uint32_t v = (in[i] << 16) | (in[i + 1] << 8) | in[i + 2];
        out[o++] = kB64Alphabet[(v >> 18) & 0x3F];
        out[o++] = kB64Alphabet[(v >> 12) & 0x3F];
        out[o++] = kB64Alphabet[(v >> 6) & 0x3F];
        out[o++] = kB64Alphabet[v & 0x3F];
        i += 3;
    }
    if (i < inLen) {
        uint32_t v = in[i] << 16;
        if (i + 1 < inLen) v |= in[i + 1] << 8;
        out[o++] = kB64Alphabet[(v >> 18) & 0x3F];
        out[o++] = kB64Alphabet[(v >> 12) & 0x3F];
        out[o++] = (i + 1 < inLen) ? kB64Alphabet[(v >> 6) & 0x3F] : '=';
        out[o++] = '=';
    }
    out[o] = '\0';
    return o;
}

namespace sporeprint {
namespace coredump {

bool isPresent(size_t* size) {
    size_t addr = 0;
    size_t img_size = 0;
    esp_err_t err = esp_core_dump_image_get(&addr, &img_size);
    if (err != ESP_OK || img_size == 0) {
        return false;
    }
    if (size) *size = img_size;
    return true;
}

bool readChunked(size_t chunkBytes,
                 std::function<bool(const uint8_t*, size_t, size_t)> sink) {
    size_t addr = 0;
    size_t img_size = 0;
    if (esp_core_dump_image_get(&addr, &img_size) != ESP_OK || img_size == 0) {
        return false;
    }

    // esp_partition_read handles flash encryption + MMU mapping; using
    // raw spi_flash_read against the absolute address would not.
    const esp_partition_t* part = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_COREDUMP, NULL);
    if (!part) {
        return false;
    }

    // Cap at 1 KB so each MQTT publish stays under the PubSubClient
    // 1024-byte buffer once base64 (~1.34x) + JSON envelope are added.
    if (chunkBytes == 0 || chunkBytes > 1024) chunkBytes = 512;

    uint8_t buf[1024];
    size_t offset = 0;
    while (offset < img_size) {
        size_t toRead = img_size - offset;
        if (toRead > chunkBytes) toRead = chunkBytes;

        if (esp_partition_read(part, offset, buf, toRead) != ESP_OK) {
            return false;
        }
        // sink returning false = soft failure; partition is NOT erased
        // so the next boot retries.
        if (!sink(buf, toRead, offset)) {
            return false;
        }
        offset += toRead;
    }
    return true;
}

bool erase() {
    return esp_core_dump_image_erase() == ESP_OK;
}

bool uploadIfPresent(MqttManager& mqtt) {
    size_t total = 0;
    if (!isPresent(&total)) return true;

    Serial.printf("[COREDUMP] Found %u-byte dump in flash, uploading...\n",
                  (unsigned)total);

    // 512 raw → ~684 base64 → fits PubSubClient 1024-byte buffer with envelope.
    const size_t kRawChunk = 512;
    const size_t kTotalChunks = (total + kRawChunk - 1) / kRawChunk;

    String topic = mqtt.buildTopic("coredump/chunk");
    bool ok = readChunked(kRawChunk,
        [&](const uint8_t* data, size_t len, size_t offset) -> bool {
            char b64[700];
            if (b64Encode(data, len, b64, sizeof(b64)) == 0) return false;

            JsonDocument doc;
            doc["seq"] = (uint32_t)(offset / kRawChunk);
            doc["total"] = (uint32_t)kTotalChunks;
            doc["size"] = (uint32_t)len;
            doc["b64_data"] = b64;

            if (!mqtt.isConnected()) return false;
            mqtt.publish(topic.c_str(), doc);
            return true;
        });

    if (!ok) {
        Serial.println("[COREDUMP] Upload failed; partition left intact for retry");
        return false;
    }

    Serial.println("[COREDUMP] Upload complete; erasing partition");
    erase();
    return true;
}

}  // namespace coredump
}  // namespace sporeprint

#else
// Native (host) build — no flash, no IDF, no panic dumps. Stub the API.
namespace sporeprint {
namespace coredump {

bool isPresent(size_t* /*size*/) { return false; }
bool readChunked(size_t /*chunkBytes*/,
                 std::function<bool(const uint8_t*, size_t, size_t)> /*sink*/) {
    return false;
}
bool erase() { return false; }
bool uploadIfPresent(MqttManager& /*mqtt*/) { return true; }

}  // namespace coredump
}  // namespace sporeprint
#endif
