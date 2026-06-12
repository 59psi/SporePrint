#pragma once
//
// wifi_provisioner — first-boot captive portal + WiFi bring-up.
//
// WDT contract: everything here runs BEFORE the task watchdog is armed
// (the composition root subscribes the loop task only in
// enterSteadyState()). v1 armed a 10-second panic WDT and then ran this
// portal — the AP died every 10 s and first-boot provisioning was
// physically impossible. Hang protection here is explicit deadlines
// instead: the portal keeps its 10-minute reboot ceiling, and connect()
// gives up after 20 s per attempt.
//
// Portal v2 fields (v1 collected only ssid/pass — nodes could never learn
// a non-default broker, an OTA password, or an HMAC key):
//   WiFi SSID + password
//   Pi address (broker host; default sporeprint.local)
//   MQTT username/password (optional)
//   Node id (optional; default node-XXXX from MAC)
//   Personality: climate / relay / lighting
//   OTA password (optional but recommended, min 12 chars enforced at use)
//   HMAC signing key (optional; empty keeps the warn+accept migration
//     posture — the operator sees a warning per accepted command)
//   NTP host (default pool.ntp.org; set to the Pi for airgapped rooms)

#include <Arduino.h>

#include "node_config.h"

namespace sp_device {

class WifiProvisioner {
public:
    explicit WifiProvisioner(NvsKvStore& kv) : kv_(kv) {}

    // Try the stored credentials. Returns true when WL_CONNECTED inside
    // `timeout_ms`. Non-throwing, no reboot — caller decides what's next.
    bool connect(const NodeConfig& cfg, uint32_t timeout_ms = 20000);

    // Run the captive portal ("SporePrint-Setup" open AP) until the form
    // is submitted (saves config + restarts) or the 10-minute ceiling
    // passes (restarts to retry stored creds). Never returns.
    [[noreturn]] void run_portal(const NodeConfig& current);

    // Start SNTP (UTC) against the configured host; non-blocking with a
    // bounded initial wait. Signed-command verification stays clock-gated
    // until time() reports a post-2020 epoch.
    void start_ntp(const NodeConfig& cfg);

private:
    NvsKvStore& kv_;
};

}  // namespace sp_device
