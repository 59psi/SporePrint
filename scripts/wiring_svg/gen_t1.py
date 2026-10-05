import sys
from parts import *  # noqa: F401,F403

OUT = sys.argv[1]
W, H = 1000, 850
s = Svg(W, H)

s.comment("═══════════════════════ TITLE ═══════════════════════")
s.text(500, 30, "Tier 1: Bare Bones Wiring Diagram", fill=T1, size=16, weight="700", anchor="middle")
s.text(500, 50, "ESP32 + two I2C sensors on one STEMMA QT chain — no soldering, no breadboard. Power strip "
       "outside the chamber; the Pi and the smart plug connect over WiFi only.", fill=T2, size=11, anchor="middle")

TOP, BOT, WX = 64, 540, 420
frame(s, TOP, BOT, wall_x=WX, inside_right=984, wall_label_y=380, wall_label="CHAMBER WALL — grommet")
s.text(32, 100, "power strip, Pi, USB charger and the smart plug", fill=T2, size=9)
s.text(WX + 50, 100, "the climate node, its sensors and the humidifier", fill=T2, size=9)

power_strip(s, 28, 112, 106, BOT - 12 - 112, "6")
OX = 116

# Pi
s.comment("Pi + its PSU")
outlet(s, OX, 140, 150)
s.rect(150, 126, 130, 28, fill=CARD, stroke=EDGE, sw=1, rx=4)
s.text(211, 138, "Pi 27 W USB-C PSU", fill=T1, size=9, weight="600", anchor="middle")
s.text(211, 149, "official, 5.1 V 5 A", fill=T3, size=7, anchor="middle")
usb(s, [(280, 140), (300, 140), (300, 168)])
s.rect(150, 168, 250, 44, fill=CARD, stroke=WIFI, sw=1.5)
s.text(275, 186, "Raspberry Pi 5 + Active Cooler (pi_case)", fill=T1, size=10, weight="600", anchor="middle")
s.text(275, 202, "SporePrint server + credentialed MQTT broker", fill=T2, size=8, anchor="middle")
s.pill(150, 218, 250, 18, "WiFi / MQTT to the node and the plug — no wires", "#0f2418", WIFI, WIFI)

# USB charger → 6 ft cable → climate ESP32
s.comment("USB charger → 6 ft USB-C cable through the grommet")
outlet(s, OX, 280, 150)
charger(s, 150, 280, 130, "UL, one per board")
usb(s, [(284, 280), (536, 280)])
s.text(292, 272, "USB-A → USB-C, 6 ft (2 m)", fill=USB_T, size=8, weight="600")
wall_grommet(s, 268, 292, wall_x=WX)

# Tasmota plug → humidifier
s.comment("Tasmota plug → humidifier cord through the grommet")
outlet(s, OX, 490, None)
s.rect(140, 479, 144, 22, fill=CARD, stroke=YEL, sw=1, rx=4)
s.text(212, 493, "Tasmota plug · humidifier", fill=T1, size=8, weight="600", anchor="middle")
s.line(284, 490, 560, 490, AC, 2.5)
wall_grommet(s, 480, 500, wall_x=WX)
s.text(150, 452, "Tasmota MQTT: User sp-3p, Topic humidifier,", fill=YEL_T, size=8, weight="600")
s.text(150, 464, "Full Topic tasmota/%topic%/%prefix%/ (required)", fill=YEL_T, size=8, weight="600")
s.rect(560, 476, 410, 30, fill=CARD, stroke=AC_T, sw=1, rx=4)
s.text(570, 489, "Ultrasonic humidifier (inside, or piped in) — plug-humidifier", fill=T1, size=9, weight="600")
s.text(570, 501, "its cord runs out through the grommet to the plug on the strip", fill=T3, size=8)

# ESP32 DevKit (inside)
s.comment("═══════ ESP32-WROOM-32 DEVKIT (inside) ═══════")
s.rect(540, 150, 170, 270, fill=CARD, stroke=EDGE, sw=1.5)
s.text(625, 172, "ESP32-WROOM-32 DevKit", fill=T1, size=11, weight="600", anchor="middle")
s.text(625, 188, "climate-01 (env node_esp32)", fill=T2, size=9, anchor="middle")
s.text(625, 201, "esp32_case", fill=T3, size=8, anchor="middle")
s.rect(536, 274, 8, 12, fill=BG, stroke=USB_T, sw=0.8, rx=1)
s.text(458, 272, "to USB-C", fill=T3, size=8)
s.rect(692, 206, 14, 196, fill="#0f172a", stroke="#334155", sw=0.5, rx=2)
for y, label, sub, dot, tc in ((222, "3V3", "red socket", RED, RED_T), (268, "GND", "any GND (not EN)", "#1e1e1e", GND_T),
                               (314, "GPIO 21", "SDA", BLUE, BLUE_T), (360, "GPIO 22", "SCL", YEL, YEL_T)):
    if dot == "#1e1e1e":
        s.circle(699, y, 6, dot, stroke="#6b7280", sw=1)
    else:
        s.circle(699, y, 6, dot)
    s.text(684, y - 3, label, fill=tc, size=11, weight="600", anchor="end")
    s.text(684, y + 11, sub, fill=T3, size=8, anchor="end")

# sensors
s.comment("SHT31-D + BH1750")
s.rect(790, 196, 176, 96, fill=CARD, stroke=EDGE, sw=1.5)
s.text(878, 222, "SHT31-D", fill=T1, size=13, weight="600", anchor="middle")
s.text(878, 240, "Temperature + Humidity", fill=T2, size=10, anchor="middle")
s.text(878, 256, "I2C address: 0x44", fill=WIFI, size=9, anchor="middle")
s.text(878, 282, "QT in (left) / QT out (bottom)", fill=T3, size=8, anchor="middle")
s.rect(778, 222, 14, 34, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=2)
s.rect(790, 336, 176, 76, fill=CARD, stroke=EDGE, sw=1.5)
s.text(878, 362, "BH1750", fill=T1, size=13, weight="600", anchor="middle")
s.text(878, 380, "Ambient Light (lux)", fill=T2, size=10, anchor="middle")
s.text(878, 398, "I2C address: 0x23", fill=WIFI, size=9, anchor="middle")

# Adafruit 4397: ESP32 pins → SHT31-D QT
s.path([(705, 222), (722, 222), (722, 228), (778, 228)], RED, 3)
s.path([(705, 268), (734, 268), (734, 236), (778, 236)], GND, 3)
s.path([(705, 314), (746, 314), (746, 244), (778, 244)], BLUE, 3)
s.path([(705, 360), (758, 360), (758, 252), (778, 252)], YEL, 3)
s.rect(716, 150, 140, 34, fill=BG, stroke="#94a3b8", sw=0.8, rx=4)
s.text(786, 164, "Adafruit 4397 cable", fill=T1, size=9, weight="600", anchor="middle")
s.text(786, 177, "female sockets → QT plug", fill=T2, size=8, anchor="middle")

# Adafruit 4210 QT-QT
for j, c in enumerate((RED, GND, BLUE, YEL)):
    s.line(842 + j * 8, 292, 842 + j * 8, 336, c, 3, cap=None)
s.rect(880, 298, 96, 30, fill=BG, stroke="#94a3b8", sw=0.8, rx=4)
s.text(928, 311, "Adafruit 4210", fill=T1, size=9, weight="600", anchor="middle")
s.text(928, 323, "QT-QT cable", fill=T2, size=8, anchor="middle")
s.text(540, 438, "One chain, not a star: ESP32 → 4397 → SHT31-D → 4210 → BH1750 (different I2C addresses).",
       fill=T2, size=8)
s.text(540, 451, "sensor_mount + sensor_bracket at the centre of the chamber, substrate level; vents open.",
       fill=T3, size=8)

# legend strip
s.comment("═══════ LEGEND ═══════")
s.rect(16, 552, 968, 40, fill=CARD, stroke=EDGE, sw=1)
x = 30
for colr, label, tc in ((RED, "RED = 3V3", RED_T), (GND, "BLACK = GND", GND_T), (BLUE, "BLUE = SDA", BLUE_T),
                        (YEL, "YELLOW = SCL", YEL_T), (AC, "ORANGE = 120 V AC cord", AC_T),
                        (USB, "CYAN = USB 5 V cable", USB_T)):
    s.line(x, 572, x + 26, 572, colr, 3)
    s.text(x + 32, 576, label, fill=tc, size=9)
    x += 32 + len(label) * 5.4 + 18
s.grommet(x, 566, 26, 12)
s.text(x + 32, 576, "= through the chamber wall", fill=T2, size=9)

# steps
s.comment("═══════ WIRING STEPS ═══════")
s.rect(16, 602, 968, 222, fill=PANEL, stroke=EDGE, sw=1)
s.text(32, 626, "Wiring Steps (two cables, no soldering)", fill=T1, size=13, weight="700")
s.text(32, 650, "Adafruit 4397 (female sockets onto the ESP32 pins):", fill=T2, size=11, weight="600")
for i, (dot, t) in enumerate(((RED, "1. red socket  →  ESP32 3V3"),
                              ("#1e1e1e", "2. black socket  →  ESP32 GND (any GND pin, never EN)"),
                              (BLUE, "3. blue socket  →  ESP32 GPIO 21 (SDA)"),
                              (YEL, "4. yellow socket  →  ESP32 GPIO 22 (SCL)"))):
    y = 672 + i * 22
    if dot == "#1e1e1e":
        s.circle(42, y - 4, 5, dot, stroke="#6b7280", sw=1)
    else:
        s.circle(42, y - 4, 5, dot)
    s.text(54, y, t, fill=TL, size=10)
s.text(480, 650, "STEMMA QT plugs, power, plug:", fill=T2, size=11, weight="600")
for i, t in enumerate(("5. 4397 QT plug  →  SHT31-D STEMMA QT port",
                       "6. Adafruit 4210 QT-QT: SHT31-D second port  →  BH1750",
                       "7. 5 V charger on the strip  →  6 ft (2 m) USB-A → USB-C cable,",
                       "    through the grommet  →  the ESP32 (charger stays outside)",
                       "8. Strip outside the chamber: Pi PSU, USB charger, Tasmota plug")):
    s.text(480, 672 + i * 18, t, fill=TL, size=10)
for i, t in enumerate((
        "Tip: the sensors share one I2C bus at different addresses (0x44 and 0x23), so there is no conflict. "
        "Leave their loose header strips unsoldered.",
        "ESP32-S3 board? Different pins: SDA = GPIO 8, SCL = GPIO 9 (env node_esp32s3 / node_esp32s3_n32r16v). "
        "See the build guide, section 8a.",
        "The Pi and the Tasmota plug need zero wires to the node — they talk over WiFi. The 6 ft cable passes a 7/8 in. "
        "grommet; zip-tie the run.")):
    s.text(32, 772 + i * 18, t, fill=T2, size=10, italic=True)

s.comment("═══════════════════════ FOOTER ═══════════════════════")
s.text(500, 842, "SporePrint  |  Tier 1: Bare Bones  |  github.com/59psi/SporePrint", fill="#334155", size=9,
       anchor="middle")

open(OUT, "w").write(s.to_string())
print("wrote", OUT)
