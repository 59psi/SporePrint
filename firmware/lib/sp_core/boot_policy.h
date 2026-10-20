#pragma once
//
// boot_policy — pure decisions the node composition root makes around boot:
// when the setup portal may open, what the BOOT button does, and when a
// freshly-OTA'd image is confirmed. Host-tested in test_core_boot.
//
// Setup portal. The portal is an OPEN access point whose form
// rewrites the broker host, HMAC key and OTA password, so it must never
// open on its own for a node that is already working:
//   * unprovisioned node            → portal (first boot)
//   * operator asked for it         → portal (BOOT held 3-10 s, then
//                                     released: a one-shot NVS flag survives
//                                     the reboot) — physical presence
//   * WiFi connect fails at boot and the stored settings have NEVER
//     connected (just typed in the portal — likely a typo, operator present;
//     see portal_save_needs_first_connect)
//                                   → portal again
//   * WiFi connect fails at boot but the credentials HAVE worked before
//     (router rebooting after a power blip, AP out of range)
//                                   → boot offline; the link watchdog keeps
//                                     re-trying the STA connection
//
// BOOT button: held > 10 s → factory reset (while still held, as before);
// released after 3-10 s → setup portal; shorter presses do nothing. Only
// densely-sampled stretches count toward a hold (see kMaxSampleGapMs).
//
// OTA confirmation. The Arduino core marks a new image valid
// before setup() unless verifyRollbackLater() returns true, which defeats
// the bootloader's rollback. The node now confirms only after MQTT has been
// up continuously for kStableMs; a crash / WDT / power loss before that
// boots the previous image, and so does an operator restart before the image
// ever reached the broker (reached_broker). A confirm that itself fails (the
// OTA data write is refused) is retried after more MQTT time, backing off,
// so a working image is not silently rolled back at the next reset.
//
// A network OTA while the image is still on probation would overwrite the
// other slot — the last confirmed image, the one any reset boots
// (ota_probation_gate).
//
// Wrap-safe (elapsed-ms math). Native-safe: no Arduino headers.

#include <stdint.h>

#include "wrap_time.h"

namespace sp {

// Open the portal before any connect attempt?
inline bool portal_at_boot(bool provisioned, bool portal_requested) {
    return !provisioned || portal_requested;
}

// The boot-time connect attempt failed: open the portal (true) or boot
// offline and keep retrying (false)?
inline bool portal_after_connect_failure(bool creds_verified) {
    return !creds_verified;
}

// A portal save that must connect once before a later boot-time WiFi failure
// is treated as transient (clears NVS "wifi_ok"): new WiFi credentials, or
// Secure MQTT on with no CA pinned yet — the trust-on-first-use CA fetch
// needs the link at the next boot, and booting offline instead would fetch
// nothing and run the whole session on the plaintext fallback.
inline bool portal_save_needs_first_connect(bool wifi_creds_changed,
                                            bool tls_enabled, bool ca_pinned) {
    return wifi_creds_changed || (tls_enabled && !ca_pinned);
}

class ButtonHold {
public:
    static constexpr uint32_t kPortalHoldMs = 3000;
    static constexpr uint32_t kFactoryResetHoldMs = 10000;
    // Loop passes are not evenly spaced: with WiFi up and the broker down a
    // connect attempt blocks one pass for up to 15 s (.local DNS) or 3 s (TCP
    // timeout). Across a gap longer than this the button's state in between
    // is unknown, so a hold is timed over densely-sampled stretches only
    // (ordinary passes are budgeted at tens of ms).
    static constexpr uint32_t kMaxSampleGapMs = 1000;

    enum class Action : uint8_t { None, OpenPortal, FactoryReset };

    // Call every loop pass with the raw level, stamped with the time it was
    // READ (a fresh millis(), not a stamp taken before a blocking call). A
    // glitch can't last 3 s. Each hold yields at most one action, and a
    // factory reset only ever fires while the hold is being observed — never
    // inferred at release from the span between two sparse samples.
    Action update(uint32_t now_ms, bool pressed) {
        if (pressed) {
            if (!down_ || elapsed_ms(now_ms, last_ms_) > kMaxSampleGapMs) {
                // New press — or a gap long enough to hide a release and a
                // second press: start timing again from this sample.
                if (!down_) fired_ = false;
                down_ = true;
                since_ = now_ms;
                last_ms_ = now_ms;
                return Action::None;
            }
            last_ms_ = now_ms;
            if (!fired_ && elapsed_ms(now_ms, since_) > kFactoryResetHoldMs) {
                fired_ = true;
                return Action::FactoryReset;
            }
            return Action::None;
        }
        if (!down_) return Action::None;
        down_ = false;
        if (fired_) return Action::None;
        // The release happened somewhere after the last pressed sample; time
        // the hold to that sample (a lower bound). It is <= 10 s here — a
        // longer observed hold already fired above.
        if (elapsed_ms(last_ms_, since_) >= kPortalHoldMs)
            return Action::OpenPortal;
        return Action::None;
    }

private:
    bool down_ = false;
    bool fired_ = false;
    uint32_t since_ = 0;
    uint32_t last_ms_ = 0;
};

class ImageConfirm {
public:
    static constexpr uint32_t kStableMs = 60UL * 1000UL;
    // Ceiling of the retry backoff after failed confirms (each attempt
    // rewrites the OTA data sector, so a stuck failure must not hammer it).
    static constexpr uint32_t kMaxRetryMs = 60UL * 60UL * 1000UL;

    // True once MQTT has been connected continuously for kStableMs (after a
    // failed confirm: for the backed-off retry_after_ms()). A disconnect
    // restarts the clock. Fires once per attempt; confirm_failed() re-arms.
    bool update(uint32_t now_ms, bool mqtt_up) {
        if (mqtt_up) reached_broker_ = true;
        if (done_) return false;
        if (!mqtt_up) {
            up_ = false;
            return false;
        }
        if (!up_) {
            up_ = true;
            up_since_ = now_ms;
            return false;
        }
        if (elapsed_ms(now_ms, up_since_) >= need_ms_) {
            done_ = true;
            return true;
        }
        return false;
    }

    // The image was confirmed (or there is nothing to confirm).
    void mark_done() { done_ = true; }
    bool done() const { return done_; }

    // The confirm itself failed (the OTA data write was refused): the image
    // is still on probation and the next reset would boot the previous one.
    // Try again once MQTT has been up for twice as long as last time (up to
    // kMaxRetryMs) — never give up while the image keeps running.
    void confirm_failed() {
        done_ = false;
        up_ = false;
        need_ms_ = need_ms_ >= kMaxRetryMs / 2 ? kMaxRetryMs : need_ms_ * 2;
    }
    // Continuous MQTT time the next confirm attempt waits for.
    uint32_t retry_after_ms() const { return need_ms_; }

    // MQTT was up on at least one pass this boot. Gates confirmation before a
    // deliberate restart (operator command, BOOT gesture): an image that
    // reached the broker is confirmed so the reboot the operator asked for
    // doesn't read as a failed image; one that never did is left to roll
    // back, as a power cycle would.
    bool reached_broker() const { return reached_broker_; }

private:
    bool done_ = false;
    bool reached_broker_ = false;
    bool up_ = false;
    uint32_t up_since_ = 0;
    uint32_t need_ms_ = kStableMs;
};

// A network OTA push is about to be accepted. The core's Update writes the
// other app slot without asking ESP-IDF's esp_ota_begin(), which refuses
// exactly this case: while the running image is on probation, that slot
// holds the last confirmed image — the one any reset boots. Overwriting it
// leaves no confirmed image, and a power cycle no longer recovers the node.
enum class OtaProbation : uint8_t {
    Proceed,       // nothing on probation
    ConfirmFirst,  // the image reached MQTT this boot: confirm it, then flash
                   // (the policy a deliberate restart applies)
    Refuse,        // it never did: refuse the push; a power cycle boots the
                   // confirmed image, which then takes the push
};

inline OtaProbation ota_probation_gate(bool image_pending, bool reached_broker) {
    if (!image_pending) return OtaProbation::Proceed;
    return reached_broker ? OtaProbation::ConfirmFirst : OtaProbation::Refuse;
}

}  // namespace sp
