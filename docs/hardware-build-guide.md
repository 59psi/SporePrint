# SporePrint Hardware Build Guide

Build a monitored, automated mushroom grow chamber from parts, end to end.

This is the **step-by-step assembly manual**. It assumes nothing. Where a number
appears here (a GPIO, a price, a dimension), it is the number the shipped
firmware and the current bill of materials actually use — not an approximation.

- **Bill of materials + links:** the Builder page in the app, or
  `server/app/builder/hardware_guides.py`. Prices and stock were re-checked on
  2026-09-27.
- **Wiring diagrams:** `docs/wiring-tier1-bare-bones.svg`,
  `docs/wiring-tier2-recommended.svg`, `docs/wiring-tier3-all-the-things.svg`
  (and `docs/wiring-overall-system.svg` for the whole system). Open them
  alongside this guide — they show every connection at once: what sits inside
  the chamber and what stays outside, the power strip, the 12 V distribution
  with its fuses, the wire gauge of every run and the common ground. They use
  the ESP32-WROOM-32 pin map; S3 boards differ (§8a).
- **Printable enclosures:** `models/*.scad`, documented in
  [`models/README.md`](../models/README.md).

---

## 0. Pick a tier

| | **Bare Bones** ~$290 | **Recommended** ~$745 | **All the Things** ~$960 |
|---|---|---|---|
| What it does | Monitors. Humidifier on a smart plug. | Full automation — fans, lights, camera, CO₂. | Everything, two shelves, plus scale + door + pump. |
| ESP32 nodes | 1 (climate) | 3 (climate, relay, lighting) + 1 camera | 4 (2 climate, relay, lighting) + 2 spares (one 6-pack) + 2 cameras |
| Sensors | Temp/RH, light | + CO₂ | + 2nd shelf, load cell, door contact |
| Actuators | 1 smart plug | 3 fans + aux, 2 LED channels, 2 plugs | + red/far-red, peristaltic pump, 4 plugs |
| 12 V supply | none | 12 V 5 A (60 W) | 12 V 10 A (120 W) |
| 12 V distribution | none | 14 AWG pigtail → WAGO 221 → inline 3 A (relay) + 5 A (lighting) fuses, 18 AWG runs | same, with a 7.5 A lighting fuse |
| Mains | 6-outlet surge strip | 12-outlet surge strip | 12-outlet + 2 USB-A surge strip |
| Reusable kits in the price | ~$72 | ~$217 | ~$245 |
| Build time | ~2 hours | ~5 hours | ~8 hours |

Prices are the sum of the Builder's parts list — boards, sensors, supplies
**and** the cabling, consumables, heat-set inserts and screws. Of that, the
"reusable kits" row is spools and assortments (wire, WAGO connectors, fuses,
heat-shrink, zip ties, VELCRO, grommets, inserts, screws, solder, the Dupont
and breadboard kits) that cover more than one chamber: a second chamber costs
that much less. The prices do **not** include the tri-spectrum strip's
shipping from China and import duty (~$10+), or the tools (§1).

Start at Bare Bones if this is your first build. **Every tier is a strict
superset of the one before it** — you add boards, you never rewire.

**The Pi software is free and open source forever, on every tier.** A cloud
subscription only adds remote access, push, and AI. The chamber works on your
LAN with no account.

---

## 1. Before you buy

Traps that will cost you money or a rebuild:

1. **Wavelength-specific LED strips cannot be bought on Amazon.** Searching
   "450nm blue LED strip" returns zero true-450nm products — generic decorative
   blue is ~465–470nm, which will **not** drive Cordyceps. Buy the tri-spectrum
   (450 + 660 + 730 nm) strip from the horticulture supplier the BOM links
   (SuperLightingLED p-7120, DC12V, with the IP67 silicone-tube option for a
   humid closet). It ships from China: allow ~$10 air mail plus import duty.
   One strip carries all three specialty channels on one 4-wire lead:
   **BLUE wire = 450 nm, RED wire = 660 nm, GREEN wire = 730 nm far-red**, plus
   the common +12 V wire.
2. **The ESP32-CAM has no USB port.** Buy the 2-pack that bundles two
   **ESP32-CAM-MB** programmer boards (micro-USB). The MB flashes the camera
   and is also its power input. Buy only the classic AI-Thinker "ESP32-CAM"
   (ESP32-S, 27 × 40.5 mm) with an **OV2640 or OV3660** sensor (OV5640 also
   works — the firmware detects which is fitted). The "ESP32-S3-CAM" boards are
   **not** supported.
3. **Buy the IRLZ44N, not the IRFZ44N.** The IRFZ44N is a standard-gate part
   that won't fully turn on from a 3.3 V GPIO, and it shows up in the same
   search.
4. **Use the official Raspberry Pi 27 W USB-C supply and the Active Cooler.**
   Generic USB-C PD chargers have no 5 V/5 A profile, so the Pi 5 limits its
   USB ports to 600 mA; and the Pi 5 throttles without the cooler in a warm
   closet. The Pi 4 does not fit `pi_case.scad`.
5. **Every ESP32 node and every camera needs its own 5 V USB charger and a data
   cable** (USB-A to USB-C for the nodes, USB-A to micro-USB for the camera's
   MB). The BOM lists them; charge-only cables won't flash.
6. **The SCD30 does not fit the default sensor mount.** It is an *electrical*
   drop-in for the SCD41 (the firmware autodetects it), but at 51 × 25.4 mm it
   needs the SCD30 variant of **both** printed parts:
   `openscad -D scd30=true -o sensor_mount_scd30.stl models/sensor_mount.scad` and
   `openscad -D scd30=true -o sensor_bracket_scd30.stl models/sensor_bracket.scad`.
7. **An ESP32-S3 board uses different GPIOs** from every wiring diagram. If you
   buy one, wire it from §8a, not from the diagrams.
8. **Boards inside the chamber need long USB cables.** The climate node(s) and
   the camera(s) live in the chamber; their chargers stay outside on the power
   strip, so they take 6 ft (2 m) cables through the wall grommet. The relay
   and lighting nodes sit outside next to their switch boards and can use the
   short cables (§7).
9. **The cabling is in the BOM — buy it with the boards.** The surge strip,
   the 12 V pigtail, WAGO 221 lever connectors, inline fuses, 18 AWG red/black,
   22 AWG hookup and 22 AWG 4-conductor wire, Noctua fan extensions,
   heat-shrink, zip ties, VELCRO, grommets, inserts, screws and solder are BOM
   lines, mapped to where each one goes in §7. Don't substitute thinner wire on
   the 12 V runs.

### Tools you need

Tools are not in the BOM or the tier prices:

- Soldering iron, with a **heat-set insert tip** for the printed enclosures
  (the solder itself is the BOM's lead-free solder)
- Wire strippers and a crimper (ferrules or butt splices)
- Multimeter — continuity checks for the reed contact, the common ground and
  the 12 V branches
- Heat gun (or a lighter, carefully) for the heat-shrink
- Hex keys 2, 2.5, 3 and 4 mm (the M2.5, M3, M4 and M5 socket heads)
- Flush cutters — trim leads to ≤ 3 mm under `relay_board_mount`
- A 3D printer for the enclosures (§2), or a print service

---

## 2. Print the enclosures (optional, do it while parts ship)

PLA or PETG, 0.2 mm layers, 3 walls, **no supports**. Every multi-piece
enclosure is held together by **brass heat-set inserts** and ISO 4762
socket-head screws: press the inserts into the finished print with a soldering
iron (about 220–230 °C for PLA, 245 °C for PETG) before assembly. No inserts?
Render with `-D 'SP_FASTENER="self_tap"'` and use self-tapping screws. Full
details, fits and presets: [`models/README.md`](../models/README.md).

| Model | Holds | Preset for the BOM part |
|---|---|---|
| `pi_case.scad` | Raspberry Pi 5 + Active Cooler | default (`cooling="active"`) |
| `esp32_case.scad` | ESP32 DevKit | default `narrow_usbc` (the BOM's USB-C board); `devkitc_v4`, `wide_usbc`, `s3_devkitc1` for others |
| `sensor_mount.scad` + `sensor_bracket.scad` | SHT31-D + SCD41 + BH1750 on one STEMMA QT chain | defaults; `-D scd30=true` on **both** for an SCD30. **Do not tape over the vents** — they are the chimney airflow over the CO₂ sensor. |
| `cam_mount.scad` | ESP32-CAM seated on its ESP32-CAM-MB | default |
| `relay_board_mount.scad` | 4-channel IRLZ44N switch board | print twice: `-D 'node="relay"'` and `-D 'node="lighting"'` (lighting board in PETG). Mount OUTSIDE the chamber. |
| `power_supply_mount.scad` | 12 V PSU brick | Recommended: default `psu="facmogu_5a"`; All the Things: `-D 'psu="facmogu_10a"'` (PETG) |
| `fan_duct.scad` | 80 mm fan → 4-inch duct | default, one per fan you duct (PETG) |
| `hx711_scale.scad` | HX711 + 5 kg bar load cell | defaults `cell="bar75"` `hx_board="ada5974"` (Adafruit 4541 + 5974); `cell="tal220"` for 80 mm TAL220 bars; 5 walls, ≥ 40 % infill |
| `pump_bracket.scad` | Peristaltic pump | default `pump="adafruit_1150"` (flange-mounted, M2.5 into inserts) |

**Heat-set inserts and screws** (BOM lines, in the tier price; counts at the
default presets, from the `models/README.md` shopping list):

| Tier | Inserts | Screws |
|---|---|---|
| Bare Bones | 10 × M2.5 × 5.7, 14 × M3 × 5.7 | 10 × M2.5 × 6, 10 × M3 × 6, 4 × M3 × 16 |
| Recommended | 10 × M2.5 × 5.7, 26 × M3 × 5.7, 12 × M4 × 8.1, 1 × M5 × 9.5 (3 fan ducts) | 10 × M2.5 × 6, 22 × M3 × 6, 4 × M3 × 16, 12 × M4 × 35, 1 × M5 × 16 |
| All the Things | 20 × M2.5 × 5.7, 40 × M3 × 5.7, 16 × M4 × 8.1, 2 × M5 × 9.5 (3 fan ducts) | 16 × M2.5 × 6, 2 × M2.5 × 8, 2 × M2.5 × 10, 36 × M3 × 6, 4 × M3 × 16, 2 × M4 × 16, 2 × M4 × 25, 12 × M4 × 35, 2 × M5 × 16, 4 × M4 × 8 set screws, 4 × M4 DIN 125 washers |

The pockets are sized for ruthex RX inserts (M2.5 × 5.7, M3 × 5.7, M4 × 8.1,
M5 × 9.5). CNC Kitchen's M3/M4/M5 match, but CNC Kitchen's M2.5 is M2.5 × 4,
too short. What the BOM buys:

- **Inserts:** Recommended and All the Things — the **ruthex M2/M3/M4/M5
  assortment** (Amazon B08K1BVGN9, ~$30); Bare Bones needs only M3 and M2.5,
  so it takes a ruthex M3 × 5.7 100-pack (B08BCRZZS3) instead. Every tier adds
  **a separate M2.5 × 5.7 pack** — the assortment has no M2.5. The exact
  design part is ruthex RX-M2.5x5.7 (3DJake sells it; Amazon US doesn't), so
  the BOM pins uxcell's ~4.5 mm OD × 6 mm M2.5 inserts, which press flush in
  the same pockets. Avoid 3.5 mm OD × 4 mm M2.5 inserts: they spin.
- **Screws** (304 stainless — the in-chamber parts live at 85–95 % RH): an
  M2.5 socket-head kit (× 6 / 8 / 10 / 12), 100 × M3 × 6, an M2.5–M8 kit for
  the M3 × 16, M4 × 16 and M5 × 16, and (Recommended up) an M4 kit with the
  M4 × 35 fan screws, M4 × 25 and washers; All the Things adds M4 × 8 set
  screws for the scale.

The switch boards mount with 4 × M3 × 16 pan-head (or #4 × ¾" wood) screws
each, or zip ties through their end slots.

---

## 3. The Raspberry Pi (the brain)

The Pi runs the server, the MQTT broker, and the local web UI. Everything else
talks to it.

1. Flash **Raspberry Pi OS (64-bit)** with Raspberry Pi Imager.
2. In Imager's **advanced options** (the gear icon), set:
   - **hostname: `sporeprint`** — this matters. Your ESP32 nodes look for the
     MQTT broker at `sporeprint.local`. Get this wrong and nothing connects
     (or give the nodes the Pi's IP instead, with a DHCP reservation).
   - Enable SSH, and enter your WiFi credentials.
3. Fit the **Active Cooler** before casing the Pi.
4. Boot the Pi, SSH in, and install with the one-command installer:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/install.sh | bash
   ```
   (or `git clone https://github.com/59psi/SporePrint.git && cd SporePrint && ./install.sh`).
   `./install.sh` matters: the MQTT broker **refuses anonymous connections**,
   and the installer is what creates the credentials — the server's own
   account and the `sp-3p` account your smart plugs will use (its password
   lands in `.env` as `SPOREPRINT_MQTT_3P_PASSWORD`). It also generates the
   command-signing key (`SPOREPRINT_MQTT_HMAC_KEY`), writes the Pi's time zone
   as `TZ` (automation schedules follow it), creates the broker's TLS
   certificates, installs Docker, starts the stack and prints the dashboard
   URL. Do **not** use `setup.sh` — it is the developer-workstation script.
5. Optional, for weather-predictive automation (All the Things relies on it):
   set `SPOREPRINT_WEATHER_LAT` and `SPOREPRINT_WEATHER_LON` in
   `~/SporePrint/.env`, then `docker compose up -d server`
   (`docker compose restart` does not re-read `.env`).
6. Open `http://<pi-ip>:3001` (install.sh printed it; `http://sporeprint.local:3001`
   if mDNS works). You should get the dashboard, with no nodes yet. **Do not
   continue until this loads.**

---

## 4. Wire the climate node (every tier)

The three sensors form one **STEMMA QT daisy chain** on the I²C bus — no
soldering, no breadboard:

1. The **Adafruit 4397** cable (STEMMA QT → female sockets) goes from the ESP32
   header to the first sensor. Push its female sockets onto the DevKit's pins:

   | 4397 wire | → | ESP32-WROOM-32 pin |
   |---|---|---|
   | red | → | **3V3** |
   | black | → | **GND** (any GND pin — not EN) |
   | blue | → | **GPIO 21 (SDA)** |
   | yellow | → | **GPIO 22 (SCL)** |

   Its STEMMA QT plug goes into the **SHT31-D**.
2. An **Adafruit 4210** QT-QT cable links each board's second QT port to the
   next board: SHT31-D → SCD41 → BH1750 (Bare Bones: SHT31-D → BH1750).
   Longer reach between boards: Adafruit 4401 (200 mm) or 5384 (300 mm).

Leave the boards' loose header strips unsoldered. The firmware **probes the I²C
bus and autodetects** whatever is there — SHT3x or SHT4x, SCD4x or SCD30,
BH1750. You do not configure which sensors you have. If a sensor answers, it
gets used.

The 4397 is 150 mm long, so the climate ESP32 (in its `esp32_case`) sits in the
chamber next to the sensor mount. Power it from its own 5 V charger on the power
strip **outside** the chamber, over a 6 ft (2 m) USB-A → USB-C cable through the
wall grommet (§7). Nothing else connects to it: there is no breadboard and no
jumper wiring on any tier's climate node.

> **Using an MH-Z19C instead of the SCD41?** It is UART, not I²C: sensor **TX →
> GPIO 16**, **RX → GPIO 17**, 5V, common GND. Unlike the I²C parts it is *not*
> autodetected — tick "MH-Z19C CO2 sensor (UART)" under **Optional peripherals**
> in the setup portal (§9), or it will silently do nothing. There is no printed
> holder for it.

---

## 5. Wire the relay node (Recommended and up)

Four MOSFET channels switch the 12 V loads. Build each channel on the printed
`relay_board_mount` (`node="relay"`) with KF301 5.08 mm screw terminals: **J1**
is the control input (IN = GPIO, − = GND), **J2** the load output ("+" on the
+12 V bus, "−" on the drain). Each channel is the same circuit, shown here end
to end from the 12 V supply (§7) to a fan:

```
PSU + ══14 AWG══ WAGO 221-413 ──18 AWG red──[ 3 A fuse ]─ +12 V bus ─ J2 + ──── +12 V wire ───┐
                                                                         │                    │
                                                       UF4007, band ─▶  ─┴─                  FAN 12 V
                                                       to +12 V          ▲         4-pin PWM extension
                                                                         │         lead; its tach + PWM
ESP32 GPIO ─Dupont─ J1 IN ──[100 Ω]──┬── G                               │         wires stay unused
                                     │     IRLZ44N   D ──── drain ─── J2 − ──── GND wire ─────┘
                                  [10 kΩ]            S
                                     │               │
ESP32 GND ──Dupont─ J1 − ────────────┴───────────────┴── GND bus ──18 AWG black── WAGO 221-415 ══14 AWG══ PSU −
     └─────────── COMMON GROUND: ESP32 GND = J1 − = GND bus = WAGO 221-415 = PSU − (one net) ───────────┘
```

- **The common ground is not optional.** Each switch board's GND bus (the 12 V
  supply's −) must be tied to its own ESP32's GND — that is the J1 "−" jumper.
  The ESP32 runs from an isolated USB charger, so without that wire the gate
  signal has no reference and the channel never switches. Do it on the relay
  board and on the lighting board.
- The **+12 V branch is fused** at the WAGO end (3 A for the relay board) and
  runs to the board in 18 AWG red; the GND branch runs in 18 AWG black and is
  not fused (§7).

- The **100 Ω gate resistor** limits the GPIO's gate-charge current and damps
  ringing at the firmware's 25 kHz PWM.
- The **10 kΩ gate-to-source pull-down is not optional** — without it the gate
  floats while the ESP32 boots and your fan twitches on.
- The **flyback diode is not optional** on any fan or pump — an inductive load
  will kill the MOSFET without it. Use an ultrafast **UF4007** (same DO-41
  package) or a 1N5819/SS14 Schottky, because the channels PWM at 25 kHz; a
  plain 1N4007 is fine only on a channel that just switches on/off.
- Clip-on TO-220 heatsinks are optional and not in the BOM: recommended above
  ~1 A per channel, required above ~2 A (`relay_board_mount -D heatsink=true`).
  A strip cut to closet length stays around 1 A.

Run Dupont jumpers (female end on the ESP32 pin) from GPIO 25 / 26 / 27 / 14 and
a GND pin into the J1 terminals — or 22 AWG stranded hookup wire where a jumper
won't reach.

**Fans plug in through 4-pin fan extension leads**, so a fan unplugs without
cutting its own cable: each fan's bundled 30 cm extension plus one **Noctua
NA-SEC3** (60 cm) reaches about 1.1 m, from inside the chamber to the board.
Cut the **far (header) end** of the NA-SEC3 — never the fan's own lead — and
land two of its wires in J2: **pin 1 (GND) → J2 "−"** (the drain) and **pin 2
(+12 V) → J2 "+"**. Identify them by pin position in the connector, not by
colour. Pins 3 (tach) and 4 (PWM) stay unused: trim them and cap them with
heat-shrink. The MOSFET switches the fan's supply on the low side: with its PWM
pin left open a Noctua runs at full speed whenever the channel is on, and a
`pwm` value (0–255) in the channel command sets the average through the
firmware's 25 kHz PWM.

| Channel | GPIO | Drives | Max-on backstop (default) |
|---|---|---|---|
| 0 — `fae` | **25** | Fresh-air-exchange fan | 30 min |
| 1 — `exhaust` | **26** | Exhaust fan | 30 min |
| 2 — `circulation` | **27** | Circulation fan | 30 min |
| 3 — `aux` | **14** | Spare (drives the peristaltic pump in All the Things) | **60 s** |

> Those channel names are the **MQTT command routing keys**. The node matches
> `cmd/<channel>` exactly and drops anything else. The 4th channel is `aux` — an
> automation rule written for a channel named "mister" reaches nothing. (The app
> rejects unknown channel names when you save a rule, and tells you the valid
> ones.)

The `aux` channel stops itself after 60 s by default (it is meant for a pump).
Using it for something else? Raise it with `cmd/config
{"max_on_sec": {"aux": N}}` (switch channels accept 1–1800 s), sent as
`POST /api/hardware/nodes/relay-01/command` with body
`{"channel": "config", "max_on_sec": {"aux": 600}}`. It is stored on the node.

**Mount the relay board outside the chamber.** It is electronics in a
95 %-humidity box otherwise. Its ESP32 sits beside it, also outside, on a short
USB cable. Only the fan leads (and on All the Things the pump leads and the
HX711 / door-contact cables) go into the chamber, through the wall grommet
(§7).

---

## 6. Wire the lighting node (Recommended and up)

The same MOSFET circuit on a second `relay_board_mount` (`node="lighting"`,
PETG), **without diodes** — LED strips are resistive. Four PWM channels at
10-bit resolution; the lighting personality always exposes all four, and you
populate as many as you bought strips for.

| Channel | GPIO | Strip |
|---|---|---|
| 0 — `white` | **25** | 6500K white (JOYLIT 5 m roll, cut to length) |
| 1 — `blue` | **26** | tri-spectrum **BLUE wire** (450 nm) |
| 2 — `red` | **27** | tri-spectrum **RED wire** (660 nm) |
| 3 — `far_red` | **14** | tri-spectrum **GREEN wire** (730 nm far-red) |

The tri-spectrum strip's **common wire goes to +12 V**; each colour wire goes to
its channel's J2 load terminal.

Each strip feed is an **18 AWG red/black pair**: red from a J2 "+" (the
+12 V bus), black to that channel's J2 "−" (the drain). For the tri-spectrum
strip, run the pair's red to the common wire and its black to the BLUE wire,
then one more 18 AWG conductor per extra colour wire (RED → CH2 "−", GREEN →
CH3 "−"). Solder each joint at the strip and seal it with **adhesive-lined
heat-shrink** — the chamber runs at 85–95 % RH. The lighting board's own feed
from the WAGO is fused at **5 A** (Recommended) or **7.5 A** (All the Things),
and its ESP32's GND goes to J1 "−" exactly like the relay board's (the common
ground, §5).

- **Recommended** wires channels 0 and 1: the white strip, and only the strip's
  BLUE wire. **Insulate the red and green wires** (heat-shrink each end) until
  you add those channels — you can wire them later **without re-flashing**.
- **All the Things** wires all four: one physical strip, three channels.

---

## 7. Power and cabling

Mains, every supply and charger, the Pi, the smart plugs, the WAGO connectors,
the fuse holders and both switch boards stay **outside** the chamber. Only
sensors, cameras, the scale, the door contact and 12 V loads go in, and every
cable enters through a rubber grommet in the wall (or the tent's cable port).
The wiring diagrams draw that boundary.

### Mains: the power strip

One **UL-listed surge-protector power strip** with widely spaced outlets, on a
shelf outside the chamber and off the floor, feeds everything that plugs into
the wall:

| On the strip | Bare Bones | Recommended | All the Things |
|---|---|---|---|
| Pi 27 W USB-C PSU | 1 | 1 | 1 |
| 5 V USB charger (one per ESP32 / ESP32-CAM-MB) | 1 | 4 | 6 |
| 12 V PSU brick | — | 1 | 1 |
| Tasmota smart plug | 1 | 2 | 4 |
| **Outlets used → the BOM's strip** | 3 → 6 outlets | 8 → 12 outlets | 12 → 12 outlets + 2 USB-A |

Widely spaced (block-space) outlets matter: the ~51 mm Athom plugs, the 12 V
brick and the Pi PSU are all wide bodies — on Bare Bones leave the outlet
beside the smart plug free. All the Things fills all 12 outlets; the strip's
two USB-A ports can power the relay and lighting nodes instead of two cubes.
Plug the strip straight into a wall outlet, never into another strip, and keep
its total under its **15 A** rating: a 1500 W space heater alone is 12.5 A, so
if the heater and the dehumidifier can run together, give the heater's smart
plug its own wall outlet.

### 12 V power distribution (Recommended and up)

```
12 V PSU ── DC barrel pigtail, 5.5 × 2.5 mm, 14 AWG
              ├─ red ───→ WAGO 221-413 (+12 V split) ─┬─[ 3 A fuse ]─── 18 AWG red ───→ relay board +12 V bus
              │                                       └─[ 5 A fuse ]─── 18 AWG red ───→ lighting board +12 V bus
              │                                         (7.5 A on All the Things)
              └─ black ─→ WAGO 221-415 (GND join) ────┬──────────────── 18 AWG black ─→ relay board GND bus    ← relay ESP32 GND (J1 −)
                                                      └──────────────── 18 AWG black ─→ lighting board GND bus ← lighting ESP32 GND (J1 −)
```

1. Push the PSU's barrel plug (centre +) into the **5.5 × 2.5 mm** female
   pigtail. A 5.5 × 2.1 jack makes spring-only contact that heats up at several
   amps. Check red = +12 V with the multimeter before anything else.
2. Land the pigtail's red in a **WAGO 221-413** (3-port) and its black in a
   **WAGO 221-415** (5-port), both from the BOM's WAGO 221 assortment. Each
   WAGO is one node: every wire in the 221-413 is +12 V, every wire in the
   221-415 is GND.
3. From the 221-413, run **one branch per switch board in 18 AWG red, each
   through an inline ATC blade-fuse holder** right at the WAGO end: **3 A**
   for the relay board, **5 A** (Recommended) or **7.5 A** (All the Things)
   for the lighting board. The holders have no IP rating — they stay outside.
4. From the 221-415, run one **18 AWG black** branch to each board's GND bus.
   GND branches are not fused.
5. Tie each ESP32's GND to its own board's J1 "−" — the **common ground** (§5).
   It reaches the same node as the 221-415; its spare ports are there if you
   would rather land the ESP32 GND wires on it directly.
6. Mount the brick in `power_supply_mount` with two 12" straps cut from the
   ¾" VELCRO ONE-WRAP roll, zip-tie the runs to the shelf and seal every
   splice with adhesive-lined heat-shrink.

| +12 V branch | Recommended (12 V 5 A PSU) | All the Things (12 V 10 A PSU) | What it carries |
|---|---|---|---|
| Relay board | **3 A** fuse | **3 A** fuse | three NF-A8 fans (~0.25 A together), plus the pump on All the Things |
| Lighting board | **5 A** fuse | **7.5 A** fuse | the LED strips — the real load |

The fuse protects the wiring, not the load: a pinched strip lead in a wet
chamber blows it long before an 18 AWG run gets hot.

**Load budget:**

- **Recommended:** Facmogu AL-1250, 12 V 5 A (60 W). Keep the load **≤ ~4 A**
  continuous.
- **All the Things:** Facmogu AL-12100, 12 V 10 A (120 W). Keep the load
  **≤ ~8 A** continuous.
- The fans draw little; the LED strips are the load. **Cut the strips to
  closet length** at their marked cut points: a full white roll is ~40–50 W
  (3.3–4.2 A) and a full tri-spectrum reel ~72 W (6 A with every channel on).

### 5 V: USB power for every board

Each ESP32 node and each camera gets its **own UL-listed 5 V USB charger** on
the strip and its own data-capable cable (charge-only cables won't flash):

| Board | Where it lives | Cable |
|---|---|---|
| Climate node(s) | inside, beside the sensor mount | 6 ft (2 m) USB-A → USB-C, through the grommet |
| Camera(s), on the ESP32-CAM-MB | inside | 6 ft (2 m) USB-A → micro-USB into the MB, through the grommet |
| Relay node, lighting node | outside, beside their switch boards | 1 ft USB-A → USB-C |

The camera needs ≥ 1 A and browns out on weak computer ports. Keep every
charger outside the humid chamber.

### Through the chamber wall

What goes in: the in-chamber boards' USB cables, the fan extensions, the
18 AWG LED-strip pairs, the humidifier's cord, and on All the Things the pump
leads, the HX711 and door-contact 22 AWG 4-conductor cables and the Peltier
cooler's cord. Drill a **7/8" or 1" hole** for one rubber grommet from the
BOM's kit (or use the tent's cable port), pass the USB overmoulds and 4-pin fan
plugs through **before** you seat the grommet, leave a drip loop below it on
the outside so condensation runs off before it reaches a connector, and
zip-tie each bundle on both sides.

### Cables, connectors and consumables

Every line below is in the BOM (the Builder page, or
`server/app/builder/hardware_guides.py`) — exact parts, pack sizes and prices
live there. This is where each one goes:

| BOM line | Where it is used | Tiers |
|---|---|---|
| Surge-protector power strip | feeds every mains device, outside the chamber: 6 outlets / 12 outlets / 12 outlets + 2 USB-A | all |
| USB wall chargers, 5 V | one per ESP32 and per ESP32-CAM-MB | all |
| USB-A → USB-C 6 ft; USB-A → micro-USB 6 ft (2-pack); USB-A → USB-C 1 ft (3-pack) | climate node(s); cameras' MBs; relay + lighting nodes | 6 ft USB-C all; the others Recommended up |
| STEMMA QT cables, Adafruit 4397 + 4210 | ESP32 header → first sensor, then sensor → sensor (§4) | all |
| DC barrel pigtail, 5.5 × 2.5 mm, 14 AWG | 12 V PSU → the two WAGOs | Recommended, All the Things |
| WAGO 221 lever connectors (assortment) | 221-413 splits the +12 V, 221-415 joins GND | Recommended, All the Things |
| Inline ATC/ATO fuse holders (14 AWG) + ATC fuse assortment | one per +12 V branch: 3 A relay, 5 A / 7.5 A lighting | Recommended, All the Things |
| 18 AWG 2-conductor red/black wire | every 12 V run: WAGO → each board; J2 → each LED strip and the pump | Recommended, All the Things |
| Noctua NA-SEC3 4-pin fan extensions | one per fan, after its bundled 30 cm extension (§5) | Recommended, All the Things |
| 22 AWG stranded hookup wire | gate / signal / GND jumpers on the boards, ESP32 GND → J1 "−", short splices | Recommended, All the Things |
| Dupont jumpers + breadboard kit | ESP32 header → J1; bench bring-up before soldering | Recommended, All the Things |
| 22 AWG 4-conductor cable | relay node → HX711 (red 3V3, black GND, yellow DOUT, white SCK); relay node → door contact (§11) | All the Things |
| Food-grade silicone tubing, 2 × 4 mm | pump → substrate line (§11) | All the Things |
| Adhesive-lined 3:1 heat-shrink | every splice, every LED-strip joint, unused fan and strip wires | Recommended, All the Things |
| UV zip ties (2.5 / 3.6 / 4.8 mm) | every cable run; the printed mounts' tie slots | all |
| 18" (457 mm) UV zip ties, 4.8 mm wide | one per `fan_duct`, round the 4" duct (a 14" tie is too short to lock) | Recommended, All the Things |
| VELCRO ONE-WRAP ¾" roll | two 12" straps for `power_supply_mount`; cable bundling | Recommended, All the Things |
| Rubber grommet kit | the 7/8" or 1" pass-through in the chamber wall | all |
| Heat-set inserts + socket-head screw kits | the printed enclosures (§2, `models/README.md`) | all |
| Lead-free solder, 0.8 mm | switch boards, strip leads, splices | Recommended, All the Things |

---

## 8. Flash the firmware

**One image covers every node.** There is no separate climate/relay/lighting
build — you pick the personality per node when you provision it. Install
PlatformIO (`pip install platformio`), then:

```bash
cd firmware
pio run -t upload -e node_esp32             # ESP32-WROOM-32 DevKit — every node board in the BOM
pio run -t upload -e node_esp32s3           # ESP32-S3-DevKitC-1 N8 / N8R8 / N16R8 (see §8a)
pio run -t upload -e node_esp32s3_n32r16v   # ESP32-S3-DevKitC-1-N32R16V — NOT node_esp32s3, it won't boot
pio run -t upload -e cam                    # the ESP32-CAM, on its ESP32-CAM-MB
```

**ESP32-CAM:** seat the camera on its **ESP32-CAM-MB**, plug the MB's
micro-USB into your computer and run the `cam` upload. If the upload doesn't
start, hold **IO0** on the MB, tap **RST**, release IO0 and retry. No FTDI
adapter or GPIO 0 jumper is needed. Leave each camera on its MB — the MB is also
its power input, and `cam_mount.scad` holds the CAM + MB stack.

Local builds report the `firmware/VERSION.txt` version in their heartbeat. The
heartbeat's `board` field (`esp32-wroom-32`, `esp32-s3-devkitc-1`,
`esp32-s3-devkitc-1-n32r16v`, `esp32-cam-ai-thinker`) tells you which image a
later OTA push needs.

(No PlatformIO clone? The app's Builder page → *ESP32 Firmware* serves a
self-contained ZIP per image.)

### 8a. ESP32-S3-DevKitC-1 pin map

The WROOM-32 is the canonical board and every diagram uses its pins. The
ESP32-S3-DevKitC-1 is supported (bench verification is still pending) with a
**different pin map** (`firmware/boards/board_profile_esp32s3.h`). Flash
`node_esp32s3` for N8 / N8R8 / N16R8 modules, or `node_esp32s3_n32r16v` for the
N32R16V sold on Amazon. Both builds use the same pins:

| Function | WROOM-32 (`node_esp32`) | ESP32-S3 (`node_esp32s3`, `node_esp32s3_n32r16v`) |
|---|---|---|
| I²C SDA / SCL | GPIO 21 / GPIO 22 | **GPIO 8 / GPIO 9** |
| Channels 0–3 | GPIO 25 / 26 / 27 / 14 | **GPIO 4 / GPIO 5 / GPIO 6 / GPIO 7** |
| HX711 DOUT / SCK | GPIO 32 / GPIO 33 | **GPIO 10 / GPIO 11** |
| Reed switch | GPIO 35 (external 10 kΩ pull-up required) | **GPIO 12** (internal pull-up works; an external 10 kΩ is harmless) |
| MH-Z19C (sensor TX → / → sensor RX) | GPIO 16 / GPIO 17 | **GPIO 16 / GPIO 17** |
| BOOT button (portal / factory reset) | GPIO 0 | GPIO 0 |

**Never wire an S3 to GPIO 26–37** (the octal flash/PSRAM bus), and avoid the
strapping pins 0, 3, 45 and 46, the native USB pins 19/20, GPIO 38 (RGB LED)
and, on the N32R16V, GPIO 47/48 (1.8 V). The STEMMA QT cable colours are the
same; only the header pins change.

---

## 9. Provision each node

**First, create each node's broker login on the Pi** — the broker refuses
anonymous clients, and each node gets its own account whose username **is**
its node ID (that's how the broker ACL scopes each node to its own topics). In
the SporePrint folder, once per board:

```bash
./scripts/add-node-mqtt-user.sh climate-01     # then relay-01, lighting-01, cam-01, climate-02, cam-02…
./scripts/provision-node.sh                    # prints the command-signing key (recommended)
```

`add-node-mqtt-user.sh` prints the Node ID, the MQTT username (always equal to
the node id) and a password. Re-running it for the same id rotates that
password.

Then: on first boot every node raises a WiFi access point called
**`SporePrint-Setup`**. Connect to it, and a captive portal opens. Set:

1. **WiFi** SSID + password ("Open network" for a network with no password).
2. **Pi address** — `sporeprint.local` if you set the hostname in step 3, or
   the Pi's IP.
3. **MQTT username + password** — from `add-node-mqtt-user.sh` above.
4. **Node ID** — leave it **blank**: a blank Node ID becomes the MQTT username
   printed by `add-node-mqtt-user.sh`. If you type one, it must equal that
   username (1–32 characters of `A–Z a–z 0–9 _ -`). **Identity is set here, not
   at flash time** — the second climate node logs in as `climate-02`, the
   top-down camera as `cam-02`.
5. **Personality** — `climate`, `relay`, or `lighting`. *This is what makes the
   one image behave as the right node.*
6. **Optional peripherals** — MH-Z19C CO₂ sensor (UART), HX711 load-cell
   scale, door reed switch (and, under it, "Door contact wired on its NO
   terminal (open with the door shut) — invert"). These are **config-flag**
   devices. Unlike the I²C sensors they are never autodetected: if you wired
   one and don't tick it, it will silently never report.
7. Optionally: **OTA password** (at least 12 characters, or OTA stays off),
   **Command signing key** (the key `provision-node.sh` printed — with it the
   node rejects unsigned, forged, replayed or redirected commands), and
   **Secure MQTT (TLS)** (+ **Require TLS**, see below).

Blank password / key fields keep the saved value when you revisit the portal.
A form the node refuses comes back with "Not saved." and the reason, with what
you typed still filled in.

The node reboots and appears on your dashboard within about 30 seconds.

**The camera's portal** has no personality or peripherals: it asks only for
the same WiFi, Pi address, MQTT and optional fields (OTA password, signing
key, Secure MQTT, NTP server). It uploads frames to
`http://<Pi address>:8000`.

**Reopening the portal later.** A node whose settings have connected before no
longer opens `SporePrint-Setup` when WiFi drops: it boots offline, buffers
telemetry, keeps its channels off and retries WiFi every 60 s.
- **Node:** hold **BOOT** 3–10 s, then release, to open the portal. Holding
  longer than 10 s factory-resets it.
- **Camera:** the gesture uses **GPIO 13**, and the AI-Thinker board has no
  button there. Short the camera's **IO13** header pin to a **GND** pin with a
  jumper lead (or wire a momentary push-button between them): 3–10 s, then
  release, opens the portal; longer than 10 s factory-resets.

**Nodes already in service** don't need a factory reset to add a peripheral:
`POST /api/hardware/nodes/<node_id>/peripherals` with
`{"mhz19": true|false, "hx711": true|false, "reed": true|false, "reed_inv": true|false}`
(any subset) sends the signed `cmd/config`. The node reboots about 1.5 s later
if its set of drivers changed; `reed_inv` applies live, with no reboot.

**Secure MQTT.** Ticking it makes the node fetch the Pi's CA (from
`/api/provision/ca`, which stays public in API-key mode) and try TLS on 8883
with it. The CA is pinned only once that TLS connection works (the broker
accepts the login); from then on the node stays on TLS. Use
`sporeprint.local` (or a DHCP-reserved IP — install.sh puts every Pi IPv4
into the certificate) as the Pi address. Until a CA is pinned, the node falls
back to plaintext **loudly**: an ERROR log, a `tls_downgrade` alert whose
message says why (no CA yet, certificate name mismatch or another CA, nothing
on 8883, TLS error, login refused), `tls:false` in its heartbeat, and
fetch-and-try retries after 1, 2, 4 and 8 min, then every 15 min, with no
reboot. A certificate that does not name the node's Pi address is never
pinned: re-run `./install.sh` on the Pi or use `sporeprint.local`. Tick
**Require TLS** to have the node stay offline instead of falling back. The
heartbeat's `ca_fp` is the SHA-256 of the CA the node pinned.

**More than one chamber?** List every node (climate, relay, light, camera) in
its chamber in the app. While grows run in two chambers, a node listed in no
chamber belongs to neither grow: its readings drive only life-safety rules and
its camera frames are not auto-analysed.

---

## 10. Smart plugs

The Athom plugs run Tasmota and talk MQTT directly — they don't touch an ESP32.
Plug each one into an outlet **outside** the humid chamber.

1. Power the plug. It raises a WiFi AP named `tasmota-XXXXXX-NNNN`.
2. Connect, open `192.168.4.1`, enter your WiFi credentials.
3. In the Tasmota web UI: **Configuration → MQTT** →
   - **Host** = your Pi's IP, **Port** = 1883
   - **User** = `sp-3p`
   - **Password** = the `SPOREPRINT_MQTT_3P_PASSWORD` value in the Pi's `.env`
     (in the SporePrint folder; created by `install.sh`)
   - **Topic** = the plug's role: `humidifier`, `dehumidifier`, `heater` or
     `cooler`
   - **Full Topic** = `tasmota/%topic%/%prefix%/` — **required**. Tasmota's
     default `%prefix%/%topic%/` publishes `stat/<topic>/POWER`, which the
     broker's `sp-3p` ACL silently drops, and listens on a command topic the Pi
     never uses.

   Console equivalent (Tasmota → Tools → Console):
   ```
   Backlog MqttHost <pi-ip>; MqttPort 1883; MqttUser sp-3p; MqttPassword <password>; Topic humidifier; FullTopic tasmota/%topic%/%prefix%/
   ```
4. Toggle the plug once. It registers itself when it first reports its relay
   state: the Topic becomes the plug id (`humidifier` → `plug-humidifier`),
   which is exactly what the built-in rules drive. A plug with another Topic can
   be given its role in the app instead.

Without the credentials the broker refuses the plug — **silently**. With the
credentials but the default Full Topic, the plug connects and still never
appears. Either way it looks fine in Tasmota.

Shelly Gen1 plugs work with their default topics (`shellies/<id>/relay/0`);
give them the `sp-3p` login too.

Humidifier inside the chamber (or piped in); dehumidifier outside with its
intake facing the chamber; heater outside, aimed at the intake; Peltier cooler
at the chamber wall. Keep a space heater ≤ 1500 W (≤ 1200 W preferred) on one
plug — the plugs are not UL/ETL listed.

---

## 11. All the Things extras

The scale and the door contact sit in or on the chamber, but both wire back to
the **relay** node outside it. Each gets its own run of **22 AWG 4-conductor
cable** through the wall grommet (§7); strip, solder and heat-shrink the ends.

**Load cell (harvest weight).** HX711 (Adafruit 5974) to the relay node over
one 22 AWG 4-conductor cable; leave the board's rate switch at 10 SPS:

| ESP32 (relay node) | → | 22 AWG 4-conductor | → | HX711 |
|---|---|---|---|---|
| 3V3 | → | red | → | VIN / VCC |
| GND | → | black | → | GND |
| GPIO 32 | ← | yellow | ← | DOUT |
| GPIO 33 | → | white | → | SCK |

Load cell (Adafruit 4541) red → E+, black → E−, the signal pair → A−/A+ (swap
A−/A+ if the weight reads negative). Mount it in `hx711_scale` under the grow
block. Tick **HX711 load-cell scale** in the relay node's setup portal, then
calibrate once: with the platform empty send `{"tare": true}`, then with a
known mass on it `{"calibrate_scale": <known grams>}`, each as
`POST /api/hardware/nodes/relay-01/command` with `"channel": "config"` in the
body. Keep the platform still until the `[CMD] scale tared/calibrated` log
line appears (the node averages 8 fresh samples, about 1 s). Until you do, the
node reports raw counts (`scale_raw`) instead of grams; after, `weight_g` rides
in telemetry.

**Door contact (reed).** The BOM part is a wired alarm door contact (weideer
MC-31B) with **COM / NO / NC** screw terminals. Run a second 22 AWG
4-conductor cable from the relay node to it; two conductors are used and two
are spare.

- **COM → GPIO 35**, the alarm **NC** terminal → **GND**. NC is closed while
  the magnet is present, i.e. with the door shut — check continuity with a
  meter before you mount it. Magnet on the door, switch on the frame.

> **The reed needs an EXTERNAL 10 kΩ pull-up from GPIO 35 to 3V3.** GPIO 34–39 on
> the ESP32 are input-only and have **no internal pull-up** — the usual
> `INPUT_PULLUP` trick does not exist on these pins. Skip the resistor and the
> input floats whenever the door is open, and you will get phantom door events.
> (A 10 kΩ is in the parts kit.) Solder it at the relay end, between the
> ESP32's 3V3 and GPIO 35, not out at the door.

Tick **Door reed switch** in the relay node's setup portal. Wired it to the
**NO** terminal instead? Either move the lead to NC, or tick **"Door contact
wired on its NO terminal (open with the door shut) — invert"** under the door
switch (NVS `reed_inv`). For a node in service, `POST
/api/hardware/nodes/relay-01/peripherals` with `{"reed_inv": true}` (or send
`cmd/config {"peripherals": {"reed_inv": true}}` through `POST
/api/hardware/nodes/relay-01/command` with body
`{"channel": "config", "peripherals": {"reed_inv": true}}`). It applies live,
with no reboot and no false door event.

**Peristaltic pump.** Adafruit 1150 (12 V, ~100 mL/min) to the relay node's
**aux** channel (GPIO 14) through an IRLZ44N + UF4007, exactly like a fan,
mounted in `pump_bracket` with its tube ports up or sideways. Its leads run in
the **18 AWG red/black pair** like every 12 V run: red → J2 "+", black → J2
"−" (the UF4007 across them, band to +12 V). The included silicone tubing is
**not** food-safe or sterile: sterilize it and use the BOM's **food-grade
silicone tubing** (2 mm ID × 4 mm OD — the 1150's barb size has changed
between batches, so measure yours first) on the substrate line. It is
low-pressure — good for drip hydration, it may not atomize through a misting
nozzle. `aux` stops itself after 60 s by default.

**Cameras.** Front-facing at substrate level angled slightly up (catches
pinning), and top-down (`cam-02`) for colonization coverage. **15–30 cm** from
the substrate — closer distorts, further loses detail. The flash LED (GPIO 4)
stays on through every exposure, so frames stay consistent as ambient light
changes.

---

## 12. Sensor placement — this decides whether your data is real

The single most common build mistake is a perfectly-wired sensor in the wrong place.

- **Put the climate sensor at the CENTER of the chamber, at SUBSTRATE LEVEL.**
  Not near the ceiling. Hot air rises; the temperature the mushrooms experience is
  at the substrate, and that is the only one worth controlling on.
- **Never** near a heat source, in a fan's direct output, or in a dead corner.
- **The CO₂ sensor needs airflow around it.** Do not seal it in. The vents in the
  printed mount are functional, not decorative.
- **The BH1750 must face the light.** It looks up through the lid's light
  window — toward the LED strips, not the floor.
- Clip the `sensor_bracket` onto a wire shelf (zip ties through the clip webs),
  or use its suction cup on a glass wall.

---

## 13. Bring-up checklist

Work down this list. Each step proves the one before it.

1. **Pi** — dashboard loads at `http://<pi-ip>:3001`.
2. **12 V wiring, before it is powered** (Recommended and up) — with the
   12 V brick unplugged, meter for continuity: each ESP32's GND ↔ its board's
   GND bus ↔ the GND WAGO (the common ground), and **no** continuity between
   the +12 V WAGO and the GND WAGO. Check each inline fuse is seated (3 A
   relay, 5 A / 7.5 A lighting). Then plug the brick in and read ~12 V on each
   board's +12 V bus.
3. **Nodes appear** — each provisioned node shows on the hardware panel within
   ~30 s of boot. If not: wrong Pi address, wrong WiFi, or a broker login that
   doesn't match the node id.
4. **Live telemetry** — temperature and humidity update. CO₂ needs a **5-minute
   warm-up** before it reads true; ignore the first few minutes.
5. **Sensors you enabled are actually reporting.** Check the node's health
   panel: it publishes an `expected_missing` list, and an enabled MH-Z19C or
   HX711 that isn't delivering is listed **and** raises a `sensor_failure`
   alert. **A declared-but-missing sensor is an alert, not silence.** The reed
   switch is the exception — electrically, an unwired switch looks like a shut
   door — so prove it in step 9.
6. **Actuators** — toggle each channel from the UI and watch the fan spin. A
   channel that does nothing is usually a gate wire on the wrong GPIO or a
   missing common ground; a whole board that does nothing is its blown or
   unseated inline fuse; one that twitches at boot is a missing 10 kΩ
   pull-down.
7. **Camera** — frames appear on the Vision page within 15 minutes of the cam
   booting.
8. **Scale** — tare, then place a known mass. It should read within a gram.
9. **Door** — open the door; `door_open` flips, and flips back when you shut
   it. If it flickers while the door is **OPEN**, the external 10 kΩ pull-up
   from GPIO 35 to 3V3 is missing (a shut door holds the pin at GND, so it
   looks stable either way). If it reads open with the door shut, the contact
   is on its NO terminal — see §11.

---

## 14. When something doesn't work

| Symptom | Cause |
|---|---|
| Node never appears | The node has the wrong Pi address, **or its broker login is missing/wrong** — run `./scripts/add-node-mqtt-user.sh <node_id>`, enter that username + password in the portal and leave Node ID blank (a Node ID that differs from the username is refused by the ACL). The broker refuses bad credentials *silently*. |
| Plug configured but never appears | You entered Host + Port without the MQTT **User/Password** (`sp-3p` / `SPOREPRINT_MQTT_3P_PASSWORD` from `.env`). Tasmota shows no error; the broker just refuses it. |
| Plug connected to the broker but never appears, or never switches | Tasmota's **Full Topic** is still the default `%prefix%/%topic%/`. Set Full Topic `tasmota/%topic%/%prefix%/` (console: `FullTopic tasmota/%topic%/%prefix%/`) and a unique Topic, then toggle the plug. |
| Sensor missing from telemetry | I²C: check the STEMMA QT cable is seated in both ports and the 4397's four sockets are on 3V3 / GND / GPIO 21 / GPIO 22 (S3: GPIO 8 / 9). Scale/door/MH-Z19C: you didn't tick it under Optional peripherals — these are never autodetected. |
| S3 node: no sensors, no channels | It was wired from the WROOM-32 diagrams, or flashed with the wrong env. Use the §8a pin map; `node_esp32s3_n32r16v` for the N32R16V board. |
| CO₂ reads a flat 400 ppm | Still warming up (5 min), or it needs a forced recalibration in fresh outdoor air (`cmd/config {"calibrate_co2": 420}`, 400–2000 ppm). |
| Fan twitches on at boot | Missing 10 kΩ gate pull-down. |
| No channel on a board ever switches | The common ground is missing — run the ESP32's GND to that board's J1 "−" (§5). Or the board's inline fuse has blown / isn't seated: check it and look for a pinched or shorted lead on that branch before you replace it. |
| One fan never spins, the rest do | Its NA-SEC3 extension landed the wrong wires in J2 — go by pin position, not colour: pin 1 (GND) → J2 "−", pin 2 (+12 V) → J2 "+"; the tach and PWM wires stay unused. |
| MOSFET died | Missing flyback diode (UF4007) across the inductive load. |
| Pump / aux load stops after a minute | The `aux` channel's 60 s max-on backstop — raise it with `cmd/config {"max_on_sec": {"aux": N}}` (§5). |
| Door sensor flickers while the door is open | Missing external 10 kΩ pull-up on GPIO 35. |
| Door reads open with the door shut | The contact is wired on NO — move the lead to NC or tick the invert box (§11). |
| Automation rule "fires" but nothing moves | The rule names a channel the node doesn't have. Channel names are exact-match routing keys — the relay's 4th channel is `aux`. |
| Node command returns 503 | The broker is down, or the Pi is cloud-paired with no `SPOREPRINT_MQTT_HMAC_KEY`. Run `./install.sh` (or `./scripts/provision-node.sh`), then `docker compose up -d server`. |
| Schedules run hours off | The Pi's `TZ` is unset or unknown. Set a canonical Region/City (e.g. `America/Chicago`) as `TZ` in `.env`, then `docker compose up -d server`. |
| Dashboard returns 401 everywhere | `SPOREPRINT_API_KEY` is set (an old `setup.sh` run generated one). Blank it, set `SPOREPRINT_ALLOW_UNAUTHENTICATED=true`, then `docker compose up -d server`. See [auth.md](auth.md). |
| `tls_downgrade` alert from a node | Secure MQTT is ticked but no Pi CA is pinned yet; the node is on plaintext and retrying. The message names the reason. "cert name mismatch": the node's Pi address is not in the broker certificate — re-run `./install.sh` on the Pi (it adds every Pi IPv4) or set the node's Pi address to `sporeprint.local`. No CA: check the Pi address resolves from the node and that `/api/provision/ca` answers. |
| Camera never uploads | Its Pi address doesn't reach `http://<Pi address>:8000` from the camera, or the camera is on a USB port that can't supply 1 A. |
| Can't reopen a camera's portal | There is no button on GPIO 13 — short IO13 to GND for 3–10 s (§9). |
| Blue light doesn't trigger Cordyceps | You bought a generic blue strip (~465 nm), not a true 450 nm one. |

---

## 15. Keeping it running

- **Update:** `cd ~/SporePrint && git pull && ./install.sh`. It keeps your
  settings and adds any new keys to `.env`.
- **Apply `.env` changes:** `docker compose up -d server`
  (`docker compose restart` does not re-read `.env`).
- **Rotate broker passwords:** `./scripts/rotate-mqtt-creds.sh` rotates the
  shared accounts (`server`, `sp-3p` — re-enter it in every plug afterwards —
  and the tooling accounts); re-running `add-node-mqtt-user.sh <node_id>`
  rotates one node's login. Edit the broker's password file only with these
  two scripts (`docker compose exec mqtt mosquitto_passwd` can't: the file is
  mounted read-only).
- **Back up** the whole `sporeprint_db` Docker volume: `sporeprint.db` (copy it
  with `sqlite3 … ".backup …"`), `.integration-key` (losing it means
  re-entering every vendor credential) and `cloud.env` (the cloud pairing).
  There is no backup script yet.

## 16. Where to go next

- Set a species profile — it drives the automation targets.
- Start a grow session so telemetry gets attributed to it.
- Rules engine: build conditions on temp, humidity, CO₂, light, weight, and door.
- Cloud (paid): remote access, push alerts, AI vision + advisor. The chamber never
  requires it.

Questions or a part that doesn't match this guide: **support@sporeprint.ai**.
