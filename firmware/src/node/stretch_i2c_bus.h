#pragma once
//
// stretch_i2c_bus — the node's sp::I2cBus: Wire for every sensor, except the
// SCD30, which gets its own ESP-IDF i2c_master device handle with a real
// clock-stretch timeout.
//
// Why: Sensirion's SCD30 Interface Description (v1.0, May 2020, §1.1) says
// "the master has to support clock stretching ... Clock stretching period in
// write- and read-frames is 30 ms, however, due to internal calibration
// processes a maximal clock stretching of 150 ms may occur once per day",
// recommends 50 kHz or slower, and rules out repeated starts. Arduino-ESP32
// 2.0.17 raised the controller's SCL timeout to its hardware maximum for every
// device (i2c_set_timeout(I2C_LL_MAX_TIMEOUT)). Core 3.3.12 on ESP-IDF 5.5
// adds every Wire device with scl_wait_us = 0, which IDF turns into
// I2C_LL_SCL_WAIT_US_VAL_DEFAULT = 2000 µs — and Wire offers no way to change
// it. An SCD30 stretching past 2 ms then times out: a read-fail every time it
// stretches, i.e. a CO2 sensor that goes stale for no hardware reason.
//
// The fix lives at the one address that needs it: transactions to 0x61 go
// through a device handle on the SAME IDF bus Wire.begin() created
// (i2cBusHandle), at 50 kHz, with scl_wait_us at the chip's hardware ceiling:
//   ESP32     20-bit timeout register in 80 MHz APB cycles → 13.1 ms max.
//             That is the 2.x value, and it is short of the 30 ms the SCD30
//             may stretch: a longer stretch is a read-fail (never data) — a
//             classic-ESP32 hardware limit, not something software can lift.
//   ESP32-S3  power-of-two register in 40 MHz XTAL cycles: 40 ms requested →
//             2^21 cycles = 52 ms, covering the 30 ms routine stretch.
// Every other address delegates to Wire unchanged (the SHT3x is read in its
// no-stretch mode; SHT4x, SCD4x, BH1750, AHT2x and BMx280 never stretch).
// Writes and reads stay separate STOP-terminated transactions — the SCD30
// does not support repeated start.
//
// Device-only (Arduino + ESP-IDF headers); composition-root glue for
// src/node/main.cpp.

#include <Arduino.h>
#include <Wire.h>
#include <esp32-hal-i2c.h>

#include "driver/i2c_master.h"

#include "arduino_hal.h"
#include "scd30.h"
#include "sp_hal/i2c_bus.h"

namespace sp_node {

#if CONFIG_IDF_TARGET_ESP32
constexpr uint32_t kScd30SclWaitUs = 13000;
static_assert(80ULL * kScd30SclWaitUs <= 0xFFFFFULL,
              "ESP32 I2C timeout register is 20 bits of 80 MHz APB cycles");
#else
constexpr uint32_t kScd30SclWaitUs = 40000;
#endif
constexpr uint32_t kScd30SclHz = 50000;  // Sensirion: 50 kHz or smaller
// Whole-transaction timeout for an SCD30 transfer: the stretch ceiling plus
// 18 bytes at 50 kHz, with margin.
constexpr int kScd30XferTimeoutMs = (int)(kScd30SclWaitUs / 1000U) * 2 + 20;

class StretchI2cBus : public sp::I2cBus {
public:
    StretchI2cBus(sp_device::ArduinoI2cBus& wire_bus, uint8_t port)
        : wire_(wire_bus), port_(port) {}

    // Call after Wire.begin(). False (logged by the caller) when the IDF
    // bus or the SCD30 device handle cannot be had — every address then
    // stays on Wire, i.e. exactly the stock core-3 behaviour.
    bool begin() {
        i2c_master_bus_handle_t bus =
            (i2c_master_bus_handle_t)i2cBusHandle(port_);
        if (bus == nullptr) return false;
        i2c_device_config_t cfg = {};
        cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
        cfg.device_address = sp::Scd30::kAddr;
        cfg.scl_speed_hz = kScd30SclHz;
        cfg.scl_wait_us = kScd30SclWaitUs;
        return i2c_master_bus_add_device(bus, &cfg, &scd30_) == ESP_OK;
    }

    bool write(uint8_t addr, const uint8_t* wbuf, size_t wlen) override {
        if (addr != sp::Scd30::kAddr || scd30_ == nullptr || wlen == 0)
            return wire_.write(addr, wbuf, wlen);
        return i2c_master_transmit(scd30_, wbuf, wlen, kScd30XferTimeoutMs) ==
               ESP_OK;
    }

    bool read(uint8_t addr, uint8_t* rbuf, size_t rlen) override {
        if (addr != sp::Scd30::kAddr || scd30_ == nullptr)
            return wire_.read(addr, rbuf, rlen);
        return i2c_master_receive(scd30_, rbuf, rlen, kScd30XferTimeoutMs) ==
               ESP_OK;
    }

private:
    sp_device::ArduinoI2cBus& wire_;
    uint8_t port_;
    i2c_master_dev_handle_t scd30_ = nullptr;
};

}  // namespace sp_node
