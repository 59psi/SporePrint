#include "mhz19.h"

#include <string.h>

#include "wrap_time.h"

namespace sp {

namespace {
constexpr uint8_t kStart = 0xFF;
constexpr uint8_t kSensorNum = 0x01;
constexpr uint8_t kCmdReadCo2 = 0x86;
constexpr uint8_t kCmdAbcToggle = 0x79;  // b3: 0xA0 = on, 0x00 = off
constexpr uint8_t kCmdZeroCal = 0x87;    // zero-point cal (400 ppm baseline)
constexpr uint32_t kReplyDeadlineMs = 100;
}  // namespace

uint8_t Mhz19::checksum(const uint8_t frame[9]) {
    uint8_t sum = 0;
    for (int i = 1; i < 8; ++i) sum = (uint8_t)(sum + frame[i]);
    return (uint8_t)((0xFF - sum) + 1);
}

void Mhz19::send_frame(uint8_t cmd, uint8_t b3) {
    uint8_t frame[9] = {kStart, kSensorNum, cmd, b3, 0, 0, 0, 0, 0};
    frame[8] = checksum(frame);
    uart_.write(frame, sizeof(frame));
}

void Mhz19::begin(bool abc_enabled) {
    // Datasheet cmd 0x79, b3 0xA0 = ABC on / 0x00 = off. Off is the
    // correct chamber posture — auto-baseline assumes weekly 400 ppm air.
    send_frame(kCmdAbcToggle, abc_enabled ? 0xA0 : 0x00);
}

void Mhz19::calibrate_zero() {
    // Datasheet cmd 0x87 (frame FF 01 87 00 00 00 00 00 78): latch the
    // current reading as the 400 ppm zero point. The operator owns the
    // fresh-air precondition; there is no reply to wait for.
    send_frame(kCmdZeroCal, 0x00);
}

bool Mhz19::request_read() {
    if (awaiting_) return false;
    uart_.flush_input();
    rx_len_ = 0;
    send_frame(kCmdReadCo2, 0);
    awaiting_ = true;
    deadline_ms_ = clock_.millis() + kReplyDeadlineMs;
    return true;
}

bool Mhz19::update(uint32_t now_ms, uint16_t* co2_ppm) {
    if (!awaiting_) return false;

    // Accumulate whatever arrived this pass.
    while (rx_len_ < sizeof(rx_)) {
        uint8_t b;
        if (uart_.read(&b, 1) != 1) break;
        if (rx_len_ == 0 && b != kStart) continue;  // resync on start byte
        if (rx_len_ == 1 && b != kCmdReadCo2) {
            // Second byte of a reply is the echoed command; anything else
            // means we latched onto noise — restart the hunt.
            rx_len_ = (b == kStart) ? 1 : 0;
            continue;
        }
        rx_[rx_len_++] = b;
    }

    if (rx_len_ == sizeof(rx_)) {
        awaiting_ = false;
        if (checksum(rx_) != rx_[8]) {
            health_.fail("checksum");
            return false;
        }
        *co2_ppm = (uint16_t)((rx_[2] << 8) | rx_[3]);
        health_.ok();
        return true;
    }

    if (deadline_reached(now_ms, deadline_ms_)) {
        awaiting_ = false;
        health_.fail("timeout");
    }
    return false;
}

}  // namespace sp
