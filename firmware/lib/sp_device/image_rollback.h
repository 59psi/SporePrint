#pragma once
//
// image_rollback — OTA probation for both images.
//
// The prebuilt SDK has CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE — core 3.x and
// core 2.0.17 alike, so the 2.x bootloader every field node keeps (OTA never
// replaces it) honours the probation below for 3.x images too. The Arduino
// core (2.x and 3.x) marks a freshly-OTA'd image valid in initArduino() —
// before setup() — unless the weak hook `verifyRollbackLater()` returns
// true. Each composition root defines that hook itself:
//
//     extern "C" bool verifyRollbackLater() { return true; }
//
// (it must live in the image's own translation unit: a strong definition
// inside a library archive is only linked if something else pulls that
// object file in, and the core's weak default already satisfies the
// reference). With it, the image stays ESP_OTA_IMG_PENDING_VERIFY until
// confirm_running_image(); any reset before that makes the bootloader boot
// the previous image. The policy (60 s of continuous MQTT, reached_broker
// before a deliberate restart, retrying a confirm that failed, no network
// OTA over the confirmed image) is sp_core/boot_policy.h.

#include <esp_ota_ops.h>

#include "boot_policy.h"
#include "log_forward.h"
#include "mqtt_link.h"
#include "ota_service.h"

namespace sp_device {

inline bool running_image_pending() {
    const esp_partition_t* running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    return running != nullptr &&
           esp_ota_get_state_partition(running, &state) == ESP_OK &&
           state == ESP_OTA_IMG_PENDING_VERIFY;
}

// Confirm the running image (cancel the rollback). True when it is confirmed
// now, or there was nothing to confirm. A confirm that fails (the OTA data
// write is refused) leaves the image on probation — the next reset would
// boot the previous image — so ImageConfirm re-arms to try again after more
// MQTT time instead of the attempt being lost. `ota` (may be null) raises the
// anti-rollback floor a manifest-verified push left pending for this image.
inline bool confirm_running_image(sp::ImageConfirm& ic, OtaService* ota,
                                  const char* why) {
    if (!running_image_pending()) {  // USB-flashed / already valid
        ic.mark_done();
        return true;
    }
    const esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
    if (err == ESP_OK) {
        ic.mark_done();
        SP_LOG(LOG_INFO, "[OTA] running image confirmed - rollback cancelled (%s)",
               why);
        if (ota != nullptr) ota->image_confirmed();
        return true;
    }
    ic.confirm_failed();
    SP_LOG(LOG_ERROR,
           "[OTA] running image confirm FAILED (%s): %s - still on probation, "
           "retrying after %u s more of MQTT",
           why, esp_err_to_name(err), (unsigned)(ic.retry_after_ms() / 1000UL));
    return false;
}

// Before an operator-requested reboot. A probation image is confirmed only if
// it reached the broker this boot: then the reboot is an operator action, not
// a failed image. One that never reached MQTT is left unconfirmed, so the
// reboot boots the previous image exactly as a power cycle would.
inline void confirm_before_deliberate_restart(sp::ImageConfirm& ic,
                                              MqttLink* mqtt, OtaService* ota,
                                              const char* why) {
    if (ic.reached_broker() || (mqtt != nullptr && mqtt->connected())) {
        confirm_running_image(ic, ota, why);
    } else if (running_image_pending()) {
        SP_LOG(LOG_WARN,
               "[OTA] image never reached MQTT this boot - left unconfirmed; "
               "this restart boots the previous image");
    }
}

// OtaService's before_flash hook (both composition roots wire it): an
// authenticated push is about to be accepted. While this image is on
// probation the other slot holds the last confirmed image, and the push
// would overwrite it (sp::ota_probation_gate). nullptr = go ahead, else the
// reason the push is refused with.
inline const char* clear_probation_for_ota(sp::ImageConfirm& ic,
                                           MqttLink* mqtt, OtaService* ota) {
    const bool reached =
        ic.reached_broker() || (mqtt != nullptr && mqtt->connected());
    switch (sp::ota_probation_gate(running_image_pending(), reached)) {
        case sp::OtaProbation::Proceed:
            return nullptr;
        case sp::OtaProbation::ConfirmFirst:
            return confirm_running_image(ic, ota, "network OTA push")
                       ? nullptr
                       : "image_confirm_failed";
        case sp::OtaProbation::Refuse:
            SP_LOG(LOG_WARN,
                   "[OTA] push refused: this image is on probation and never "
                   "reached MQTT - power-cycle to boot the previous image, "
                   "then push again");
            return "image_on_probation";
    }
    return nullptr;
}

// Boot log + nothing-to-confirm bookkeeping; call at the end of setup().
inline void note_probation_at_boot(sp::ImageConfirm& ic) {
    if (running_image_pending()) {
        SP_LOG(LOG_WARN,
               "[OTA] new image on probation: confirmed after %u s of MQTT; "
               "a crash or reboot before then boots the previous image",
               (unsigned)(sp::ImageConfirm::kStableMs / 1000UL));
    } else {
        ic.mark_done();  // nothing to confirm
    }
}

}  // namespace sp_device
