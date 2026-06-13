#pragma once
//
// Board profile — classic ESP32-WROOM-32 38-pin DevKit (canonical node
// board, platformio env: node_esp32).
//
// These pins ARE the wiring contract: they match every wiring diagram
// (docs/wiring-tier*.svg), the hardware guides, and the v1 firmware, so
// existing field wiring carries over unchanged. Per project rule, changing
// any pin here requires updating every wiring diagram/BOM/setup guide in
// the same PR.
//
// Included ONLY from src/ composition roots — never from lib/.

#define SP_BOARD_NAME "esp32-wroom-32"

// Shared I²C bus (SHT3x/SHT4x + SCD4x/SCD30 + BH1750).
#define SP_PIN_I2C_SDA 21
#define SP_PIN_I2C_SCL 22

// Channel bank — 4× MOSFET gates (relay personality: fae/exhaust/
// circulation/aux · lighting personality: white/blue/red/far_red).
#define SP_CHANNEL_PINS {25, 26, 27, 14}
#define SP_CHANNEL_COUNT 4

// Tier 3 peripherals (config-flag enabled).
#define SP_PIN_HX711_DOUT 32
#define SP_PIN_HX711_SCK 33
#define SP_PIN_REED 35  // input-only pin: INPUT only — external behavior
                        // matches INPUT_PULLUP wiring (leg to GND) because
                        // GPIO34-39 have no internal pulls; wiring guide
                        // calls for the magnet-closed = LOW convention.

// MH-Z19C on UART2.
#define SP_UART_CO2_RX 16
#define SP_UART_CO2_TX 17

// Factory reset — BOOT button (hold 10 s).
#define SP_PIN_FACTORY_RESET 0

// LEDC: classic ESP32 has 16 channels; both banks fit with headroom.
#define SP_LEDC_FREQ_HZ 25000
#define SP_LEDC_RES_BITS 10
