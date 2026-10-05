"""Pre-built hardware integration guides for the 3 SporePrint tiers.

Prices, links and stock were re-checked live on 2026-09-27 (hardware BOM
audit). Rules this file keeps, pinned by tests/test_hardware_guides.py:

- price_approx is the per-unit price as a plain "$N" string. Parts that are
  only sold in packs also carry pack_price; the tier cost counts that once.
- estimated_cost stays within 10% of HardwareTier.parts_cost().
- One 100 ohm gate resistor and one 10K pull-down per IRLZ44N (plus the reed
  switch's 10K pull-up); flyback diodes only on the inductive relay channels.
- Every GPIO in a wiring row exists in firmware/boards/board_profile_esp32dev.h
  and follows the channel order of firmware/lib/sp_core/personality.h.
- A tier's copy of a shared part PREPENDS its tier note to the shared buying
  guidance instead of replacing it (see _for_tier).
"""

from .models import CapabilityGroup, Component, HardwareTier, WiringConnection

# ── Shared text ─────────────────────────────────────────────────

# srv-hw#15: the S3 is a supported alternative, but it has its own pin map.
_S3_PIN_MAP = (
    "ESP32-S3-DevKitC-1 builds use env node_esp32s3 (N8 / N8R8 / N16R8) or node_esp32s3_n32r16v "
    "(the Espressif N32R16V sold on Amazon — plain node_esp32s3 does not boot on it) and a "
    "DIFFERENT pin map "
    "(firmware/boards/board_profile_esp32s3.h): SDA 8, SCL 9, channels GPIO 4/5/6/7, HX711 "
    "DOUT/SCK 10/11, reed 12, MH-Z19C TX→16 / RX→17 — every wiring row and step here is for the "
    "WROOM-32 (SDA 21, SCL 22, channels 25/26/27/14); never wire an S3 to GPIO 26-37 (octal "
    "flash/PSRAM)."
)

_INSTALL_STEP = (
    "Install SporePrint on the Pi with the one-command installer: curl -fsSL "
    "https://raw.githubusercontent.com/59psi/SporePrint/main/install.sh | bash (or git clone "
    "https://github.com/59psi/SporePrint.git && cd SporePrint && ./install.sh). It installs "
    "Docker, writes a LAN-trust .env with the MQTT broker credentials ('server' + the smart-plug "
    "user 'sp-3p'), creates the broker TLS certificates, starts the stack and prints the "
    "dashboard URL. Do not use setup.sh — it is the developer-workstation script. (A Pi set up "
    "with an older setup.sh has an API key that makes the dashboard return 401: blank "
    "SPOREPRINT_API_KEY in .env, set SPOREPRINT_ALLOW_UNAUTHENTICATED=true, then docker compose "
    "up -d server.)"
)

_WEATHER_STEP = (
    "Optional weather-predictive automation: set SPOREPRINT_WEATHER_LAT and _LON in the "
    "SporePrint folder's .env, then run docker compose up -d server ('restart' does not re-read "
    ".env)"
)

# Clip-on heatsinks are not in the BOM: a strip cut to closet length stays
# around 1 A per channel, where a bare upright TO-220 copes.
_HEATSINK_NOTE = (
    "add -D heatsink=true if you fit clip-on TO-220 heatsinks, e.g. Aavid 574502B00000G (not "
    "in this list) — worth it on an LED channel above ~1 A, needed above ~2 A"
)

_PLATFORMIO_STEP = (
    "Install PlatformIO on your computer: pip install platformio (or download each node's ZIP "
    "from the Builder page → ESP32 Firmware section — self-contained, no git clone needed)"
)


def _flash_nodes_step(boards: str) -> str:
    return (
        f"Flash {boards}: cd firmware && pio run -t upload -e node_esp32 — ONE unified image "
        "covers climate/relay/lighting (you pick the personality per node in its setup portal). "
        + _S3_PIN_MAP
    )


def _mqtt_credential_step(node_ids: str) -> str:
    # srv-hw#8: the broker refuses anonymous clients and scopes each node by
    # username == node id, so every node needs its own credential first.
    return (
        "Create each node's MQTT login BEFORE provisioning it — on the Pi, in the SporePrint "
        f"folder, run ./scripts/add-node-mqtt-user.sh <node_id> once per board ({node_ids}). "
        "It prints the Node ID, the MQTT username (always equal to the node id — the broker ACL "
        "scopes each node to its own topics by username) and a password. Recommended (and "
        "required once the Pi is cloud-paired): run ./scripts/provision-node.sh for the command "
        "signing key, then docker compose up -d server"
    )


def _portal_step(extra: str = "", *, cams: bool = False) -> str:
    # The ESP32-CAM has no BOOT gesture (its GPIO 0 is the camera clock): its
    # portal gesture is IO13 to GND (board_profile_esp32cam.h), and its
    # portal has no personality select or peripherals.
    cam_note = (
        " Cameras: their portal has no personality or peripherals, and there is no BOOT "
        "gesture — to reopen a camera's portal, short its IO13 header pin to a GND pin for "
        "3-10 s, then release (no button on that pin; longer than 10 s factory-resets)."
    )
    return (
        "Each ESP32 opens the 'SporePrint-Setup' WiFi AP on first boot — join it and enter: WiFi "
        "SSID + password; Pi address (sporeprint.local or the Pi's IP); the MQTT username and "
        "MQTT password printed by add-node-mqtt-user.sh (leave Node id blank — it becomes the "
        "MQTT username); the node personality (climate / relay / lighting); and optionally an "
        "OTA password, the command signing key (HMAC) and the Secure MQTT (TLS) toggle."
        + (f" {extra}" if extra else "")
        + " Once a node has connected it no longer reopens this AP when WiFi drops (it retries "
        "every 60 s) — to reopen the portal, hold BOOT for 3-10 s and release; holding longer "
        "than 10 s factory-resets."
        + (cam_note if cams else "")
    )


_CAM_FLASH_STEP = (
    "Flash each ESP32-CAM: seat it on its ESP32-CAM-MB programmer board, plug the MB's "
    "micro-USB into your computer and run cd firmware && pio run -t upload -e cam. If the upload "
    "doesn't start, hold IO0 on the MB, tap RST, release IO0 and retry (no FTDI adapter or GPIO 0 "
    "jumper needed). Leave each camera on its MB — the MB is also its USB power input, and "
    "cam_mount.scad holds the CAM + MB stack"
)


def _tasmota_step(plugs: str, topics: str) -> str:
    # srv-hw#9 / docs#2 / deps-infra#11: without sp-3p and this FullTopic the
    # broker drops every plug frame and the Pi can never command the plug.
    return (
        f"SMART PLUG SETUP — {plugs} Plug each Athom Tasmota plug into an outlet OUTSIDE the "
        "humid chamber. Power it on, join its 'tasmota-XXXXXX-NNNN' WiFi AP, open 192.168.4.1 "
        "and enter your WiFi credentials. Then in the Tasmota web UI: Configuration → MQTT → "
        "Host = the Pi's IP, Port = 1883, User = sp-3p, Password = SPOREPRINT_MQTT_3P_PASSWORD "
        "(from the .env in the Pi's SporePrint folder), Topic = the plug's role "
        f"({topics}), Full Topic = tasmota/%topic%/%prefix%/ — REQUIRED: Tasmota's default "
        "%prefix%/%topic%/ publishes stat/…, which the broker silently drops, so the plug never "
        "appears. Console equivalent: Backlog MqttHost <pi-ip>; MqttPort 1883; MqttUser sp-3p; "
        "MqttPassword <password>; Topic humidifier; FullTopic tasmota/%topic%/%prefix%/. The "
        "Topic becomes the plug id (humidifier → plug-humidifier), which is exactly what the "
        "built-in rules drive. Toggle the plug and check it appears on the dashboard. Heater: "
        "≤ 1500 W (≤ 1200 W preferred) on one plug"
    )


def _print_step(parts: str) -> str:
    return (
        "PRINT THE ENCLOSURES (models/ or Builder → 3D Models; PLA or PETG, 0.2 mm layers, no "
        f"supports) with the preset for each part you bought: {parts} Every multi-piece "
        "enclosure is held together by brass heat-set inserts + ISO 4762 socket-head screws — "
        "press the inserts into the finished print with a soldering iron (models/README.md → "
        "Heat-set inserts). No inserts? Render with -D 'SP_FASTENER=\"self_tap\"' and use "
        "self-tapping screws"
    )


def _inserts_step(inserts: str, screws: str) -> str:
    return (
        "HEAT-SET INSERTS AND SCREWS (the insert and screw lines in this parts list; counts "
        f"from the models/README.md shopping list at default presets): inserts {inserts}; "
        f"screws {screws}. The pockets are sized for ruthex RX inserts (M2.5 x 5.7, M3 x 5.7, "
        "M4 x 8.1, M5 x 9.5; CNC Kitchen's M3/M4/M5 match, but CNC Kitchen's M2.5 is M2.5 x 4, "
        "too short). Press each insert flush with a soldering iron (insert tip, ~220-245 °C)"
    )


# ── Shared components ───────────────────────────────────────────

_RPI = Component(
    name="Raspberry Pi 5 (4GB)",
    role="Server — runs SporePrint backend, MQTT broker, and web UI",
    price_approx="$110",
    url="https://www.pishop.us/product/raspberry-pi-5-4gb/",
    category="controller",
    shared=True,
    notes="Official list price $110 since the third memory-cost rise (Apr 2026; unchanged when "
          "re-checked 2026-09-27). PiShop, CanaKit and SparkFun sell the bare board at $110; "
          "Amazon board-only listings run ~$126 with thin stock. Needs the microSD card, the "
          "official 27W USB-C PSU and the Active Cooler listed below. Budget option: Pi 5 2GB "
          "($65) — untested with the full stack (Docker, Mosquitto, ntfy, nginx, FastAPI, TFLite). "
          "The Pi 4 4GB (~$100) is NOT recommended: its port layout differs and pi_case.scad does "
          "not fit it. Check rpilocator.com for live stock.",
)

_RPI_COOLER = Component(
    name="Raspberry Pi Active Cooler (official, SC1148)",
    role="Pi 5 SoC cooling — the Pi 5 throttles without it in a warm closet",
    price_approx="$11",
    url="https://www.pishop.us/product/raspberry-pi-active-cooler/",
    category="misc",
    shared=True,
    notes="Clips into the Pi 5's two heatsink holes and plugs into its FAN header. "
          "pi_case.scad's default cooling=\"active\" preset is built around it (intake grille + "
          "shroud); render cooling=\"fan40\" only for a bare Pi with a 40 mm fan.",
)

_RPI_SD = Component(
    name="microSD Card (64GB, A1)",
    role="Raspberry Pi boot + data storage",
    price_approx="$15",
    url="https://www.amazon.com/dp/B07FKJS15M",
    category="misc",
    shared=True,
    notes="Patriot 64GB V30 A1 — room for vision frames. NAND pricing roughly doubled card "
          "prices, so the old ~$8 32GB figure is gone. Endurance option: SanDisk High Endurance "
          "64GB (B07P3D6Y5B, ~$27) is built for continuous writes but is not A1-rated, so it "
          "trades random I/O speed for endurance. Premium: official Raspberry Pi A2 64GB "
          "(SC1629, ~$40 at PiShop).",
)

_RPI_PSU = Component(
    name="Raspberry Pi 27W USB-C Power Supply (official)",
    role="Raspberry Pi power",
    price_approx="$13",
    url="https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-white-us/",
    category="power",
    shared=True,
    notes="5.1V / 5A. Use the official unit: generic USB-C PD chargers do NOT offer a 5V/5A "
          "profile, and on a 5V/3A supply the Pi 5 limits its USB ports to 600 mA. Also sold by "
          "Adafruit (5814) and on Amazon (B0D3MFLNC1, usually marked up).",
)

_ESP32 = Component(
    name="ESP32-WROOM-32 DevKit (38-pin)",
    role="Microcontroller for sensor/actuator nodes",
    price_approx="$9",
    url="https://www.amazon.com/s?k=esp32+wroom+32+devkit+38+pin",
    category="controller",
    notes="The canonical node board (firmware env node_esp32) and the GPIO map in every wiring "
          "diagram. Current listings are the narrow USB-C + CP2102 board (~52 x 25.5 mm, "
          "pre-soldered headers, no mounting holes) — esp32_case.scad's default preset "
          "(narrow_usbc). Singles are ~$9; best multi-node value: HiLetgo 3-pack B0CNYK7WT2 "
          "(~$18) or a 6-pack B0DSZBH9N9 (~$30). Espressif's own DevKitC V4 (micro-USB, wider) "
          "→ esp32_case preset devkitc_v4. " + _S3_PIN_MAP + " S3 bench verification is still "
          "pending, and genuine N8R8 boards are often out of stock (DigiKey, Adafruit).",
)

_QT_TO_SOCKETS = Component(
    name="STEMMA QT to Female Sockets Cable (150 mm) — Adafruit 4397",
    role="ESP32 header pins (3V3 / GND / GPIO 21 / GPIO 22) → first sensor's STEMMA QT port",
    price_approx="$0.95",
    url="https://www.adafruit.com/product/4397",
    category="misc",
    notes="One per climate node. Red = 3V3, black = GND, blue = SDA (GPIO 21), yellow = SCL "
          "(GPIO 22); the female sockets push onto the DevKit's downward header pins and the QT "
          "plug goes into the first sensor board.",
)

_QT_TO_QT = Component(
    name="STEMMA QT Cable, QT-QT (100 mm) — Adafruit 4210",
    role="Daisy-chains the sensor boards (each has two STEMMA QT ports)",
    price_approx="$0.95",
    url="https://www.adafruit.com/product/4210",
    category="misc",
    notes="One between each pair of sensor boards — the bus is a chain, not a star, so nothing "
          "needs splicing and no breadboard is required. Same cable carries 3V3/GND/SDA/SCL. "
          "Need more reach between boards: Adafruit 4401 (200 mm, $1.25) or 5384 (300 mm, "
          "$1.25).",
)

_SHT31 = Component(
    name="SHT31-D Sensor Breakout",
    role="Temperature + humidity sensor (I2C, 0x44)",
    price_approx="$14",
    url="https://www.adafruit.com/product/2857",
    category="sensor",
    notes="±0.3 °C / ±2% RH, I2C 0x44 — the SHT3x part the climate firmware drives. The "
          "firmware autodetects SHT3x vs SHT4x, sensor_mount bay 1 is sized for the current "
          "STEMMA QT board (25.4 x 17.78 mm), and the SHT4x boards share that outline — so these "
          "are electrical AND physical drop-ins: SHT45 "
          "(Adafruit 5665, $12.50), SHT41 (5776, $5.95), SHT40 (4885, $5.95). Cheaper modules "
          "without STEMMA QT: HiLetgo GY-SHT31-D B07ZSZW92J (~$8.50; loose headers to solder, "
          "needs soldered wires, won't seat in the bay) and DFRobot SEN0331 ($8.90; 19 x 16 mm, "
          "won't seat).",
)

_BH1750 = Component(
    name="BH1750 Light Sensor Breakout",
    role="Ambient light level sensor (I2C, 0x23)",
    price_approx="$5",
    url="https://www.adafruit.com/product/4681",
    category="sensor",
    notes="1-65535 lux, I2C 0x23. Adafruit 4681 ($4.50) is STEMMA QT and seats in sensor_mount "
          "bay 3 under the lid's light window. Cheaper, no STEMMA QT: HiLetgo GY-302 3-pack "
          "B00M0F29OS ($7.49; loose headers to solder, won't seat in bay 3); DFRobot "
          "product-531 ($4.50, no QT).",
)

_SCD41 = Component(
    name="SCD41 CO2 Sensor Breakout",
    role="CO2, temperature, humidity sensor (I2C, 0x62)",
    price_approx="$50",
    url="https://www.adafruit.com/product/5190",
    category="sensor",
    notes="True NDIR CO2, 400-5000 ppm, I2C 0x62, ~5 min warm-up. Adafruit 5190 ($49.95) was in "
          "stock when re-checked 2026-09-27. Budget alternate: SCD40 (Adafruit 5187, $44.95) — "
          "same board and pinout, accuracy specified only to 2000 ppm. Pimoroni PIM587 is out of "
          "stock. SparkFun SEN-22396 ($74.95) is an electrical drop-in, but its 25.4 x 25.4 mm "
          "board won't seat in the mount. UART alternate: MH-Z19C (~$27, B0CRKH5XVX, few "
          "ratings) — tick 'MH-Z19C CO2 sensor (UART)' under Optional peripherals in the node's "
          "setup portal and wire its TX to GPIO 16 and RX to GPIO 17 (ESP32 UART2), 5V supply, "
          "common GND; there is no printed holder for it. SCD30 (Adafruit 4867, $58.95) also "
          "autodetects but is 51 x 25.4 mm: render BOTH sensor_mount.scad and "
          "sensor_bracket.scad with -D scd30=true (sensor_mount_scd30.stl / "
          "sensor_bracket_scd30.stl).",
)

_IRLZ44N = Component(
    name="IRLZ44N N-Channel MOSFET",
    role="Logic-level low-side switch for each fan / pump / LED channel",
    price_approx="$1",
    pack_price="$10",
    url="https://www.amazon.com/s?k=IRLZ44N+mosfet",
    category="actuator",
    notes="Logic-level, TO-220, 55 V. Rds(on) 22 mΩ @ 10 V / 25 mΩ @ 5 V / 35 mΩ @ 4 V (not "
          "specified at 3.3 V). Do NOT substitute the IRFZ44N — a standard-gate part that won't "
          "fully turn on from a 3.3 V GPIO and shows up in the same search. Amazon sells 10-12 "
          "packs (~$10); genuine Infineon from distributors: Newark 63J7709 (~$1.44) or DigiKey "
          "IRLZ44NPBF-ND (~$1.80). Keep each channel ≤ ~2 A, or fit clip-on TO-220 heatsinks "
          "(relay_board_mount -D heatsink=true).",
)

_FLYBACK_DIODE = Component(
    name="Flyback Diode — UF4007 (1N4007 OK for on/off only)",
    role="Flyback protection across each inductive load (fans, pump)",
    price_approx="$0.05",
    pack_price="$6",
    url="https://www.amazon.com/dp/B07Q6LLGKH",
    category="misc",
    notes="Reverse-biased across each fan or pump (cathode band to +12V). The firmware PWMs "
          "every channel at 25 kHz, so use an ultrafast UF4007 (same DO-41 package; pinned: "
          "BOJACK 125-pack, ~$6) or a 1N5819/SS14 Schottky; a plain 1N4007 is fine only on "
          "channels that just switch on/off. LED strips are resistive and need no diode. "
          "relay_board_mount.scad has a DO-41 footprint per channel.",
)

_10K_RESISTOR = Component(
    name="10K Ohm Resistor",
    role="Gate pull-down — keeps each MOSFET off while the ESP32 boots",
    price_approx="$0.05",
    pack_price="$5.49",
    url="https://www.amazon.com/s?k=10k+ohm+resistor+1%2F4w",
    category="misc",
    notes="One per MOSFET, gate to source/GND (plus the reed switch's pull-up in All the "
          "Things). Sold in 100-packs (~$5.50, e.g. B07HDGX5LM, 1/4 W metal film — the same "
          "listing family as the 100 Ω pack; California JOS B0B4JFPHTW, ~$5, is also 1/4 W). "
          "Buy 1/4 W: 1/2 W bodies (~9 x Ø3.2 mm) won't seat in relay_board_mount.scad's "
          "resistor footprint.",
)

_100R_RESISTOR = Component(
    name="100 Ohm Resistor (gate)",
    role="Gate resistor — one in series with each MOSFET gate (GPIO → 100 Ω → gate)",
    price_approx="$0.05",
    pack_price="$5.49",
    url="https://www.amazon.com/s?k=100+ohm+resistor",
    category="misc",
    notes="Every wiring row's 'via 100R': limits the GPIO's gate-charge current and damps "
          "ringing at 25 kHz PWM. Sold in 100-packs (~$5.50, e.g. B07QKDSCSM, 1/4 W metal film). "
          "relay_board_mount.scad has a 10.16 mm footprint per channel.",
)

_SCREW_TERMINALS = Component(
    name="2-pos 5.08 mm PCB Screw Terminals, KF301-2P (30-pack)",
    role="Load and control-input terminals on the relay_board_mount switch boards",
    price_approx="$6",
    url="https://www.amazon.com/dp/B0DPYF3M41",
    category="misc",
    notes="relay_board_mount.scad seats 8 per board (J2 load output + J1 control input per "
          "channel; 4 with -D input_terminals=false). The relay and lighting boards use 16. "
          "Also fits DG301 or Phoenix MKDS 1,5/2-5,08. This listing's stock is thin — any "
          "KF301-2P 5.0/5.08 mm straight-pin pack works (e.g. ZYAMY 30 x 2-pin + 20 x 3-pin, "
          "B07T8GZ3T6).",
)

_DUPONT = Component(
    name="Dupont Jumper Wires, M-F / M-M / F-F (120 pcs, 20 cm)",
    role="Gate + GND runs from each ESP32's header pins into the switch board's J1 terminals",
    price_approx="$7",
    url="https://www.amazon.com/dp/B01EV70C78",
    category="misc",
    shared=True,
    notes="ELEGOO 120-pc mix. Female end onto the ESP32's downward header pin, male end into "
          "the J1 screw terminal (IN = GPIO, − = GND). The M-M wires serve the breadboard.",
)

_BREADBOARD = Component(
    name="Breadboard + Jumper Wire Kit",
    role="Bench bring-up — prove each node on a breadboard before soldering the switch boards",
    price_approx="$10",
    url="https://www.amazon.com/dp/B08Y59P6D1",
    category="misc",
    shared=True,
    notes="BOJACK: 4 solderless breadboards (830 + 400 tie points) + 126 flexible jumpers. The "
          "permanent build solders each switch stage into the printed relay_board_mount.scad "
          "chassis instead.",
)

_NOCTUA = Component(
    name="Noctua NF-A8 PWM Fan (80mm, 12V)",
    role="FAE / exhaust / circulation fans",
    quantity=3,
    price_approx="$18",
    url="https://www.amazon.com/dp/B00NEMG62M",
    category="actuator",
    notes="12V, 80 x 80 x 25 mm, 71.5 mm hole spacing, 0.96 W max @ 12V; sold by Noctua on "
          "Amazon ($17.95). This build powers fans from the 12V PSU rail through the relay "
          "node's MOSFETs — do NOT buy the NF-A8 5V PWM variant. fan_duct.scad fits it (one per "
          "fan you duct). Budget alternative: Arctic P8 PWM PST (~$10) — buy ASIN B07XR1KLLK "
          "specifically; the other P8 listing (B07WWKF96F) has no buy box and resells from "
          "$16+. Other dealers: https://www.noctua.at/en/products/nf-a8-pwm/buy",
)

_WHITE_STRIP = Component(
    name="12V LED Strip - Cool White (6500K), 5m roll (cut to length)",
    role="General fruiting / pinning light",
    price_approx="$12",
    url="https://www.amazon.com/dp/B00X5MEHGS",
    category="actuator",
    notes="JOYLIT SMD5050 6000-6500K, IP65 (coated — suits the humid closet), sold only as a "
          "5 m roll. Cut it to closet length at the marked cut points: a full roll draws "
          "~40-50 W (3.3-4.2 A). Lighting channel 0 (GPIO 25) through an IRLZ44N; resistive "
          "load, no flyback diode.",
)

_TRISPECTRUM = Component(
    name="12V LED Strip - Tri-spectrum 450 + 660 + 730nm, IP67, 5m",
    role="Blue (Cordyceps, pinning), red and far-red horticulture channels in one strip",
    price_approx="$41",
    url="https://www.superlightingled.com/450nm-660nm-730nm-trispectrum-tunable-red-blue-led-horticulture-grow-light-strip-p-7120.html",
    category="actuator",
    notes="SuperLightingLED p-7120, 5 m reel, 60 LEDs/m, one 4-wire lead: BLUE wire = 450 nm, "
          "RED wire = 660 nm, GREEN wire = 730 nm far-red, plus the common +12V wire. Order DC12V "
          "with the 'Outdoor Silicone Tube IP67' option ($35.98 + $5) for an 85-95% RH closet; "
          "the base IP20 strip is $36. Ships from China: ~$10 air mail + import duty on top. A "
          "full reel is ~72 W (6 A with every channel on) — cut it to closet length (cut points "
          "every 50 mm). Buy wavelength-spec'd strips from a horticulture supplier: generic "
          "'blue' strips are ~465-470 nm, which does not drive Cordyceps. Dedicated far-red "
          "alternates: SuperLightingLED p-6959 ($43.98 / 5 m, "
          "https://www.superlightingled.com/smd-5050-trichip-led-far-red-730nm-light-strip-300-diodes-5m-p-6959.html) "
          "and p-7066 ($48.98 / 5 m, "
          "https://www.superlightingled.com/dc1224v-730nm-smd2835-8mm-600-diodes-red-light-therapy-led-strip-p-7066.html).",
)

_DC_PIGTAIL = Component(
    name="DC Barrel Pigtail, 5.5 x 2.5 mm female, 14 AWG (2-pack)",
    role="Takes the 12V PSU's barrel plug to the switch boards' +12V / GND buses",
    price_approx="$8",
    url="https://www.amazon.com/dp/B0DXTQ1LYT",
    category="power",
    notes="The Facmogu bricks end in a 5.5 x 2.5 mm plug (centre +). Use a 2.5 mm female — a "
          "5.5 x 2.1 jack makes spring-only contact that heats up at several amps. Pre-tinned "
          "ends go into the switch boards' bus wiring; the second pigtail is a spare.",
)

_ESP32_CAM = Component(
    name="ESP32-CAM (AI-Thinker, OV2640 or OV3660) — 2-pack with ESP32-CAM-MB programmers",
    role="Camera node — captures images for contamination detection + growth tracking",
    price_approx="$22",
    url="https://www.amazon.com/dp/B097BLT24K",
    category="controller",
    notes="AITRIP 2-pack: two AI-Thinker ESP32-CAMs (OV2640) + two ESP32-CAM-MB micro-USB "
          "programmer boards — the board the cam firmware targets (env cam). Each camera "
          "stays on its MB, which flashes it over USB and powers it. OV2640 is being phased out; "
          "OV3660 packs work too — the firmware auto-detects OV2640 / OV3660 / OV5640 and applies "
          "the OV3660 tuning: Aideepen B0FQPCQWH2 (~$21, OV3660 + micro-USB MBs), HiLetgo "
          "B07RXPHYNM (~$22, OV3660). Singles: bare OV2640 board B07WCFGMTF (~$12, no programmer) "
          "or Aideepen B0CMTVFCYD (~$13, with a USB-C MB). Buy only the classic 'ESP32-CAM' "
          "(ESP32-S, 27 x 40.5 mm): the many 'ESP32-S3-CAM N16R8 OV3660' listings use a "
          "different chip and pin map and are NOT supported.",
)

_USB_C_CABLE = Component(
    name="USB-A to USB-C Data Cable, 1 ft (3-pack)",
    role="Power + programming for each ESP32 node (USB-C DevKit)",
    price_approx="$7",
    url="https://www.amazon.com/dp/B0D12JLQMT",
    category="power",
    notes="SUNGUY braided, data-capable (charge-only cables won't flash). USB-A pairs with the "
          "5V wall charger; many clone boards skip the USB-C CC resistors, so a C-to-C cable "
          "from a USB-C charger may not power them. For the nodes OUTSIDE the chamber (relay, "
          "lighting) next to the surge strip; in-chamber nodes use the 6 ft cable line. The 3 ft "
          "3-pack is B0B2DCV9T2 (~$10); the 6-inch 3-pack B0CQ82WBJR (~$7) suits the bench. An "
          "official Espressif DevKitC V4 needs micro-USB instead.",
)

_USB_C_CABLE_6FT = Component(
    name="USB-A to USB-C Data Cable, 6 ft",
    role="Power + programming for an ESP32 node INSIDE the chamber (climate node)",
    price_approx="$8",
    url="https://www.amazon.com/dp/B01GGKYO1I",
    category="power",
    notes="Amazon Basics, USB-IF certified, USB 2.0 data (charge-only cables won't flash). The "
          "climate node sits at substrate level inside the chamber; 6 ft reaches its 5V cube on "
          "the surge strip outside, through the pass-through grommet. Nodes outside the chamber "
          "(relay, lighting) use the short cables. 2-pack: B0CH3WQ93P (~$16).",
)

_MICRO_USB_CABLE = Component(
    name="USB-A to Micro-USB Data Cable, 6 ft (2-pack)",
    role="Power + programming for each ESP32-CAM-MB (micro-USB) — the cameras sit inside the chamber",
    price_approx="$10",
    url="https://www.amazon.com/dp/B071S5NPG9",
    category="power",
    notes="Amazon Basics, data-capable, rated to 2.1 A. 6 ft reaches from a camera inside the "
          "chamber to its 5V cube on the surge strip outside. The AITRIP / Aideepen "
          "ESP32-CAM-MB programmers are micro-USB (USB-C MB boards need a USB-C cable instead). "
          "Single: B07232M876 (~$9).",
)

# ── Mains, cabling, connectors and assembly consumables ─────────

_SURGE_STRIP_6 = Component(
    name="Surge Protector Power Strip, 6 outlets (Belkin, 1080 J)",
    role="Mains outlets for the Pi PSU, the USB cube and the smart plug — outside the chamber",
    price_approx="$14",
    url="https://www.amazon.com/dp/B000JJI6XA",
    category="power",
    notes="Belkin 6-outlet, 6 ft cord, widely spaced outlets, tested to UL standards. This tier "
          "uses 3 outlets — leave the outlet beside the ~51 mm Athom plug free. Keep it off the "
          "floor and outside the humid chamber. Alternate: Belkin 8-outlet BP108000-06 "
          "(B000JE9LCK, ~$28).",
)

_SURGE_STRIP_12 = Component(
    name="Surge Protector Power Strip, 12 outlets (Belkin, UL 1449)",
    role="Mains outlets for the Pi PSU, 12V PSU, USB cubes and smart plugs — outside the chamber",
    price_approx="$30",
    url="https://www.amazon.com/dp/B0C6S6TPRH",
    category="power",
    notes="Belkin SRA009p12tt8: 12 outlets (6 block-space for bricks), 8 ft flat plug, "
          "UL 1449, 15 A. This tier uses 8 (Pi PSU, 12V brick, 4 USB cubes, 2 smart plugs). "
          "The heater / humidifier loads go through the smart plugs — keep the strip's total "
          "under its 15 A rating (a 1500 W heater alone is 12.5 A).",
)

_SURGE_STRIP_12_USB = Component(
    name="Surge Protector Power Strip, 12 outlets + 2 USB-A (Belkin, 3,996 J)",
    role="Mains outlets for the Pi PSU, 12V PSU, USB cubes and 4 smart plugs — outside the chamber",
    price_approx="$33",
    url="https://www.amazon.com/dp/B00966IFQ0",
    category="power",
    notes="Belkin 12 AC + 2 USB-A (2.1 A shared), block-space outlets, 8 ft cord. This tier "
          "needs all 12 AC outlets (Pi PSU, 12V brick, 6 USB cubes, 4 plugs); its two USB-A "
          "ports can power the relay and lighting nodes instead of two cubes, freeing 2 "
          "outlets. Keep the total under 15 A — the heater, dehumidifier and humidifier share "
          "it; if the heater runs alongside the dehumidifier, give the heater's smart plug its "
          "own wall outlet.",
)

_WIRE_22AWG = Component(
    name="22 AWG Stranded Hookup Wire, 6 colours x 10 ft (silicone)",
    role="Gate / signal / GND jumpers on the switch boards, short splices, ESP32 GND to the GND bus",
    price_approx="$13",
    url="https://www.amazon.com/dp/B089CQHRDT",
    category="wiring",
    shared=True,
    notes="Fermerry tinned-copper silicone wire (black, red, blue, white, green, yellow; 600 V). "
          "Use it for everything that carries signal or < 1 A; the 12V feeds use the 18 AWG "
          "pair. Comes with a few heat-shrink pieces. 25 ft/colour version: B089D29FHC (~$20).",
)

_WIRE_18AWG = Component(
    name="18 AWG 2-Conductor Red/Black Wire, 100 ft",
    role="12V feeds: PSU → WAGO split → fuses → switch-board buses → LED strips, fans' and pump's runs",
    price_approx="$26",
    url="https://www.amazon.com/dp/B07CWQ6JPB",
    category="wiring",
    shared=True,
    notes="MILAPEAK bonded red/black pair, pure tinned copper (not CCA). 18 AWG is the "
          "build's 12V standard: good for the ≤ 7.5 A fused branches over these short runs. "
          "Recommended uses ~20 ft, All the Things ~35 ft. Shorter: BNTECHGO 18 AWG silicone "
          "25 ft (B0779QRR58, ~$15).",
)

_CABLE_22_4 = Component(
    name="22 AWG 4-Conductor Stranded Cable, 50 ft (UL 2464)",
    role="HX711 run and door-contact run from the chamber back to the relay node",
    price_approx="$20",
    url="https://www.amazon.com/dp/B0CN76J8KR",
    category="wiring",
    shared=True,
    notes="ENERJOUR UL 2464, tinned copper, black / red / yellow / white. HX711 run: red 3.3V, "
          "black GND, yellow DOUT → GPIO 32, white SCK → GPIO 33. Door-contact run: two "
          "conductors, COM → GPIO 35, NC → GND. Shielded alternate for long or noisy runs: "
          "B0D9JTVS2P (~$28).",
)

_WAGO = Component(
    name="WAGO 221 Lever Connectors, 12-pc assortment (221-412 / 413 / 415 / 2401)",
    role="12V distribution: split the PSU's +12V to the two fused branches; join the GND bus",
    price_approx="$12",
    url="https://www.amazon.com/dp/B0CJ5QF4Z2",
    category="wiring",
    shared=True,
    notes="Genuine WAGO, 24-12 AWG, 20 A. A 221-413 splits the pigtail's +12V into the two "
          "fuse holders; a 221-415 joins the pigtail's GND to both switch boards' GND buses "
          "and each ESP32's GND (the common ground the gate drive needs). Keep them outside "
          "the chamber. 36-pc kit: B08W3QXN9B (~$26).",
)

_FUSE_HOLDERS = Component(
    name="Inline ATC/ATO Blade Fuse Holders, 14 AWG (10-pack)",
    role="One fuse per 12V branch, right after the WAGO split",
    price_approx="$9",
    url="https://www.amazon.com/dp/B07426WCLM",
    category="wiring",
    shared=True,
    notes="Nilight NI-FH01, 14 AWG leads, covered holder (no IP rating — mount it outside the "
          "chamber). Fuse ratings: relay board 3 A; lighting board 5 A on the 5 A PSU "
          "(Recommended), 7.5 A on the 10 A PSU (All the Things). IP66 alternate: VANTRONIK "
          "6-pack (B081YDV8PS, ~$6).",
)

_FUSES = Component(
    name="ATC Blade Fuse Assortment, 150 pc (2-35 A)",
    role="3 A / 5 A / 7.5 A fuses for the inline holders, plus spares",
    price_approx="$10",
    url="https://www.amazon.com/dp/B07VWRK2VD",
    category="wiring",
    shared=True,
    notes="Riseuvo: 15 each of 2 / 3 / 5 / 7.5 / 10 / 15 / 20 / 25 / 30 / 35 A, with a puller. "
          "Fit 3 A on the relay branch and 5 A (Recommended) or 7.5 A (All the Things) on the "
          "lighting branch.",
)

_FAN_EXTENSIONS = Component(
    name="Noctua NA-SEC3 4-pin Fan Extension Cables, 60 cm (3-pack)",
    role="Carry each fan's 12V leads out of the chamber to the relay switch board",
    price_approx="$10",
    url="https://www.amazon.com/dp/B09RPLPBQH",
    category="wiring",
    notes="Fan + its bundled 30 cm extension + an NA-SEC3 reaches ~1.1 m. Cut the FAR (header) "
          "end of the extension — never the fan's own lead — and land pin 1 (GND) on the "
          "channel's J2 '−' (MOSFET drain) and pin 2 (+12V) on J2 '+'; the tach and PWM wires "
          "stay unused (the MOSFET switches the fan's supply). Identify wires by pin position, "
          "not colour. One pack per chamber's 3 fans. 30 cm set: NA-SEC1 (B00KG3K9AM).",
)

_HEAT_SHRINK = Component(
    name="Adhesive-Lined Heat Shrink Tubing Kit, 3:1 (400 pc)",
    role="Seal every splice and LED-strip joint against 85-95% RH",
    price_approx="$12",
    url="https://www.amazon.com/dp/B0BVVMCY86",
    category="hardware",
    shared=True,
    notes="Eventronic dual-wall 3:1, 7 sizes 3/32\"-3/4\". Use 1/2\"-3/4\" over the IP65 / IP67 "
          "strip-to-lead joints and the small sizes on splices; it also caps the tri-spectrum "
          "strip's unused red and green wires on the Recommended tier.",
)

_ZIP_TIES = Component(
    name="UV-Resistant Zip Ties, 4\" / 6\" / 8\" / 12\" (400 pc)",
    role="Printed-mount tie slots, shelf clips and cable routing",
    price_approx="$13",
    url="https://www.amazon.com/dp/B09SSPXBPR",
    category="hardware",
    shared=True,
    notes="Superun nylon 6/6: 2.5 mm (4\"), 3.6 mm (6\") and 4.8 mm (8\", 12\") widths — the "
          "printed parts' slots take ≤ 2.5 mm (cam_mount, relay board), ≤ 3.6 mm (esp32_case, "
          "hx711_scale, pump_bracket) and ≤ 4.8 mm (pi_case ears, sensor_bracket, PSU mount).",
)

_ZIP_TIES_DUCT = Component(
    name="Zip Ties, 18\" (457 mm) UV-resistant, 60 lb (100 pc)",
    role="Clamp 4-inch flex duct onto each fan_duct collar",
    price_approx="$9",
    url="https://www.amazon.com/dp/B0BR3FY296",
    category="hardware",
    shared=True,
    notes="Tantti Supply, 0.19\" (4.8 mm) wide — the fan_duct finger tunnels take ≤ 4.8 mm x "
          "1.4 mm ties. One per fan_duct: the tie loops ~340 mm around the collar through its "
          "four fingers, so a 14\" (356 mm) tie is too short to lock; 16\"+ works, 18\" leaves "
          "slack for imperial 4\" duct. Heavier 120 lb+ ties are 7.6 mm wide and won't fit. A 4\" "
          "worm-drive hose clamp above the fingers also works.",
)

_HOOK_LOOP = Component(
    name="VELCRO ONE-WRAP Strap Roll, 3/4\" x 12 ft",
    role="The two 12\" straps that hold the 12V PSU in power_supply_mount, plus cable bundling",
    price_approx="$7",
    url="https://www.amazon.com/dp/B000078CUB",
    category="hardware",
    shared=True,
    notes="Cut two 12\" (300 mm) straps for power_supply_mount.scad's 20 mm strap slots; the "
          "rest bundles cable runs.",
)

_GROMMETS = Component(
    name="Rubber Grommet Kit, 1/4\" - 1\" (188 pc)",
    role="Cable pass-through into the grow chamber / tent wall",
    price_approx="$13",
    url="https://www.amazon.com/dp/B094XY2GVR",
    category="hardware",
    shared=True,
    notes="Vrupin assortment incl. 7/8\" and 1\" grommets. Drill 7/8\" or 1\" for the main "
          "pass-through: USB overmolds (~13 x 7 mm) and 4-pin fan plugs pass before the "
          "grommet is seated. A tent's own cable port works too.",
)

_INSERTS_M3 = Component(
    name="ruthex Heat-Set Inserts M3 x 5.7 (100 pc)",
    role="M3 threads in the printed cases (pi_case, esp32_case, sensor_mount, sensor_bracket)",
    price_approx="$10",
    url="https://www.amazon.com/dp/B08BCRZZS3",
    category="hardware",
    shared=True,
    notes="RX-M3x5.7 brass, the size the M3 pockets are designed around (Ø4.0 x 6.7 mm). This "
          "tier needs 14. Install with a soldering iron at ~220-245 °C until flush.",
)

_INSERTS_ASSORTMENT = Component(
    name="ruthex Heat-Set Insert Assortment M2 / M3 / M4 / M5 (270 pc)",
    role="M3 / M4 / M5 threads in every printed case, duct and mount",
    price_approx="$30",
    url="https://www.amazon.com/dp/B08K1BVGN9",
    category="hardware",
    shared=True,
    notes="70 x RX-M2x4, 100 x RX-M3x5.7, 50 x RX-M4x8.1, 50 x RX-M5x9.5 — covers this tier's "
          "M3, M4 (fan ducts) and M5 (camera pivot) inserts. It has no M2.5: see the M2.5 "
          "line. CNC Kitchen's M3 / M4 / M5 inserts match these pockets too.",
)

_INSERTS_M25 = Component(
    name="Heat-Set Inserts M2.5 (70 pc, ~4.5 mm OD x 6 mm)",
    role="M2.5 threads: Pi standoffs, sensor board posts, HX711 posts, pump flange",
    price_approx="$9",
    url="https://www.amazon.com/dp/B0CT8V76RL",
    category="hardware",
    shared=True,
    notes="uxcell brass knurled inserts — fit the Ø3.6 x 6.7 mm M2.5 pockets (press flush). "
          "Thin stock: the exact design part is ruthex RX-M2.5x5.7, which Amazon US doesn't "
          "carry — 3DJake sells it (https://www.3djake.com/ruthex/threaded-insert-m25-70-pieces, "
          "~$8 + EU shipping). Avoid 3.5 mm-OD x 4 mm M2.5 inserts (they spin in the pocket) "
          "and CNC Kitchen's M2.5 x 4 (too short).",
)

_SCREWS_M25 = Component(
    name="M2.5 Socket Head Screw Kit, 304 stainless (6 / 8 / 10 / 12 mm + nuts)",
    role="Pi to its standoffs, sensor boards, HX711 board, pump flange",
    price_approx="$9",
    url="https://www.amazon.com/dp/B0C7ZRTH3Q",
    category="hardware",
    shared=True,
    notes="mxuteuk: 40 x M2.5x6, 25 x M2.5x8, 20 x M2.5x10, 15 x M2.5x12. Stainless because "
          "the in-chamber parts live at 85-95% RH. Use x6 for the Pi (x8 bottoms out in its "
          "pocket).",
)

_SCREWS_M3X6 = Component(
    name="M3 x 6 mm Socket Head Screws, 304 stainless (100 pc)",
    role="Lid and board screws into the M3 inserts",
    price_approx="$8",
    url="https://www.amazon.com/dp/B089KR3XHR",
    category="hardware",
    shared=True,
    notes="iexcell, 5.5 mm head. The most-used size: 10 (Bare Bones) to 36 (All the Things). "
          "Budget alternative covering M3 x 6-20: mxuteuk M3 kit (B0C7ZPZ214, ~$8, black steel).",
)

_SCREWS_KIT = Component(
    name="Socket Head Screw Kit M2.5-M8, 304 stainless (135 pc)",
    role="M3 x 16 (Pi lid), M5 x 16 (camera pivot), M4 x 16 and longer M2.5",
    price_approx="$10",
    url="https://www.amazon.com/dp/B0711DX7LC",
    category="hardware",
    shared=True,
    notes="DANA FRED: 10 each of M2.5x8/10/16/20, M3x10/16/20, M4x16/20, M5x16/20, M6x16/20 "
          "+ 5 x M8x25. Single-size alternates: BNUOK M3x16 (B0DJQGNDC7), MewuDecor M5x16 "
          "(B07PXL8DGH).",
)

_SCREWS_M4 = Component(
    name="M4 Socket Head Screw Kit, 304 stainless (25-50 mm + washers)",
    role="M4 x 35 fan screws through each fan into the fan_duct inserts; M4 x 25 for the scale",
    price_approx="$9",
    url="https://www.amazon.com/dp/B0DCVTWC5B",
    category="hardware",
    shared=True,
    notes="VGBUY: 15 x M4x25, 15 x M4x30, 13 x M4x35, 10 each M4x40/45/50, nuts, lock + flat "
          "washers. 4 x M4 x 35 per fan_duct (x30 / x40 also fit).",
)

_SET_SCREWS_M4 = Component(
    name="M4 x 8 mm Cup-Point Set Screws, 304 stainless (50 pc)",
    role="hx711_scale's adjustable overload stops",
    price_approx="$8",
    url="https://www.amazon.com/dp/B0D8TJ4DHB",
    category="hardware",
    shared=True,
    notes="QWUEE. Four go into the platform's M4 inserts as overload stops (medium threadlocker "
          "or nylon-patch screws). Flat-point alternate: B0B39272FF.",
)

_PUMP_TUBING = Component(
    name="Food-Grade Silicone Tubing 2 mm ID x 4 mm OD, 5 m",
    role="Pump outlet → substrate hydration line",
    price_approx="$11",
    url="https://www.amazon.com/dp/B0852HZSTR",
    category="hardware",
    notes="Quickun pure silicone, FDA / 3A sanitary compliant, 50A. Adafruit says the 1150's "
          "tube size has changed between batches (~2 x 4 mm, its spare is 2.5 x 4.7 mm) — "
          "measure the pump's barb before cutting. Alternate: Hooshing 2 x 4 mm, 10 ft "
          "(B08PTXMNCN, ~$9).",
)

_SOLDER = Component(
    name="Lead-Free Rosin-Core Solder, 0.8 mm (50 g)",
    role="Switch-board joints and LED-strip leads",
    price_approx="$10",
    url="https://www.amazon.com/dp/B07QZX9LG2",
    category="hardware",
    shared=True,
    notes="ZSHX Sn99 / Ag0.3 / Cu0.7 with rosin flux (melts 217 °C). The relay_board_mount "
          "switch boards are soldered point-to-point underneath. Bigger reel: AUSTOR 100 g "
          "(B01M071WEE, ~$18). A soldering iron with a heat-set insert tip installs the "
          "inserts too (tools aren't BOM lines — see the build guide's tool list).",
)

_USB_CHARGER = Component(
    name="USB Wall Charger 5V 2A, UL-listed (2-pack)",
    role="5V power for the ESP32 nodes and cameras — one port per board",
    price_approx="$8",
    url="https://www.amazon.com/dp/B0DQ43LMRH",
    category="power",
    notes="UL-listed USB-A 5V/2A cubes (it stays plugged in beside a humidifier, so buy "
          "listed). A node draws < 0.5 A; the ESP32-CAM needs ≥ 1 A and browns out on weak "
          "computer ports. One cube per board.",
)


def _tasmota_plug(quantity: int, roles: str) -> Component:
    return Component(
        name="Athom Tasmota US Plug V2",
        role=f"Smart plug — {roles}",
        quantity=quantity,
        price_approx="$10",
        url="https://www.athom.tech/blank-1/tasmota-us-plug-v2",
        category="plug",
        notes="Ships pre-flashed with Tasmota (MQTT, no cloud) with HLW8032 power monitoring. "
              "Pick the Tasmota listing — NOT the 'US V2 Plug Made For ESPHome' twin "
              "(SKU PG03V2-…), which SporePrint can't talk to. $10 is Athom's sale price (list "
              "$18.40); the 2-pack is $17.50. Also on Tindie ($14.90 + shipping). Fallback if V2 "
              "sells out: Athom Tasmota ESP32-C3 US Plug V3 ($14.35, "
              "https://www.athom.tech/blank-1/tasmota-esp32-c3-us-plug-v3). MQTT setup: User "
              "sp-3p, Password SPOREPRINT_MQTT_3P_PASSWORD, Topic = the plug's role, Full Topic "
              "tasmota/%topic%/%prefix%/ (see the setup steps). Not UL/ETL listed: keep plugs "
              "outside the humid chamber, and a space heater ≤ 1500 W (≤ 1200 W preferred) on "
              "one plug.",
    )


def _for_tier(base: Component, *, quantity: int, tier_note: str = "", **fields) -> Component:
    """A tier's copy of a shared part.

    The tier note is PREPENDED to the shared buying guidance. The old
    overrides replaced ``notes`` wholesale, which silently dropped the
    IRFZ44N warning, the pack advice and the S3 pin map from Tiers 2/3.
    """
    notes = f"{tier_note} {base.notes}" if tier_note else base.notes
    return base.model_copy(update={"quantity": quantity, "notes": notes, **fields})


# ── Wiring rows ─────────────────────────────────────────────────


def _climate_chain(node: str, sensors: list[str]) -> list[WiringConnection]:
    """STEMMA QT daisy chain: the node's header pins → the first board over an
    Adafruit 4397, then board to board over 4210 QT-QT cables."""
    first = sensors[0]
    lead = "Adafruit 4397: female socket on the ESP32 pin, QT plug in the sensor"
    rows = [
        WiringConnection(from_device=node, from_pin="3.3V", to_device=first,
                         to_pin="STEMMA QT — red (V+)", note=lead),
        WiringConnection(from_device=node, from_pin="GND", to_device=first,
                         to_pin="STEMMA QT — black (GND)", note=lead),
        WiringConnection(from_device=node, from_pin="GPIO 21 (SDA)", to_device=first,
                         to_pin="STEMMA QT — blue (SDA)", note=lead),
        WiringConnection(from_device=node, from_pin="GPIO 22 (SCL)", to_device=first,
                         to_pin="STEMMA QT — yellow (SCL)", note=lead),
    ]
    for a, b in zip(sensors, sensors[1:]):
        rows.append(WiringConnection(
            from_device=a, from_pin="STEMMA QT (second port)", to_device=b, to_pin="STEMMA QT",
            note="Adafruit 4210 QT-QT cable — carries 3V3 / GND / SDA / SCL on down the chain",
        ))
    return rows


def _relay_rows(aux_note: str) -> list[WiringConnection]:
    gate = "via 100R resistor"
    pull = "10K gate-to-source pull-down; UF4007 across the fan (cathode to +12V)"
    return [
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 25", to_device="IRLZ44N #1 Gate",
                         to_pin=gate, note=f"FAE fan — {pull}"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 26", to_device="IRLZ44N #2 Gate",
                         to_pin=gate, note=f"Exhaust fan — {pull}"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 27", to_device="IRLZ44N #3 Gate",
                         to_pin=gate, note=f"Circulation fan — {pull}"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 14", to_device="IRLZ44N #4 Gate",
                         to_pin=gate, note=aux_note),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GND", to_device="Relay switch board",
                         to_pin="J1 '−' / GND bus",
                         note="Common ground with the 12V PSU — the gate signal is referenced to it"),
    ]


def _lighting_rows(blue_note: str, extra: list[WiringConnection]) -> list[WiringConnection]:
    # The lighting personality always exposes FOUR PWM channels — white/blue/
    # red/far_red on SP_CHANNEL_PINS {25, 26, 27, 14}. Recommended wires the
    # first two; All the Things passes the red/far-red rows in `extra`.
    return [
        WiringConnection(from_device="ESP32 (Lighting)", from_pin="GPIO 25", to_device="IRLZ44N Gate",
                         to_pin="via 100R",
                         note="White 6500K strip (JOYLIT) — 10K pull-down; no diode (resistive load)"),
        WiringConnection(from_device="ESP32 (Lighting)", from_pin="GPIO 26", to_device="IRLZ44N Gate",
                         to_pin="via 100R", note=blue_note),
        *extra,
        WiringConnection(from_device="ESP32 (Lighting)", from_pin="GND", to_device="Lighting switch board",
                         to_pin="J1 '−' / GND bus", note="Common ground with the 12V PSU"),
    ]


def _power_rows(lighting_fuse: str) -> list[WiringConnection]:
    """12V distribution: PSU → barrel pigtail → WAGO split → one inline fuse
    per branch → each switch board's +12V bus; GND joined on a WAGO. 18 AWG
    for every 12V run, 22 AWG for signal / ESP32 GND."""
    return [
        WiringConnection(from_device="12V PSU", from_pin="5.5 x 2.5 mm barrel (centre +)",
                         to_device="DC barrel pigtail", to_pin="female jack",
                         note="14 AWG pigtail leads — red +12V, black GND"),
        WiringConnection(from_device="DC pigtail", from_pin="+12V (red)", to_device="WAGO 221-413",
                         to_pin="+12V split", note="One lead in, two 18 AWG red leads out (one per branch)"),
        WiringConnection(from_device="WAGO 221-413 (+12V)", from_pin="branch 1",
                         to_device="Inline fuse 3 A → relay switch board", to_pin="+12V bus → every J2 '+'",
                         note="18 AWG red; fans + aux draw well under 1 A"),
        WiringConnection(from_device="WAGO 221-413 (+12V)", from_pin="branch 2",
                         to_device=f"Inline fuse {lighting_fuse} → lighting switch board",
                         to_pin="+12V bus → every J2 '+'",
                         note="18 AWG red; LED strips are the load — cut them to closet length"),
        WiringConnection(from_device="DC pigtail", from_pin="GND (black)", to_device="WAGO 221-415",
                         to_pin="GND join",
                         note="18 AWG black on to both boards' GND buses (every IRLZ44N source); each "
                              "ESP32's GND reaches the same bus through its board's J1 '−'"),
        WiringConnection(from_device="Switch board J2 (per channel)", from_pin="'+' (+12V) / '−' (drain)",
                         to_device="Load: fan / LED strip / pump", to_pin="+ / −",
                         note="18 AWG to the strips and pump; fans through a Noctua 4-pin extension "
                              "(pin 2 = +12V, pin 1 = GND); adhesive heat shrink on every joint"),
    ]


# ── Tier 1: Bare Bones ─────────────────────────────────────────

TIER_BARE_BONES = HardwareTier(
    id="bare_bones",
    name="Bare Bones",
    tagline="Monitor your grow. Smart plug for humidifier.",
    estimated_cost="~$290",
    best_for=(
        "First-time mushroom cultivators who want reliable monitoring and basic humidity "
        "control without committing to full automation. Ideal for a single grow tent or "
        "monotub setup where fresh air exchange is handled manually."
    ),
    species_support=(
        "Gourmet species that tolerate manual FAE: white button, cremini, basic oyster "
        "grows. Not recommended for CO2-sensitive species like Lion's Mane or King Oyster "
        "— those benefit from the Recommended tier's active CO2-triggered fans."
    ),
    what_you_get=[
        "Live temperature + humidity + light monitoring on dashboard",
        "Alerts when conditions go out of range",
        "Smart plug control for humidifier (on/off via app)",
        "Session tracking with manual observations",
        "Species profile target overlays on gauges",
    ],
    capability_groups=[
        CapabilityGroup(
            title="Environmental monitoring",
            items=[
                "Temperature at substrate level (±0.3°C accuracy, SHT31-D)",
                "Relative humidity (±2% RH, SHT31-D)",
                "Ambient light level in lux (BH1750, 1-65535 lux range)",
                "Single-zone monitoring — one set of sensors per chamber",
            ],
        ),
        CapabilityGroup(
            title="Automation & control",
            items=[
                "Smart plug on/off control for humidifier (Athom Tasmota, MQTT)",
                "Threshold-based rules: humidifier triggers when RH drops below setpoint",
                "Time-based schedules (e.g. scheduled hydration cycles)",
                "Manual override from mobile app — remote on/off from anywhere",
            ],
        ),
        CapabilityGroup(
            title="Session tracking",
            items=[
                "Manual session creation with species selection and target profiles",
                "Visual overlays showing target ranges on live gauges",
                "Harvest logging with wet/dry weights per flush",
                "Notes and photo attachments per session",
                "Full event transcript export (Markdown / JSON)",
            ],
        ),
        CapabilityGroup(
            title="Alerting",
            items=[
                "Push notifications (ntfy) when conditions exit target range",
                "Alerts for sensor failures or node offline events",
                "Tiered alerts — critical pages go out at once, repeats collapse for 15 min",
            ],
        ),
    ],
    limitations=[
        "No CO2 monitoring — required for heavy fruiters like Lion's Mane or King Oyster",
        "No fan automation — you must open the chamber manually for fresh air exchange",
        "No lighting automation — LED timers must be external",
        "No camera / vision features — no contamination detection, no growth tracking",
        "No automated heating or cooling — single plug channel only",
    ],
    components=[
        _RPI, _RPI_COOLER, _RPI_SD, _RPI_PSU,
        _ESP32,
        _SHT31,
        _BH1750,
        _QT_TO_SOCKETS,
        _QT_TO_QT,
        _USB_C_CABLE_6FT,
        _USB_CHARGER,
        _tasmota_plug(1, "humidifier on/off"),
        _SURGE_STRIP_6,
        _ZIP_TIES,
        _GROMMETS,
        _INSERTS_M3,
        _for_tier(_INSERTS_M25, quantity=1, tier_note="This tier needs 10 (Pi standoffs, sensor posts)."),
        _SCREWS_M25,
        _SCREWS_M3X6,
        _for_tier(_SCREWS_KIT, quantity=1, tier_note="This tier uses its M3 x 16 (Pi lid)."),
    ],
    wiring=_climate_chain("ESP32", ["SHT31-D", "BH1750"]),
    wiring_diagram="See docs/wiring-tier1-bare-bones.svg for full wiring diagram with color-coded signal, I2C, power, and ground lines.",
    firmware_targets=["node_esp32"],
    setup_steps=[
        "Set up the Raspberry Pi: flash Raspberry Pi OS (64-bit) with Raspberry Pi Imager — set "
        "the hostname to 'sporeprint' in its advanced options (ESP32 nodes find the MQTT broker "
        "at sporeprint.local) and enable SSH + WiFi. Fit the Active Cooler before casing the Pi",
        _INSTALL_STEP,
        _print_step(
            "pi_case (default: Pi 5 + Active Cooler); esp32_case (default preset narrow_usbc fits "
            "the pinned narrow USB-C DevKit — devkitc_v4 / wide_usbc / s3_devkitc1 for other "
            "boards); sensor_mount + sensor_bracket (defaults; -D scd30=true on both only for an "
            "SCD30)."
        ),
        _inserts_step(
            "10 x M2.5 x 5.7 and 14 x M3 x 5.7",
            "10 x M2.5 x 6, 10 x M3 x 6 and 4 x M3 x 16",
        ),
        "Wire the climate node as a STEMMA QT daisy chain (no soldering, no breadboard): the "
        "Adafruit 4397 cable's female sockets go on the ESP32's 3.3V (red), GND (black), GPIO 21 "
        "SDA (blue) and GPIO 22 SCL (yellow) pins and its QT plug into the SHT31-D; a 4210 QT-QT "
        "cable links the SHT31-D's second port to the BH1750. Leave the boards' loose header "
        "strips unsoldered",
        _PLATFORMIO_STEP,
        _flash_nodes_step("the node"),
        _mqtt_credential_step("e.g. climate-01"),
        _portal_step("Choose the climate personality."),
        "SENSOR PLACEMENT — Climate node (SHT31 + BH1750): Mount the sensor boards inside the "
        "ventilated sensor enclosure (sensor_mount.scad). Place at CENTER of growing chamber at "
        "SUBSTRATE LEVEL — not near the ceiling where hot air rises. Temperature and humidity at "
        "substrate level are what matter for mushroom growth, not ambient room temp. Clip the "
        "sensor_bracket onto a wire shelf (zip ties through the clip webs), or use the bracket's "
        "suction cup on glass walls. AVOID placing near heat sources (heaters, lights), direct "
        "airflow (fan output), or dead air zones (corners). The BH1750 looks up through the lid's "
        "light window — face it toward the light source, not the floor",
        "POWER + CABLING: plug the Pi PSU, the 5V USB cube and the smart plug into the surge "
        "strip OUTSIDE the chamber (off the floor). Run the 6 ft USB-A to USB-C cable from the cube "
        "through a grommeted 7/8\" hole (or the tent's cable port) to the climate node — the "
        "ESP32 draws < 0.5 A — and tidy the run with zip ties",
        _tasmota_step(
            "Connect your humidifier (ultrasonic, inside the chamber or piped in via tubing).",
            "humidifier",
        ),
        "Open http://<pi-ip>:3001 (install.sh printed it; http://sporeprint.local:3001 if mDNS "
        "works) — you should see live sensor data on the dashboard",
    ],
)

# ── Tier 2: Recommended ────────────────────────────────────────

TIER_RECOMMENDED = HardwareTier(
    id="recommended",
    name="Recommended",
    tagline="Full monitoring + automated fans, lights, and vision.",
    estimated_cost="~$745",
    best_for=(
        "Serious hobbyists producing 2-10 flushes per year and experimenting with multiple "
        "species. This is the sweet spot for most home growers: full climate sensing, "
        "active FAE automation, multi-spectrum lighting, and camera-based contamination "
        "detection — without the complexity or cost of redundant systems."
    ),
    species_support=(
        "All gourmet varieties: Blue Oyster, Pink Oyster, Lion's Mane, Shiitake, King "
        "Oyster, Pioppino, Chestnut, Pearl Oyster, Maitake, Nameko. Covers CO2-sensitive "
        "species via active FAE fans. Cordyceps militaris is supported via the blue "
        "450nm LED channel, though best results come from the All the Things tier's "
        "full 4-spectrum setup."
    ),
    what_you_get=[
        "Live temperature + humidity + light monitoring on dashboard",
        "Alerts when conditions go out of range",
        "Smart plug control for humidifier and heater/cooler (on/off via app)",
        "Session tracking with manual observations",
        "Species profile target overlays on gauges",
        "CO2 monitoring — critical for oyster and lion's mane species",
        "Automated FAE fans triggered by CO2 thresholds",
        "Multi-spectrum LED lighting with scene presets (colonization, fruiting, cordyceps blue)",
        "Camera vision — contamination detection + growth stage tracking",
        "Claude Vision analysis on demand",
        "Automated humidity control via smart plug",
        "Full automation rules engine",
    ],
    capability_groups=[
        CapabilityGroup(
            title="Environmental monitoring",
            items=[
                "Temperature (±0.3°C, SHT31-D) and humidity (±2% RH)",
                "CO2 (±50 ppm, SCD41 NDIR) — required for commercial-quality oyster/lion's mane",
                "Ambient light (BH1750, 1-65535 lux)",
                "Single-chamber monitoring on one STEMMA QT sensor chain",
            ],
        ),
        CapabilityGroup(
            title="Active automation (4 relay channels)",
            items=[
                "CO2-triggered FAE fan — opens when ppm exceeds species setpoint",
                "Exhaust fan for temperature regulation",
                "Circulation fan for even humidity distribution",
                "Aux channel — misting, secondary exhaust, or custom device",
                "Flyback-protected MOSFET switching (safe for inductive loads)",
            ],
        ),
        CapabilityGroup(
            title="Lighting (2 of the node's 4 PWM channels)",
            items=[
                "6500K cool white LED strip — colonization and general fruiting light",
                "450nm blue (tri-spectrum strip) — Cordyceps fruiting, pinning trigger",
                "Two spare PWM channels (red 660nm / far-red 730nm) on the same node — the "
                "tri-spectrum strip already carries both; wire them later without re-flashing",
                "Scene presets: colonization (dark), fruiting (white), cordyceps blue",
                "Schedulable photoperiods per species profile",
            ],
        ),
        CapabilityGroup(
            title="Vision & AI",
            items=[
                "ESP32-CAM AI-Thinker (OV2640 2MP or OV3660 3MP, auto-detected) with built-in flash LED",
                "Auto-capture every 15 minutes, stored per session",
                "Claude Vision auto-analysis every 6 h and on each phase change — contamination alerts",
                "Claude Vision analysis on demand — detailed growth stage + issue reports",
                "Photo gallery per session with capture timestamps",
            ],
        ),
        CapabilityGroup(
            title="Smart plug control (2 plugs)",
            items=[
                "Humidifier plug — threshold-based RH control via MQTT",
                "Heater or cooler plug — thermostat rules for temperature setpoints",
                "Power monitoring built in (Athom HLW8032) — reports watts per plug",
                "Remote manual control from mobile app",
            ],
        ),
        CapabilityGroup(
            title="Session & analytics",
            items=[
                "Full automation rules engine with condition/action builder",
                "Per-session metric timelines (temp, RH, CO2, light trends)",
                "Yield analytics — per-flush yields, biological efficiency, species averages",
                "Claude transcript analysis — conditions vs targets, issues, next-run advice",
                "CSV + Markdown exports for every session",
            ],
        ),
    ],
    limitations=[
        "Single climate sensor per chamber — no redundancy if a sensor fails",
        "Two-channel lighting only — no red or far-red morphology tuning",
        "Two smart plugs — can't run both humidifier + dehumidifier concurrently",
        "Single camera angle — either front view or top-down, not both",
        "No load cell — harvest weights are manually entered",
        "The tri-spectrum strip ships from China (~$10 air mail + import duty, not in the estimate)",
    ],
    components=[
        _RPI, _RPI_COOLER, _RPI_SD, _RPI_PSU,
        _for_tier(_ESP32, quantity=3, pack_price="$18",
                  tier_note="This tier: 3 nodes (climate, relay, lighting) — one HiLetgo 3-pack "
                            "(B0CNYK7WT2, ~$18)."),
        _SHT31,
        _BH1750,
        _SCD41,
        _QT_TO_SOCKETS,
        _for_tier(_QT_TO_QT, quantity=2, tier_note="Two: SHT31-D → SCD41 → BH1750."),
        _for_tier(_IRLZ44N, quantity=6,
                  tier_note="This tier: 6 — 4 on the relay node (FAE, exhaust, circulation, aux) + "
                            "2 on the lighting node (white, blue)."),
        _for_tier(_100R_RESISTOR, quantity=6, tier_note="This tier: 6 — one per MOSFET gate."),
        _for_tier(_10K_RESISTOR, quantity=6, tier_note="This tier: 6 — the gate pull-downs."),
        _for_tier(_FLYBACK_DIODE, quantity=4,
                  tier_note="This tier: 4 — the relay node's fan/aux channels only (LED strips "
                            "are resistive)."),
        _SCREW_TERMINALS,
        _DUPONT,
        _NOCTUA,
        _WHITE_STRIP,
        _for_tier(_TRISPECTRUM, quantity=1,
                  tier_note="This tier drives only its BLUE (450 nm) wire, on lighting ch 1 "
                            "(GPIO 26), plus the common wire to +12V; insulate the red and green "
                            "wires until you add the red/far-red channels (All the Things)."),
        Component(
            name="12V Power Supply (5A, 60W) — Facmogu AL-1250",
            role="Power for the LED strips and 12V fans",
            price_approx="$12",
            url="https://www.amazon.com/dp/B0711Q5B49",
            category="power",
            notes="UL-certified 113 x 55 x 33 mm brick, hard-wired 2-prong AC cord (~40 cm on "
                  "the AC side — the outlet must be within reach), 5.5 x 2.5 mm barrel output "
                  "(centre +). power_supply_mount.scad's default preset (psu=\"facmogu_5a\") "
                  "fits it. Load budget: keep ≤ ~4 A continuous — three NF-A8 fans draw ~0.25 A "
                  "together, so the LED strips are the load: cut them to closet length (a full "
                  "white roll is ~40-50 W, a full tri-spectrum reel 72 W).",
        ),
        _DC_PIGTAIL,
        _ESP32_CAM,
        _for_tier(_USB_C_CABLE, quantity=1, tier_note="This tier: the relay + lighting nodes (outside the chamber)."),
        _USB_C_CABLE_6FT,
        _MICRO_USB_CABLE,
        _for_tier(_USB_CHARGER, quantity=2,
                  tier_note="This tier: 2 packs = 4 cubes (3 nodes + 1 camera)."),
        _tasmota_plug(2, "humidifier; heater or cooler"),
        _SURGE_STRIP_12,
        _WIRE_18AWG,
        _WIRE_22AWG,
        _WAGO,
        _FUSE_HOLDERS,
        _FUSES,
        _FAN_EXTENSIONS,
        _HEAT_SHRINK,
        _ZIP_TIES,
        _ZIP_TIES_DUCT,
        _HOOK_LOOP,
        _GROMMETS,
        _INSERTS_ASSORTMENT,
        _for_tier(_INSERTS_M25, quantity=1, tier_note="This tier needs 10."),
        _SCREWS_M25,
        _SCREWS_M3X6,
        _SCREWS_KIT,
        _SCREWS_M4,
        _SOLDER,
        _BREADBOARD,
    ],
    wiring=[
        *_climate_chain("ESP32 (Climate)", ["SHT31-D", "SCD41", "BH1750"]),
        *_relay_rows(
            "Aux channel — spare (the misting pump in All the Things); 60 s max-on backstop by "
            "default; add a UF4007 if the load is inductive"
        ),
        *_lighting_rows(
            "Blue 450nm — BLUE wire of the tri-spectrum strip; insulate its red + green wires; "
            "strip's common wire to +12V",
            [],
        ),
        *_power_rows("5 A"),
    ],
    wiring_diagram="See docs/wiring-tier2-recommended.svg: every node and the camera, inside vs outside the chamber, the STEMMA QT chain, both MOSFET switch boards, the fused 12V distribution (PSU → pigtail → WAGO → 3 A / 5 A fuses, 18 AWG) with the common ground, fan extensions, USB power and the surge strip.",
    firmware_targets=["node_esp32", "cam"],
    setup_steps=[
        "Set up the Raspberry Pi: flash Raspberry Pi OS (64-bit) with Raspberry Pi Imager — set "
        "the hostname to 'sporeprint' in its advanced options (nodes find the MQTT broker at "
        "sporeprint.local) and enable SSH + WiFi. Fit the Active Cooler before casing the Pi",
        _INSTALL_STEP,
        _WEATHER_STEP,
        _print_step(
            "pi_case (default: Pi 5 + Active Cooler); 3 x esp32_case (default preset narrow_usbc "
            "fits the HiLetgo 3-pack; devkitc_v4 / wide_usbc / s3_devkitc1 for other boards); "
            "sensor_mount + sensor_bracket (defaults; -D scd30=true on both only for an SCD30); "
            "cam_mount (default, CAM + MB stack); relay_board_mount twice — -D 'node=\"relay\"' "
            "and -D 'node=\"lighting\"' (lighting board in PETG; " + _HEATSINK_NOTE + "); "
            "power_supply_mount (default psu=\"facmogu_5a\" fits the pinned Facmogu 5A); "
            "fan_duct (default) for each fan you duct."
        ),
        _inserts_step(
            "10 x M2.5 x 5.7, 26 x M3 x 5.7, 12 x M4 x 8.1 and 1 x M5 x 9.5 (3 fan ducts)",
            "10 x M2.5 x 6, 22 x M3 x 6, 4 x M3 x 16, 12 x M4 x 35 and 1 x M5 x 16",
        ),
        "Wire the climate node as a STEMMA QT daisy chain: the Adafruit 4397 cable's female "
        "sockets on the ESP32's 3.3V (red), GND (black), GPIO 21 SDA (blue) and GPIO 22 SCL "
        "(yellow) pins, its QT plug into the SHT31-D; then 4210 QT-QT cables SHT31-D → SCD41 → "
        "BH1750. No soldering, no breadboard",
        "Build the relay switch board on relay_board_mount (node=\"relay\"), per channel: "
        "IRLZ44N, 100 Ω from the J1 IN terminal to the gate, 10K from gate to source, UF4007 "
        "across the J2 load terminals (cathode to +12V), source to the GND bus. Run Dupont "
        "jumpers (female end on the ESP32 pin) from GPIO 25 / 26 / 27 / 14 and a GND pin into "
        "the J1 terminals",
        "Build the lighting switch board the same way (node=\"lighting\") but "
        "WITHOUT diodes — LED strips are resistive. Populate channels 0 and 1: white 6500K on "
        "GPIO 25, blue 450 nm on GPIO 26. The lighting personality also exposes GPIO 27 + GPIO "
        "14 (red 660 nm / far-red 730 nm); leave them unpopulated for now and add them later "
        "without re-flashing",
        _PLATFORMIO_STEP,
        _flash_nodes_step("each node"),
        _CAM_FLASH_STEP,
        _mqtt_credential_step("climate-01, relay-01, lighting-01, cam-01"),
        _portal_step(
            "The camera's portal asks for the same WiFi / Pi address / MQTT fields; it uploads "
            "frames to http://<Pi address>:8000.",
            cams=True,
        ),
        "SENSOR PLACEMENT — Climate node (SHT31 + SCD41 + BH1750): Mount the sensor boards inside "
        "the ventilated sensor enclosure (sensor_mount.scad). Place at CENTER of growing chamber "
        "at SUBSTRATE LEVEL — not near the ceiling where hot air rises. Temperature and humidity "
        "at substrate level are what matter for mushroom growth, not ambient room temp. Clip the "
        "sensor_bracket onto a wire shelf, or use its suction cup on glass walls. AVOID placing "
        "near heat sources (heaters, lights), direct airflow (fan output), or dead air zones "
        "(corners). CO2 SPECIFIC: the SCD41 needs air moving around it — the chimney vents in "
        "the enclosure are critical for accurate readings. LIGHT SPECIFIC: the BH1750 looks up "
        "through the lid's light window — face it toward the LED strips",
        "RELAY NODE PLACEMENT: Mount both switch boards (relay_board_mount.scad) OUTSIDE the grow "
        "chamber — electronics do not belong in 85-95% RH. Fix them to the outside wall or a "
        "nearby shelf with 4 x M3 x 16 pan-head (or #4 x 3/4\" wood) screws through the corner "
        "feet, or zip ties through the end slots. Route wires into the chamber through a small "
        "grommeted hole. Keep the MOSFETs ventilated — they warm up under load",
        "Connect fans to the relay node: FAE fan to channel 0 (GPIO 25), exhaust to channel 1 "
        "(GPIO 26), circulation to channel 2 (GPIO 27). Aux (channel 3, GPIO 14) has a 60 s "
        "max-on backstop by default — if you use it for something other than a misting pump, "
        "raise it with cmd/config {\"max_on_sec\": {\"aux\": N}}",
        "Connect LED strips to the lighting node: the white strip to channel 0 (GPIO 25); the "
        "tri-spectrum strip's BLUE wire to channel 1 (GPIO 26) and its common wire to +12V — "
        "insulate its red and green wires",
        "POWER (12V): 12V 5A PSU → DC barrel pigtail → WAGO 221-413 splits +12V into two "
        "inline fuses — 3 A to the relay board's +12V bus, 5 A to the lighting board's — and a "
        "WAGO 221-415 joins the pigtail GND to both boards' GND buses. Every 12V run is the 18 AWG "
        "red/black pair; the ESP32s' GND reaches the same bus through each board's J1 '−' "
        "(common ground). Keep the load ≤ ~4 A: cut the strips to closet length",
        "CABLING: fans reach the relay board through their bundled 30 cm extension + a Noctua "
        "NA-SEC3 (cut the extension's far end: pin 2 → J2 '+', pin 1 → J2 '−'); strips get 18 "
        "AWG leads; adhesive heat shrink on every splice and strip joint. Everything 12V/mains "
        "stays OUTSIDE the chamber — pass the fan, strip and USB runs through a grommeted 7/8\" "
        "hole (or the tent's port) and tie them off. The surge strip feeds the Pi PSU, the 12V "
        "brick, the 4 USB cubes and both smart plugs. The climate node and the camera get the "
        "6 ft cables (USB-C / micro-USB into the camera's MB); the relay and lighting nodes the "
        "short USB-C ones",
        "CAMERA PLACEMENT: Two recommended positions — (1) FRONT-FACING at substrate level, angled "
        "slightly upward to capture pin formation and fruiting body development, or (2) TOP-DOWN "
        "above the substrate looking straight down for overall colonization progress. Use "
        "cam_mount.scad — suction cup on a glass door, screws, or zip ties to a shelf rail. "
        "Distance: 15-30cm from substrate for good detail without fish-eye distortion. The "
        "camera's flash LED (GPIO 4) fires for every capture, so photos stay consistent while "
        "ambient light varies",
        _tasmota_step(
            "Humidifier plug: an ultrasonic humidifier (inside the chamber or piped in). "
            "Heater/cooler plug: a space heater (outside, aimed at the chamber intake) or a "
            "Peltier cooler (at the chamber wall).",
            "humidifier, and heater or cooler",
        ),
        "Open http://<pi-ip>:3001 — verify all nodes appear on the Dashboard hardware panel",
        "Camera frames should appear in the Vision page within 15 minutes of the camera booting",
    ],
)

# ── Tier 3: All the Things ──────────────────────────────────────

TIER_ALL = HardwareTier(
    id="all_the_things",
    name="All the Things",
    tagline="Full automation. Redundant sensors. Every bell and whistle.",
    estimated_cost="~$960",
    best_for=(
        "Advanced growers running multiple shelves or chambers, commercial-adjacent "
        "operations, and researchers tuning parameters for yield optimization. Ideal "
        "for anyone producing specialty medicinal species, running A/B experiments, "
        "or wanting a second climate node watching high-value crops."
    ),
    species_support=(
        "Everything the Recommended tier supports plus specialty varieties requiring "
        "precise spectral control: Cordyceps militaris (demands blue 450nm), Reishi "
        "(benefits from red 660nm for antler formation), Turkey Tail, Chaga substrate "
        "grows, and experimental cultivars. Dual climate nodes let you run two "
        "different species on separate shelves simultaneously."
    ),
    what_you_get=[
        "Live temperature + humidity + light monitoring on dashboard",
        "Alerts when conditions go out of range",
        "Session tracking with manual observations",
        "Species profile target overlays on gauges",
        "CO2 monitoring — critical for oyster and lion's mane species",
        "Automated FAE fans triggered by CO2 thresholds",
        "Camera vision — contamination detection + growth stage tracking",
        "Claude Vision analysis on demand",
        "Full automation rules engine",
        "Two climate nodes (2 shelves or chambers, or a second opinion on one shelf)",
        "Full 4-spectrum LED lighting (white, blue, red, far-red) for all species",
        "4 smart plugs: humidifier, dehumidifier, heater, Peltier cooler",
        "2 cameras (front + top-down views)",
        "Door reed switch — door-open telemetry + alerts (automation suspension via rules)",
        "Load cell — weight in grams for harvest tracking (once tared + calibrated)",
        "Peristaltic pump for automated hydration / misting between flushes",
        "Weather-predictive automation",
    ],
    capability_groups=[
        CapabilityGroup(
            title="Dual-zone environmental monitoring",
            items=[
                "2x climate nodes — different shelves OR primary + second opinion on one shelf",
                "Per-shelf temperature, humidity, CO2, and light readings",
                "Node-offline alerts if either climate node stops reporting",
                "Door reed switch — debounced open/close events feed alerts + rules",
            ],
        ),
        CapabilityGroup(
            title="Full-spectrum lighting (4 PWM channels)",
            items=[
                "6500K cool white — colonization and general fruiting",
                "450nm blue — Cordyceps fruiting + pinning trigger",
                "660nm red — fruiting enhancement (reishi antler formation, stem elongation)",
                "730nm far-red — morphology control, day/night transitions",
                "Scene presets per species and per phase (colonization/pinning/fruiting)",
            ],
        ),
        CapabilityGroup(
            title="Comprehensive power control (4 smart plugs)",
            items=[
                "Humidifier — on below the phase's humidity minimum, off above its maximum",
                "Dehumidifier — on above the humidity band, off back inside it",
                "Space heater — thermostat rules on the phase's temperature band, safety max-on",
                "Peltier cooler — active cooling for temperature-sensitive species",
                "Per-plug power draw in watts from each plug's HLW8032 meter",
            ],
        ),
        CapabilityGroup(
            title="Advanced automation",
            items=[
                "Peristaltic dosing pump for hydration / misting between flushes (60 s max-on backstop)",
                "Load cell (5kg HX711) — calibrated weight in grams in telemetry",
                "Weather-predictive automation — pre-cools and humidifies ahead of the forecast",
                "Door-open detection — alert events; pair with a rule to pause humidity",
                "Multi-zone rules — different setpoints per shelf",
            ],
        ),
        CapabilityGroup(
            title="Dual-angle vision + AI",
            items=[
                "Front-facing camera at substrate level — pin formation and fruiting bodies",
                "Top-down camera — colonization progress and full-chamber overview",
                "Both views go through Claude Vision contamination analysis",
                "Claude Vision — on-demand detailed species ID and health assessment",
                "Frame gallery and timeline per session",
            ],
        ),
        CapabilityGroup(
            title="Experiment & analytics suite",
            items=[
                "Full metrics history with custom time ranges and downsampling",
                "A/B experiment mode — compare chambers side-by-side",
                "Claude transcript analysis — conditions vs targets, issues, next-run advice",
                "Species yield benchmarks across all your grows",
                "Lineage tracking for culture propagation and genetic experiments",
                "CSV + Markdown + JSON exports for external analysis",
            ],
        ),
    ],
    limitations=[
        "Higher assembly complexity — plan for a weekend build",
        "Requires 12V 10A power supply and more wiring than lower tiers",
        "Far-red 730nm LED strips are specialty items — may require non-Amazon suppliers",
        "The tri-spectrum strip ships from China (~$10 air mail + import duty, not in the estimate)",
        "Peltier coolers have limited capacity — not suitable for large chambers in hot rooms",
    ],
    components=[
        _RPI, _RPI_COOLER, _RPI_SD, _RPI_PSU,
        _for_tier(_ESP32, quantity=6, pack_price="$30",
                  tier_note="This tier: 4 nodes (2 climate, relay, lighting) + 2 spares — the "
                            "pinned 6-pack (B0DSZBH9N9, ~$30) is cheapest."),
        _for_tier(_SHT31, quantity=2),
        _for_tier(_BH1750, quantity=2),
        _for_tier(_SCD41, quantity=2,
                  tier_note="One per climate node for per-shelf CO2 monitoring."),
        _for_tier(_QT_TO_SOCKETS, quantity=2, tier_note="One per climate node."),
        _for_tier(_QT_TO_QT, quantity=4, tier_note="Two per climate node: SHT31-D → SCD41 → BH1750."),
        _for_tier(_IRLZ44N, quantity=8,
                  tier_note="This tier: 8 — 4 relay channels + 4 lighting channels."),
        _for_tier(_100R_RESISTOR, quantity=8, tier_note="This tier: 8 — one per MOSFET gate."),
        _for_tier(_10K_RESISTOR, quantity=9,
                  tier_note="This tier: 9 — 8 gate pull-downs + the reed switch's pull-up."),
        _for_tier(_FLYBACK_DIODE, quantity=4,
                  tier_note="This tier: 4 — the relay node's fans + pump (LED strips are "
                            "resistive)."),
        _SCREW_TERMINALS,
        _DUPONT,
        _NOCTUA,
        _WHITE_STRIP,
        _for_tier(_TRISPECTRUM, quantity=1,
                  tier_note="This tier drives all three wires: BLUE → lighting ch 1 (GPIO 26), "
                            "RED → ch 2 (GPIO 27), GREEN (730 nm far-red) → ch 3 (GPIO 14), "
                            "common → +12V. One physical strip, three channels."),
        Component(
            name="12V Power Supply (10A, 120W) — Facmogu AL-12100",
            role="Power for all 12V devices (fans, LED strips, pump)",
            price_approx="$18",
            url="https://www.amazon.com/dp/B087LY94T6",
            category="power",
            notes="UL-certified 153 x 60 x 33 mm brick, 5.5 x 2.5 mm barrel output (centre +). It "
                  "is Class II (double-insulated): the included 2-prong cord is correct, and a "
                  "3-prong cord adds no ground. power_supply_mount.scad: render -D "
                  "'psu=\"facmogu_10a\"' (PETG). Load budget: keep ≤ ~8 A continuous — the fans "
                  "and pump draw little, the LED strips are the load: cut them to closet length "
                  "(uncut, the white roll + every tri-spectrum channel alone reach ~10 A).",
        ),
        _DC_PIGTAIL,
        _for_tier(_ESP32_CAM, quantity=1,
                  tier_note="This tier: the 2-pack is exactly its two cameras (front + "
                            "top-down), each on its own MB."),
        _for_tier(_USB_C_CABLE, quantity=1,
                  tier_note="This tier: the relay + lighting nodes (outside the chamber) + a spare."),
        _for_tier(_USB_C_CABLE_6FT, quantity=2, tier_note="This tier: both climate nodes (inside the chamber)."),
        _for_tier(_MICRO_USB_CABLE, quantity=1, tier_note="This tier: the 2-pack covers both cameras."),
        _for_tier(_USB_CHARGER, quantity=3,
                  tier_note="This tier: 3 packs = 6 cubes (4 nodes + 2 cameras)."),
        _tasmota_plug(4, "humidifier; dehumidifier; space heater; Peltier cooler"),
        Component(
            name="HX711 Load Cell Amplifier (Adafruit 5974) + 5kg Load Cell (Adafruit 4541)",
            role="Automated harvest weight tracking (enable the scale at provisioning)",
            price_approx="$14",
            url="https://www.adafruit.com/product/5974",
            category="sensor",
            notes="HX711 board $9.95; add the 5 kg bar cell, Adafruit 4541 ($3.95, "
                  "https://www.adafruit.com/product/4541), to the same cart. Leave the board's "
                  "rate switch at 10 SPS. hx711_scale.scad presets: cell=\"bar75\" (default — "
                  "Adafruit 4541 and most generic 75 mm kit bars) or cell=\"tal220\" (80 mm M5/M4 "
                  "bars, e.g. SparkFun SEN-13329, YZC-133 kits); SparkFun SEN-14729 (55 mm "
                  "TAL220B) does NOT fit. Run the 22 AWG 4-conductor cable to the relay node — red "
                  "3.3V, black GND, yellow DOUT → GPIO 32, white SCK → GPIO 33 — tick 'HX711 load-cell scale' under Optional peripherals in its setup "
                  "portal (or send cmd/config {\"peripherals\": {\"hx711\": true}} to a node in "
                  "service), then tare + calibrate once; weight_g rides in telemetry in grams "
                  "after that.",
        ),
        Component(
            name="Magnetic Door Contact (wired alarm reed switch, 2-set)",
            role="Door sensor — door-open telemetry + alerts",
            price_approx="$10",
            url="https://www.amazon.com/dp/B0BX2ZRZ8T",
            category="sensor",
            notes="weideer MC-31B surface-mount contacts with COM / NO / NC screw terminals "
                  "(run two conductors of the 22 AWG 4-conductor cable back to the relay node); "
                  "one set per door, the second is a spare. Use "
                  "COM + the alarm 'NC' terminal — closed while the magnet is present, i.e. "
                  "door shut; check continuity with a meter. COM to GPIO 35, NC to GND, and an "
                  "EXTERNAL 10K pull-up from GPIO 35 to 3V3 (input-only pins 34-39 have no "
                  "internal pulls; the 10K is in the parts list). Magnet on the door, switch on "
                  "the frame; tick 'Door reed switch' under Optional peripherals in the relay "
                  "node's setup portal. Wired to the NO terminal instead? Also tick 'Door "
                  "contact wired on its NO terminal (open with the door shut) — invert' (NVS "
                  "reed_inv; for a node in service send cmd/config {\"peripherals\": "
                  "{\"reed_inv\": true}}), or move the lead to NC. Moulded housing — no printed "
                  "mount needed.",
        ),
        Component(
            name="12V Peristaltic Pump (dosing pump)",
            role="Automated substrate hydration / misting assist between flushes",
            price_approx="$25",
            url="https://www.adafruit.com/product/1150",
            category="actuator",
            notes="Adafruit 1150: 12V DC, ~100 mL/min, Ø27 mm motor, ~72 mm long, flange holes "
                  "Ø2.7 at ~50 mm c-c. The included silicone tubing is NOT food-safe or sterile — "
                  "sterilize, and use FDA-grade silicone tubing for the substrate line. Low "
                  "pressure: suits drip / hydration, may not atomize through a misting nozzle. "
                  "pump_bracket.scad (default pump=\"adafruit_1150\") bolts through the pump's "
                  "flange with M2.5 screws into heat-set inserts; the Kamoer NKP (B07GWJ78FN) "
                  "fits pump=\"kamoer_nkp\". Wire to the relay node's aux channel (GPIO 14) via "
                  "IRLZ44N + flyback diode with 18 AWG leads; aux has a 60 s max-on backstop "
                  "by default.",
        ),
        _SURGE_STRIP_12_USB,
        _WIRE_18AWG,
        _WIRE_22AWG,
        _CABLE_22_4,
        _WAGO,
        _FUSE_HOLDERS,
        _FUSES,
        _FAN_EXTENSIONS,
        _HEAT_SHRINK,
        _ZIP_TIES,
        _ZIP_TIES_DUCT,
        _HOOK_LOOP,
        _GROMMETS,
        _PUMP_TUBING,
        _INSERTS_ASSORTMENT,
        _for_tier(_INSERTS_M25, quantity=1, tier_note="This tier needs 20."),
        _SCREWS_M25,
        _SCREWS_M3X6,
        _SCREWS_KIT,
        _SCREWS_M4,
        _SET_SCREWS_M4,
        _SOLDER,
        _BREADBOARD,
    ],
    wiring=[
        *_climate_chain("ESP32 (Climate #1)", ["SHT31-D #1", "SCD41 #1", "BH1750 #1"]),
        *_climate_chain("ESP32 (Climate #2)", ["SHT31-D #2", "SCD41 #2", "BH1750 #2"]),
        *_relay_rows(
            "Aux channel — peristaltic pump; 10K gate-to-source pull-down; UF4007 across the "
            "pump (cathode to +12V); 60 s max-on backstop by default"
        ),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 14 (aux)", to_device="Peristaltic Pump",
                         to_pin="− lead to IRLZ44N #4 drain (J2 '−'); + lead to +12V",
                         note="UF4007 across the pump; FDA-grade tubing on the substrate line"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="3.3V", to_device="HX711",
                         to_pin="VIN / VCC", note="Load cell amplifier — power (22/4 cable: red)"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GND", to_device="HX711",
                         to_pin="GND", note="Load cell amplifier — ground (22/4 cable: black)"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 32", to_device="HX711",
                         to_pin="DOUT (DATA)", note="Load cell amplifier — data (22/4 cable: yellow)"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 33", to_device="HX711",
                         to_pin="SCK (CLK)", note="Load cell amplifier — clock (22/4 cable: white)"),
        WiringConnection(from_device="Load cell (4 wires)", from_pin="red / black / signal pair",
                         to_device="HX711 terminal block", to_pin="E+ / E− / A− / A+",
                         note="Red to E+, black to E−; swap A−/A+ if weight reads negative"),
        # GPIO 35 is input-only with NO internal pull-up: the pull-up is an
        # external 10K to 3V3, and the switch closes to GND with the door shut.
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 35", to_device="Door contact (reed)",
                         to_pin="COM", note="EXTERNAL 10K pull-up GPIO 35 → 3V3 (input-only pin, no internal pull); "
                         "two conductors of a second 22/4 run"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GND", to_device="Door contact (reed)",
                         to_pin="NC (alarm 'normally closed')",
                         note="Closed with the magnet present (door shut) → GPIO 35 reads LOW"),
        *_lighting_rows(
            "Blue 450nm — BLUE wire of the tri-spectrum strip; strip's common wire to +12V",
            [
                WiringConnection(from_device="ESP32 (Lighting)", from_pin="GPIO 27", to_device="IRLZ44N Gate",
                                 to_pin="via 100R", note="Red 660nm — RED wire of the tri-spectrum strip"),
                WiringConnection(from_device="ESP32 (Lighting)", from_pin="GPIO 14", to_device="IRLZ44N Gate",
                                 to_pin="via 100R",
                                 note="Far-red 730nm — GREEN wire of the tri-spectrum strip (green = far-red)"),
            ],
        ),
        *_power_rows("7.5 A"),
    ],
    wiring_diagram="See docs/wiring-tier3-all-the-things.svg for full wiring diagram with every ESP32 node, load cell, reed switch, pump, and 4-channel lighting.",
    firmware_targets=["node_esp32", "cam"],
    setup_steps=[
        "Set up the Raspberry Pi: flash Raspberry Pi OS (64-bit) with Raspberry Pi Imager — set "
        "the hostname to 'sporeprint' in its advanced options (nodes find the MQTT broker at "
        "sporeprint.local) and enable SSH + WiFi. Fit the Active Cooler before casing the Pi",
        _INSTALL_STEP,
        _WEATHER_STEP + " — this tier's predictive rules need it",
        _print_step(
            "pi_case (default: Pi 5 + Active Cooler); 4 x esp32_case (default preset narrow_usbc "
            "fits the narrow USB-C DevKits — measure 6-pack boards and use devkitc_v4 / "
            "wide_usbc if they are wider); 2 x sensor_mount + 2 x sensor_bracket (defaults; -D "
            "scd30=true on both only for an SCD30); 2 x cam_mount (default); relay_board_mount "
            "twice — -D 'node=\"relay\"' and -D 'node=\"lighting\"' (lighting board in PETG; "
            + _HEATSINK_NOTE + "); power_supply_mount -D 'psu=\"facmogu_10a\"' (PETG); hx711_scale "
            "(defaults cell=\"bar75\" hx_board=\"ada5974\" fit the Adafruit 4541 + 5974; "
            "cell=\"tal220\" for 80 mm TAL220 bars; 5 walls, ≥ 40% infill); pump_bracket "
            "(default pump=\"adafruit_1150\"); fan_duct (default) for each fan you duct."
        ),
        _inserts_step(
            "20 x M2.5 x 5.7, 40 x M3 x 5.7, 16 x M4 x 8.1 and 2 x M5 x 9.5 (3 fan ducts)",
            "16 x M2.5 x 6, 2 x M2.5 x 8, 2 x M2.5 x 10, 36 x M3 x 6, 4 x M3 x 16, 2 x M4 x 16, "
            "2 x M4 x 25, 12 x M4 x 35, 2 x M5 x 16, 4 x M4 x 8 set screws and 4 x M4 DIN 125 "
            "washers",
        ),
        "Wire climate node #1 as a STEMMA QT daisy chain: the Adafruit 4397 cable's female "
        "sockets on the ESP32's 3.3V (red), GND (black), GPIO 21 SDA (blue) and GPIO 22 SCL "
        "(yellow) pins, its QT plug into the SHT31-D; then 4210 QT-QT cables SHT31-D → SCD41 → "
        "BH1750",
        "Wire climate node #2 identically on a second ESP32 — it goes on a different shelf for "
        "per-shelf monitoring",
        "Build the relay switch board on relay_board_mount (node=\"relay\"), per channel: "
        "IRLZ44N, 100 Ω from the J1 IN terminal to the gate, 10K from gate to source, UF4007 "
        "across the J2 load terminals (cathode to +12V), source to the GND bus. Run Dupont "
        "jumpers (female end on the ESP32 pin) from GPIO 25 / 26 / 27 / 14 and a GND pin into "
        "the J1 terminals",
        "Build the lighting switch board the same way (node=\"lighting\") but "
        "WITHOUT diodes — LED strips are resistive: white (GPIO 25), blue (GPIO 26), red (GPIO "
        "27), far-red (GPIO 14)",
        _PLATFORMIO_STEP,
        _flash_nodes_step("the four node boards (and the spares, if you like)"),
        _CAM_FLASH_STEP,
        _mqtt_credential_step("climate-01, climate-02, relay-01, lighting-01, cam-01, cam-02"),
        _portal_step(
            "Node identity is set here, not at flash time: the second climate node logs in as "
            "climate-02 and the top-down camera as cam-02. On the relay node tick 'HX711 "
            "load-cell scale' and 'Door reed switch' under Optional peripherals (nodes already in "
            "service: cmd/config {\"peripherals\": {\"hx711\": true, \"reed\": true}}). The "
            "cameras upload frames to http://<Pi address>:8000.",
            cams=True,
        ),
        "SENSOR PLACEMENT — Climate nodes (SHT31 + SCD41 + BH1750): Mount each set of sensor "
        "boards inside a ventilated sensor enclosure (sensor_mount.scad). Place at CENTER of "
        "growing chamber at SUBSTRATE LEVEL — not near the ceiling where hot air rises. "
        "Temperature and humidity at substrate level are what matter for mushroom growth, not "
        "ambient room temp. For the second climate node, place on a different shelf at the same "
        "height relative to that shelf's substrate. Clip each sensor_bracket onto a wire shelf, "
        "or use its suction cup on glass walls. AVOID placing near heat sources (heaters, "
        "lights), direct airflow (fan output), or dead air zones (corners). CO2 SPECIFIC: the "
        "SCD41 needs air moving around it — the chimney vents are critical. LIGHT SPECIFIC: the "
        "BH1750 looks up through the lid's light window — face it toward the LED strips",
        "RELAY NODE PLACEMENT: Mount both switch boards (relay_board_mount.scad) OUTSIDE the grow "
        "chamber — electronics do not belong in 85-95% RH. Fix them to the outside wall or a "
        "nearby shelf with 4 x M3 x 16 pan-head (or #4 x 3/4\" wood) screws through the corner "
        "feet, or zip ties through the end slots, and bundle the 12V wires with zip ties. Route "
        "wires into the chamber through a small grommeted hole. Keep the MOSFETs ventilated — "
        "they warm up under load",
        "Connect fans to the relay node: FAE fan to channel 0 (GPIO 25), exhaust to channel 1 "
        "(GPIO 26), circulation to channel 2 (GPIO 27)",
        "Connect LED strips to the lighting node: the white strip to ch 0 (GPIO 25). The "
        "tri-spectrum strip's lead has one wire per wavelength — BLUE wire (450 nm) to ch 1 "
        "(GPIO 26), RED wire (660 nm) to ch 2 (GPIO 27), GREEN wire (730 nm far-red) to ch 3 "
        "(GPIO 14), and its common wire to +12V. One physical strip, three channels",
        "CAMERA PLACEMENT: Use BOTH recommended positions for full coverage — (1) FRONT-FACING "
        "camera (cam-01) at substrate level, angled slightly upward to capture pin formation and "
        "fruiting body development. (2) TOP-DOWN camera (cam-02) above the substrate looking "
        "straight down for overall colonization progress. Use cam_mount.scad — suction cup on a "
        "glass door, screws, or zip ties to a shelf rail. Distance: 15-30cm from substrate for "
        "good detail without fish-eye distortion. The camera's flash LED (GPIO 4) fires for every "
        "capture, so photos stay consistent while ambient light varies",
        "Wire the HX711 to the RELAY node's spare GPIOs (DOUT = GPIO 32, SCK = GPIO 33; 3.3V + "
        "GND), load cell red to E+ and black to E−, leave the rate switch at 10 SPS, and mount "
        "the cell in hx711_scale under the grow block. Tare and calibrate once — send "
        "{\"tare\":true}, then {\"calibrate_scale\":<known grams>} as cmd/config (POST "
        "/api/hardware/nodes/relay-01/command with channel \"config\") — keeping the platform still "
        "until the '[CMD] scale tared/calibrated' log line appears; after that weight_g rides in "
        "telemetry in grams",
        "Mount the door contact on the door frame (magnet on the door): COM to GPIO 35, the alarm "
        "'NC' terminal to GND (closed while the door is shut — check with a meter), and an "
        "EXTERNAL 10K pull-up from GPIO 35 to 3V3 (input-only pins 34-39 have no internal "
        "pulls). Wired to NO instead? Tick 'Door contact wired on its NO terminal (open with the "
        "door shut) — invert' in the portal (or send cmd/config {\"peripherals\": "
        "{\"reed_inv\": true}}), or move the lead to NC",
        "Connect the peristaltic pump to the relay node's aux channel (GPIO 14) via IRLZ44N + "
        "UF4007, mounted in pump_bracket with its tube ports pointing up or sideways. Sterilize "
        "the tubing and use FDA-grade silicone on the substrate line; the pump suits drip "
        "hydration better than atomizing nozzles. Aux stops itself after 60 s by default "
        "(raise with cmd/config {\"max_on_sec\": {\"aux\": N}} if you repurpose it)",
        "POWER (12V): 12V 10A PSU → DC barrel pigtail → WAGO 221-413 splits +12V into two "
        "inline fuses — 3 A to the relay board's +12V bus (fans + pump), 7.5 A to the lighting "
        "board's — and a WAGO 221-415 joins the pigtail GND to both boards' GND buses. Every 12V "
        "run is the 18 AWG red/black pair; the ESP32s' GND reaches the same bus through each "
        "board's J1 '−' (common ground). Keep the load ≤ ~8 A: cut the strips to closet length",
        "CABLING: fans reach the relay board through their bundled 30 cm extension + a Noctua "
        "NA-SEC3 (cut the extension's far end: pin 2 → J2 '+', pin 1 → J2 '−'); strips and the "
        "pump get 18 AWG leads; the HX711 and the door contact come back to the relay node on "
        "the 22/4 cable; adhesive heat shrink on every splice and strip joint. Everything "
        "12V/mains stays OUTSIDE the chamber — pass the runs through a grommeted 7/8\" hole (or "
        "the tent's port) and tie them off. The surge strip feeds the Pi PSU, the 12V brick, the "
        "USB cubes and all four smart plugs (its USB-A ports can power the relay and lighting "
        "nodes). Both climate nodes and both cameras get the 6 ft cables; the relay and lighting "
        "nodes the short USB-C ones",
        _tasmota_step(
            "Humidifier plug: an ultrasonic humidifier (inside or piped in via tubing). "
            "Dehumidifier plug: a dehumidifier (outside the chamber, intake facing it). Heater "
            "plug: a space heater (outside, aimed at the chamber intake). Cooler plug: a Peltier "
            "cooler (at the chamber wall).",
            "humidifier, dehumidifier, heater, cooler",
        ),
        "Open http://<pi-ip>:3001 — verify all nodes, cameras, and plugs appear on the Dashboard",
        "Camera frames should appear in the Vision page within 15 minutes. Verify both front and "
        "top-down views are capturing",
    ],
)

# ── All tiers ───────────────────────────────────────────────────

TIERS = [TIER_BARE_BONES, TIER_RECOMMENDED, TIER_ALL]
