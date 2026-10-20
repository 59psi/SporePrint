#pragma once
//
// deferred_restart — the operator-requested reboot both images share (the
// BOOT / reset gesture into the setup portal; the node's peripheral-set
// change). The restart waits kDelayMs so the line saying why reaches MQTT,
// and the queued log lines are flushed right before it. A probation image is
// confirmed only if it reached MQTT this boot (image_rollback.h), so the
// gesture an operator reaches for when a fresh OTA cannot connect does not
// lock that image in. Boot step 1 drives every channel off again.

#include <Arduino.h>

#include "boot_policy.h"
#include "image_rollback.h"
#include "log_forward.h"
#include "mqtt_link.h"
#include "ota_service.h"
#include "wrap_time.h"

namespace sp_device {

class DeferredRestart {
public:
    static constexpr uint32_t kDelayMs = 1500;  // let logs / MQTT flush

    // `mqtt` / `ota` may be null (not constructed yet).
    void request(const char* why, sp::ImageConfirm& ic, MqttLink* mqtt,
                 OtaService* ota) {
        SP_LOG(LOG_WARN, "[SYSTEM] restarting: %s", why);
        confirm_before_deliberate_restart(ic, mqtt, ota, why);
        pending_ = true;
        requested_ms_ = millis();
    }

    bool pending() const { return pending_; }

    // Every loop pass. The delay is measured on a fresh millis(): a request
    // made by a command handled inside mqtt->loop() comes after that pass's
    // `now` was taken.
    void loop() {
        if (!pending_ || sp::elapsed_ms(millis(), requested_ms_) < kDelayMs)
            return;
        // Whatever is still queued (the reason for this restart among it)
        // goes out first.
        logfwd::flush_now();
        ESP.restart();
    }

private:
    bool pending_ = false;
    uint32_t requested_ms_ = 0;
};

}  // namespace sp_device
