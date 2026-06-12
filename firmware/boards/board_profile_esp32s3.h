#pragma once
//
// Board profile — ESP32-S3-DevKitC-1 (N8R8/N16R8), platformio env:
// node_esp32s3.
//
// Pin choices avoid: strapping pins (0, 3, 45, 46), native USB (19, 20),
// flash/PSRAM (26–37 on octal-PSRAM modules), and the v1.1 RGB LED (38).
// SDA/SCL match the DevKitC-1 silk defaults. BENCH VERIFICATION PENDING —
// the BOM keeps WROOM-32 canonical until an S3 board passes the checklist.
//
// Included ONLY from src/ composition roots — never from lib/.

#define SP_BOARD_NAME "esp32-s3-devkitc-1"

#define SP_PIN_I2C_SDA 8
#define SP_PIN_I2C_SCL 9

#define SP_CHANNEL_PINS {4, 5, 6, 7}
#define SP_CHANNEL_COUNT 4

#define SP_PIN_HX711_DOUT 10
#define SP_PIN_HX711_SCK 11
#define SP_PIN_REED 12  // full GPIO on S3 — internal pullup works here

#define SP_UART_CO2_RX 16
#define SP_UART_CO2_TX 17

// Factory reset — BOOT button (GPIO 0; read-only use is strapping-safe).
#define SP_PIN_FACTORY_RESET 0

// LEDC: S3 has exactly 8 channels — both banks fit, nothing else may
// claim LEDC on this board.
#define SP_LEDC_FREQ_HZ 25000
#define SP_LEDC_RES_BITS 10
