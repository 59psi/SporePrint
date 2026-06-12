#pragma once
//
// Board profile — AI-Thinker ESP32-CAM (OV2640), platformio env: cam.
//
// Camera pin map is the AI-Thinker standard (matches v1). One deliberate
// change from v1: factory reset moves from GPIO 0 to GPIO 13 — v1 used
// GPIO 0 for BOTH the camera XCLK and the reset button, so arming the
// reset pullup fought the camera clock. GPIO 13 (SD DAT3) is free when no
// SD card is used, which is every SporePrint deployment.
//
// Included ONLY from src/ composition roots — never from lib/.

#define SP_BOARD_NAME "esp32-cam-ai-thinker"

// OV2640 sensor pins (AI-Thinker).
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

// Onboard flash LED.
#define SP_PIN_FLASH 4

// Factory reset — GPIO 13 (changed from v1's GPIO 0 / XCLK conflict).
#define SP_PIN_FACTORY_RESET 13
