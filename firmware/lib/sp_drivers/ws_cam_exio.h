#pragma once
//
// ws_cam_exio — the on-board I/O expander of the Waveshare
// ESP32-S3-CAM-OVxxxx (a CH32V003 running Waveshare's expander firmware,
// I²C 0x24 on the board bus GPIO 8 / 7). The camera image (env
// cam_waveshare_s3) uses it for one thing: holding the sensor powered.
//
// Register protocol (Waveshare's own drivers: the Arduino demo's
// io_extension.{h,cpp} and the ESP-IDF BSP's custom_io_expander_ch32v003):
//   write {0x02, mask}    direction, one bit per EXIO, 1 = output
//   write {0x03, levels}  output levels
//
// EXIO assignment (ESP32-S3-CAM-XXXX-schematic.pdf, GPIO table):
//   EXIO0 TP_RST   EXIO1 LCD_RST  EXIO2 SD_CS    EXIO3 CAM_PWDN
//   EXIO4 PA_CTRL  EXIO5 BAT_EN   EXIO6 PWR_LED  EXIO7 CHG_DET (input)
//
// camera_power_on() drives CAM_PWDN low (sensor on; the schematic's R8
// pull-down already holds it there while the pin floats, this makes it
// definite) and leaves the rest where Waveshare's BSP leaves them: the
// LCD / touch resets and SD chip select deasserted (high), the speaker
// amplifier off (PA_CTRL low), BAT_EN high (keeps a battery-powered board
// latched on; no effect on USB power) and the power LED on. EXIO7 stays an
// input: it is the charger's status line, and driving it would fight the
// charge-detect transistor.
//
// Native-safe; host-tested against scripted bus transactions.

#include <stdint.h>

#include "sp_hal/i2c_bus.h"

namespace sp {

class WsCamExio {
public:
    static constexpr uint8_t kAddr = 0x24;
    static constexpr uint8_t kRegDirection = 0x02;
    static constexpr uint8_t kRegOutput = 0x03;

    static constexpr uint8_t kTpRst = 1u << 0;
    static constexpr uint8_t kLcdRst = 1u << 1;
    static constexpr uint8_t kSdCs = 1u << 2;
    static constexpr uint8_t kCamPwdn = 1u << 3;
    static constexpr uint8_t kPaCtrl = 1u << 4;
    static constexpr uint8_t kBatEn = 1u << 5;
    static constexpr uint8_t kPwrLed = 1u << 6;
    static constexpr uint8_t kChgDet = 1u << 7;

    // Every EXIO but CHG_DET is an output.
    static constexpr uint8_t kOutputs = (uint8_t)~kChgDet;
    // Camera powered (PWDN low), amplifier off, everything else idle.
    static constexpr uint8_t kCameraOnLevels =
        kTpRst | kLcdRst | kSdCs | kBatEn | kPwrLed;

    explicit WsCamExio(I2cBus& bus) : bus_(bus) {}

    // Direction, then levels. False when either write is NACKed (no
    // expander answering at 0x24: the camera may still come up, held on
    // by the PWDN pull-down).
    bool camera_power_on();

private:
    I2cBus& bus_;
};

}  // namespace sp
