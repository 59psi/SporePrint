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
          "Alternative: Raspberry Pi 4 (4GB) ~$55 — still available, cheaper. "
          "Also: canakit.com, thepihut.com, pishop.us. Check rpilocator.com for real-time stock.",
)

_RPI_SD = Component(
    name="microSD Card (32GB+)",
    role="Raspberry Pi boot + data storage",
    price_approx="$8",
    url="https://www.amazon.com/s?k=microsd+card+32gb+a1",
    category="misc",
    notes="Class 10 / A1 rated minimum. 64GB recommended for vision frame storage. "
          "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
)

_RPI_PSU = Component(
    name="USB-C Power Supply (5V 5A)",
    role="Raspberry Pi power",
    price_approx="$12",
    url="https://www.amazon.com/s?k=raspberry+pi+5+power+supply+27w",
    category="power",
    notes="Official Raspberry Pi 27W PSU recommended for Pi 5 stability. "
          "Alternative: any USB-C PD supply (5V 5A). Pi 4 users can use 5V 3A. "
          "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
)

_ESP32 = Component(
    name="ESP32-S3 DevKit",
    role="Microcontroller for sensor/actuator nodes",
    price_approx="$8",
    url="https://www.amazon.com/s?k=esp32-s3+devkit",
    category="controller",
    notes="USB-C, more GPIO, better WiFi. Runs the same firmware as classic ESP32. "
          "Alternative: ESP32-WROOM-32 DevKit (~$6) — classic, widely available, works identically. "
          "Also: digikey.com, aliexpress.com (search ESP32-S3-DevKitC-1). Official: espressif.com/devkits",
)

_SHT31 = Component(
    name="SHT31-D Sensor Breakout",
    role="Temperature + humidity sensor (I2C, 0x44)",
    price_approx="$7",
    url="https://www.amazon.com/s?k=sht31+sensor+breakout",
    category="sensor",
    notes="Accuracy: +/-0.3C, +/-2% RH. I2C address 0x44. "
          "Also: adafruit.com/product/2857, dfrobot.com. Multiple Amazon sellers (HiLetgo, Adafruit).",
)

_BH1750 = Component(
    name="BH1750 Light Sensor Breakout",
    role="Ambient light level sensor (I2C, 0x23)",
    price_approx="$4",
    url="https://www.amazon.com/s?k=bh1750+light+sensor",
    category="sensor",
    notes="Measures 1-65535 lux. I2C address 0x23. "
          "Also: adafruit.com/product/4681, dfrobot.com/product-531.html, thepihut.com",
)

_SCD41 = Component(
    name="SCD41 CO2 Sensor Breakout",
    role="CO2, temperature, humidity sensor (I2C, 0x62)",
    price_approx="$45",
    url="https://www.amazon.com/s?k=SCD41+CO2+sensor+module",
    category="sensor",
    notes="True NDIR CO2 sensor. 400-5000ppm range. Needs 5min warm-up. I2C 0x62. "
          "Same pinout as SCD40 — drop-in replacement with better accuracy. "
          "Budget alternative: MH-Z19B (~$15, UART interface, different wiring). "
          "Also: shop.pimoroni.com (in stock), newark.com, sparkfun.com. Avoid Adafruit (24-week backorder).",
)

_IRLZ44N = Component(
    name="IRLZ44N N-Channel MOSFET",
    role="Logic-level power switching for fans/LEDs",
    price_approx="$1",
    url="https://www.amazon.com/s?k=IRLZ44N+mosfet",
    category="actuator",
    notes="Logic-level gate (3.3V compatible). 55V, 47A max. Rds(on) ~22mOhm. "
          "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
)

_1N4007 = Component(
    name="1N4007 Diode",
    role="Flyback protection for inductive loads (fans, solenoids)",
    price_approx="$0.10",
    url="https://www.amazon.com/s?k=1N4007+diode",
    category="misc",
    notes="Place reverse-biased across each fan/motor. Protects MOSFET from voltage spikes. "
          "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
)

_10K_RESISTOR = Component(
    name="10K Ohm Resistor",
    role="Gate pull-down — keeps MOSFET off when ESP32 boots",
    price_approx="$0.05",
    url="https://www.amazon.com/s?k=10k+ohm+resistor",
    category="misc",
    notes="One per MOSFET channel. Gate-to-GND pull-down. "
          "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
)

_ESP32_CAM = Component(
    name="ESP32-S3 CAM (OV5640)",
    role="Camera node — captures images for contamination detection + growth tracking",
    price_approx="$12",
    url="https://www.amazon.com/s?k=ESP32-S3+CAM+OV5640",
    category="controller",
    notes="USB-C, no separate programmer needed. 5MP OV5640 camera. "
          "Alternative: ESP32-CAM AI-Thinker (OV2640) (~$8) — needs UART programmer, 2MP. "
          "Also: seeedstudio.com (XIAO ESP32S3 Sense with OV5640), walmart.com, ebay.com",
)

_FTDI = Component(
    name="USB-to-UART Programmer (CP2102/CH340)",
    role="Flash firmware to ESP32-CAM (no built-in USB)",
    price_approx="$4",
    url="https://www.amazon.com/s?k=cp2102+usb+uart+programmer",
    category="misc",
    notes="Only needed if using classic ESP32-CAM AI-Thinker. "
          "ESP32-S3 CAM has built-in USB — no programmer needed. "
          "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
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
              "Also: tindie.com/products/athom/pre-flashed-tasmota-us-plug/, aliexpress.com (search 'athom tasmota plug'). US/EU/UK/AU variants available.",
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
            notes="Need at least 8 wires: 2x VCC, 2x GND, 2x SDA, 2x SCL. "
                  "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
        ),
        Component(
            name="USB-C Cable",
            role="Power + programming for ESP32-S3",
            price_approx="$3",
            url="https://www.amazon.com/s?k=usb-c+cable+short",
            category="power",
            notes="ESP32-S3 uses USB-C. If using classic ESP32, use micro-USB instead. "
                  "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
        ),
        Component(
            name="USB Power Supply (5V 2A)",
            role="ESP32 power",
            price_approx="$5",
            url="https://www.amazon.com/s?k=usb+power+supply+5v+2a",
            category="power",
            notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
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
    wiring_diagram="See docs/wiring-tier1-bare-bones.svg for full wiring diagram with color-coded signal, I2C, power, and ground lines.",
    firmware_targets=["climate_node"],
    setup_steps=[
        "Set up Raspberry Pi: install Raspberry Pi OS, run setup.sh",
        "Wire SHT31-D and BH1750 to ESP32 per diagram above (shared I2C bus)",
        "Install PlatformIO: pip install platformio",
        "Flash climate_node firmware: cd firmware && pio run -t upload -e climate_node",
        "ESP32 creates 'SporePrint-Setup' WiFi AP on first boot — connect and enter your WiFi credentials",
        "SENSOR PLACEMENT — Climate node (SHT31 + BH1750): Mount the sensor board inside the "
        "ventilated sensor enclosure (sensor_mount.scad). Place at CENTER of growing chamber at "
        "SUBSTRATE LEVEL — not near the ceiling where hot air rises. Temperature and humidity at "
        "substrate level are what matter for mushroom growth, not ambient room temp. Attach to shelf "
        "with zip ties (thread through the side slots) or use the suction cup mount on back for glass "
        "walls. AVOID placing near heat sources (heaters, lights), direct airflow (fan output), or "
        "dead air zones (corners). BH1750 light sensor should face the light source — mount with the "
        "sensor chip facing the LED strips, not the floor",
        "SMART PLUG PLACEMENT — Athom Tasmota plug: plug into an accessible outlet OUTSIDE the chamber. "
        "Connect your humidifier (ultrasonic, placed inside chamber or piped in via tubing). "
        "Set up plug: power on — it creates a WiFi AP named 'tasmota-XXXX'. "
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
                  "Alternative: Arctic P8 PWM (~$8). "
                  "Also: newegg.com, walmart.com, noctua.at/buy. Alternative: Arctic P8 PWM (~$8).",
        ),
        Component(
            name="12V LED Strip - Cool White (6500K), 1m",
            role="General fruiting/pinning light",
            price_approx="$8",
            url="https://www.amazon.com/s?k=12v+led+strip+6500k+1m",
            category="actuator",
            notes="Cut to length. Connect to lighting node white channel. "
                  "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
        ),
        Component(
            name="12V LED Strip - Blue (450nm), 1m",
            role="Cordyceps fruiting + pinning trigger",
            price_approx="$8",
            url="https://www.amazon.com/s?k=12v+blue+led+strip+450nm+1m",
            category="actuator",
            notes="Critical for Cordyceps militaris. Also benefits pinning in other species. "
                  "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
        ),
        Component(
            name="12V Power Supply (5A, 60W)",
            role="Power for LED strips and 12V fans",
            price_approx="$12",
            url="https://www.amazon.com/s?k=12v+5a+power+supply+60w",
            category="power",
            notes="Barrel jack or screw terminal. 5A supports ~4 LED strips + fans. "
                  "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
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
            notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
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
    wiring_diagram="See docs/wiring-tier2-recommended.svg for full wiring diagram with all 4 ESP32 nodes, MOSFET circuits, and I2C bus layout.",
    firmware_targets=["climate_node", "relay_node", "lighting_node", "cam_node"],
    setup_steps=[
        "Set up Raspberry Pi: install Raspberry Pi OS (64-bit), enable SSH, connect to WiFi",
        "Clone SporePrint: git clone https://github.com/59psi/SporePrint.git && cd SporePrint",
        "Copy .env.example to .env, set SPOREPRINT_WEATHER_LAT and _LON for your location",
        "Wire climate node: SHT31-D + SCD41 + BH1750 on shared I2C bus (SDA=GPIO21, SCL=GPIO22) per diagram",
        "Wire relay node: 4x IRLZ44N MOSFETs with 10K pull-down resistors (gate to GND) and 1N4007 flyback diodes per diagram",
        "Wire lighting node: same MOSFET pattern — white LED strip on GPIO 25, blue on GPIO 26",
        "Install PlatformIO: pip install platformio",
        "Flash all 4 firmwares: cd firmware && pio run -t upload -e climate_node (repeat for relay_node, lighting_node, cam_node)",
        "Flash ESP32-S3 CAM: connect via USB-C, flash cam_node firmware (no programmer needed)",
        "Each ESP32 creates 'SporePrint-Setup' WiFi AP on first boot — connect and enter your WiFi credentials",
        "SENSOR PLACEMENT — Climate node (SHT31 + SCD41 + BH1750): Mount the sensor board inside the "
        "ventilated sensor enclosure (sensor_mount.scad). Place at CENTER of growing chamber at "
        "SUBSTRATE LEVEL — not near the ceiling where hot air rises. Temperature and humidity at "
        "substrate level are what matter for mushroom growth, not ambient room temp. Attach to shelf "
        "with zip ties (thread through the side slots) or use the suction cup mount on back for glass "
        "walls. AVOID placing near heat sources (heaters, lights), direct airflow (fan output), or "
        "dead air zones (corners). CO2 SPECIFIC: SCD41 needs good air circulation around it — don't "
        "enclose it too tightly. The vent holes in the sensor mount are critical for accurate CO2 "
        "readings. LIGHT SPECIFIC: BH1750 should face the light source — mount with the sensor chip "
        "facing the LED strips, not the floor",
        "RELAY NODE PLACEMENT: Mount the relay board (relay_board_mount.scad) OUTSIDE the grow chamber — "
        "electronics should not be in a high-humidity environment. Mount on the outside wall or a nearby "
        "shelf using M3 screws or zip ties through the edge channels. Route wires through a small hole or "
        "gap in the chamber — use grommets if drilling through plastic. Keep MOSFETs accessible for "
        "inspection and ensure good ventilation — MOSFETs generate heat under load",
        "Connect fans to relay node: FAE fan to channel 0 (GPIO 25), exhaust to channel 1 (GPIO 26), circulation to channel 2 (GPIO 27)",
        "Connect LED strips to lighting node: white to channel 0 (GPIO 25), blue to channel 1 (GPIO 26)",
        "Power 12V devices (fans, LED strips) from the 12V PSU. ESP32s powered via USB",
        "CAMERA PLACEMENT: Two recommended positions — (1) FRONT-FACING at substrate level, angled "
        "slightly upward to capture pin formation and fruiting body development, or (2) TOP-DOWN above "
        "the substrate looking straight down for overall colonization progress. Use cam_mount.scad — "
        "suction cup on glass door or zip tie to shelf rail. Distance: 15-30cm from substrate for good "
        "detail without fish-eye distortion. The camera has a built-in flash LED (GPIO 4) — use it for "
        "consistent photos since ambient light varies",
        "SMART PLUG PLACEMENT — Athom Tasmota plugs: plug into accessible outlets OUTSIDE the chamber. "
        "Humidifier plug: connect an ultrasonic humidifier (placed inside or piped in). "
        "Heater/cooler plug: connect a space heater (placed outside, directed at chamber intake) or "
        "Peltier cooler (placed at chamber wall). "
        "Set up each plug: power on — connect to 'tasmota-XXXX' AP, "
        "open 192.168.4.1, enter WiFi credentials. In Tasmota web UI: Configuration → MQTT → "
        "set Host to Pi's IP, Port 1883. Assign roles: humidifier, heater/cooler",
        "Start SporePrint: docker compose up -d",
        "Open http://<pi-ip>:3001 — verify all nodes appear on Dashboard hardware panel",
        "Camera frames should appear in Vision page within 15 minutes of cam_node booting",
    ],
)

# ── Tier 3: All the Things ──────────────────────────────────────

TIER_ALL = HardwareTier(
    id="all_the_things",
    name="All the Things",
    tagline="Full automation. Redundant sensors. Every bell and whistle.",
    estimated_cost="~$370+",
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
            notes="Alternative: Arctic P8 PWM (~$8). "
                  "Also: newegg.com, walmart.com, noctua.at/buy. Alternative: Arctic P8 PWM (~$8).",
        ),
        Component(name="12V LED Strip - Cool White (6500K), 2m", role="General light", price_approx="$12", url="https://www.amazon.com/s?k=12v+led+strip+6500k+2m", category="actuator", notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser."),
        Component(name="12V LED Strip - Blue (450nm), 1m", role="Cordyceps + pinning", price_approx="$8", url="https://www.amazon.com/s?k=12v+blue+led+strip+450nm+1m", category="actuator", notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser."),
        Component(name="12V LED Strip - Red (660nm), 1m", role="Fruiting enhancement", price_approx="$8", url="https://www.amazon.com/s?k=12v+red+led+strip+660nm+1m", category="actuator", notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser."),
        Component(name="12V LED Strip - Far Red (730nm), 1m", role="Morphology control", price_approx="$12", url="https://www.amazon.com/s?k=730nm+far+red+led+strip+12v", category="actuator", notes="Specialty item. Also: superlightingled.com, ledlightsworld.com. May need to order from grow light suppliers."),
        Component(name="12V Power Supply (10A, 120W)", role="Power for all 12V devices", price_approx="$18", url="https://www.amazon.com/s?k=12v+10a+power+supply+120w", category="power", notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser."),
        Component(**{**_ESP32_CAM.model_dump(), "quantity": 2, "notes": "Front view + top-down view. Also: seeedstudio.com (XIAO ESP32S3 Sense with OV5640), walmart.com, ebay.com"}),
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
                  "Place under grow block to track water loss and harvest weight. "
                  "Widely available. Also: sparkfun.com, adafruit.com. Multiple Amazon sellers.",
        ),
        Component(
            name="Reed Switch (magnetic, normally open)",
            role="Door sensor — pauses humidity when closet opens",
            price_approx="$3",
            url="https://www.amazon.com/s?k=magnetic+reed+switch+normally+open",
            category="sensor",
            notes="Mount on closet door frame. Wire to any ESP32 GPIO with internal pull-up. "
                  "Magnet on door, switch on frame. "
                  "Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
        ),
        Component(
            name="12V Peristaltic Pump (dosing pump)",
            role="Automated misting / substrate hydration between flushes",
            price_approx="$12",
            url="https://www.amazon.com/s?k=12v+peristaltic+pump+dosing",
            category="actuator",
            notes="12V DC, ~100mL/min flow rate. Connect to relay node aux channel. "
                  "Use food-safe silicone tubing. "
                  "Also: adafruit.com/product/1150, ebay.com. Kamoer brand recommended for reliability.",
        ),
        Component(
            name="Breadboard + Jumper Wire Kit",
            role="Prototyping connections (or solder to perfboard)",
            price_approx="$8",
            url="https://www.amazon.com/s?k=breadboard+jumper+wire+kit",
            category="misc",
            notes="Widely available from any electronics supplier. Amazon, AliExpress, eBay, DigiKey, Mouser.",
        ),
    ],
    wiring=[
        *TIER_RECOMMENDED.wiring,
        WiringConnection(from_device="ESP32 (Climate #2)", from_pin="GPIO 21/22", to_device="SHT31-D #2 / SCD41 #2 / BH1750 #2", to_pin="Shared I2C", note="Second shelf"),
        WiringConnection(from_device="ESP32 (Relay)", from_pin="GPIO 14 (aux)", to_device="Peristaltic Pump", to_pin="Via IRLZ44N + flyback diode"),
        WiringConnection(from_device="Any ESP32 GPIO", from_pin="GPIO (INPUT_PULLUP)", to_device="Reed Switch", to_pin="One leg to GPIO, other to GND"),
    ],
    wiring_diagram="See docs/wiring-tier3-all-the-things.svg for full wiring diagram with all 5 ESP32 nodes, load cell, reed switch, pump, and 4-channel lighting.",
    firmware_targets=["climate_node", "relay_node", "lighting_node", "cam_node"],
    setup_steps=[
        "Set up Raspberry Pi: install Raspberry Pi OS (64-bit), enable SSH, connect to WiFi",
        "Clone SporePrint: git clone https://github.com/59psi/SporePrint.git && cd SporePrint",
        "Copy .env.example to .env, set SPOREPRINT_WEATHER_LAT and _LON for your location (enables predictive automation)",
        "Wire climate node #1: SHT31-D + SCD41 + BH1750 on shared I2C bus (SDA=GPIO21, SCL=GPIO22) per diagram",
        "Wire climate node #2 identically on a second ESP32 — this goes on a different shelf for per-shelf monitoring",
        "Wire relay node: 4x IRLZ44N MOSFETs with 10K pull-down resistors (gate to GND) and 1N4007 flyback diodes per diagram",
        "Wire lighting node: same MOSFET pattern — white (GPIO 25), blue (GPIO 26), red (GPIO 27), far-red (GPIO 14)",
        "Install PlatformIO: pip install platformio",
        "Flash all firmwares: cd firmware && pio run -t upload -e climate_node (repeat for relay_node, lighting_node, cam_node)",
        "Flash climate node #2 with different node_id: set MQTT node_id to 'climate-02' before flashing",
        "Flash both ESP32-S3 CAMs via USB-C: first cam with default node_id, second cam with node_id 'cam-02' for top-down view",
        "Each ESP32 creates 'SporePrint-Setup' WiFi AP on first boot — connect and enter your WiFi credentials",
        "SENSOR PLACEMENT — Climate nodes (SHT31 + SCD41 + BH1750): Mount each sensor board inside "
        "the ventilated sensor enclosure (sensor_mount.scad). Place at CENTER of growing chamber at "
        "SUBSTRATE LEVEL — not near the ceiling where hot air rises. Temperature and humidity at "
        "substrate level are what matter for mushroom growth, not ambient room temp. For the second "
        "climate node, place on a different shelf at the same height relative to that shelf's substrate. "
        "Attach to shelf with zip ties (thread through the side slots) or use the suction cup mount on "
        "back for glass walls. AVOID placing near heat sources (heaters, lights), direct airflow (fan "
        "output), or dead air zones (corners). CO2 SPECIFIC: SCD41 needs good air circulation — don't "
        "enclose it too tightly. The vent holes in the sensor mount are critical. LIGHT SPECIFIC: "
        "BH1750 should face the light source — mount with the sensor chip facing the LED strips, not the floor",
        "RELAY NODE PLACEMENT: Mount the relay board (relay_board_mount.scad) OUTSIDE the grow chamber — "
        "electronics should not be in a high-humidity environment. Mount on the outside wall or a nearby "
        "shelf using M3 screws or zip ties through the edge channels. Route wires through a small hole or "
        "gap in the chamber — use grommets if drilling through plastic. Keep MOSFETs accessible for "
        "inspection and ensure good ventilation — MOSFETs generate heat under load. Use the zip tie "
        "channels on the relay board for cable management — bundle the 12V wires neatly",
        "Connect fans to relay node: FAE fan to channel 0 (GPIO 25), exhaust to channel 1 (GPIO 26), circulation to channel 2 (GPIO 27)",
        "Connect LED strips to lighting node: white to ch 0, blue to ch 1, red (660nm) to ch 2 (GPIO 27), far-red (730nm) to ch 3 (GPIO 14)",
        "CAMERA PLACEMENT: Use BOTH recommended positions for full coverage — (1) FRONT-FACING camera "
        "(default node_id) at substrate level, angled slightly upward to capture pin formation and "
        "fruiting body development. (2) TOP-DOWN camera (cam-02) above the substrate looking straight "
        "down for overall colonization progress. Use cam_mount.scad — suction cup on glass door or zip "
        "tie to shelf rail. Distance: 15-30cm from substrate for good detail without fish-eye distortion. "
        "The camera has a built-in flash LED (GPIO 4) — use it for consistent photos since ambient light varies",
        "Wire HX711 load cell to relay node spare GPIOs (DOUT=GPIO 32, SCK=GPIO 33) — place cell under grow block for harvest weight tracking",
        "Mount reed switch on closet door frame — wire one leg to any ESP32 GPIO (set INPUT_PULLUP), other leg to GND",
        "Connect peristaltic pump to relay node aux channel (GPIO 14) via IRLZ44N + flyback diode — run food-safe silicone tubing to misting nozzle",
        "Power all 12V devices (fans, LED strips, pump) from the 12V 10A PSU. ESP32s powered via USB",
        "SMART PLUG PLACEMENT — All 4 Athom Tasmota plugs go into accessible outlets OUTSIDE the chamber. "
        "Humidifier plug: connect an ultrasonic humidifier (placed inside or piped in via tubing). "
        "Dehumidifier plug: connect a dehumidifier (placed outside chamber, intake facing chamber). "
        "Heater plug: connect a space heater (placed outside, directed at chamber intake). "
        "Peltier cooler plug: connect a Peltier cooler (placed at chamber wall). "
        "Set up each plug: power on — connect to 'tasmota-XXXX' AP, "
        "open 192.168.4.1, enter WiFi credentials. In Tasmota web UI: Configuration → MQTT → "
        "set Host to Pi's IP, Port 1883. Assign roles: humidifier, dehumidifier, heater, cooler",
        "Start SporePrint: docker compose up -d",
        "Open http://<pi-ip>:3001 — verify all nodes, cameras, and plugs appear on the Dashboard",
        "Camera frames should appear in Vision page within 15 minutes. Verify both front and top-down views are capturing",
    ],
)

# ── All tiers ───────────────────────────────────────────────────

TIERS = [TIER_BARE_BONES, TIER_RECOMMENDED, TIER_ALL]
