#pragma once
//
// task_wdt — the loop-task watchdog on ESP-IDF 5 (Arduino-ESP32 3.x).
//
// The core initializes the task WDT before setup() (CONFIG_ESP_TASK_WDT_INIT:
// 5 s, panic, the CPU0 idle task subscribed). On core 2.x (IDF 4.4) the
// composition roots re-ran esp_task_wdt_init(timeout_s, true), which IDF 4.4
// accepted as "change the timeout". IDF 5 takes a config struct and refuses a
// second init (ESP_ERR_INVALID_STATE), so the timeout is changed with
// esp_task_wdt_reconfigure() — keeping the idle-task subscription the core
// made, i.e. exactly what the 2.x re-init changed (the timeout) and nothing
// else. A build with CONFIG_ESP_TASK_WDT_INIT off falls through to init.
//
// pet_task_wdt(): for the sanctioned pet sites outside loop()'s top (the OTA
// flash). IDF 5's esp_task_wdt_reset() logs a "task not found" error for an
// unsubscribed task (IDF 4.4 returned silently) — e.g. anything still in
// setup() — so it pets only a subscribed task. (The coredump upload no longer
// needs one: it sends a few chunks per loop pass.)

#include <esp_err.h>
#include <esp_task_wdt.h>
#include <sdkconfig.h>

#include <stdint.h>

namespace sp_device {

// Idle tasks the core's own TWDT init watches (Kconfig), kept on reconfigure.
constexpr uint32_t kTwdtIdleCoreMask =
#if defined(CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU0)
    (1u << 0) |
#endif
#if defined(CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU1)
    (1u << 1) |
#endif
    0u;

// Set the task-WDT timeout (panic on expiry) and subscribe the CALLING task.
// The composition roots call this once, at the end of setup().
inline esp_err_t arm_loop_task_wdt(uint32_t timeout_s) {
    esp_task_wdt_config_t cfg = {};
    cfg.timeout_ms = timeout_s * 1000UL;
    cfg.idle_core_mask = kTwdtIdleCoreMask;
    cfg.trigger_panic = true;
    esp_err_t err = esp_task_wdt_reconfigure(&cfg);
    if (err == ESP_ERR_INVALID_STATE) err = esp_task_wdt_init(&cfg);
    if (err != ESP_OK) return err;
    return esp_task_wdt_add(nullptr);
}

// Pet the task WDT from a long operation — only if the calling task is
// subscribed (see above).
inline void pet_task_wdt() {
    if (esp_task_wdt_status(nullptr) == ESP_OK) esp_task_wdt_reset();
}

}  // namespace sp_device
