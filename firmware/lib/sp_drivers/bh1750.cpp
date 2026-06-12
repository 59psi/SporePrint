#include "bh1750.h"

namespace sp {

namespace {
constexpr uint8_t kOpPowerOn = 0x01;
constexpr uint8_t kOpContinuousHighRes = 0x10;
}  // namespace

bool Bh1750::probe() {
    uint8_t op = kOpPowerOn;
    return bus_.write(addr_, &op, 1);
}

bool Bh1750::begin() {
    uint8_t op = kOpPowerOn;
    if (!bus_.write(addr_, &op, 1)) return false;
    op = kOpContinuousHighRes;
    return bus_.write(addr_, &op, 1);
}

bool Bh1750::read(float* lux) {
    uint8_t raw[2];
    if (!bus_.read(addr_, raw, sizeof(raw))) {
        health_.fail("read error");
        return false;
    }
    uint16_t counts = (uint16_t)((raw[0] << 8) | raw[1]);
    *lux = (float)counts / 1.2f;
    health_.ok();
    return true;
}

}  // namespace sp
