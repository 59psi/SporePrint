#pragma once
//
// link_watchdog — the node's MQTT/WiFi-loss failsafe policy.
//
// CLAUDE.md §5c: "10min MQTT watchdog → safe mode". Before this, a dead Pi or
// broker left the lighting bank lit indefinitely (dim channels have no
// max-on) and relays running to their max-on, and the only WiFi recovery was
// the Arduino core's auto-reconnect — which gives up for good on some
// disconnect reasons (e.g. AUTH_FAIL during a router reboot), leaving the
// node dark until power-cycled.
//
// Policy (pure; the composition root performs the actions):
//   * MQTT disconnected for kSafeModeAfterMs → enter_safe_mode ONCE (the
//     root drives every channel off, exactly the boot state). Latched until
//     MQTT reconnects → exit_safe_mode ONCE (the root reports the channel
//     states it cut). Commands can only arrive over MQTT, so nothing can
//     turn a channel back on while in safe mode.
//   * WiFi down → wifi_retry every kWifiRetryMs (the root re-begins the STA
//     connection with the stored credentials). No reboot: a reboot drops the
//     RAM offline-telemetry buffer and, with WiFi still down at boot, lands
//     in the setup portal.
//
// Wrap-safe (elapsed-ms math; retry timestamps are refreshed each firing).
// Native-safe: no Arduino headers.

#include <stdint.h>

#include "wrap_time.h"

namespace sp {

class LinkWatchdog {
public:
    static constexpr uint32_t kSafeModeAfterMs = 10UL * 60UL * 1000UL;
    static constexpr uint32_t kWifiRetryMs = 60UL * 1000UL;

    struct Actions {
        bool enter_safe_mode = false;
        bool exit_safe_mode = false;
        bool wifi_retry = false;
    };

    // Start both clocks at boot (treated as "just seen").
    void begin(uint32_t now_ms) {
        last_mqtt_ok_ms_ = now_ms;
        last_wifi_attempt_ms_ = now_ms;
        safe_mode_ = false;
    }

    Actions update(uint32_t now_ms, bool wifi_up, bool mqtt_up) {
        Actions a;
        if (mqtt_up) {
            if (safe_mode_) {
                safe_mode_ = false;
                a.exit_safe_mode = true;
                last_outage_ms_ = elapsed_ms(now_ms, last_mqtt_ok_ms_);
            }
            last_mqtt_ok_ms_ = now_ms;
        } else if (!safe_mode_ &&
                   elapsed_ms(now_ms, last_mqtt_ok_ms_) >= kSafeModeAfterMs) {
            safe_mode_ = true;
            a.enter_safe_mode = true;
        }

        if (wifi_up) {
            last_wifi_attempt_ms_ = now_ms;
        } else if (elapsed_ms(now_ms, last_wifi_attempt_ms_) >= kWifiRetryMs) {
            last_wifi_attempt_ms_ = now_ms;
            a.wifi_retry = true;
        }
        return a;
    }

    bool safe_mode() const { return safe_mode_; }
    // Length of the outage that the last exit_safe_mode ended (log line).
    uint32_t last_outage_ms() const { return last_outage_ms_; }

private:
    uint32_t last_mqtt_ok_ms_ = 0;
    uint32_t last_outage_ms_ = 0;
    uint32_t last_wifi_attempt_ms_ = 0;
    bool safe_mode_ = false;
};

}  // namespace sp
