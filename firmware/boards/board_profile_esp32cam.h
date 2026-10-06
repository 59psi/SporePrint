#pragma once
//
// Board profile — AI-Thinker ESP32-CAM, platformio env: cam. Sensor: OV2640
// (original), OV3660 (what the BOM 2-pack now ships) or OV5640 — all three
// use the same 24-pin module connector and this pin map; the firmware
// detects which one is fitted at init (sensor PID) and tunes per sensor.
//
// Camera pin map is the AI-Thinker standard (matches v1). One deliberate
// change from v1: factory reset moves from GPIO 0 to GPIO 13 — v1 used
// GPIO 0 for BOTH the camera XCLK and the reset button, so arming the
// reset pullup fought the camera clock. GPIO 13 (SD DAT3) is free when no
// SD card is used, which is every SporePrint deployment.
//
// Included ONLY from src/ composition roots — never from lib/.

#define SP_BOARD_NAME "esp32-cam-ai-thinker"

// Camera sensor pins (AI-Thinker) — shared by OV2640 / OV3660 / OV5640.
#define SP_CAM_PWDN 32
#define SP_CAM_RESET -1
#define SP_CAM_XCLK 0
#define SP_CAM_SIOD 26
#define SP_CAM_SIOC 27
#define SP_CAM_Y9 35
#define SP_CAM_Y8 34
#define SP_CAM_Y7 39
#define SP_CAM_Y6 36
#define SP_CAM_Y5 21
#define SP_CAM_Y4 19
#define SP_CAM_Y3 18
#define SP_CAM_Y2 5
#define SP_CAM_VSYNC 25
#define SP_CAM_HREF 23
#define SP_CAM_PCLK 22

// Onboard flash LED — plain GPIO on/off. LEDC is the camera's: its XCLK runs
// on LEDC timer 0 / channel 0 (src/cam/main.cpp init_camera), set up through
// ESP-IDF, which the Arduino LEDC allocator (ledcAttach / analogWrite) cannot
// see — it would hand out that same channel. scripts/image_guard.py fails a
// cam build that links it.
#define SP_PIN_FLASH 4

// Factory reset — GPIO 13 (changed from v1's GPIO 0 / XCLK conflict).
#define SP_PIN_FACTORY_RESET 13
