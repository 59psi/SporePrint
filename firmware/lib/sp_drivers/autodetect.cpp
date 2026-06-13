#include "autodetect.h"

#include "bh1750.h"
#include "scd30.h"
#include "scd4x.h"
#include "sht3x.h"
#include "sht4x.h"

namespace sp {

const char* temp_rh_kind_str(TempRhKind k) {
    switch (k) {
        case TempRhKind::None:  return "none";
        case TempRhKind::Sht3x: return "sht3x";
        case TempRhKind::Sht4x: return "sht4x";
    }
    return "none";
}

const char* co2_kind_str(Co2Kind k) {
    switch (k) {
        case Co2Kind::None:  return "none";
        case Co2Kind::Scd4x: return "scd4x";
        case Co2Kind::Scd30: return "scd30";
    }
    return "none";
}

DetectedSensors autodetect_i2c(I2cBus& bus, Clock& clock) {
    DetectedSensors out;

    // Temp/RH at 0x44 then 0x45 — SHT4x FIRST at each address (see header).
    const uint8_t sht_addrs[] = {0x44, 0x45};
    for (uint8_t addr : sht_addrs) {
        Sht4x sht4(bus, clock, addr);
        if (sht4.probe()) {
            out.temp_rh = TempRhKind::Sht4x;
            out.temp_rh_addr = addr;
            break;
        }
        Sht3x sht3(bus, clock, addr);  // probe() opens with soft-reset
        if (sht3.probe()) {
            out.temp_rh = TempRhKind::Sht3x;
            out.temp_rh_addr = addr;
            break;
        }
    }

    // CO₂ — SCD4x (0x62) is canonical, SCD30 (0x61) the alternate.
    {
        Scd4x scd4(bus, clock);
        if (scd4.probe()) {
            out.co2 = Co2Kind::Scd4x;
        } else {
            Scd30 scd30(bus, clock);
            if (scd30.probe()) out.co2 = Co2Kind::Scd30;
        }
    }

    // Light — BH1750 default then alternate address.
    const uint8_t bh_addrs[] = {Bh1750::kAddrLow, Bh1750::kAddrHigh};
    for (uint8_t addr : bh_addrs) {
        Bh1750 bh(bus, addr);
        if (bh.probe()) {
            out.bh1750 = true;
            out.bh1750_addr = addr;
            break;
        }
    }

    return out;
}

}  // namespace sp
