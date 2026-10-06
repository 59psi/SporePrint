#pragma once
//
// idf_i2c_bus — an sp::I2cBus straight on the ESP-IDF i2c_master driver, for
// the camera image's one I²C peer outside the camera: the Waveshare
// ESP32-S3-CAM's I/O expander (sp_drivers/ws_cam_exio.h).
//
// Why not Wire: the bus it opens is then handed to the camera driver
// (camera_config_t sccb_i2c_port → i2c_master_get_bus_handle), and Arduino
// Wire would cost every cam image ~16 KB — PlatformIO's library finder
// links Wire's global TwoWire objects (and their constructors) into any
// image whose sources name <Wire.h>, even behind an #if. This header names
// only ESP-IDF headers, so the AI-Thinker and the other S3 images stay
// byte-for-byte what they were.
//
// One device handle at a time (re-added when the address changes): the
// cam talks to one address. Writes and reads are separate STOP-terminated
// transactions, like sp_device's Wire adapter.
//
// Device-only (ESP-IDF headers); composition-root glue for src/cam/main.cpp.

#include "driver/i2c_master.h"

#include "sp_hal/i2c_bus.h"

namespace sp_cam {

class IdfI2cBus : public sp::I2cBus {
public:
    static constexpr uint32_t kSclHz = 100000;
    static constexpr int kXferTimeoutMs = 50;

    // Opens I²C `port` on the two pins. False when the port is taken or the
    // pins are invalid.
    bool begin(int port, int sda, int scl) {
        i2c_master_bus_config_t cfg = {};
        cfg.i2c_port = (i2c_port_num_t)port;
        cfg.sda_io_num = (gpio_num_t)sda;
        cfg.scl_io_num = (gpio_num_t)scl;
        cfg.clk_source = I2C_CLK_SRC_DEFAULT;
        cfg.glitch_ignore_cnt = 7;
        cfg.flags.enable_internal_pullup = true;  // the board fits 4.7 kΩ too
        return i2c_new_master_bus(&cfg, &bus_) == ESP_OK;
    }

    bool write(uint8_t addr, const uint8_t* wbuf, size_t wlen) override {
        if (!device(addr)) return false;
        return i2c_master_transmit(dev_, wbuf, wlen, kXferTimeoutMs) == ESP_OK;
    }

    bool read(uint8_t addr, uint8_t* rbuf, size_t rlen) override {
        if (!device(addr)) return false;
        return i2c_master_receive(dev_, rbuf, rlen, kXferTimeoutMs) == ESP_OK;
    }

private:
    bool device(uint8_t addr) {
        if (bus_ == nullptr) return false;
        if (dev_ != nullptr && dev_addr_ == addr) return true;
        if (dev_ != nullptr) {
            i2c_master_bus_rm_device(dev_);
            dev_ = nullptr;
        }
        i2c_device_config_t cfg = {};
        cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
        cfg.device_address = addr;
        cfg.scl_speed_hz = kSclHz;
        if (i2c_master_bus_add_device(bus_, &cfg, &dev_) != ESP_OK) {
            dev_ = nullptr;
            return false;
        }
        dev_addr_ = addr;
        return true;
    }

    i2c_master_bus_handle_t bus_ = nullptr;
    i2c_master_dev_handle_t dev_ = nullptr;
    uint8_t dev_addr_ = 0;
};

}  // namespace sp_cam
