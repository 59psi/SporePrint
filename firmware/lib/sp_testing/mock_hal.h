#pragma once
//
// sp_testing — scripted HAL mocks for the native driver tests. Header-only,
// host-only (never linked into device images; nothing here is included by
// device code).
//
// MockI2cBus runs a SCRIPT of expected transactions in order: each entry
// asserts the address and written bytes, then either NACKs or returns the
// scripted reply. Out-of-script transactions fail the test — which is what
// makes autodetect probe ORDER itself testable.

#include <cstdint>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#include "sp_hal/clock.h"
#include "sp_hal/gpio.h"
#include "sp_hal/i2c_bus.h"
#include "sp_hal/uart_port.h"

namespace sp_testing {

// ── scripted I²C ───────────────────────────────────────────────

struct I2cStep {
    enum Kind : uint8_t { Write, Read } kind;
    uint8_t addr;
    std::vector<uint8_t> bytes;  // Write: expected bytes; Read: reply bytes
    bool ack;                    // false = NACK / timeout
};

class MockI2cBus : public sp::I2cBus {
public:
    std::deque<I2cStep> script;
    std::string error;  // first mismatch description (empty = clean)

    void expect_write(uint8_t addr, std::vector<uint8_t> bytes, bool ack = true) {
        script.push_back({I2cStep::Write, addr, std::move(bytes), ack});
    }
    void expect_read(uint8_t addr, std::vector<uint8_t> reply, bool ack = true) {
        script.push_back({I2cStep::Read, addr, std::move(reply), ack});
    }
    // Convenience: a NACK to ANY write at this address (probe miss).
    void expect_write_nack(uint8_t addr) {
        script.push_back({I2cStep::Write, addr, {}, false});
    }

    bool write(uint8_t addr, const uint8_t* wbuf, size_t wlen) override {
        if (script.empty()) {
            note_error("unexpected write — script exhausted");
            return false;
        }
        I2cStep step = script.front();
        script.pop_front();
        if (step.kind != I2cStep::Write || step.addr != addr) {
            note_error("write mismatch (kind/addr)");
            return false;
        }
        if (!step.ack) return false;  // scripted NACK — bytes not compared
        if (step.bytes.size() != wlen ||
            (wlen && std::memcmp(step.bytes.data(), wbuf, wlen) != 0)) {
            note_error("write payload mismatch");
            return false;
        }
        return true;
    }

    bool read(uint8_t addr, uint8_t* rbuf, size_t rlen) override {
        if (script.empty()) {
            note_error("unexpected read — script exhausted");
            return false;
        }
        I2cStep step = script.front();
        script.pop_front();
        if (step.kind != I2cStep::Read || step.addr != addr) {
            note_error("read mismatch (kind/addr)");
            return false;
        }
        if (!step.ack) return false;
        if (step.bytes.size() != rlen) {
            note_error("read length mismatch");
            return false;
        }
        std::memcpy(rbuf, step.bytes.data(), rlen);
        return true;
    }

    bool script_consumed() const { return script.empty(); }

private:
    void note_error(const char* what) {
        if (error.empty()) error = what;
    }
};

// ── manual clock ───────────────────────────────────────────────

class MockClock : public sp::Clock {
public:
    uint32_t now_ms = 0;
    uint32_t total_delayed_ms = 0;

    uint32_t millis() override { return now_ms; }
    void delay_ms(uint32_t ms) override {
        now_ms += ms;
        total_delayed_ms += ms;
    }
};

// ── scripted UART ──────────────────────────────────────────────

class MockUart : public sp::UartPort {
public:
    std::deque<uint8_t> rx;             // bytes the "sensor" will send us
    std::vector<uint8_t> tx;            // bytes the driver wrote
    size_t max_read_per_call = 64;      // simulate trickling arrival

    size_t available() override { return rx.size(); }
    size_t read(uint8_t* buf, size_t maxlen) override {
        size_t n = 0;
        while (n < maxlen && n < max_read_per_call && !rx.empty()) {
            buf[n++] = rx.front();
            rx.pop_front();
        }
        return n;
    }
    size_t write(const uint8_t* buf, size_t len) override {
        tx.insert(tx.end(), buf, buf + len);
        return len;
    }
    void flush_input() override { rx.clear(); }

    void queue_reply(const std::vector<uint8_t>& bytes) {
        for (uint8_t b : bytes) rx.push_back(b);
    }
};

// ── scripted pin ───────────────────────────────────────────────

class MockPin : public sp::GpioPin {
public:
    bool level = true;                  // current input level
    std::deque<bool> read_script;       // optional per-read levels
    std::vector<bool> writes;           // levels written by the driver
    sp::PinMode mode = sp::PinMode::Input;

    void set_mode(sp::PinMode m) override { mode = m; }
    bool read() override {
        if (!read_script.empty()) {
            bool v = read_script.front();
            read_script.pop_front();
            return v;
        }
        return level;
    }
    void write(bool l) override {
        level = l;
        writes.push_back(l);
    }
};

}  // namespace sp_testing
