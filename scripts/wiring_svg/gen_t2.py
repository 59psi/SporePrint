import sys
from parts import *  # noqa: F401,F403

OUT = sys.argv[1]
W, H = 1600, 1496
s = Svg(W, H)

s.comment("═══════════════════════ TITLE ═══════════════════════")
s.text(800, 30, "Tier 2: Recommended Wiring Diagram", fill=T1, size=16, weight="700", anchor="middle")
s.text(800, 50, "3 ESP32 nodes + 1 camera · power strip → 12V 5A PSU → 14 AWG pigtail → WAGO → fused 18 AWG "
       "branches → 2 switch boards · STEMMA QT sensor chain · 2 smart plugs", fill=T2, size=11, anchor="middle")

TOP, BOT = 64, 1030
frame(s, TOP, BOT, wall_label_y=540)
s.text(32, 100, "power strip, 12 V supply, chargers, Pi, smart plugs and both switch boards", fill=T2, size=9)
s.text(1062, 100, "sensors, camera and 12 V loads only — no supplies, chargers or switch boards", fill=T2, size=9)

# ── power strip + outlets ─────────────────────────────────────────
power_strip(s, 28, 112, 112, 908, "12")
OX = 122
CB = 160          # column B (chargers / supplies) left edge
CBW = 130

s.comment("USB chargers for the two in-chamber boards (6 ft cables)")
for y, sub in ((132, "6 ft micro-USB → CAM-MB"), (176, "6 ft USB-C → climate")):
    outlet(s, OX, y, CB)
    charger(s, CB, y, CBW, sub)
usb(s, [(294, 132), (1096, 132)])
usb(s, [(294, 176), (1058, 176)])
s.text(560, 126, "USB-A → micro-USB, 6 ft (2 m) → the camera's ESP32-CAM-MB", fill=USB_T, size=9)
s.text(560, 170, "USB-A → USB-C, 6 ft (2 m) → the climate ESP32 (in the chamber)", fill=USB_T, size=9)
wall_grommet(s, 120, 188)

# ── relay node ────────────────────────────────────────────────────
s.comment("═══════ RELAY NODE (outside) ═══════")
s.rect(304, 206, 692, 296, fill="#0f1623", stroke=EDGE, sw=1)
s.text(318, 226, "Relay node", fill=T1, size=12, weight="700")
s.text(392, 226, "relay_board_mount, node=\"relay\" — 4 switch channels, a UF4007 on every one", fill=T2, size=9)
outlet(s, OX, 276, CB)
charger(s, CB, 276, CBW, "1 ft USB-C → relay")
esp32(s, 320, 250, 120, 140, "ESP32", "relay-01", "esp32_case",
      pins=[("GPIO 25", 306, "gpio"), ("GPIO 26", 322, "gpio"), ("GPIO 27", 338, "gpio"),
            ("GPIO 14", 354, "gpio"), ("GND", 374, "gnd")], usb_y=276)
usb(s, [(294, 276), (316, 276)])
RY = [298, 336, 374, 412]
switch_board(s, 540, 258, 440, 220, "IRLZ44N switch board (relay_board_mount)", [
    dict(y=RY[0], name="CH0 fae — FAE fan (GPIO 25)", sub="100R gate · 10K pull-down · IRLZ44N · UF4007 across J2"),
    dict(y=RY[1], name="CH1 exhaust — exhaust fan (GPIO 26)", sub="same circuit"),
    dict(y=RY[2], name="CH2 circulation — circulation fan (GPIO 27)", sub="same circuit"),
    dict(y=RY[3], name="CH3 aux — spare, 60 s max-on (GPIO 14)", sub="the pump channel in All the Things",
         colour=T2),
], plus_x=930, gnd_x=590, rail_top=284, rail_bottom=478)
s.text(596, 470, "GND bus", fill=GND_T, size=8, weight="600")
s.text(924, 470, "+12 V bus", fill=RED_T, size=8, weight="600", anchor="end")
# Dupont jumpers GPIO → J1 IN
s.path([(440, 306), (470, 306), (470, RY[0] - 4), (544, RY[0] - 4)], GRN, 2)
s.path([(440, 322), (478, 322), (478, RY[1] - 4), (544, RY[1] - 4)], GRN, 2)
s.path([(440, 338), (486, 338), (486, RY[2] - 4), (544, RY[2] - 4)], GRN, 2)
s.path([(440, 354), (494, 354), (494, RY[3] - 4), (544, RY[3] - 4)], GRN, 2)
s.path([(440, 374), (462, 374), (462, 446), (520, 446), (520, RY[3] + 6), (544, RY[3] + 6)], GND, 3)
s.text(492, 272, "Dupont jumpers", fill=GRN_T, size=8, anchor="middle")
s.text(492, 283, "(or 22 AWG)", fill=T3, size=7, anchor="middle")
callout(s, 320, 454, 200, 40, [("COMMON GROUND", True), ("ESP32 GND → J1 − → GND bus", False),
                               ])
# fans
for i, (name, sub) in enumerate((("FAE fan — Noctua NF-A8 12 V", "fresh-air intake at the wall · fan_duct"),
                                 ("Exhaust fan — Noctua NF-A8 12 V", "exhaust at the wall · fan_duct"),
                                 ("Circulation fan — Noctua NF-A8 12 V", "inside, away from the sensors"))):
    y = RY[i]
    load_pair(s, 976, y, 1180)
    s.rect(1180, y - 16, 300, 32, fill=CARD, stroke=GRN_T, sw=1, rx=4)
    s.text(1190, y - 3, name, fill=T1, size=9, weight="600")
    s.text(1190, y + 10, sub, fill=T3, size=8)
wall_grommet(s, 284, 392)
s.text(1056, 432, "Fans: bundled 30 cm extension + Noctua NA-SEC3 4-pin extension (cut its far end): GND → J2 −,",
       fill=T2, size=8)
s.text(1056, 444, "+12 V → J2 + — identify by pin position, not colour; tach + PWM unused (heat-shrink them).",
       fill=T2, size=8)

# ── 12 V distribution ─────────────────────────────────────────────
s.comment("═══════ 12 V DISTRIBUTION: PSU → pigtail → WAGO → fuses ═══════")
outlet(s, OX, 558, CB)
s.rect(CB, 516, CBW, 84, fill=CARD, stroke=RED, sw=1.5)
s.text(CB + CBW / 2, 534, "12V 5A PSU (60W)", fill=RED_T, size=10, weight="700", anchor="middle")
s.text(CB + CBW / 2, 548, "Facmogu AL-1250", fill=T2, size=8, anchor="middle")
s.text(CB + CBW / 2, 561, "power_supply_mount", fill=T3, size=8, anchor="middle")
s.text(CB + CBW / 2, 574, "5.5 × 2.5 mm barrel", fill=T3, size=8, anchor="middle")
s.text(CB + CBW / 2, 587, "load ≤ ~4 A", fill=T3, size=8, anchor="middle")
s.rect(290, 546, 10, 22, fill=BG, stroke="#94a3b8", sw=0.8, rx=2)
# pigtail
s.path([(300, 562), (546, 562)], GND, 3.5)
s.path([(300, 552), (330, 552), (330, 520), ("hop", 590, 520, 6, "h"), (866, 520), (866, 548), (886, 548)], RED, 3.5)
s.text(318, 584, "5.5 × 2.5 mm DC barrel pigtail — 14 AWG", fill=T2, size=8)
# WAGO blocks
s.rect(546, 540, 88, 24, fill=CARD, stroke="#9ca3af", sw=1.2, rx=3)
s.text(590, 555, "WAGO 221-415 GND", fill=GND_T, size=7, weight="700", anchor="middle")
s.rect(886, 540, 88, 24, fill=CARD, stroke=RED, sw=1.2, rx=3)
s.text(930, 555, "WAGO 221-413 +12V", fill=RED_T, size=7, weight="700", anchor="middle")
# branches up to the relay board
s.line(590, 540, 590, 478, GND, 3, cap=None)
s.line(930, 540, 930, 478, RED, 3, cap=None)
s.fuse(923, 490, 14, 28, "", vertical=True)
s.text(916, 515, "3 A fuse", fill=RED_T, size=8, weight="700", anchor="end")
s.text(916, 525, "relay branch", fill=T3, size=7, anchor="end")
# branches down to the lighting board
s.line(590, 564, 590, 652, GND, 3, cap=None)
s.line(930, 564, 930, 652, RED, 3, cap=None)
s.fuse(923, 584, 14, 28, "", vertical=True)
s.text(916, 597, "5 A fuse", fill=RED_T, size=8, weight="700", anchor="end")
s.text(916, 608, "lighting branch", fill=T3, size=7, anchor="end")
s.text(604, 596, "branches: 18 AWG red (+12 V, fused)", fill=T2, size=8)
s.text(604, 608, "and black (GND, not fused)", fill=T2, size=8)

# ── lighting node ─────────────────────────────────────────────────
s.comment("═══════ LIGHTING NODE (outside) ═══════")
s.rect(304, 626, 692, 300, fill="#0f1623", stroke=EDGE, sw=1)
s.text(318, 646, "Lighting node", fill=T1, size=12, weight="700")
s.text(318, 660, "relay_board_mount, node=\"lighting\" (PETG)", fill=T2, size=9)
s.text(318, 672, "no diodes — LED strips are resistive", fill=T2, size=9)
outlet(s, OX, 710, CB)
charger(s, CB, 710, CBW, "1 ft USB-C → lighting")
esp32(s, 320, 684, 120, 140, "ESP32", "lighting-01", "esp32_case",
      pins=[("GPIO 25", 740, "gpio"), ("GPIO 26", 756, "gpio"), ("GPIO 27 spare", 772, "gpio"),
            ("GPIO 14 spare", 788, "gpio"), ("GND", 808, "gnd")], usb_y=710)
usb(s, [(294, 710), (316, 710)])
LY = [700, 738, 776, 814]
switch_board(s, 540, 652, 440, 196, "IRLZ44N switch board (relay_board_mount)", [
    dict(y=LY[0], name="CH0 white — 6500K strip (GPIO 25)", sub="100R gate · 10K pull-down · IRLZ44N · no diode"),
    dict(y=LY[1], name="CH1 blue — tri-spectrum BLUE wire (GPIO 26)", sub="same circuit"),
    dict(y=LY[2], name="CH2 red — spare (GPIO 27)", sub="the strip's RED wire, later — no re-flash", colour=T2),
    dict(y=LY[3], name="CH3 far_red — spare (GPIO 14)", sub="the strip's GREEN wire (730 nm), later", colour=T2),
], plus_x=930, gnd_x=590, rail_top=652, rail_bottom=834)
s.text(596, 844, "GND bus", fill=GND_T, size=8, weight="600")
s.text(924, 844, "+12 V bus", fill=RED_T, size=8, weight="600", anchor="end")
s.path([(440, 740), (470, 740), (470, LY[0] - 4), (544, LY[0] - 4)], GRN, 2)
s.path([(440, 756), (478, 756), (478, LY[1] - 4), (544, LY[1] - 4)], GRN, 2)
s.path([(440, 808), (500, 808), (500, LY[1] + 6), (544, LY[1] + 6)], GND, 3)
callout(s, 320, 864, 200, 40, [("COMMON GROUND", True), ("ESP32 GND → J1 − → GND bus", False)])
# LED strips
load_pair(s, 976, LY[0], 1180)
s.rect(1180, LY[0] - 16, 390, 32, fill=CARD, stroke=GRN_T, sw=1, rx=4)
s.text(1190, LY[0] - 3, "White 6500K LED strip — JOYLIT 5 m roll, cut to closet length", fill=T1, size=9, weight="600")
s.text(1190, LY[0] + 10, "red → J2 +, black → J2 − (18 AWG red/black pair)", fill=T3, size=8)
load_pair(s, 976, LY[1], 1180)
s.rect(1180, LY[1] - 14, 390, 100, fill=CARD, stroke=BLUE_T, sw=1, rx=4)
s.text(1192, LY[1] - 2, "common wire → +12 V (J2 +)", fill=RED_T, size=8, weight="600")
s.text(1192, LY[1] + 9, "BLUE wire (450 nm) → J2 − of CH1", fill=BLUE_T, size=8, weight="600")
s.line(1180, LY[1] + 22, 1200, LY[1] + 22, RED, 2)
s.rect(1198, LY[1] + 18, 6, 8, fill=T3, stroke=None, rx=1)
s.text(1210, LY[1] + 25, "RED wire (660 nm) — insulated with heat-shrink for now", fill=T2, size=8)
s.line(1180, LY[1] + 36, 1200, LY[1] + 36, GRN, 2)
s.rect(1198, LY[1] + 32, 6, 8, fill=T3, stroke=None, rx=1)
s.text(1210, LY[1] + 39, "GREEN wire (730 nm far-red) — insulated for now", fill=T2, size=8)
s.text(1192, LY[1] + 60, "Tri-spectrum strip, IP67 — one strip, one 4-wire lead", fill=T1, size=9, weight="600")
s.text(1192, LY[1] + 74, "SuperLightingLED p-7120 · cut to length · heat-shrink every joint", fill=T3, size=8)
wall_grommet(s, 688, 750)
s.text(1056, 678, "18 AWG red/black pairs", fill=T2, size=8)

# ── Pi + smart plugs ──────────────────────────────────────────────
s.comment("═══════ PI + SMART PLUGS ═══════")
outlet(s, OX, 946, CB)
s.rect(CB, 932, CBW, 28, fill=CARD, stroke=EDGE, sw=1, rx=4)
s.text(CB + CBW / 2 - 4, 944, "Pi 27 W USB-C PSU", fill=T1, size=9, weight="600", anchor="middle")
s.text(CB + CBW / 2 - 4, 955, "official, 5.1 V 5 A", fill=T3, size=7, anchor="middle")
usb(s, [(290, 946), (330, 946)])
s.rect(330, 928, 290, 40, fill=CARD, stroke=WIFI, sw=1.5)
s.text(475, 945, "Raspberry Pi 5 + Active Cooler (pi_case)", fill=T1, size=10, weight="600", anchor="middle")
s.text(475, 960, "Server · Mosquitto :1883 / :8883 TLS · Web UI :3001", fill=T2, size=8, anchor="middle")
s.pill(640, 932, 340, 18, "MQTT over WiFi — no wires from the Pi to any node or plug", "#0f2418", WIFI, WIFI)
s.text(640, 965, "Plugs: User sp-3p, Topic = role, Full Topic tasmota/%topic%/%prefix%/ (required)",
       fill=YEL_T, size=8, weight="600")
for y, label in ((976, "Tasmota plug #1 · humidifier"), (1002, "Tasmota plug #2 · heat / cool")):
    outlet(s, OX, y, None)
    s.rect(146, y - 11, 144, 22, fill=CARD, stroke=YEL, sw=1, rx=4)
    s.text(218, y + 3, label, fill=T1, size=8, weight="600", anchor="middle")
s.line(290, 976, 1180, 976, AC, 2.5)
wall_grommet(s, 966, 986)
s.rect(1180, 962, 300, 30, fill=CARD, stroke=AC_T, sw=1, rx=4)
s.text(1190, 975, "Ultrasonic humidifier (or piped in)", fill=T1, size=9, weight="600")
s.text(1190, 987, "plug-humidifier (Topic humidifier)", fill=T3, size=8)
s.line(290, 1002, 690, 1002, AC, 2.5)
s.rect(690, 986, 300, 34, fill=CARD, stroke=AC_T, sw=1, rx=4)
s.text(700, 999, "Space heater ≤ 1500 W, outside, aimed at the intake", fill=T1, size=8, weight="600")
s.text(700, 1012, "or a Peltier cooler at the wall (Topic heater / cooler)", fill=T3, size=8)

# ── inside: camera + climate node ────────────────────────────────
s.comment("═══════ CAMERA + CLIMATE NODE (inside) ═══════")
s.rect(1100, 114, 470, 36, fill=CARD, stroke=EDGE, sw=1.2, rx=4)
s.rect(1096, 126, 8, 12, fill=BG, stroke=USB_T, sw=0.8, rx=1)
s.text(1112, 129, "ESP32-CAM on its ESP32-CAM-MB · OV2640 or OV3660 · cam_mount", fill=T1, size=9, weight="600")
s.text(1112, 142, "cam-01 · no GPIO wiring · flash LED (GPIO 4) · 15-30 cm from the substrate", fill=T3, size=8)
esp32(s, 1062, 160, 110, 110, "ESP32", "climate-01", "esp32_case",
      pins=[("3V3", 212, "v33"), ("GND", 228, "gnd"), ("GPIO 21", 244, "sda"), ("GPIO 22", 260, "scl")],
      usb_y=176)
# Adafruit 4397: sockets on the header → QT plug in the SHT31-D
s.path([(1172, 212), (1196, 212), (1196, 200), (1250, 200)], RED, 2.5)
s.path([(1172, 228), (1206, 228), (1206, 210), (1250, 210)], GND, 2.5)
s.path([(1172, 244), (1216, 244), (1216, 220), (1250, 220)], BLUE, 2.2)
s.path([(1172, 260), (1226, 260), (1226, 230), (1250, 230)], YEL, 2.2)
for x, name, sub in ((1250, "SHT31-D", "Temp + RH · 0x44"), (1362, "SCD41", "CO2 · 0x62"), (1474, "BH1750", "Light · 0x23")):
    s.rect(x, 186, 96, 56, fill=CARD, stroke=EDGE, sw=1.5)
    s.text(x + 48, 204, name, fill=T1, size=10, weight="600", anchor="middle")
    s.text(x + 48, 218, sub, fill=T2, size=8, anchor="middle")
    s.text(x + 48, 233, "STEMMA QT ×2", fill=T3, size=7, anchor="middle")
for x in (1346, 1458):
    for j, c in enumerate((RED, GND, BLUE, YEL)):
        s.line(x, 205 + j * 6, x + 16, 205 + j * 6, c, 2, cap=None)
    s.text(x + 8, 182, "4210", fill=T2, size=7, weight="600", anchor="middle")
s.text(1222, 194, "4397", fill=T2, size=7, weight="600", anchor="middle")
s.text(1250, 254, "QT chain, not a star: 4397 → SHT31-D, 4210 → SCD41, 4210 → BH1750", fill=T2, size=8)
s.text(1250, 266, "sensor_mount + sensor_bracket: chamber centre, substrate level", fill=T3, size=8)

# ── bottom: one channel end to end ───────────────────────────────
s.comment("═══════ ONE CHANNEL, END TO END ═══════")
s.rect(16, 1044, 988, 262, fill=PANEL, stroke=EDGE, sw=1)
s.text(30, 1066, "One switch-board channel, end to end — CH0 (FAE fan) on relay_board_mount", fill=T1, size=12,
       weight="700")
s.text(30, 1081, "Every relay and lighting channel is this circuit; the lighting board leaves out the UF4007 and "
       "feeds a strip instead of a fan.", fill=T2, size=9)
YP, YS, YG = 1106, 1186, 1262
s.rect(30, 1096, 90, 178, fill=CARD, stroke=RED, sw=1.5)
s.text(75, 1176, "12V 5A", fill=RED_T, size=10, weight="700", anchor="middle")
s.text(75, 1190, "PSU", fill=T2, size=9, anchor="middle")
s.text(112, YP + 4, "+", fill=RED_T, size=10, weight="700", anchor="end")
s.text(112, YG + 4, "−", fill=GND_T, size=10, weight="700", anchor="end")
s.line(120, YP, 180, YP, RED, 3.5)
s.line(120, YG, 180, YG, GND, 3.5)
s.text(150, YP - 6, "14 AWG", fill=RED_T, size=8, anchor="middle")
s.text(150, YG - 6, "14 AWG", fill=GND_T, size=8, anchor="middle")
s.rect(180, YP - 10, 60, 20, fill=CARD, stroke=RED, sw=1.2, rx=3)
s.text(210, YP + 3, "221-413 +12V", fill=RED_T, size=7, weight="700", anchor="middle")
s.rect(180, YG - 10, 60, 20, fill=CARD, stroke="#9ca3af", sw=1.2, rx=3)
s.text(210, YG + 3, "221-415 GND", fill=GND_T, size=7, weight="700", anchor="middle")
s.line(240, YP, 290, YP, RED, 2.5)
s.text(265, YP - 6, "18 AWG", fill=RED_T, size=8, anchor="middle")
s.fuse(290, YP - 8, 46, 16, "3 A fuse")
s.line(336, YP, 690, YP, RED, 2.5)
s.text(520, YP - 6, "+12 V bus → J2 +", fill=RED_T, size=8, weight="600", anchor="middle")
# J2 + fan
s.rect(690, 1094, 34, 90, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=3)
s.text(707, 1090, "J2", fill=T2, size=8, weight="600", anchor="middle")
s.text(707, YP + 4, "+", fill=RED_T, size=10, weight="700", anchor="middle")
s.text(707, 1174, "−", fill=GRN_T, size=10, weight="700", anchor="middle")
s.line(724, YP, 850, YP, RED, 2.5)
s.line(724, 1170, 850, 1170, GRN, 2.5)
s.text(787, YP - 6, "+12 V wire", fill=RED_T, size=8, anchor="middle")
s.text(787, 1164, "GND wire", fill=GRN_T, size=8, anchor="middle")
s.text(787, 1140, "4-pin PWM fan", fill=T2, size=8, weight="600", anchor="middle")
s.text(787, 1151, "extension lead", fill=T2, size=8, weight="600", anchor="middle")
s.text(787, 1190, "tach + PWM wires unused", fill=T3, size=7, anchor="middle")
s.rect(850, 1092, 140, 92, fill=CARD, stroke=GRN_T, sw=1, rx=4)
s.text(920, 1126, "FAE fan", fill=T1, size=10, weight="600", anchor="middle")
s.text(920, 1141, "Noctua NF-A8 12 V", fill=T2, size=8, anchor="middle")
s.text(920, 1155, "inside the chamber", fill=CHAMBER_T, size=8, anchor="middle")
# UF4007 across J2
s.line(676, YP, 676, 1170, "#94a3b8", 1.5, cap=None)
s.raw('  <path d="M 668 1152 L 684 1152 L 676 1138 Z" fill="#94a3b8"/>')
s.line(668, 1136, 684, 1136, "#e2e8f0", 2, cap=None)
s.circle(676, YP, 3, RED)
s.circle(676, 1170, 3, GRN)
s.text(666, 1136, "UF4007", fill=TL, size=8, weight="600", anchor="end")
s.text(666, 1147, "band to +12 V", fill=T3, size=7, anchor="end")
# MOSFET
s.rect(560, 1152, 70, 52, fill=CARD, stroke=YEL, sw=1.5, rx=4)
s.text(595, 1172, "IRLZ44N", fill=YEL_T, size=9, weight="700", anchor="middle")
s.text(566, 1190, "G", fill=T3, size=7)
s.text(620, 1174, "D", fill=T3, size=7)
s.text(591, 1200, "S", fill=T3, size=7)
s.line(630, 1170, 676, 1170, GRN, 2.5)
s.line(676, 1170, 690, 1170, GRN, 2.5)
s.text(650, 1164, "drain", fill=T3, size=7, anchor="middle")
s.line(595, 1204, 595, YG, GND, 2.5)
# gate path
s.rect(400, 1166, 40, 58, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=3)
s.text(420, 1162, "J1", fill=T2, size=8, weight="600", anchor="middle")
s.text(420, YS + 3, "IN", fill=GRN_T, size=8, weight="600", anchor="middle")
s.text(420, 1215, "−", fill=GND_T, size=10, weight="700", anchor="middle")
s.line(440, YS, 470, YS, GRN, 2)
s.rect(470, YS - 8, 50, 16, fill=CARD, stroke=GRN_T, sw=1, rx=3)
s.text(495, YS + 3, "100R", fill=GRN_T, size=8, weight="600", anchor="middle")
s.text(495, YS - 12, "gate resistor", fill=T3, size=7, anchor="middle")
s.line(520, YS, 560, YS, GRN, 2)
s.circle(540, YS, 3, GRN)
s.line(540, YS, 540, 1214, "#94a3b8", 1.5, cap=None)
s.rect(531, 1214, 18, 30, fill=CARD, stroke="#94a3b8", sw=1, rx=2)
s.text(540, 1232, "10K", fill=TL, size=7, weight="600", anchor="middle", rotate=-90)
s.line(540, 1244, 540, YG, GND, 1.5)
s.text(527, 1232, "pull-down", fill=T3, size=7, anchor="end")
s.path([(440, 1212), (460, 1212), (460, YG)], GND, 2.5)
s.line(240, YG, 600, YG, GND, 3.5)
s.text(300, YG - 6, "18 AWG black → GND bus", fill=GND_T, size=8)
# ESP32 + common ground
s.rect(270, 1138, 90, 88, fill=CARD, stroke=EDGE, sw=1.5)
s.text(315, 1155, "ESP32", fill=T1, size=10, weight="600", anchor="middle")
s.text(315, 1168, "relay node", fill=T2, size=8, anchor="middle")
s.text(354, YS + 3, "GPIO 25", fill=GRN_T, size=7, weight="600", anchor="end")
s.text(354, 1215, "GND", fill=GND_T, size=7, weight="600", anchor="end")
s.circle(360, YS, 3.5, GRN)
s.circle(360, 1212, 3.5, "#1e1e1e", stroke="#9ca3af", sw=1)
s.line(360, YS, 400, YS, GRN, 2)
s.line(360, 1212, 400, 1212, GND, 3)
s.text(380, YS - 5, "Dupont", fill=GRN_T, size=7, anchor="middle")
s.line(250, 1200, 270, 1200, USB, 2.5)
s.text(258, 1194, "USB", fill=USB_T, size=7, anchor="middle")
s.rect(356, 1203, 48, 18, fill="none", stroke=YEL, sw=1, rx=3, dash="3,2")
s.pill(330, 1228, 100, 14, "COMMON GROUND", "#2a1f00", YEL, YEL_T, size=7)
s.text(30, 1296, "COMMON GROUND: ESP32 GND → J1 − → GND bus → WAGO 221-415 → PSU −. Leave it out and the gate has "
       "no reference — the channel never switches. Do it on both boards.", fill=YEL_T, size=9, weight="600")

# ── legend + 12 V budget ─────────────────────────────────────────
legend(s, 1046, 1044, 538, 152, extra=(
    "Wire: 14 AWG pigtail · 18 AWG red/black for every 12 V run · 22 AWG hookup wire or",
    "Dupont for GPIO / GND → J1. Adhesive-lined heat-shrink on every splice; zip-tie every run.",
))
s.rect(1046, 1204, 538, 102, fill=CARD, stroke=RED, sw=1)
s.text(1060, 1224, "12 V branches and fuses (inline blade fuse on each +12 V branch)", fill=RED_T, size=10,
       weight="700")
for i, t in enumerate((
        "Relay board: 3 A — three NF-A8 fans draw ~0.25 A together.",
        "Lighting board: 5 A — the LED strips are the real load.",
        "12V 5A PSU: keep the total ≤ ~4 A — cut the strips to closet length",
        "(a full white roll alone is 3.3-4.2 A). GND branches are not fused.")):
    s.text(1060, 1242 + i * 15, t, fill=TL, size=9)

# ── wiring steps ─────────────────────────────────────────────────
s.comment("═══════ WIRING STEPS ═══════")
s.rect(16, 1316, 1568, 154, fill=PANEL, stroke=EDGE, sw=1)
s.text(30, 1338, "Wiring Steps", fill=T1, size=13, weight="700")
cols = [
    (30, "1 · Mains and 12 V (outside)", AC_T, [
        "12-outlet strip outside: Pi PSU, 12 V PSU, 4 chargers, 2 plugs.",
        "PSU barrel → 14 AWG pigtail → WAGO 221-413 (+12V) / 221-415 (GND).",
        "221-413 → inline 3 A fuse → relay +12 V bus (18 AWG red).",
        "221-413 → inline 5 A fuse → lighting +12 V bus (18 AWG red).",
        "221-415 → both boards' GND bus (18 AWG black).",
    ]),
    (420, "2 · Each switch channel (relay_board_mount)", GRN_T, [
        "GPIO → Dupont jumper → J1 IN → 100R → IRLZ44N gate.",
        "10K from gate to source; source → GND bus.",
        "Drain → J2 −; J2 + → +12 V bus.",
        "UF4007 across J2 on every relay channel, band to +12 V.",
        "ESP32 GND → J1 − on both boards: the COMMON GROUND.",
    ]),
    (810, "3 · Into the chamber (through the grommet)", CHAMBER_T, [
        "Fans: NA-SEC3 extension, far end cut — GND → J2 −, +12 V → J2 +.",
        "FAE on CH0 (GPIO 25), exhaust CH1 (26), circulation CH2 (27).",
        "Strips: 18 AWG red/black, red → J2 +, black → J2 −.",
        "Tri-spectrum: BLUE wire → CH1 J2 −, common wire → +12 V.",
        "Insulate its red + green wires; heat-shrink every joint.",
    ]),
    (1200, "4 · Climate, camera, plugs", BLUE_T, [
        "4397: red 3V3, black GND, blue GPIO 21, yellow GPIO 22.",
        "4397 QT plug → SHT31-D; 4210 → SCD41; 4210 → BH1750.",
        "Climate + camera: 6 ft (2 m) USB cables through the grommet.",
        "Relay + lighting ESP32s stay outside on short cables.",
        "Plugs: WiFi only — sp-3p + Full Topic (see the build guide).",
    ]),
]
for x, head, colour, lines in cols:
    s.text(x, 1360, head, fill=colour, size=10, weight="700")
    for i, t in enumerate(lines):
        s.text(x, 1378 + i * 15, t, fill=TL, size=9)
s.text(1200, 1462, "ESP32-S3 boards use other pins: build guide §8a.", fill=T2, size=9, italic=True)

s.comment("═══════════════════════ FOOTER ═══════════════════════")
s.text(800, 1486, "SporePrint  |  Tier 2: Recommended  |  github.com/59psi/SporePrint", fill="#334155", size=9,
       anchor="middle")

open(OUT, "w").write(s.to_string())
print("wrote", OUT)
