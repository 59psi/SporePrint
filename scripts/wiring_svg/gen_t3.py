import sys
from parts import *  # noqa: F401,F403

OUT = sys.argv[1]
W, H = 1600, 1770
s = Svg(W, H)


def new_pill(x, y, label="NEW IN TIER 3", w=92):
    s.pill(x, y, w, 15, label, "#2e1065", PUR, PUR_T, size=7)


s.comment("═══════════════════════ TITLE ═══════════════════════")
s.text(800, 30, "Tier 3: All The Things Wiring Diagram", fill=T1, size=16, weight="700", anchor="middle")
s.text(800, 50, "Tier 2 + 2nd climate node, 2nd camera, 4 LED channels, HX711 scale, door contact, peristaltic pump, "
       "4 smart plugs · 12V 10A PSU, fused branches (3 A relay, 7.5 A lighting)", fill=T2, size=11, anchor="middle")

TOP, BOT = 64, 1282
frame(s, TOP, BOT, wall_label_y=768)
s.text(32, 100, "power strip, 12 V supply, chargers, Pi, smart plugs and both switch boards", fill=T2, size=9)
s.text(1062, 100, "sensors, cameras, scale, door contact and 12 V loads only", fill=T2, size=9)

power_strip(s, 28, 112, 112, BOT - 12 - 112, "12 + 2 USB-A")
OX, CB, CBW = 122, 160, 130

# ── 4 long USB runs to the in-chamber boards ─────────────────────
s.comment("USB chargers for the four in-chamber boards (6 ft cables)")
runs = [(128, "6 ft micro-USB → CAM-MB", "USB-A → micro-USB, 6 ft (2 m) → cam-01's ESP32-CAM-MB"),
        (168, "6 ft micro-USB → CAM-MB", "USB-A → micro-USB, 6 ft (2 m) → cam-02's ESP32-CAM-MB"),
        (210, "6 ft USB-C → climate-01", "USB-A → USB-C, 6 ft (2 m) → climate-01 (shelf A)"),
        (250, "6 ft USB-C → climate-02", "USB-A → USB-C, 6 ft (2 m) → climate-02 (shelf B)")]
for y, sub, label in runs:
    outlet(s, OX, y, CB)
    charger(s, CB, y, CBW, sub)
    s.text(560, y - 6, label, fill=USB_T, size=9)
usb(s, [(294, 128), (1096, 128)])
usb(s, [(294, 168), (1096, 168)])
usb(s, [(294, 210), (1058, 210)])
usb(s, [(294, 250), (1050, 250), (1050, 322), (1058, 322)])
wall_grommet(s, 116, 262)

# ── inside: cameras ──────────────────────────────────────────────
s.comment("═══════ CAMERAS + CLIMATE NODES (inside) ═══════")
for y, l1, l2, stroke in (
        (112, "cam-01 · ESP32-CAM on its ESP32-CAM-MB · OV2640 or OV3660 · front view",
         "cam_mount · no GPIO wiring · flash LED (GPIO 4) · substrate level, angled slightly up", EDGE),
        (152, "cam-02 · ESP32-CAM on its ESP32-CAM-MB · OV2640 or OV3660 · top-down",
         "cam_mount · looking straight down, 15-30 cm from the substrate", PUR)):
    s.rect(1100, y, 470, 34, fill=CARD, stroke=stroke, sw=1.2, rx=4)
    s.rect(1096, y + 10, 8, 12, fill=BG, stroke=USB_T, sw=0.8, rx=1)
    s.text(1112, y + 15, l1, fill=T1, size=9, weight="600")
    s.text(1112, y + 28, l2, fill=T3, size=8)
new_pill(1474, 170)


def climate(y0, name, shelf, purple=False):
    """ESP32 at (1062, y0) + a 3-sensor STEMMA QT chain to its right."""
    esp32(s, 1062, y0, 110, 104, "ESP32", name, shelf,
          pins=[("3V3", y0 + 44, "v33"), ("GND", y0 + 58, "gnd"), ("GPIO 21", y0 + 72, "sda"),
                ("GPIO 22", y0 + 86, "scl")], usb_y=y0 + 16)
    sy = y0 + 20
    s.path([(1172, y0 + 44), (1196, y0 + 44), (1196, sy + 12), (1250, sy + 12)], RED, 2.5)
    s.path([(1172, y0 + 58), (1206, y0 + 58), (1206, sy + 20), (1250, sy + 20)], GND, 2.5)
    s.path([(1172, y0 + 72), (1216, y0 + 72), (1216, sy + 28), (1250, sy + 28)], BLUE, 2.2)
    s.path([(1172, y0 + 86), (1226, y0 + 86), (1226, sy + 36), (1250, sy + 36)], YEL, 2.2)
    s.text(1222, sy + 6, "4397", fill=T2, size=7, weight="600", anchor="middle")
    for x, sname, sub in ((1250, "SHT31-D", "Temp + RH · 0x44"), (1362, "SCD41", "CO2 · 0x62"),
                          (1474, "BH1750", "Light · 0x23")):
        s.rect(x, sy, 96, 50, fill=CARD, stroke=PUR if purple else EDGE, sw=1.5)
        s.text(x + 48, sy + 17, sname, fill=T1, size=10, weight="600", anchor="middle")
        s.text(x + 48, sy + 30, sub, fill=T2, size=8, anchor="middle")
        s.text(x + 48, sy + 43, "STEMMA QT ×2", fill=T3, size=7, anchor="middle")
    for x in (1346, 1458):
        for j, c in enumerate((RED, GND, BLUE, YEL)):
            s.line(x, sy + 16 + j * 6, x + 16, sy + 16 + j * 6, c, 2, cap=None)
        s.text(x + 8, sy - 4, "4210", fill=T2, size=7, weight="600", anchor="middle")
    s.text(1250, sy + 64, "4397 → SHT31-D, 4210 → SCD41, 4210 → BH1750 · sensor_mount, substrate level",
           fill=T3, size=8)


climate(194, "climate-01", "shelf A")
climate(306, "climate-02", "shelf B", purple=True)
new_pill(1474, 296)

# ── relay node (outside) ─────────────────────────────────────────
s.comment("═══════ RELAY NODE (outside) + HX711 / reed runs ═══════")
s.rect(304, 384, 692, 332, fill="#0f1623", stroke=EDGE, sw=1)
s.text(318, 402, "Relay node", fill=T1, size=12, weight="700")
s.text(392, 402, "relay_board_mount, node=\"relay\" — 4 switch channels (UF4007 on each) + HX711 + door contact",
       fill=T2, size=9)
outlet(s, OX, 440, CB)
charger(s, CB, 440, CBW, "1 ft USB-C → relay")
esp32(s, 320, 412, 130, 248, "ESP32", "relay-01", "esp32_case", pins=[
    ("GND", 470, "gnd"), ("GPIO 32 HX DOUT", 486, "purple"), ("GPIO 33 HX SCK", 502, "purple"),
    ("3V3", 518, "v33"), ("GPIO 35 reed", 534, "purple"), ("GND", 550, "gnd"),
    ("GPIO 25", 578, "gpio"), ("GPIO 26", 594, "gpio"), ("GPIO 27", 610, "gpio"), ("GPIO 14", 626, "gpio"),
    ("GND", 646, "gnd")], usb_y=440)
usb(s, [(294, 440), (316, 440)])
# 22 AWG 4-conductor runs: HX711 (GND, DOUT, SCK, 3V3) and the reed (COM, NC)
cond = [(470, 456, 414, GND), (486, 462, 418, PUR), (502, 468, 422, PUR), (518, 474, 426, RED),
        (534, 494, 446, PUR), (550, 500, 450, GND)]
for py, vx, cy, colour in cond:
    s.path([(450, py), (vx, py), (vx, cy), (1180, cy)], colour, 1.8)
# 10K pull-up GPIO 35 → 3V3, at the relay end (between the 3V3 and GPIO 35 conductors)
s.line(520, 426, 520, 431, RED, 1.5, cap=None)
s.rect(516, 431, 8, 10, fill=CARD, stroke=TL, sw=1, rx=1)
s.line(520, 441, 520, 446, PUR, 1.5, cap=None)
s.circle(520, 426, 2.2, RED)
s.circle(520, 446, 2.2, PUR)
s.text(528, 439, "10K pull-up", fill=PUR_T, size=7, weight="700")
s.text(590, 437, "↑ 22 AWG 4-conductor → HX711: red 3V3 → VCC, black GND, yellow DOUT → 32, white SCK → 33",
       fill=PUR_T, size=8)
s.text(590, 461, "↑ second 22 AWG 4-conductor run (2 used) → door contact: COM → GPIO 35, alarm NC → GND",
       fill=PUR_T, size=8)
RY = [506, 544, 582, 620]
switch_board(s, 540, 466, 440, 200, "IRLZ44N switch board (relay_board_mount)", [
    dict(y=RY[0], name="CH0 fae — FAE fan (GPIO 25)", sub="100R gate · 10K pull-down · IRLZ44N · UF4007 across J2"),
    dict(y=RY[1], name="CH1 exhaust — exhaust fan (GPIO 26)", sub="same circuit"),
    dict(y=RY[2], name="CH2 circulation — circulation fan (GPIO 27)", sub="same circuit"),
    dict(y=RY[3], name="CH3 aux — peristaltic pump (GPIO 14)", sub="UF4007 across the pump · 60 s max-on",
         colour=PUR_T),
], plus_x=930, gnd_x=590, rail_top=492, rail_bottom=666)
s.text(596, 660, "GND bus", fill=GND_T, size=8, weight="600")
s.text(924, 660, "+12 V bus", fill=RED_T, size=8, weight="600", anchor="end")
s.path([(450, 578), (512, 578), (512, RY[0] - 4), (544, RY[0] - 4)], GRN, 2)
s.path([(450, 594), (518, 594), (518, RY[1] - 4), (544, RY[1] - 4)], GRN, 2)
s.path([(450, 610), (524, 610), (524, RY[2] - 4), (544, RY[2] - 4)], GRN, 2)
s.path([(450, 626), (530, 626), (530, RY[3] - 4), (544, RY[3] - 4)], GRN, 2)
s.path([(450, 646), (470, 646), (470, 674), (536, 674), (536, RY[3] + 6), (544, RY[3] + 6)], GND, 3)
callout(s, 604, 674, 220, 34, [("COMMON GROUND", True), ("ESP32 GND → J1 − → GND bus (both boards)", False)])
# loads: fans + pump
for i, (name, sub) in enumerate((("FAE fan — Noctua NF-A8 12 V", "fresh-air intake at the wall · fan_duct"),
                                 ("Exhaust fan — Noctua NF-A8 12 V", "exhaust at the wall · fan_duct"),
                                 ("Circulation fan — Noctua NF-A8 12 V", "inside, away from the sensors"))):
    y = RY[i]
    load_pair(s, 976, y, 1180)
    s.rect(1180, y - 16, 300, 32, fill=CARD, stroke=GRN_T, sw=1, rx=4)
    s.text(1190, y - 3, name, fill=T1, size=9, weight="600")
    s.text(1190, y + 10, sub, fill=T3, size=8)
load_pair(s, 976, RY[3], 1180)
s.rect(1180, RY[3] - 16, 390, 32, fill=CARD, stroke=PUR, sw=1.2, rx=4)
s.text(1190, RY[3] - 3, "Peristaltic pump — Adafruit 1150 12 V, in pump_bracket (new in Tier 3)", fill=T1, size=9, weight="600")
s.text(1190, RY[3] + 10, "18 AWG red/black leads · food-grade silicone tubing (2 × 4 mm) to the substrate", fill=T3, size=8)
wall_grommet(s, 406, 632)
s.text(1056, 652, "Fans: bundled 30 cm extension + Noctua NA-SEC3 (cut its far end): GND → J2 −, +12 V → J2 +",
       fill=T2, size=8)
s.text(1056, 664, "by pin position, not colour; tach + PWM unused. Pump: 18 AWG red/black, red → J2 +, black → J2 −.",
       fill=T2, size=8)
# HX711 + reed (inside)
s.rect(1180, 406, 390, 30, fill=CARD, stroke=PUR, sw=1.2, rx=4)
s.text(1190, 418, "HX711 (Adafruit 5974) + 5 kg cell (4541) in hx711_scale, under the grow block", fill=T1, size=8,
       weight="600")
s.text(1190, 430, "22/4 cable: red VCC · black GND · yellow DOUT · white SCK · cell red E+, black E− · 10 SPS",
       fill=T3, size=8)
s.rect(1180, 440, 390, 34, fill=CARD, stroke=PUR, sw=1.2, rx=4)
s.text(1190, 453, "Door contact (weideer MC-31B) on the door frame, magnet on the door", fill=T1, size=8,
       weight="600")
s.text(1190, 466, "COM → GPIO 35, alarm NC → GND (closed = door shut) · wired on NO? tick invert (reed_inv)",
       fill=T3, size=8)

# ── 12 V distribution ────────────────────────────────────────────
s.comment("═══════ 12 V DISTRIBUTION: PSU → pigtail → WAGO → fuses ═══════")
outlet(s, OX, 778, CB)
s.rect(CB, 736, CBW, 84, fill=CARD, stroke=RED, sw=1.5)
s.text(CB + CBW / 2, 754, "12V 10A PSU (120W)", fill=RED_T, size=10, weight="700", anchor="middle")
s.text(CB + CBW / 2, 768, "Facmogu AL-12100", fill=T2, size=8, anchor="middle")
s.text(CB + CBW / 2, 781, "power_supply_mount", fill=T3, size=8, anchor="middle")
s.text(CB + CBW / 2, 794, "5.5 × 2.5 mm barrel", fill=T3, size=8, anchor="middle")
s.text(CB + CBW / 2, 807, "load ≤ ~8 A", fill=T3, size=8, anchor="middle")
s.rect(290, 766, 10, 22, fill=BG, stroke="#94a3b8", sw=0.8, rx=2)
s.path([(300, 782), (546, 782)], GND, 3.5)
s.path([(300, 772), (330, 772), (330, 740), ("hop", 590, 740, 6, "h"), (866, 740), (866, 768), (886, 768)], RED, 3.5)
s.text(318, 804, "5.5 × 2.5 mm DC barrel pigtail — 14 AWG", fill=T2, size=8)
s.rect(546, 760, 88, 24, fill=CARD, stroke="#9ca3af", sw=1.2, rx=3)
s.text(590, 775, "WAGO 221-415 GND", fill=GND_T, size=7, weight="700", anchor="middle")
s.rect(886, 760, 88, 24, fill=CARD, stroke=RED, sw=1.2, rx=3)
s.text(930, 775, "WAGO 221-413 +12V", fill=RED_T, size=7, weight="700", anchor="middle")
s.line(590, 760, 590, 666, GND, 3, cap=None)
s.line(930, 760, 930, 666, RED, 3, cap=None)
s.fuse(923, 716, 14, 28, "", vertical=True)
s.text(916, 729, "3 A fuse", fill=RED_T, size=8, weight="700", anchor="end")
s.text(916, 740, "relay branch", fill=T3, size=7, anchor="end")
s.line(590, 784, 590, 868, GND, 3, cap=None)
s.line(930, 784, 930, 868, RED, 3, cap=None)
s.fuse(923, 804, 14, 28, "", vertical=True)
s.text(916, 817, "7.5 A fuse", fill=RED_T, size=8, weight="700", anchor="end")
s.text(916, 828, "lighting branch", fill=T3, size=7, anchor="end")
s.text(604, 816, "branches: 18 AWG red (+12 V, fused)", fill=T2, size=8)
s.text(604, 828, "and black (GND, not fused)", fill=T2, size=8)

# ── lighting node (outside) ──────────────────────────────────────
s.comment("═══════ LIGHTING NODE (outside), 4 channels ═══════")
s.rect(304, 842, 692, 290, fill="#0f1623", stroke=EDGE, sw=1)
s.text(318, 862, "Lighting node", fill=T1, size=12, weight="700")
s.text(318, 876, "relay_board_mount, node=\"lighting\" (PETG)", fill=T2, size=9)
s.text(318, 888, "no diodes — LED strips are resistive", fill=T2, size=9)
outlet(s, OX, 926, CB)
charger(s, CB, 926, CBW, "1 ft USB-C → lighting")
esp32(s, 320, 900, 120, 140, "ESP32", "lighting-01", "esp32_case",
      pins=[("GPIO 25", 956, "gpio"), ("GPIO 26", 972, "gpio"), ("GPIO 27", 988, "gpio"),
            ("GPIO 14", 1004, "gpio"), ("GND", 1024, "gnd")], usb_y=926)
usb(s, [(294, 926), (316, 926)])
LY = [916, 954, 992, 1030]
switch_board(s, 540, 868, 440, 196, "IRLZ44N switch board (relay_board_mount)", [
    dict(y=LY[0], name="CH0 white — 6500K strip (GPIO 25)", sub="100R gate · 10K pull-down · IRLZ44N · no diode"),
    dict(y=LY[1], name="CH1 blue — tri-spectrum BLUE wire (GPIO 26)", sub="same circuit"),
    dict(y=LY[2], name="CH2 red — tri-spectrum RED wire (GPIO 27)", sub="same circuit", colour=PUR_T),
    dict(y=LY[3], name="CH3 far_red — tri-spectrum GREEN wire (GPIO 14)", sub="same circuit (green = 730 nm)",
         colour=PUR_T),
], plus_x=930, gnd_x=590, rail_top=868, rail_bottom=1050)
s.text(596, 1058, "GND bus", fill=GND_T, size=8, weight="600")
s.text(924, 1058, "+12 V bus", fill=RED_T, size=8, weight="600", anchor="end")
s.path([(440, 956), (470, 956), (470, LY[0] - 4), (544, LY[0] - 4)], GRN, 2)
s.path([(440, 972), (478, 972), (478, LY[1] - 4), (544, LY[1] - 4)], GRN, 2)
s.path([(440, 988), (544, 988)], GRN, 2)
s.path([(440, 1004), (494, 1004), (494, LY[3] - 4), (544, LY[3] - 4)], GRN, 2)
s.path([(440, 1024), (462, 1024), (462, 1050), (520, 1050), (520, LY[3] + 6), (544, LY[3] + 6)], GND, 3)
callout(s, 320, 1076, 200, 40, [("COMMON GROUND", True), ("ESP32 GND → J1 − → GND bus", False)])
# strips
load_pair(s, 976, LY[0], 1180)
s.rect(1180, LY[0] - 16, 390, 32, fill=CARD, stroke=GRN_T, sw=1, rx=4)
s.text(1190, LY[0] - 3, "White 6500K LED strip — JOYLIT 5 m roll, cut to closet length", fill=T1, size=9, weight="600")
s.text(1190, LY[0] + 10, "red → J2 +, black → J2 − (18 AWG red/black pair)", fill=T3, size=8)
s.line(976, LY[1] - 5, 1180, LY[1] - 5, RED, 2)
for y in LY[1:]:
    s.line(976, y + 6, 1180, y + 6, GRN, 2)
s.rect(1180, LY[1] - 14, 390, 132, fill=CARD, stroke=PUR, sw=1.2, rx=4)
s.text(1192, LY[1] - 2, "common wire → +12 V (CH1 J2 +)", fill=RED_T, size=8, weight="600")
s.text(1192, LY[1] + 9, "BLUE wire (450 nm) → CH1 J2 −", fill=BLUE_T, size=8, weight="600")
s.text(1192, LY[2] + 9, "RED wire (660 nm) → CH2 J2 −", fill=RED_T, size=8, weight="600")
s.text(1192, LY[3] + 9, "GREEN wire (730 nm far-red) → CH3 J2 −", fill=GRN_T, size=8, weight="600")
s.text(1400, LY[1] + 30, "Tri-spectrum strip, IP67", fill=T1, size=9, weight="600", anchor="middle")
s.text(1400, LY[1] + 44, "one strip, three channels", fill=T2, size=8, anchor="middle")
s.text(1400, LY[1] + 58, "SuperLightingLED p-7120", fill=T3, size=8, anchor="middle")
s.text(1400, LY[1] + 72, "cut to length · heat-shrink", fill=T3, size=8, anchor="middle")
s.text(1400, LY[1] + 84, "every joint", fill=T3, size=8, anchor="middle")
wall_grommet(s, 904, 1044)
s.text(1056, 894, "18 AWG red/black pairs", fill=T2, size=8)

# ── Pi + 4 smart plugs ───────────────────────────────────────────
s.comment("═══════ PI + 4 SMART PLUGS ═══════")
outlet(s, OX, 1150, CB)
s.rect(CB, 1136, CBW, 28, fill=CARD, stroke=EDGE, sw=1, rx=4)
s.text(CB + CBW / 2 - 4, 1148, "Pi 27 W USB-C PSU", fill=T1, size=9, weight="600", anchor="middle")
s.text(CB + CBW / 2 - 4, 1159, "official, 5.1 V 5 A", fill=T3, size=7, anchor="middle")
usb(s, [(290, 1150), (330, 1150)])
s.rect(330, 1132, 290, 40, fill=CARD, stroke=WIFI, sw=1.5)
s.text(475, 1149, "Raspberry Pi 5 + Active Cooler (pi_case)", fill=T1, size=10, weight="600", anchor="middle")
s.text(475, 1164, "Server · Mosquitto :1883 / :8883 TLS · Web UI :3001", fill=T2, size=8, anchor="middle")
s.pill(640, 1136, 340, 18, "MQTT over WiFi — no wires from the Pi to any node or plug", "#0f2418", WIFI, WIFI)
s.text(640, 1168, "Plugs: User sp-3p, Topic = role, Full Topic tasmota/%topic%/%prefix%/ (required)",
       fill=YEL_T, size=8, weight="600")
plugs = [(1182, "Tasmota #1 · humidifier", YEL), (1208, "Tasmota #2 · dehumidifier", PUR),
         (1234, "Tasmota #3 · heater", YEL), (1260, "Tasmota #4 · cooler", PUR)]
for y, label, stroke in plugs:
    outlet(s, OX, y, None)
    s.rect(146, y - 11, 144, 22, fill=CARD, stroke=stroke, sw=1, rx=4)
    s.text(218, y + 3, label, fill=T1, size=8, weight="600", anchor="middle")
s.line(290, 1182, 1180, 1182, AC, 2.5)
s.rect(1180, 1168, 390, 28, fill=CARD, stroke=AC_T, sw=1, rx=4)
s.text(1190, 1180, "Ultrasonic humidifier (or piped in)", fill=T1, size=9, weight="600")
s.text(1190, 1191, "plug-humidifier (Topic humidifier)", fill=T3, size=8)
s.line(290, 1208, 640, 1208, AC, 2.5)
s.rect(640, 1196, 176, 24, fill=CARD, stroke=PUR, sw=1, rx=4)
s.text(648, 1206, "Dehumidifier (outside)", fill=T1, size=8, weight="600")
s.text(648, 1216, "intake facing the chamber", fill=T3, size=7)
s.line(290, 1234, 822, 1234, AC, 2.5)
s.rect(822, 1222, 176, 24, fill=CARD, stroke=AC_T, sw=1, rx=4)
s.text(830, 1232, "Space heater ≤ 1500 W (outside)", fill=T1, size=8, weight="600")
s.text(830, 1242, "aimed at the intake", fill=T3, size=7)
s.line(290, 1260, 1180, 1260, AC, 2.5)
s.rect(1180, 1246, 390, 28, fill=CARD, stroke=PUR, sw=1, rx=4)
s.text(1190, 1258, "Peltier cooler at the chamber wall", fill=T1, size=9, weight="600")
s.text(1190, 1269, "plug-cooler (Topic cooler) · plugs #2 + #4 are new in Tier 3", fill=T3, size=8)
wall_grommet(s, 1172, 1192)
wall_grommet(s, 1250, 1270)

# ── bottom: pump channel end to end, legend, budget ──────────────
channel_detail(
    s, 1296,
    "One switch-board channel, end to end — CH3 aux (peristaltic pump) on relay_board_mount",
    "Every relay and lighting channel is this circuit; fans use a 4-pin PWM extension lead instead, and the "
    "lighting board leaves out the UF4007.",
    "12V 10A", "GPIO 14", "3 A fuse", "Peristaltic pump",
    ["Adafruit 1150, 12 V", "pump_bracket", "inside the chamber"],
    "18 AWG red/black", "pump leads", "60 s max-on backstop (aux)", "red (+)", "black (−)")
legend(s, 1046, 1296, 538, 170, purple=True, extra=(
    "Wire: 14 AWG pigtail · 18 AWG red/black for every 12 V run (strips, pump) · 22 AWG hookup",
    "or Dupont for GPIO / GND → J1 · 22 AWG 4-conductor for the HX711 + reed. Heat-shrink splices.",
))
s.rect(1046, 1474, 538, 84, fill=CARD, stroke=RED, sw=1)
s.text(1060, 1494, "12 V branches and fuses (inline blade fuse on each +12 V branch)", fill=RED_T, size=10,
       weight="700")
for i, t in enumerate((
        "Relay board: 3 A — three fans + the pump stay under ~1 A.",
        "Lighting board: 7.5 A — the strips are the load. GND branches are not fused.",
        "12V 10A PSU: keep the total ≤ ~8 A — cut the strips to closet length.")):
    s.text(1060, 1512 + i * 15, t, fill=TL, size=9)

steps(s, 1568, 176, [
    (30, "1 · Mains and 12 V (outside)", AC_T, [
        "Strip (12 + 2 USB-A): Pi PSU, 12 V PSU, 6 chargers, 4 plugs.",
        "PSU barrel → 14 AWG pigtail → WAGO 221-413 / 221-415.",
        "221-413 → inline 3 A fuse → relay +12 V bus (18 AWG red).",
        "221-413 → inline 7.5 A fuse → lighting +12 V bus (18 AWG red).",
        "221-415 → both boards' GND bus (18 AWG black).",
        "ESP32 GND → J1 − on both boards: the COMMON GROUND.",
    ]),
    (420, "2 · Switch channels + loads", GRN_T, [
        "GPIO → Dupont → J1 IN → 100R → gate; 10K gate → source.",
        "Drain → J2 −; J2 + → +12 V bus; UF4007 on relay channels.",
        "Fans: NA-SEC3 extension, far end cut — GND → J2 −, +12 V → J2 +.",
        "Pump on CH3 aux (GPIO 14): 18 AWG, UF4007 across it.",
        "Strips: 18 AWG red/black. BLUE wire → CH1, RED → CH2,",
        "GREEN (730 nm) → CH3, common wire → +12 V.",
    ]),
    (810, "3 · HX711 + door contact (relay node)", PUR_T, [
        "22/4: red 3V3 → VCC, black GND, yellow DOUT → 32, white SCK → 33.",
        "22 AWG 4-conductor (2 used): COM → GPIO 35, alarm NC → GND.",
        "EXTERNAL 10K pull-up GPIO 35 → 3V3 (no internal pull on 34-39).",
        "Wired on NO? Tick the portal's invert box (reed_inv).",
        "Tick HX711 + door reed under Optional peripherals.",
        "Cell red → E+, black → E−; tare, then calibrate once.",
    ]),
    (1200, "4 · Climate, cameras, plugs", BLUE_T, [
        "Each climate node: 4397 on 3V3 / GND / GPIO 21 / GPIO 22,",
        "QT plug → SHT31-D, 4210 → SCD41, 4210 → BH1750.",
        "climate-01/02 + cam-01/02: 6 ft (2 m) USB through the grommet.",
        "Relay + lighting ESP32s stay outside on short cables.",
        "Plugs: humidifier, dehumidifier, heater, cooler —",
        "WiFi only, sp-3p + Full Topic (see the build guide).",
    ]),
], footnote=(1200, "ESP32-S3 nodes use other pins (build guide §8a); S3 cameras: §8b."))

s.comment("═══════════════════════ FOOTER ═══════════════════════")
s.text(800, 1760, "SporePrint  |  Tier 3: All The Things  |  github.com/59psi/SporePrint", fill="#334155", size=9,
       anchor="middle")

open(OUT, "w").write(s.to_string())
print("wrote", OUT)
