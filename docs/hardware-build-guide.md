# SporePrint Hardware Build Guide

Build a monitored, automated mushroom grow chamber from parts, end to end.

This is the **step-by-step assembly manual**. It assumes nothing. Where a number
appears here (a GPIO, a price, a dimension), it is the number the shipped
firmware and the current bill of materials actually use — not an approximation.

- **Bill of materials + live stock/prices:** the Builder page in the app, or
  `server/app/builder/hardware_guides.py`.
- **Wiring diagrams:** `docs/wiring-tier1-bare-bones.svg`,
  `docs/wiring-tier2-recommended.svg`, `docs/wiring-tier3-all-the-things.svg`.
  Open them alongside this guide — they show every connection at once.
- **Printable enclosures:** `models/*.scad`.

---

## 0. Pick a tier

| | **Bare Bones** ~$180 | **Recommended** ~$390 | **All the Things** ~$555 |
|---|---|---|---|
| What it does | Monitors. Humidifier on a smart plug. | Full automation — fans, lights, camera, CO₂. | Everything, redundant, plus scale + door + misting. |
| ESP32 nodes | 1 (climate) | 3 (climate, relay, lighting) + 1 camera | 5 + 2 cameras |
| Sensors | Temp/RH, light | + CO₂ | + 2nd shelf, load cell, door switch |
| Actuators | 1 smart plug | 3 fans, 2 LED channels, 2 plugs | + red/far-red, pump, 4 plugs |
| Build time | ~2 hours | ~5 hours | ~8 hours |

Start at Bare Bones if this is your first build. **Every tier is a strict
superset of the one before it** — you add boards, you never rewire.

**The Pi software is free and open source forever, on every tier.** A cloud
subscription only adds remote access, push, and AI. The chamber works on your
LAN with no account.

---

## 1. Before you buy

Three traps that will cost you money or a rebuild:

1. **Wavelength-specific LED strips cannot be bought on Amazon.** Searching
   "450nm blue LED strip" returns zero true-450nm products — generic decorative
   blue is ~465–470nm, which will **not** drive Cordyceps. Buy the tri-spectrum
   (450 + 660 + 730 nm) strip from the horticulture supplier the BOM links. One
   strip carries all three specialty channels.
2. **The ESP32-CAM has no USB port.** It needs a CH340/CP2102 programmer to
   flash. The 2-pack the BOM specifies bundles one — buy that, not a bare single.
3. **The SCD30 does not fit the printed sensor mount.** It is an *electrical*
   drop-in for the SCD41 (the firmware autodetects it), but at 51 × 25.4 mm it
   will not go in the 26 × 23.5 mm bay. Use the SCD41, or print the SCD30 variant
   of `sensor_mount.scad`.

---

## 2. Print the enclosures (optional, do it while parts ship)

PLA, 0.2 mm layers, no supports needed.

| Model | Holds | Notes |
|---|---|---|
| `sensor_mount.scad` | SHT31-D + SCD41 + BH1750 | **Do not tape over the vents.** They are the chimney airflow over the CO₂ sensor — block them and your CO₂ readings are wrong. |
| `esp32_case.scad` | ESP32 DevKit | |
| `relay_board_mount.scad` | MOSFET board | Mount OUTSIDE the chamber. |
| `cam_mount.scad` | ESP32-CAM | Suction cup or zip tie. |
| `pi_case.scad` | Raspberry Pi | |
| `fan_duct.scad`, `power_supply_mount.scad`, `sensor_bracket.scad` | | |

---

## 3. The Raspberry Pi (the brain)

The Pi runs the server, the MQTT broker, and the local web UI. Everything else
talks to it.

1. Flash **Raspberry Pi OS (64-bit)** with Raspberry Pi Imager.
2. In Imager's **advanced options** (the gear icon), set:
   - **hostname: `sporeprint`** — this matters. Your ESP32 nodes look for the
     MQTT broker at `sporeprint.local`. Get this wrong and nothing connects.
   - Enable SSH, and enter your WiFi credentials.
3. Boot the Pi, SSH in, and install:
   ```bash
   git clone https://github.com/59psi/SporePrint.git && cd SporePrint
   cp .env.example .env          # set SPOREPRINT_WEATHER_LAT / _LON
   docker compose up -d
   ```
4. Open `http://sporeprint.local:3001`. You should get the dashboard, with no
   nodes yet. **Do not continue until this loads.**

---

## 4. Wire the climate node (every tier)

All three sensors share one I²C bus — they daisy-chain onto the same two pins.

| ESP32 pin | → | Sensor |
|---|---|---|
| **3V3** | → | VIN on SHT31-D, SCD41, BH1750 |
| **GND** | → | GND on all three |
| **GPIO 21 (SDA)** | → | SDA on all three |
| **GPIO 22 (SCL)** | → | SCL on all three |

That's it. The firmware **probes the I²C bus and autodetects** whatever is there
— SHT3x or SHT4x, SCD4x or SCD30, BH1750. You do not configure which sensors you
have. If a sensor answers, it gets used.

> **Using an MH-Z19C instead of the SCD41?** It is UART, not I²C: sensor **TX →
> GPIO 16**, **RX → GPIO 17**, 5V, common GND. Unlike the I²C parts it is *not*
> autodetected — you must enable the MH-Z19 option in the setup portal (step 6),
> or it will silently do nothing.

---

## 5. Wire the relay node (Recommended and up)

Four MOSFET channels switch the 12V loads. Each channel is the same circuit:

```
ESP32 GPIO ──[100Ω]── Gate                     +12V ── Load (fan) ── Drain
                       │                                              │
                    [10kΩ]                              1N4007 across the load
                       │                                (band toward +12V)
                      GND                                Source ── GND
```

The **10kΩ gate pull-down is not optional** — without it the gate floats while
the ESP32 boots and your fan twitches on. The **1N4007 flyback diode is not
optional** on any fan or pump — an inductive load will kill the MOSFET without it.

| Channel | GPIO | Drives |
|---|---|---|
| 0 — `fae` | **25** | Fresh-air-exchange fan |
| 1 — `exhaust` | **26** | Exhaust fan |
| 2 — `circulation` | **27** | Circulation fan |
| 3 — `aux` | **14** | Spare (drives the misting pump in All the Things) |

> Those channel names are the **MQTT command routing keys**. The node matches
> `cmd/<channel>` exactly and drops anything else. The 4th channel is `aux` — an
> automation rule written for a channel named "mister" reaches nothing. (The app
> now rejects unknown channel names when you save a rule, and tells you the valid
> ones.)

**Mount the relay board outside the chamber.** It is electronics in a 95%-humidity
box otherwise.

---

## 6. Wire the lighting node (Recommended and up)

Identical MOSFET circuit, four PWM channels. The lighting personality always
exposes all four — you populate as many as you bought strips for.

| Channel | GPIO | Strip |
|---|---|---|
| 0 — `white` | **25** | 6500K white |
| 1 — `blue` | **26** | 450 nm |
| 2 — `red` | **27** | 660 nm |
| 3 — `far_red` | **14** | 730 nm |

- **Recommended** buys white + blue → wire channels 0 and 1. Channels 2 and 3 sit
  idle; you can add strips later **without re-flashing**.
- **All the Things** buys white + the **tri-spectrum strip**. That one strip has
  three separate leads: blue → GPIO 26, red → GPIO 27, far-red → GPIO 14. One
  physical strip, three channels.

---

## 7. Flash the firmware

**One image covers every node.** There is no separate climate/relay/lighting
build — you pick the personality per node when you provision it.

```bash
cd firmware
pio run -t upload -e node_esp32      # every node board (use node_esp32s3 for an S3)
pio run -t upload -e cam             # the ESP32-CAM only
```

For the **ESP32-CAM**: it has no USB. Connect the bundled CH340 programmer, and
**hold GPIO 0 to GND while flashing**. Release and reset afterwards.

(No PlatformIO? The app's Builder page → *ESP32 Firmware* serves a self-contained
ZIP per node. No git clone needed.)

---

## 8. Provision each node

On first boot every node raises a WiFi access point called **`SporePrint-Setup`**.

Connect to it, and a captive portal opens. Set:

1. **WiFi** credentials.
2. **Pi address** — `sporeprint.local` if you set the hostname in step 3.
3. **Personality** — `climate`, `relay`, or `lighting`. *This is what makes the
   one image behave as the right node.*
4. **Node ID** — accept the default, except: the second climate node must be
   `climate-02` and the top-down camera `cam-02`. **Identity is set here, not at
   flash time.**
5. **Optional peripherals** — the scale (HX711) and door sensor (reed) are
   **config-flag** devices. Unlike the I²C sensors they are never autodetected.
   If you wired one and don't tick the box here, it will silently never report.
6. Optionally: OTA password, command-signing key, TLS.

The node reboots and appears on your dashboard within about 30 seconds.

---

## 9. Smart plugs

The Athom plugs run Tasmota and talk MQTT directly — they don't touch an ESP32.

1. Power the plug. It raises an AP named `tasmota-XXXX`.
2. Connect, open `192.168.4.1`, enter your WiFi credentials.
3. In the Tasmota web UI: **Configuration → MQTT → Host** = your Pi's IP,
   **Port** = 1883.
4. Assign its role in SporePrint (humidifier / dehumidifier / heater / cooler).

Plugs live **outside** the chamber. Humidifier inside (or piped in), heater
outside pointed at the intake.

---

## 10. All the Things extras

**Load cell (harvest weight).** HX711 to the **relay** node:

| ESP32 | → | HX711 |
|---|---|---|
| GPIO 32 | → | DOUT |
| GPIO 33 | → | SCK |
| 3V3 / GND | → | VCC / GND |

Load cell under the grow block. Enable the **scale** option in the setup portal,
then calibrate once — send `{"tare": true}` with the platform empty, then
`{"calibrate_scale": <known grams>}` with a known mass on it. Until you do, the
node reports raw counts instead of grams; after, `weight_g` rides in telemetry.

**Door switch (reed).**

> **The reed needs an EXTERNAL 10 kΩ pull-up from GPIO 35 to 3V3.** GPIO 34–39 on
> the ESP32 are input-only and have **no internal pull-up** — the usual
> `INPUT_PULLUP` trick does not exist on these pins. Skip the resistor and the
> input floats, and you will get phantom door-open events forever. (A 10 kΩ is in
> the parts kit.)

One leg of the switch to GPIO 35, the other to GND. Magnet on the door, switch on
the frame. Enable the **door sensor** option in the setup portal.

**Misting pump.** Peristaltic pump to the relay node's **aux** channel (GPIO 14)
through an IRLZ44N + flyback diode, exactly like a fan. Food-safe silicone tubing
to the nozzle.

**Cameras.** Front-facing at substrate level angled slightly up (catches pinning),
and top-down (`cam-02`) for colonization coverage. **15–30 cm** from the substrate
— closer distorts, further loses detail. Use the built-in flash (GPIO 4) so your
frames are consistent as ambient light changes.

---

## 11. Sensor placement — this decides whether your data is real

The single most common build mistake is a perfectly-wired sensor in the wrong place.

- **Put the climate sensor at the CENTER of the chamber, at SUBSTRATE LEVEL.**
  Not near the ceiling. Hot air rises; the temperature the mushrooms experience is
  at the substrate, and that is the only one worth controlling on.
- **Never** near a heat source, in a fan's direct output, or in a dead corner.
- **The CO₂ sensor needs airflow around it.** Do not seal it in. The vents in the
  printed mount are functional, not decorative.
- **The BH1750 must face the light.** Sensor chip toward the LED strips, not the
  floor.

---

## 12. Bring-up checklist

Work down this list. Each step proves the one before it.

1. **Pi** — dashboard loads at `http://sporeprint.local:3001`.
2. **Nodes appear** — each provisioned node shows on the hardware panel within
   ~30 s of boot. If not: wrong Pi hostname, or wrong WiFi.
3. **Live telemetry** — temperature and humidity update. CO₂ needs a **5-minute
   warm-up** before it reads true; ignore the first few minutes.
4. **Sensors you enabled are actually reporting.** Check the node's health
   panel: it publishes an `expected_missing` list. If you ticked the scale box
   but the HX711 isn't wired, it says so. **A declared-but-missing sensor is an
   alert, not silence.**
5. **Actuators** — toggle each channel from the UI and watch the fan spin. A
   channel that does nothing is almost always a missing 10 kΩ gate pull-down.
6. **Camera** — frames appear on the Vision page within 15 minutes of the cam
   booting.
7. **Scale** — tare, then place a known mass. It should read within a gram.
8. **Door** — open the door; `door_open` flips. If it flickers with the door
   shut, you skipped the external 10 kΩ pull-up.

---

## 13. When something doesn't work

| Symptom | Cause |
|---|---|
| Node never appears | Pi hostname isn't `sporeprint`, or the node has the wrong broker address. Check the setup portal. |
| Sensor missing from telemetry | I²C: check SDA/SCL aren't swapped and the part has 3V3. Scale/door/MH-Z19: you didn't tick its box in the setup portal — these are never autodetected. |
| CO₂ reads a flat 400 ppm | Still warming up (5 min), or it needs a forced recalibration in fresh outdoor air. |
| Fan twitches on at boot | Missing 10 kΩ gate pull-down. |
| MOSFET died | Missing 1N4007 flyback diode across the inductive load. |
| Door sensor flickers | Missing external 10 kΩ pull-up on GPIO 35. |
| Automation rule "fires" but nothing moves | The rule names a channel the node doesn't have. Channel names are exact-match routing keys — the relay's 4th channel is `aux`. |
| Blue light doesn't trigger Cordyceps | You bought a generic blue strip (~465 nm), not a true 450 nm one. |

---

## 14. Where to go next

- Set a species profile — it drives the automation targets.
- Start a grow session so telemetry gets attributed to it.
- Rules engine: build conditions on temp, humidity, CO₂, light, weight, and door.
- Cloud (paid): remote access, push alerts, AI vision + advisor. The chamber never
  requires it.

Questions or a part that doesn't match this guide: **support@sporeprint.ai**.
