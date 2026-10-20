#pragma once
//
// sensor_memory — the autodetected I²C sensors a node has found at an
// earlier boot.
//
// CO2 and light sensors are autodetected (sp_drivers/autodetect.h): a part
// that answers at boot is used, one that does not is never built. On its own
// that made a CO2 sensor that died or came unplugged before a reboot simply
// vanish — no driver, so no staleness clock, no sensor_failure alert and no
// expected_missing entry — while every CO2 rule on the Pi (FAE trigger,
// emergency exhaust) silently stopped evaluating. The node now remembers, in
// NVS, what it has found:
//   seen_co2  int   the CO2 sensor kind last detected (autodetect.h Co2Kind
//                   value; missing key / 0 = none found yet)
//   seen_lux  bool  a BH1750 has been detected
// A remembered sensor that does not answer at boot is listed in the health
// document's expected_missing and raises the latched sensor_failure alert.
// The memory is kept while the sensor is missing (every boot says so until it
// is back), follows a swap (an SCD30 replacing an SCD4x raises nothing) and
// is only dropped deliberately: a factory reset (it clears the namespace) or
// the setup portal's "forget removed sensors" box. A node that never saw a
// sensor behaves exactly as before.
//
// Native-safe: no Arduino headers.

#include <stdint.h>

#include "kv_store.h"

namespace sp {

constexpr const char* kSeenCo2Key = "seen_co2";
constexpr const char* kSeenLuxKey = "seen_lux";

struct SeenSensors {
    int32_t co2 = 0;   // Co2Kind value of the CO2 sensor found; 0 = none
    bool lux = false;  // a light sensor was found
};

inline bool operator==(const SeenSensors& a, const SeenSensors& b) {
    return a.co2 == b.co2 && a.lux == b.lux;
}
inline bool operator!=(const SeenSensors& a, const SeenSensors& b) {
    return !(a == b);
}

struct SeenCheck {
    bool co2_missing = false;  // remembered, not detected at this boot
    bool lux_missing = false;
    int32_t co2_missing_kind = 0;  // the remembered kind (for its name)
    SeenSensors remember;      // what to keep in NVS after this boot
    bool changed = false;      // remember differs from what was stored
};

// Boot: `before` (NVS) against what autodetect found now (`co2_now`: the
// Co2Kind value, 0 = none; `lux_now`).
inline SeenCheck check_seen_sensors(const SeenSensors& before, int32_t co2_now,
                                    bool lux_now) {
    SeenCheck c;
    c.co2_missing = before.co2 != 0 && co2_now == 0;
    c.co2_missing_kind = c.co2_missing ? before.co2 : 0;
    c.lux_missing = before.lux && !lux_now;
    c.remember.co2 = co2_now != 0 ? co2_now : before.co2;
    c.remember.lux = before.lux || lux_now;
    c.changed = c.remember != before;
    return c;
}

inline SeenSensors load_seen_sensors(KvStore& kv) {
    SeenSensors s;
    s.co2 = kv.get_int(kSeenCo2Key, 0);
    s.lux = kv.get_bool(kSeenLuxKey, false);
    return s;
}

inline void store_seen_sensors(KvStore& kv, const SeenSensors& s) {
    kv.set_int(kSeenCo2Key, s.co2);
    kv.set_bool(kSeenLuxKey, s.lux);
}

// The operator removed a sensor on purpose: the next boot learns again from
// what is fitted.
inline void forget_seen_sensors(KvStore& kv) {
    store_seen_sensors(kv, SeenSensors{});
}

}  // namespace sp
