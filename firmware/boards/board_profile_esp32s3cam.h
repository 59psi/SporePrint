#pragma once
//
// Board profile — ESP32-S3 camera boards, platformio envs cam_esp32s3,
// cam_xiao_esp32s3 and cam_waveshare_s3. These are the S3 camera boards the
// BOM listed from 2026-04-15 to 2026-06-11 (the AI-Thinker ESP32-CAM, env
// cam, is the camera it recommends today). The cam image is the same; only
// the pin map, the flash LED and the reset button differ. Sensor: OV2640,
// OV3660 or OV5640 on the board's 24-pin DVP connector, detected at init by
// PID like on the AI-Thinker.
//
// Pin maps, by source:
//   * Freenove ESP32-S3-WROOM CAM (FNK0085, N8R8) — the 2026-04-16 BOM
//     camera — is wired like Espressif's ESP32-S3-EYE: arduino-esp32
//     3.3.12 CameraWebServer/camera_pins.h CAMERA_MODEL_ESP32S3_EYE (the
//     model Freenove's own examples select). Generic "ESP32-S3 CAM" boards
//     that are Freenove clones use the same map; one whose vendor example
//     selects another model is not this board.
//   * Seeed Studio XIAO ESP32S3 Sense: camera_pins.h
//     CAMERA_MODEL_XIAO_ESP32S3.
//   * Waveshare ESP32-S3-CAM-OVxxxx (OV5640 / OV3660 / GC2145 / GC0308
//     variants; ESP32-S3R8 + 16 MB flash): Waveshare's schematic
//     (ESP32-S3-CAM-XXXX-schematic.pdf, GPIO table) and its BSP
//     (esp32_s3_cam_ovxxxx.h BSP_CAMERA_*), which agree pin for pin. Its
//     SCCB shares the board I²C bus (GPIO 8 / 7) with an on-board
//     CH32V003 I/O expander at 0x24 whose EXIO3 drives the sensor's PWDN
//     (sp_drivers/ws_cam_exio.h).
//
// None of the three has a flash LED (SP_PIN_FLASH -1: frames are taken by
// the chamber's own light, X-Flash-Used: 0). The reset/portal button is the
// board's BOOT button, GPIO 0 on all three — GPIO 0 is free here (the
// AI-Thinker needs it for XCLK, hence its GPIO 13). SP_CAM_BOARD_KIND names
// the board for src/cam/cam_policy.h (orientation); SP_CAM_XCLK_HZ is each
// vendor's own camera clock.
//
// Included ONLY from src/ composition roots — never from lib/.

#if defined(SP_CAM_BOARD_XIAO_S3)

#define SP_BOARD_NAME "xiao-esp32s3-sense"
#define SP_CAM_BOARD_KIND XiaoS3
#define SP_CAM_XCLK_HZ 20000000  // Seeed's examples

#define SP_CAM_PWDN -1
#define SP_CAM_RESET -1
#define SP_CAM_XCLK 10
#define SP_CAM_SIOD 40
#define SP_CAM_SIOC 39
#define SP_CAM_Y9 48
#define SP_CAM_Y8 11
#define SP_CAM_Y7 12
#define SP_CAM_Y6 14
#define SP_CAM_Y5 16
#define SP_CAM_Y4 18
#define SP_CAM_Y3 17
#define SP_CAM_Y2 15
#define SP_CAM_VSYNC 38
#define SP_CAM_HREF 47
#define SP_CAM_PCLK 13

#elif defined(SP_CAM_BOARD_WAVESHARE_S3)

#define SP_BOARD_NAME "waveshare-esp32-s3-cam"
#define SP_CAM_BOARD_KIND WaveshareS3
#define SP_CAM_XCLK_HZ 20000000  // Waveshare's demo and BSP

#define SP_CAM_PWDN -1   // on the I/O expander (EXIO3), not a GPIO
#define SP_CAM_RESET -1  // RC power-on reset (R10 / C20)
#define SP_CAM_XCLK 38
#define SP_CAM_SIOD 8    // board I²C SDA (TWI_SDA), shared with the expander
#define SP_CAM_SIOC 7    // board I²C SCL (TWI_CLK)
#define SP_CAM_Y9 21     // CAM_D7
#define SP_CAM_Y8 39     // CAM_D6
#define SP_CAM_Y7 40     // CAM_D5
#define SP_CAM_Y6 42     // CAM_D4
#define SP_CAM_Y5 46     // CAM_D3
#define SP_CAM_Y4 48     // CAM_D2
#define SP_CAM_Y3 47     // CAM_D1
#define SP_CAM_Y2 45     // CAM_D0
#define SP_CAM_VSYNC 17
#define SP_CAM_HREF 18
#define SP_CAM_PCLK 41

// SCCB rides the board I²C bus: the cam opens I²C port 0 on SIOD / SIOC
// (src/cam/idf_i2c_bus.h), sets the expander up over it, and the camera
// driver reuses that bus (camera_config_t pin_sccb_sda = -1, sccb_i2c_port).
#define SP_CAM_SCCB_I2C_PORT 0
#define SP_CAM_HAS_WS_EXIO 1

#else  // SP_CAM_BOARD_S3_EYE (default): Freenove ESP32-S3-WROOM CAM

#define SP_BOARD_NAME "freenove-esp32-s3-wroom-cam"
#define SP_CAM_BOARD_KIND FreenoveS3
// Freenove's own camera_init runs XCLK at 10 MHz on this board (vs the
// usual 20): a still every 15 min loses nothing at the lower frame rate.
#define SP_CAM_XCLK_HZ 10000000

#define SP_CAM_PWDN -1
#define SP_CAM_RESET -1
#define SP_CAM_XCLK 15
#define SP_CAM_SIOD 4
#define SP_CAM_SIOC 5
#define SP_CAM_Y9 16
#define SP_CAM_Y8 17
#define SP_CAM_Y7 18
#define SP_CAM_Y6 12
#define SP_CAM_Y5 10
#define SP_CAM_Y4 8
#define SP_CAM_Y3 9
#define SP_CAM_Y2 11
#define SP_CAM_VSYNC 6
#define SP_CAM_HREF 7
#define SP_CAM_PCLK 13

#endif

// No flash LED on any of the three boards.
#define SP_PIN_FLASH -1

// Reset / setup-portal button: the board's BOOT button.
#define SP_PIN_FACTORY_RESET 0
