#include "sensirion_transport.h"

namespace sp {

uint8_t crc8_sensirion(const uint8_t* data, size_t len) {
    uint8_t crc = 0xFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int b = 0; b < 8; ++b) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

bool SensirionTransport::cmd(uint16_t c) {
    uint8_t buf[2] = {(uint8_t)(c >> 8), (uint8_t)(c & 0xFF)};
    return bus_.write(addr_, buf, sizeof(buf));
}

bool SensirionTransport::cmd_arg(uint16_t c, uint16_t arg) {
    uint8_t buf[5];
    buf[0] = (uint8_t)(c >> 8);
    buf[1] = (uint8_t)(c & 0xFF);
    buf[2] = (uint8_t)(arg >> 8);
    buf[3] = (uint8_t)(arg & 0xFF);
    buf[4] = crc8_sensirion(buf + 2, 2);
    return bus_.write(addr_, buf, sizeof(buf));
}

bool SensirionTransport::read_words(uint16_t* words, size_t n) {
    if (n > kMaxWords) return false;
    uint8_t raw[kMaxWords * 3];
    if (!bus_.read(addr_, raw, n * 3)) return false;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t* w = raw + i * 3;
        if (crc8_sensirion(w, 2) != w[2]) return false;  // reject the whole read
        words[i] = (uint16_t)((w[0] << 8) | w[1]);
    }
    return true;
}

bool SensirionTransport::cmd_read(uint16_t c, uint32_t delay_ms, uint16_t* words,
                                  size_t n) {
    if (!cmd(c)) return false;
    if (delay_ms > 0) clock_.delay_ms(delay_ms);
    return read_words(words, n);
}

}  // namespace sp
