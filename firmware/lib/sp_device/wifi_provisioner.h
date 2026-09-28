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
//   Personality: climate / relay / lighting (node image only — the camera
//     has no channel bank and ignores it, so its portal doesn't show it)
//   OTA password (optional but recommended, min 12 chars enforced at use)
//   HMAC signing key (optional; empty keeps the warn+accept migration
//     posture — the operator sees a warning per accepted command)
//   Secure MQTT (tls_en) + Require TLS (tls_req: with no pinned Pi CA, stay
//     offline instead of the loud plaintext fallback — tls_policy.h)
//   NTP host (default pool.ntp.org; set to the Pi for airgapped rooms)
//   Optional peripherals (node image only): MH-Z19C, HX711 scale, reed
//     door switch — the NVS flags the node's setup() reads (docs#0) — and
//     the reed invert option (reed_inv: contact wired on its NO lead)
//
// Form policy (sp_core/provisioning.h, host-tested): every pre-filled value
// is HTML-escaped; blank password fields keep the stored secret (WiFi only
// for the same SSID; "Open network" clears it); the node id must match the
// server's NODE_ID_RE and equal the MQTT username when one is set (the
// broker ACL scopes each node by username) — blank = the username. A
// refused form is re-rendered with the error instead of being saved, carrying
// back exactly what was submitted (secrets included — never the stored ones)
// so a resubmit saves what was first intended.
//
// When the portal opens is the composition root's call. The node image
// follows sp_core/boot_policy.h: a provisioned node whose WiFi has worked
// before no longer falls into this open AP just because the router was slow
// to come back (fw-node#9).

#include <Arduino.h>

#include "node_config.h"

namespace sp_device {

class WifiProvisioner {
public:
    // `peripheral_opts`: render + save the Tier-3 peripheral checkboxes. Only
    // the node image builds those drivers — the camera keeps the default.
    // `personality_opt`: render + save the "Node personality" select. Only
    // the node image has a channel bank — the camera keeps the default (its
    // portal used to show the select although the image ignores it). When
    // off, a stored personality is left untouched.
    explicit WifiProvisioner(NvsKvStore& kv, bool peripheral_opts = false,
                             bool personality_opt = false)
        : kv_(kv),
          peripheral_opts_(peripheral_opts),
          personality_opt_(personality_opt) {}

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
    bool peripheral_opts_;
    bool personality_opt_;
};

}  // namespace sp_device
