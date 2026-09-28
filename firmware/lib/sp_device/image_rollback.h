#pragma once
//
// image_rollback — OTA probation for both images (fw-node#12).
//
// The prebuilt SDK has CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE, but the Arduino
// core marks a freshly-OTA'd image valid in initArduino() — before setup() —
// unless the weak hook `verifyRollbackLater()` returns true. Each composition
// root defines that hook itself:
//
//     extern "C" bool verifyRollbackLater() { return true; }
//
// (it must live in the image's own translation unit: a strong definition
// inside a library archive is only linked if something else pulls that
// object file in, and the core's weak default already satisfies the
// reference). With it, the image stays ESP_OTA_IMG_PENDING_VERIFY until
// confirm_running_image(); any reset before that makes the bootloader boot
// the previous image. The policy (60 s of continuous MQTT, reached_broker
// before a deliberate restart) is sp::ImageConfirm in sp_core/boot_policy.h.

#include <esp_ota_ops.h>

#include "boot_policy.h"
#include "log_forward.h"
#include "mqtt_link.h"

namespace sp_device {

inline bool running_image_pending() {
    const esp_partition_t* running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    return running != nullptr &&
           esp_ota_get_state_partition(running, &state) == ESP_OK &&
           state == ESP_OTA_IMG_PENDING_VERIFY;
}

inline void confirm_running_image(sp::ImageConfirm& ic, const char* why) {
    ic.mark_done();
    if (!running_image_pending()) return;  // USB-flashed / already valid
    esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
    SP_LOG(err == ESP_OK ? LOG_INFO : LOG_ERROR, "[OTA] running image %s (%s)",
           err == ESP_OK ? "confirmed - rollback cancelled" : "confirm FAILED",
           why);
}

// Before an operator-requested reboot. A probation image is confirmed only if
// it reached the broker this boot: then the reboot is an operator action, not
// a failed image. One that never reached MQTT is left unconfirmed, so the
// reboot boots the previous image exactly as a power cycle would.
inline void confirm_before_deliberate_restart(sp::ImageConfirm& ic,
                                              MqttLink* mqtt,
                                              const char* why) {
    if (ic.reached_broker() || (mqtt != nullptr && mqtt->connected())) {
        confirm_running_image(ic, why);
    } else if (running_image_pending()) {
        SP_LOG(LOG_WARN,
               "[OTA] image never reached MQTT this boot - left unconfirmed; "
               "this restart boots the previous image");
    }
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
