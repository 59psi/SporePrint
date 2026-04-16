"""Pre-built hardware integration guides for the 3 SporePrint tiers."""

from .models import Component, WiringConnection, HardwareTier

# ── Shared components ───────────────────────────────────────────

_RPI = Component(
    name="Raspberry Pi 5 (4GB)",
    role="Server — runs SporePrint backend, MQTT broker, and web UI",
    price_approx="$75",
    url="https://www.amazon.com/s?k=raspberry+pi+5+4gb",
    category="controller",
    notes="2GB model works but 4GB recommended. Needs microSD card (32GB+), USB-C power supply (5V 5A). "
          "Alternative: Raspberry Pi 4 (4GB) ~$55 — still available, cheaper.",
)

_RPI_SD = Component(
    name="microSD Card (32GB+)",
    role="Raspberry Pi boot + data storage",
    price_approx="$8",
    url="https://www.amazon.com/s?k=microsd+card+32gb+a1",
    category="misc",
    notes="Class 10 / A1 rated minimum. 64GB recommended for vision frame storage.",
)

_RPI_PSU = Component(
    name="USB-C Power Supply (5V 5A)",
    role="Raspberry Pi power",
    price_approx="$12",
    url="https://www.amazon.com/s?k=raspberry+pi+5+power+supply+27w",
    category="power",
    notes="Official Raspberry Pi 27W PSU recommended for Pi 5 stability. "
          "Alternative: any USB-C PD supply (5V 5A). Pi 4 users can use 5V 3A.",
)

_ESP32 = Component(
    name="ESP32-S3 DevKit",
    role="Microcontroller for sensor/actuator nodes",
    price_approx="$8",
    url="https://www.amazon.com/s?k=esp32-s3+devkit",
    category="controller",
    notes="USB-C, more GPIO, better WiFi. Runs the same firmware as classic ESP32. "
          "Alternative: ESP32-WROOM-32 DevKit (~$6) — classic, widely available, works identically.",
)

_SHT31 = Component(
    name="SHT31-D Sensor Breakout",
    role="Temperature + humidity sensor (I2C, 0x44)",
    price_approx="$7",
    url="https://www.amazon.com/s?k=sht31+sensor+breakout",
    category="sensor",
    notes="Accuracy: +/-0.3C, +/-2% RH. I2C address 0x44.",
)

_BH1750 = Component(
    name="BH1750 Light Sensor Breakout",
    role="Ambient light level sensor (I2C, 0x23)",
    price_approx="$4",
    url="https://www.amazon.com/s?k=bh1750+light+sensor",
    category="sensor",
    notes="Measures 1-65535 lux. I2C address 0x23.",
)

_SCD41 = Component(
    name="SCD41 CO2 Sensor Breakout",
    role="CO2, temperature, humidity sensor (I2C, 0x62)",
    price_approx="$45",
    url="https://www.amazon.com/s?k=SCD41+CO2+sensor+module",
    category="sensor",
    notes="True NDIR CO2 sensor. 400-5000ppm range. Needs 5min warm-up. I2C 0x62. "
          "Same pinout as SCD40 — drop-in replacement with better accuracy. "
          "Also available at Pimoroni (pimoroni.com, ships from UK) and Newark Electronics. "
          "Adafruit (product 5190) has 24-week backorder — avoid. "
          "Budget alternative: MH-Z19B (~$15, UART interface, different wiring).",
)

_IRLZ44N = Component(
    name="IRLZ44N N-Channel MOSFET",
    role="Logic-level power switching for fans/LEDs",
    price_approx="$1",
    url="https://www.amazon.com/s?k=IRLZ44N+mosfet",
    category="actuator",
    notes="Logic-level gate (3.3V compatible). 55V, 47A max. Rds(on) ~22mOhm.",
)

_1N4007 = Component(
    name="1N4007 Diode",
    role="Flyback protection for inductive loads (fans, solenoids)",
    price_approx="$0.10",
    url="https://www.amazon.com/s?k=1N4007+diode",
    category="misc",
    notes="Place reverse-biased across each fan/motor. Protects MOSFET from voltage spikes.",
)

_10K_RESISTOR = Component(
    name="10K Ohm Resistor",
    role="Gate pull-down — keeps MOSFET off when ESP32 boots",
    price_approx="$0.05",
    url="https://www.amazon.com/s?k=10k+ohm+resistor",
    category="misc",
    notes="One per MOSFET channel. Gate-to-GND pull-down.",
)

_ESP32_CAM = Component(
    name="ESP32-S3 CAM (OV5640)",
    role="Camera node — captures images for contamination detection + growth tracking",
    price_approx="$12",
    url="https://www.amazon.com/s?k=ESP32-S3+CAM+OV5640",
    category="controller",
    notes="USB-C, no separate programmer needed. 5MP OV5640 camera. "
          "Also available at Seeed Studio (XIAO ESP32S3 Sense) and Walmart. "
          "Alternative: ESP32-CAM AI-Thinker (OV2640) (~$8) — needs UART programmer, 2MP.",
)

_FTDI = Component(
    name="USB-to-UART Programmer (CP2102/CH340)",
    role="Flash firmware to ESP32-CAM (no built-in USB)",
    price_approx="$4",
    url="https://www.amazon.com/s?k=cp2102+usb+uart+programmer",
    category="misc",
    notes="Only needed if using classic ESP32-CAM AI-Thinker. "
          "ESP32-S3 CAM has built-in USB — no programmer needed.",
)


def _tasmota_plug(role: str) -> Component:
    return Component(
        name="Athom Tasmota Smart Plug (US/EU)",
        role=f"Smart plug — {role}",
        price_approx="$10",
        url="https://www.athom.tech/blank-1/tasmota-us-plug-v2",
        category="plug",
        notes="Pre-flashed with Tasmota firmware. MQTT ready out of the box. "
              "Power monitoring via HLW8032. No cloud required. "
              "Available in US/EU/UK/AU variants from athom.tech. "
              "Also available on AliExpress and Tindie.",
    )


# ── Tier 1: Bare Bones ─────────────────────────────────────────

TIER_BARE_BONES = HardwareTier(
    id="bare_bones",
    name="Bare Bones",
    tagline="Monitor your grow. Smart plug for humidifier.",
    estimated_cost="~$115",
    what_you_get=[
        "Live temperature + humidity + light monitoring on dashboard",
        "Alerts when conditions go out of range",
        "Smart plug control for humidifier (on/off via app)",
        "Session tracking with manual observations",
        "Species profile target overlays on gauges",
    ],
    components=[
        _RPI, _RPI_SD, _RPI_PSU,
        _ESP32,
        _SHT31,
        _BH1750,
        Component(
            name="Jumper Wires (M-F, 20cm)",
            role="Connect sensors to ESP32",
            price_approx="$4",
            url="https://www.amazon.com/s?k=jumper+wires+male+female+20cm",
            category="misc",
            notes="Need at least 8 wires: 2x VCC, 2x GND, 2x SDA, 2x SCL.",
        ),
        Component(
            name="USB-C Cable",
            role="Power + programming for ESP32-S3",
            price_approx="$3",
            url="https://www.amazon.com/s?k=usb-c+cable+short",
            category="power",
            notes="ESP32-S3 uses USB-C. If using classic ESP32, use micro-USB instead.",
        ),
        Component(
            name="USB Power Supply (5V 2A)",
            role="ESP32 power",
            price_approx="$5",
            url="https://www.amazon.com/s?k=usb+power+supply+5v+2a",
            category="power",
        ),
        _tasmota_plug("Humidifier on/off"),
    ],
    wiring=[
        WiringConnection(from_device="ESP32", from_pin="3.3V", to_device="SHT31-D", to_pin="VIN"),
        WiringConnection(from_device="ESP32", from_pin="GND", to_device="SHT31-D", to_pin="GND"),
        WiringConnection(from_device="ESP32", from_pin="GPIO 21 (SDA)", to_device="SHT31-D", to_pin="SDA"),
        WiringConnection(from_device="ESP32", from_pin="GPIO 22 (SCL)", to_device="SHT31-D", to_pin="SCL"),
        WiringConnection(from_device="ESP32", from_pin="3.3V", to_device="BH1750", to_pin="VCC"),
        WiringConnection(from_device="ESP32", from_pin="GND", to_device="BH1750", to_pin="GND"),
        WiringConnection(from_device="ESP32", from_pin="GPIO 21 (SDA)", to_device="BH1750", to_pin="SDA", note="shared I2C bus"),
        WiringConnection(from_device="ESP32", from_pin="GPIO 22 (SCL)", to_device="BH1750", to_pin="SCL", note="shared I2C bus"),
    ],
    wiring_diagram="""\
  ESP32-S3 DevKit                SHT31-D          BH1750
 ┌──────────────────┐       ┌──────────┐     ┌──────────┐
 │              3.3V ├───┬───┤ VIN      │  ┌──┤ VCC      │
 │               GND ├───┼───┤ GND      │  │  ├──────────┤
 │                   │   │   ├──────────┤  │  │ GND ─────┼── GND (shared)
 │  GPIO 21 (SDA) ──├───┼───┤ SDA      │──┼──┤ SDA      │
 │  GPIO 22 (SCL) ──├───┼───┤ SCL      │──┼──┤ SCL      │
 │                   │   │   └──────────┘  │  └──────────┘
 │                   │   └─────────────────┘
 └──────────────────┘

 I2C Bus: Both sensors share SDA (GPIO 21) and SCL (GPIO 22)
 SHT31-D address: 0x44  |  BH1750 address: 0x23

 Power: ESP32 via USB (5V), sensors from 3.3V pin""",
    firmware_targets=["climate_node"],
    setup_steps=[
        "Set up Raspberry Pi: install Raspberry Pi OS, run setup.sh",
        "Wire SHT31-D and BH1750 to ESP32 per diagram above (shared I2C bus)",
        "Install PlatformIO: pip install platformio",
        "Flash climate_node firmware: cd firmware && pio run -t upload -e climate_node",
        "ESP32 creates 'SporePrint-Setup' WiFi AP on first boot — connect and enter your WiFi credentials",
        "Set up Athom Tasmota Plug: power on — it creates a WiFi AP named 'tasmota-XXXX'. "
        "Connect to the AP, open 192.168.4.1, enter your WiFi credentials. "
        "In Tasmota web UI: Configuration → MQTT → set Host to your Pi's IP, Port 1883",
        "Start SporePrint: docker compose up -d (or run dev servers manually)",
        "Open http://<pi-ip>:3001 — you should see live sensor data on the dashboard",
    ],
)

# ── Tier 2: Recommended ────────────────────────────────────────

TIER_RECOMMENDED = HardwareTier(
    id="recommended",
    name="Recommended",
    tagline="Full monitoring + automated fans, lights, and vision.",
    estimated_cost="~$220",
    what_you_get=[
        "Everything in Bare Bones, plus:",
        "CO2 monitoring — critical for oyster and lion's mane species",
        "Automated FAE fans triggered by CO2 thresholds",
        "Multi-spectrum LED lighting with scene presets (colonization, fruiting, cordyceps blue)",
        "Camera vision — contamination detection + growth stage tracking",
        "Claude Vision analysis on demand",
        "Automated humidity control via smart plug",
        "Full automation rules engine",
    ],
    components=[
        _RPI, _RPI_SD, _RPI_PSU,
        Component(**{**_ESP32.model_dump(), "quantity": 3, "notes": "3 ESP32s: climate, relay, lighting nodes"}),
        _SHT31,
        _BH1750,
        _SCD41,
        Component(**{**_IRLZ44N.model_dump(), "quantity": 4, "notes": "4 MOSFETs for relay node (FAE, exhaust, circulation, aux)"}),
        Component(**{**_1N4007.model_dump(), "quantity": 8, "notes": "4 for relay node + 4 for lighting node flyback protection"}),
        Component(**{**_10K_RESISTOR.model_dump(), "quantity": 8, "notes": "4 for relay + 4 for lighting gate pull-downs"}),
        Component(
            name="Noctua NF-A8 5V PWM Fan (80mm)",
            role="FAE / exhaust / circulation fans",
            quantity=3,
            price_approx="$14",
            url="https://www.amazon.com/s?k=noctua+nf-a8+5v+pwm",
            category="actuator",
            notes="Quiet, PWM controllable, 5V version. Use 12V fans with 12V supply for stronger airflow. "
                  "Alternative: Arctic P8 PWM (~$8) — cheaper, noisier.",
        ),
        Component(
            name="12V LED Strip - Cool White (6500K), 1m",
            role="General fruiting/pinning light",
            price_approx="$8",
            url="https://www.amazon.com/s?k=12v+led+strip+6500k+1m",
            category="actuator",
            notes="Cut to length. Connect to lighting node white channel.",
        ),
        Component(
            name="12V LED Strip - Blue (450nm), 1m",
            role="Cordyceps fruiting + pinning trigger",
            price_approx="$8",
            url="https://www.amazon.com/s?k=12v+blue+led+strip+450nm+1m",
            category="actuator",
            notes="Critical for Cordyceps militaris. Also benefits pinning in other species.",
        ),
        Component(
            name="12V Power Supply (5A, 60W)",
            role="Power for LED strips and 12V fans",
            price_approx="$12",
            url="https://www.amazon.com/s?k=12v+5a+power+supply+60w",
            category="power",
            notes="Barrel jack or screw terminal. 5A supports ~4 LED strips + fans.",
        ),
        _ESP32_CAM,
        _FTDI,
        _tasmota_plug("Humidifier on/off"),
        _tasmota_plug("Heater or cooler on/off"),
        Component(
            name="Breadboard + Jumper Wire Kit",
            role="Prototyping connections",
            price_approx="$8",
            url="https://www.amazon.com/s?k=breadboard+jumper+wire+kit",
            category="misc",
        ),
    ],
    wiring=[
        # Climate node (same as Tier 1 + SCD41)
        WiringConnection(from_device="ESP32 (Climate)", from_pin="3.3V", to_device="SHT31-D", to_pin="VIN"),
        WiringConnection(from_device="ESP32 (Climate)", from_pin="GND", to_device="SHT31-D", to_pin="GND"),
        WiringConnection(from_device="ESP32 (Climate)", from_pin="GPIO 21 (SDA)", to_device="SHT31-D / SCD41 / BH1750", to_pin="SDA (shared I2C)"),
        WiringConnection(from_device="ESP32 (Climate)", from_pin="GPIO 22 (SCL)", to_device="SHT31-D / SCD41 / BH1750", to_pin="SCL (shared I2C)"),
        # Relay node
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 25", to_device="IRLZ44N #1 Gate", to_pin="via 100R resistor", note="FAE fan"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 26", to_device="IRLZ44N #2 Gate", to_pin="via 100R resistor", note="Exhaust fan"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 27", to_device="IRLZ44N #3 Gate", to_pin="via 100R resistor", note="Circulation fan"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 14", to_device="IRLZ44N #4 Gate", to_pin="via 100R resistor", note="Aux channel"),
        # Lighting node
        WiringConnection(from_device="ESP32 (Lighting)", from_pin="GPIO 25", to_device="IRLZ44N Gate", to_pin="via 100R", note="White 6500K strip"),
        WiringConnection(from_device="ESP32 (Lighting)", from_pin="GPIO 26", to_device="IRLZ44N Gate", to_pin="via 100R", note="Blue 450nm strip"),
    ],
    wiring_diagram="""\
 === CLIMATE NODE (I2C sensor hub) ===

  ESP32 (Climate)           SHT31-D    SCD41     BH1750
 ┌───────────────┐       ┌────────┐ ┌────────┐ ┌────────┐
 │          3.3V ├───┬───┤ VIN    │ │ VIN ───┼─┤ VCC    │
 │           GND ├───┼───┤ GND    │ │ GND ───┼─┤ GND    │
 │  GPIO 21 SDA ─├───┼───┤ SDA    │ │ SDA ───┼─┤ SDA    │
 │  GPIO 22 SCL ─├───┼───┤ SCL    │ │ SCL ───┼─┤ SCL    │
 └───────────────┘   │   └────────┘ └────────┘ └────────┘
 Addresses: SHT31=0x44, SCD41=0x62, BH1750=0x23

 === RELAY NODE (MOSFET fan control, 1 of 4 channels shown) ===

                    10K pull-down
  ESP32 (Relay)        │
 ┌───────────────┐     │     IRLZ44N         12V Fan
 │  GPIO 25 ─────├──100R──┤ Gate              ┌─────────┐
 │               │         │ Drain ────────────┤ -       │
 │           GND ├─────────┤ Source ──── GND   │ +  ─────┼── +12V
 └───────────────┘         └───────┘           └─────────┘
                                          ┌──── 1N4007 ────┐
                                          │ (flyback diode) │
                                       Fan -             Fan +

 Repeat for GPIO 26 (exhaust), 27 (circulation), 14 (aux)

 === LIGHTING NODE (MOSFET LED dimming, 10-bit PWM) ===

  ESP32 (Lighting)   10K     IRLZ44N         12V LED Strip
 ┌───────────────┐    │
 │  GPIO 25 ─────├─100R──┤ Gate              ┌─────────────┐
 │               │        │ Drain ────────────┤ - (white)   │
 │           GND ├────────┤ Source ─── GND    │ +  ─────────┼── +12V
 └───────────────┘        └───────┘           └─────────────┘

 Repeat for GPIO 26 (blue 450nm), 27 (red 660nm), 14 (far-red 730nm)

 === CAMERA NODE (ESP32-S3 CAM — USB-C, no programmer needed) ===

  ESP32-S3 CAM
 ┌──────────────┐
 │  USB-C ──────├── computer (flash) or 5V power
 │  OV5640 cam  │
 └──────────────┘
 Flash via USB-C: pio run -t upload -e cam_node
 No GPIO 0 jumper or UART programmer required.
 Camera auto-captures every 15min and POSTs to SporePrint server.

 (If using classic ESP32-CAM AI-Thinker: needs USB-UART programmer,
  connect TX→RX, RX→TX, GND→GND, hold GPIO 0 to GND during flash)""",
    firmware_targets=["climate_node", "relay_node", "lighting_node", "cam_node"],
    setup_steps=[
        "Set up Raspberry Pi with SporePrint (same as Bare Bones steps 1)",
        "Wire climate node: SHT31-D + SCD41 + BH1750 on shared I2C bus per diagram",
        "Wire relay node: 4x IRLZ44N MOSFETs with pull-down resistors and flyback diodes per diagram",
        "Wire lighting node: same MOSFET pattern for LED strip channels",
        "Flash all 4 firmwares: pio run -t upload -e climate_node (repeat for relay_node, lighting_node, cam_node)",
        "Flash ESP32-S3 CAM: connect via USB-C, flash cam_node firmware (no programmer needed)",
        "Connect fans to relay node: FAE fan → channel 0 (GPIO 25), exhaust → channel 1 (GPIO 26), circulation → channel 2 (GPIO 27)",
        "Connect LED strips to lighting node: white → channel 0, blue → channel 1",
        "Power 12V devices from the 12V PSU. ESP32s powered via USB.",
        "Set up Athom Tasmota Plugs: power on each plug — connect to 'tasmota-XXXX' AP, "
        "open 192.168.4.1, enter WiFi credentials. In Tasmota web UI: Configuration → MQTT → "
        "set Host to Pi's IP, Port 1883. Assign roles in SporePrint settings",
        "Start SporePrint: docker compose up -d",
        "Verify all nodes appear on Dashboard hardware panel. Camera frames should appear in Vision page within 15 min.",
    ],
)

# ── Tier 3: All the Things ──────────────────────────────────────

TIER_ALL = HardwareTier(
    id="all_the_things",
    name="All the Things",
    tagline="Full automation. Redundant sensors. Every bell and whistle.",
    estimated_cost="~$370+",
    what_you_get=[
        "Everything in Recommended, plus:",
        "Redundant climate monitoring (2 nodes — different shelves or backup)",
        "Full 4-spectrum LED lighting (white, blue, red, far-red) for all species",
        "4 smart plugs: humidifier, dehumidifier, heater, Peltier cooler",
        "2 cameras (front + top-down views)",
        "Door reed switch — pauses humidity when closet opens",
        "Load cell for automated harvest weight tracking",
        "Peristaltic pump for automated misting between flushes",
        "Weather-predictive automation",
    ],
    components=[
        _RPI, _RPI_SD, _RPI_PSU,
        Component(**{**_ESP32.model_dump(), "quantity": 5, "notes": "2 climate + 1 relay + 1 lighting + 1 spare"}),
        Component(**{**_SHT31.model_dump(), "quantity": 2}),
        Component(**{**_BH1750.model_dump(), "quantity": 2}),
        Component(**{**_SCD41.model_dump(), "quantity": 2, "notes": "One per climate node for per-shelf CO2 monitoring"}),
        Component(**{**_IRLZ44N.model_dump(), "quantity": 8, "notes": "4 relay + 4 lighting channels"}),
        Component(**{**_1N4007.model_dump(), "quantity": 8}),
        Component(**{**_10K_RESISTOR.model_dump(), "quantity": 8}),
        Component(
            name="Noctua NF-A8 5V PWM Fan (80mm)",
            role="FAE / exhaust / circulation fans",
            quantity=3,
            price_approx="$14",
            url="https://www.amazon.com/s?k=noctua+nf-a8+5v+pwm",
            category="actuator",
            notes="Alternative: Arctic P8 PWM (~$8) — cheaper, noisier.",
        ),
        Component(name="12V LED Strip - Cool White (6500K), 2m", role="General light", price_approx="$12", url="https://www.amazon.com/s?k=12v+led+strip+6500k+2m", category="actuator"),
        Component(name="12V LED Strip - Blue (450nm), 1m", role="Cordyceps + pinning", price_approx="$8", url="https://www.amazon.com/s?k=12v+blue+led+strip+450nm+1m", category="actuator"),
        Component(name="12V LED Strip - Red (660nm), 1m", role="Fruiting enhancement", price_approx="$8", url="https://www.amazon.com/s?k=12v+red+led+strip+660nm+1m", category="actuator"),
        Component(name="12V LED Strip - Far Red (730nm), 1m", role="Morphology control", price_approx="$12", url="https://www.amazon.com/s?k=12v+far+red+led+strip+730nm", category="actuator"),
        Component(name="12V Power Supply (10A, 120W)", role="Power for all 12V devices", price_approx="$18", url="https://www.amazon.com/s?k=12v+10a+power+supply+120w", category="power"),
        Component(**{**_ESP32_CAM.model_dump(), "quantity": 2, "notes": "Front view + top-down view"}),
        _FTDI,
        _tasmota_plug("Humidifier"),
        _tasmota_plug("Dehumidifier"),
        _tasmota_plug("Space heater"),
        _tasmota_plug("Peltier cooler"),
        Component(
            name="HX711 Load Cell Amplifier + 5kg Load Cell",
            role="Automated harvest weight tracking",
            price_approx="$8",
            url="https://www.amazon.com/s?k=hx711+load+cell+5kg",
            category="sensor",
            notes="Wire to relay node aux channel (GPIO 14). HX711 uses 2 GPIO pins (DOUT + SCK). "
                  "Place under grow block to track water loss and harvest weight.",
        ),
        Component(
            name="Reed Switch (magnetic, normally open)",
            role="Door sensor — pauses humidity when closet opens",
            price_approx="$3",
            url="https://www.amazon.com/s?k=magnetic+reed+switch+normally+open",
            category="sensor",
            notes="Mount on closet door frame. Wire to any ESP32 GPIO with internal pull-up. "
                  "Magnet on door, switch on frame.",
        ),
        Component(
            name="12V Peristaltic Pump (dosing pump)",
            role="Automated misting / substrate hydration between flushes",
            price_approx="$12",
            url="https://www.amazon.com/s?k=12v+peristaltic+pump+dosing",
            category="actuator",
            notes="12V DC, ~100mL/min flow rate. Connect to relay node aux channel. "
                  "Use food-safe silicone tubing.",
        ),
        Component(
            name="Breadboard + Jumper Wire Kit",
            role="Prototyping connections (or solder to perfboard)",
            price_approx="$8",
            url="https://www.amazon.com/s?k=breadboard+jumper+wire+kit",
            category="misc",
        ),
    ],
    wiring=[
        *TIER_RECOMMENDED.wiring,
        WiringConnection(from_device="ESP32 (Climate #2)", from_pin="GPIO 21/22", to_device="SHT31-D #2 / SCD41 #2 / BH1750 #2", to_pin="Shared I2C", note="Second shelf"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 14 (aux)", to_device="Peristaltic Pump", to_pin="Via IRLZ44N + flyback diode"),
        WiringConnection(from_device="Any ESP32 GPIO", from_pin="GPIO (INPUT_PULLUP)", to_device="Reed Switch", to_pin="One leg to GPIO, other to GND"),
    ],
    wiring_diagram="""\
 Same as Recommended tier wiring, plus:

 === SECOND CLIMATE NODE (clone of first, different shelf) ===
 Wire identically to first climate node. Set different node_id via MQTT config.

 === LOAD CELL (HX711) ===

  ESP32 (Relay)            HX711 Board         Load Cell
 ┌───────────────┐       ┌───────────┐       ┌──────────┐
 │  GPIO 32 ─────├───────┤ DOUT      │       │  Red ────┼─┤ E+
 │  GPIO 33 ─────├───────┤ SCK       │       │  Black ──┼─┤ E-
 │          3.3V ├───────┤ VCC       │       │  White ──┼─┤ A-
 │           GND ├───────┤ GND       │       │  Green ──┼─┤ A+
 └───────────────┘       └───────────┘       └──────────┘

 === DOOR REED SWITCH ===

  Any ESP32 GPIO (INPUT_PULLUP)
 ┌──────────┐
 │  GPIO XX ├──────┤ Reed Switch ├────── GND
 └──────────┘
 (Magnet on door, switch on frame. GPIO reads LOW when door closed, HIGH when open)

 === PERISTALTIC PUMP (via relay node aux channel) ===

  Same MOSFET circuit as fans (GPIO 14, aux channel).
  Connect pump +12V and GND through IRLZ44N drain/source.
  Add flyback diode across pump terminals.""",
    firmware_targets=["climate_node", "relay_node", "lighting_node", "cam_node"],
    setup_steps=[
        "Complete all Recommended tier setup steps first",
        "Wire second climate node identically — flash with different node_id (climate-02)",
        "Add red (660nm) and far-red (730nm) LED strips to lighting node channels 2 and 3",
        "Set up all 4 Athom Tasmota Plugs with MQTT — for each plug: connect to 'tasmota-XXXX' AP, "
        "open 192.168.4.1, enter WiFi, then Configuration → MQTT → Host = Pi IP, Port 1883. "
        "Assign roles: humidifier, dehumidifier, heater, cooler",
        "Mount second ESP32-CAM for top-down view — configure with node_id cam-02",
        "Wire HX711 load cell to relay node spare GPIOs (32, 33) — place cell under grow block",
        "Mount reed switch on closet door frame — wire to any ESP32 GPIO with INPUT_PULLUP",
        "Connect peristaltic pump to relay node aux channel (GPIO 14) — run food-safe tubing to misting nozzle",
        "Configure weather: set SPOREPRINT_WEATHER_LAT and _LON in .env for predictive automation",
        "Verify all nodes, cameras, and plugs appear in SporePrint dashboard",
    ],
)

# ── All tiers ───────────────────────────────────────────────────

TIERS = [TIER_BARE_BONES, TIER_RECOMMENDED, TIER_ALL]
