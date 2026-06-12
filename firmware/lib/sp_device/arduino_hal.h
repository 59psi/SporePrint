#pragma once
//
// arduino_hal — Arduino-core implementations of the sp_hal interfaces.
// The only place Wire / HardwareSerial / digital* meet the driver layer.
// Device-only: everything else in lib/sp_core + lib/sp_drivers stays
// Arduino-free and host-testable.

#include <Arduino.h>
#include <Wire.h>

#include "sp_hal/clock.h"
#include "sp_hal/gpio.h"
#include "sp_hal/i2c_bus.h"
#include "sp_hal/uart_port.h"

namespace sp_device {

class ArduinoI2cBus : public sp::I2cBus {
public:
    explicit ArduinoI2cBus(TwoWire& wire) : wire_(wire) {}

    bool write(uint8_t addr, const uint8_t* wbuf, size_t wlen) override {
        wire_.beginTransmission(addr);
        if (wlen > 0) wire_.write(wbuf, wlen);
        return wire_.endTransmission() == 0;
    }

    bool read(uint8_t addr, uint8_t* rbuf, size_t rlen) override {
        size_t got = wire_.requestFrom((int)addr, (int)rlen);
        if (got != rlen) {
            // Drain whatever arrived so a short read can't poison the next
            // transaction.
            while (wire_.available()) wire_.read();
            return false;
        }
        for (size_t i = 0; i < rlen; ++i) rbuf[i] = (uint8_t)wire_.read();
        return true;
    }

private:
    TwoWire& wire_;
};

class ArduinoUart : public sp::UartPort {
public:
    explicit ArduinoUart(HardwareSerial& serial) : serial_(serial) {}

    size_t available() override { return (size_t)serial_.available(); }
    size_t read(uint8_t* buf, size_t maxlen) override {
        size_t n = 0;
        while (n < maxlen && serial_.available() > 0) {
            int b = serial_.read();
            if (b < 0) break;
            buf[n++] = (uint8_t)b;
        }
        return n;
    }
    size_t write(const uint8_t* buf, size_t len) override {
        return serial_.write(buf, len);
    }
    void flush_input() override {
        while (serial_.available() > 0) serial_.read();
    }

private:
    HardwareSerial& serial_;
};

class ArduinoPin : public sp::GpioPin {
public:
    explicit ArduinoPin(int pin) : pin_(pin) {}

    void set_mode(sp::PinMode mode) override {
        switch (mode) {
            case sp::PinMode::Input: pinMode(pin_, INPUT); break;
            case sp::PinMode::InputPullup:
                // GPIO 34–39 on classic ESP32 have no internal pulls —
                // INPUT_PULLUP degrades to INPUT there (wiring guides call
                // for an external 10K on those pins, e.g. the reed on 35).
                pinMode(pin_, INPUT_PULLUP);
                break;
            case sp::PinMode::Output: pinMode(pin_, OUTPUT); break;
        }
    }
    bool read() override { return digitalRead(pin_) == HIGH; }
    void write(bool level) override { digitalWrite(pin_, level ? HIGH : LOW); }

private:
    int pin_;
};

class ArduinoClock : public sp::Clock {
public:
    uint32_t millis() override { return ::millis(); }
    void delay_ms(uint32_t ms) override { ::delay(ms); }
};

inline void hx711_delay_us(uint32_t us) { delayMicroseconds(us); }

}  // namespace sp_device
