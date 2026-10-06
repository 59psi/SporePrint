# Firmware driver inventory

Every sensor, actuator and board the bill of materials recommends today, or
recommended at any point in the project's history, mapped to the firmware
that drives it. **Project rule:** a driver is never removed. Anything a BOM
once told an operator to buy keeps working.

Sources scanned: every revision of `server/app/builder/hardware_guides.py`,
`README.md`, `docs/hardware-build-guide.md`, `docs/*.svg` and `CLAUDE.md` in
this repo, plus the cloud repo's shopping alternates and
`frontend/HARDWARE_AUDIT.md`. Last full pass: 2026-10-05.

Status values:

- **OK**: a driver ships and has host tests.
- **OK (new)**: added in the 2026-10 driver pass.
- **partial**: driven, with a known hardware limit on some board (stated
  in the row).
- **n/a**: a passive part, a load on a MOSFET channel, or a device that talks
  to the Pi rather than to an ESP32.
- **MISSING**: no firmware support. Nothing the BOM ever recommended is in
  this state now.

## Sensors

Telemetry keys are the `sporeprint/<node_id>/telemetry` fields
(`lib/sp_core/wire_contract.h`). Every key is optional: a node publishes only
what it has. Health names are the keys under `sensors` in
`sporeprint/<node_id>/health`.

| Part (where / when recommended) | Bus / protocol | Driver | Autodetect | Telemetry keys | Native tests | Status |
|---|---|---|---|---|---|---|
| **SHT31-D**: Adafruit 2857 (canonical temp/RH since 2026-06; v1's part), HiLetgo GY-SHT31-D, DFRobot SEN0331 | I²C 0x44 / 0x45, 16-bit commands + CRC-8, single-shot no-stretch `0x2400` | `lib/sp_drivers/sht3x.cpp` | yes, probed after SHT4x with a soft reset in between | `temp_f` `temp_c` `humidity` `dew_point_f` | `test_drivers_i2c` | OK |
| **SHT45 / SHT41 / SHT40**: Adafruit 5665 / 5776 / 4885 (the v4.1 "drop-in" promotion; listed alternates) | I²C 0x44 / 0x45, 1-byte commands `0xFD` / `0x89` | `lib/sp_drivers/sht4x.cpp` | yes, probed first at each SHT address | same as SHT3x | `test_drivers_i2c` | OK |
| **AHT20 / AHT21 / AHT25**: Adafruit 4566, the AHT20 half of "AHT20 + BMP280" combo boards (cloud shopping alternate 2026-05 to 2026-10; the audit recorded "AHT20 remains undriven") | I²C 0x38, status `0x71`, init when `(status & 0x18) != 0x18`: Aosong's v1.1 register init of 0x1B / 0x1C / 0x1E, then the v1.0 `0xBE 08 00` if still uncalibrated; trigger `0xAC 33 00`, 80 ms conversion, CRC-8 0x31/0xFF | `lib/sp_drivers/aht20.cpp` | yes, by one CRC-valid measurement (~90 ms, boot only); an ACK alone at 0x38 is not trusted | temp/RH keys, only when no SHT is fitted | `test_drivers_i2c` (formulas, busy, CRC, calibration bit, the v1.1 init transaction script at boot and as the non-blocking runtime re-init, async pump, 2 s self-heating limit) | OK (new) |
| **BME280**: shown on the climate node in `docs/architecture-overview.svg` ("BME280 Pressure", then "Optional BME280") from 2026-04-14 to 2026-09-27 | I²C 0x76 / 0x77, chip ID `0xD0` = `0x60`, forced mode ×1/×1/×1, Bosch integer compensation | `lib/sp_drivers/bme280.cpp` | yes, by chip ID | `pressure_hpa` (new, additive); temp/RH keys only as a fallback below SHT and AHT | `test_drivers_i2c` (BMP280 datasheet worked example, humidity vs. the datasheet double formula, trim layout incl. signed H4/H5, forced-mode transactions) | OK (new) |
| **BMP280**: the BMP280 half of the "AHT20 + BMP280" combo; also what many "BME280" listings actually ship | I²C 0x76 / 0x77, chip ID `0x58` (`0x56` / `0x57` samples) | `lib/sp_drivers/bme280.cpp` | yes, by chip ID; reported as `bmp280`, never claims humidity | `pressure_hpa` | `test_drivers_i2c` | OK (new) |
| **SCD41 / SCD40**: Adafruit 5190 / 5187 (canonical CO₂), Pimoroni PIM587, SparkFun SEN-22395 / SEN-22396 | I²C 0x62, periodic mode, ASC forced off, FRC on command | `lib/sp_drivers/scd4x.cpp` | yes, stops a stale periodic mode first | `co2_ppm` (+ coarse temp/RH fallback) | `test_drivers_i2c` | OK |
| **SCD30**: Adafruit 4867 (alternate) | I²C 0x61, data-ready gated, clock-stretching (≤ 30 ms per Sensirion; 150 ms once a day) | `lib/sp_drivers/scd30.cpp` + `src/node/stretch_i2c_bus.h` | yes | `co2_ppm` (+ fallback) | `test_drivers_i2c` | **ESP32-S3: OK** (bench-pending). **WROOM-32 (`node_esp32`): partial, bench-pending.** Core 3.x's Wire allows only a 2 ms stretch, so 0x61 has its own IDF device at 50 kHz with the stretch timeout at the hardware ceiling: 52 ms on the S3 (covers Sensirion's 30 ms), but 13.1 ms on the classic ESP32 (a 20-bit APB-cycle register, the same limit core 2.x had). On a WROOM-32 every stretch past 13.1 ms fails that read (counted, retried next pass, never data); how often that happens in practice is the bench item |
| **MH-Z19C**: Winsen, UART alternate (current BOM) | UART2 9600 8N1 (WROOM-32 GPIO 16 / 17, S3 the same), 9-byte frames + checksum | `lib/sp_drivers/mhz19.cpp` | no: config flag `mhz19` (portal or `cmd/config peripherals`) | `co2_ppm` | `test_drivers_misc` | OK |
| **MH-Z19B**: `CLAUDE.md` §5b and the BOM's budget CO₂ alternate 2026-04 to 2026-06 | same frames as the C (read `0x86`, ABC `0x79`, zero `0x87`) | `lib/sp_drivers/mhz19.cpp` | no: same `mhz19` flag | `co2_ppm` | `test_drivers_misc` pins the B manual's frames and its example reply byte for byte | OK |
| **BH1750**: Adafruit 4681, HiLetgo GY-302, DFRobot | I²C 0x23 / 0x5C, continuous high-res, lux = counts / 1.2 | `lib/sp_drivers/bh1750.cpp` | yes, 0x23 then 0x5C | `lux` | `test_drivers_i2c` | OK |
| **HX711** load-cell ADC: Adafruit 5974 and generic boards | bit-banged DOUT / PD_SCK (WROOM-32 GPIO 32 / 33, S3 10 / 11), 25 pulses = gain 128, channel A | `lib/sp_drivers/hx711.cpp` (+ `sp_core/scale_calibrator.h`) | no: config flag `hx711` | `weight_g` once calibrated, `scale_raw` before (sent, not stored) | `test_drivers_misc`, `test_core_sensing` | OK |
| **Load cells**: Adafruit 4541 (5 kg, 75 mm bar), TAL220 80 mm (SparkFun SEN-13329, YZC-133 kits), SparkFun SEN-14729 (55 mm TAL220B) | analog Wheatstone bridge into the HX711 | none needed (the HX711 driver) | n/a | `weight_g` | n/a | n/a. Electrically identical. Only the printed `hx711_scale` fit differs (SEN-14729 does not fit it) |
| **Door contact / reed switch**: weideer MC-31B (COM + NC; NO wiring via `reed_inv`), bare N.O. reed | GPIO (WROOM-32 GPIO 35 + external 10 kΩ pull-up; S3 GPIO 12, internal pull-up), 50 ms debounce | `lib/sp_drivers/reed_switch.h` | no: config flags `reed`, `reed_inv` | `door_open` + `door` alerts | `test_drivers_misc` | OK |

Address map of the autodetected set. No two supported parts share an
address except where the probe tells them apart:

| Address | Candidates | How they are told apart |
|---|---|---|
| 0x23 / 0x5C | BH1750 | ACK of power-on (only part there) |
| 0x38 | AHT2x | a CRC-valid measurement, not an ACK (PCF8574A expanders and FT62xx touch controllers also use 0x38) |
| 0x44 / 0x45 | SHT4x, SHT3x | SHT4x `0x89` serial + CRC first, then SHT3x soft reset + `0x3780` serial |
| 0x61 | SCD30 | firmware-version read + CRC |
| 0x62 | SCD4x | stop periodic, then serial + CRC |
| 0x76 / 0x77 | BME280, BMP280 | chip ID; BME680 (`0x61`) and BMP180 (`0x55`) are rejected, not misread |

Temp/RH source priority when several are fitted: SHT3x/SHT4x, then AHT20,
then BME280, then the SCD4x/SCD30 coarse fallback. An AHT20 next to an SHT is
detected and logged but not driven, so it adds no self-heating and no bus
traffic.

## Actuators

| Part (where / when recommended) | Interface | Firmware | Telemetry / reports | Native tests | Status |
|---|---|---|---|---|---|
| **IRLZ44N** low-side MOSFET channels: relay bank `fae` / `exhaust` / `circulation` / `aux`, lighting bank `white` / `blue` / `red` / `far_red` | LEDC 25 kHz, 10-bit, WROOM-32 GPIO 25 / 26 / 27 / 14, S3 GPIO 4 / 5 / 6 / 7 | `lib/sp_core/channel_runtime.cpp`, `personality.h`, `scene_table.h`; LEDC binding in `src/node/main.cpp` | `telemetry/<channel>` switch reports, dim levels | `test_core_channel` | OK |
| **Noctua NF-A8 PWM 12 V**, Arctic P8 PWM PST (4-pin fans) | supply switched by a relay-bank MOSFET; the fan's own tach and PWM wires stay unconnected (BOM + build guide) | channel runtime | channel state | `test_core_channel` | n/a. No tach driver by design: with a low-side switch the tach output is referenced to the switched ground and cannot be read |
| **12 V LED strips**: JOYLIT 6500 K white, SuperLightingLED tri-spectrum 450 / 660 / 730 nm, far-red p-6959 / p-7066 | lighting-bank MOSFET channels | channel runtime + scenes | dim levels | `test_core_channel` | n/a (resistive load) |
| **Peristaltic pump**: Adafruit 1150, Kamoer NKP | relay `aux` channel, 60 s max-on default | channel runtime | switch reports | `test_core_channel` | n/a |
| **SSRs / solenoid valves** (spec §2 / §5c; flyback-diode note) | any relay-bank channel | channel runtime | switch reports | `test_core_channel` | n/a |
| **Smart plugs**: Athom Tasmota, Shelly Gen1, Shelly Gen2+ (Plus / Pro / Mini / Gen3 / Gen4, JSON-RPC under MQTT prefix `shellies/<role>`) (humidifier, dehumidifier, heater, Peltier) | MQTT straight to the Pi | `server/app/automation/smart_plugs.py`; no ESP32 firmware involved | n/a | server tests | n/a |

## Boards

| Board (where / when recommended) | Firmware env | Status |
|---|---|---|
| ESP32-WROOM-32 38-pin DevKit (canonical node; DevKitC V4 too) | `node_esp32` | OK |
| ESP32-S3-DevKitC-1 N8 / N8R8 / N16R8 (quad flash) | `node_esp32s3` | OK. Bench verification of the S3 is still pending |
| ESP32-S3-DevKitC-1-N32R16V, and Adafruit 5364 (DevKitC-1 on an ESP32-S3-WROOM-2: 32 MB octal flash + octal PSRAM; the canonical MCU in the 2026-04 cloud BOM) | `node_esp32s3_n32r16v` (`opi_opi`; ESP-IDF detects the PSRAM size, so an 8 MB WROOM-2 board also runs it) | OK. Bench verification pending. A WROOM-2 board does **not** boot `node_esp32s3` |
| AI-Thinker ESP32-CAM with **OV2640 / OV3660 / OV5640** (canonical camera since 2026-06) | `cam`, sensor detected by PID (`src/cam/cam_policy.h`) | OK (`test_cam_url` covers the per-sensor profiles) |
| **Freenove ESP32-S3-WROOM CAM** (N8R8; the BOM camera 2026-04-16 to 2026-06-11, and the generic "ESP32-S3 CAM (OV5640)" of 2026-04-15 when it is a Freenove clone) | `cam_esp32s3` (`boards/board_profile_esp32s3cam.h`, ESP32-S3-EYE pin map) | OK (new). Bench-pending |
| **Seeed XIAO ESP32S3 Sense** + OV5640 add-on (or its stock OV2640 / OV3660) | `cam_xiao_esp32s3` | OK (new). Bench-pending |
| **Waveshare ESP32-S3-CAM-OV5640** (also its OV3660 variant) | `cam_waveshare_s3`; sensor power through the on-board CH32V003 expander (`lib/sp_drivers/ws_cam_exio.cpp`) | OK (new). Bench-pending |

## Checked and never recommended

These parts came up in the history scan, but never as a BOM recommendation:

- Capacitive soil-moisture probes: only in `CLAUDE.md`'s operator background.
- AHT10: different init command (`0xE1`), no CRC byte; it fails the AHT2x
  probe.
- BME680 and BMP180: share 0x76 / 0x77, rejected by chip ID.
- DHT22 and DS18B20: never mentioned.
- VOC and particulate sensors: Builder's Assistant example prompts only.

None of these has a driver.

## ESP32-S3 camera boards

From 2026-04-15 to 2026-06-11 the BOM's camera was an ESP32-S3 board. The
cam image builds for each of them; only `boards/board_profile_esp32s3cam.h`
differs from the AI-Thinker build:

| Env | Board | Pin map source | XCLK | Reset / portal button | Serial |
|---|---|---|---|---|---|
| `cam_esp32s3` | Freenove ESP32-S3-WROOM CAM (FNK0085) and its clones | arduino-esp32 3.3.12 `camera_pins.h` `CAMERA_MODEL_ESP32S3_EYE`, the model Freenove's own `Sketch_07.1_CameraWebServer` selects: XCLK 15, SIOD 4, SIOC 5, Y2–Y9 = 11 / 9 / 8 / 10 / 12 / 18 / 17 / 16, VSYNC 6, HREF 7, PCLK 13 | 10 MHz (Freenove's `camera_init`) | BOOT (GPIO 0) | the USB-UART port |
| `cam_xiao_esp32s3` | Seeed Studio XIAO ESP32S3 Sense | `camera_pins.h` `CAMERA_MODEL_XIAO_ESP32S3`: XCLK 10, SIOD 40, SIOC 39, Y2–Y9 = 15 / 17 / 18 / 16 / 14 / 12 / 11 / 48, VSYNC 38, HREF 47, PCLK 13 | 20 MHz | B / BOOT (GPIO 0) | USB CDC |
| `cam_waveshare_s3` | Waveshare ESP32-S3-CAM-OVxxxx | Waveshare's schematic GPIO table (`ESP32-S3-CAM-XXXX-schematic.pdf`) and BSP (`BSP_CAMERA_*`), which agree: XCLK 38, SIOD 8, SIOC 7, Y2–Y9 = 45 / 47 / 48 / 46 / 42 / 40 / 39 / 21, VSYNC 17, HREF 18, PCLK 41 | 20 MHz | BOOT (GPIO 0) | USB CDC |

Differences from the AI-Thinker build:

- **No flash LED** on any of them. A capture asks for the flash as before,
  `cam_policy.h flash_for_capture()` turns that off on these boards, and the
  upload says `X-Flash-Used: 0`. Light the chamber for photos.
- **Orientation**: on the Freenove the vendor's example mirrors every
  sensor and also flips the OV2640; `board_orientation()` applies that.
  The other two keep Espressif's per-sensor correction, like the AI-Thinker.
- **Waveshare sensor power**: the sensor's PWDN is on the board's CH32V003
  I/O expander (I²C 0x24, EXIO3), which shares the SCCB bus (GPIO 8 / 7).
  The cam opens that bus with ESP-IDF's I²C driver (`src/cam/idf_i2c_bus.h`;
  not Wire, which would add ~16 KB to every cam image), writes the
  expander's direction and levels (`lib/sp_drivers/ws_cam_exio.cpp`, register
  protocol from Waveshare's own `io_extension.cpp`), then hands the bus to the
  camera driver (`sccb_i2c_port`). An expander that does not answer is
  logged; the schematic's PWDN pull-down keeps the sensor on anyway.
- All three use the 8 MB partition table (`partitions_8mb.csv`) and
  octal-PSRAM SDK builds (`qio_opi`). Their images are about 1.25–1.28 MB in
  a 3 MB slot.

The `cam_mount.scad` print fits the AI-Thinker + ESP32-CAM-MB stack only.
The BOM keeps recommending the AI-Thinker; these envs exist so boards bought
from the earlier BOMs keep working. Other "ESP32-S3-CAM" listings use other
pin maps (check which `CAMERA_MODEL_*` the seller's example selects) and are
not supported unless it is `CAMERA_MODEL_ESP32S3_EYE`.

Not verified on hardware yet: each board's first capture, the Freenove
orientation, and the Waveshare expander write.
