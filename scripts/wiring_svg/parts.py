"""Reusable SporePrint wiring-diagram parts (built on svglib)."""
from svglib import *  # noqa: F401,F403


def frame(s, top, bottom, wall_x=1012, inside_right=1584, outside_left=16, wall_label_y=None,
          wall_label="CHAMBER WALL — 7/8 in. grommet / tent cable port"):
    """Outside panel | chamber wall band | inside panel."""
    s.comment("═══════ OUTSIDE THE CHAMBER (dry side) ═══════")
    s.rect(outside_left, top, wall_x - 8 - outside_left, bottom - top, fill=PANEL, stroke=EDGE, sw=1)
    s.text(outside_left + 16, top + 22, "OUTSIDE THE CHAMBER — the dry side", fill=T1, size=12, weight="700")
    s.comment("═══════ CHAMBER WALL ═══════")
    s.rect(wall_x, top, 26, bottom - top, fill="#1f2937", stroke="#64748b", sw=1, rx=4, dash="4,3")
    mid = wall_label_y if wall_label_y is not None else (top + bottom) / 2
    s.text(wall_x + 17, mid, wall_label,
           fill=T2, size=9, anchor="middle", rotate=-90)
    s.comment("═══════ INSIDE THE GROW CHAMBER ═══════")
    s.rect(wall_x + 34, top, inside_right - wall_x - 34, bottom - top, fill="#0b1716", stroke=CHAMBER, sw=1.2,
           dash="6,4")
    s.text(wall_x + 50, top + 22, "INSIDE THE GROW CHAMBER (85-95 % RH)", fill=CHAMBER_T, size=12, weight="700")


def wall_grommet(s, y1, y2, wall_x=1012):
    s.grommet(wall_x + 3, y1, 20, y2 - y1)


def power_strip(s, x, y, w, h, outlets_text):
    s.comment("Power strip (mains, outside the chamber)")
    s.rect(x, y, w, h, fill=CARD, stroke=AC, sw=1.5, rx=8)
    cx = x + w / 2
    s.text(cx, y + 20, "Power strip", fill=AC_T, size=11, weight="700", anchor="middle")
    s.text(cx, y + 34, "UL-listed surge", fill=T2, size=8, anchor="middle")
    s.text(cx, y + 46, "protector", fill=T2, size=8, anchor="middle")
    s.text(cx, y + 58, outlets_text, fill=T2, size=8, anchor="middle")
    s.text(cx, y + 70, "widely spaced", fill=T2, size=8, anchor="middle")
    s.text(cx, y + 82, "outlets", fill=T2, size=8, anchor="middle")
    s.text(cx, y + h - 22, "cord to a", fill=T3, size=8, anchor="middle")
    s.text(cx, y + h - 11, "wall outlet", fill=T3, size=8, anchor="middle")


def outlet(s, x, y, to_x):
    """An outlet on the strip's right edge at height y, with its cord to to_x."""
    s.rect(x, y - 9, 24, 18, fill=BG, stroke=AC_T, sw=0.8, rx=3)
    s.line(x + 8, y - 4, x + 8, y + 4, AC_T, 1.4, cap=None)
    s.line(x + 16, y - 4, x + 16, y + 4, AC_T, 1.4, cap=None)
    if to_x is not None:
        s.line(x + 24, y, to_x, y, AC, 2.5)


def charger(s, x, y, w, sub):
    s.rect(x, y - 16, w, 32, fill=CARD, stroke=EDGE, sw=1, rx=4)
    s.text(x + w / 2 - 4, y - 3, "5 V USB charger", fill=T1, size=9, weight="600", anchor="middle")
    s.text(x + w / 2 - 4, y + 10, sub, fill=T3, size=8, anchor="middle")
    s.rect(x + w - 4, y - 5, 8, 10, fill=BG, stroke=USB_T, sw=0.8, rx=1)


def usb(s, pts, sw=2.5):
    s.path(pts, USB, sw)


def esp32(s, x, y, w, h, title, sub, sub2=None, pins=(), usb_y=None):
    """pins: (label, y, kind) with kind in gpio/gnd/v33/sda/scl/purple; dots on the right edge."""
    s.rect(x, y, w, h, fill=CARD, stroke=EDGE, sw=1.5)
    s.text(x + w / 2, y + 17, title, fill=T1, size=11, weight="600", anchor="middle")
    s.text(x + w / 2, y + 31, sub, fill=T2, size=9, anchor="middle")
    if sub2:
        s.text(x + w / 2, y + 44, sub2, fill=T3, size=8, anchor="middle")
    colours = {"gpio": (GRN, GRN_T), "gnd": ("#1e1e1e", GND_T), "v33": (RED, RED_T), "sda": (BLUE, BLUE_T),
               "scl": (YEL, YEL_T), "purple": (PUR, PUR_T)}
    for label, py, kind in pins:
        dot, tc = colours[kind]
        s.text(x + w - 8, py + 3, label, fill=tc, size=8, weight="600", anchor="end")
        if kind == "gnd":
            s.circle(x + w, py, 3.5, dot, stroke="#9ca3af", sw=1)
        else:
            s.circle(x + w, py, 3.5, dot)
    if usb_y is not None:
        s.rect(x - 4, usb_y - 6, 8, 12, fill=BG, stroke=USB_T, sw=0.8, rx=1)


def switch_board(s, x, y, w, h, title, rows, plus_x, gnd_x, rail_top, rail_bottom):
    """rows: dicts(y, name, sub, colour, j2=True). J1 on the left, J2 on the right."""
    s.rect(x, y, w, h, fill="#16202f", stroke="#64748b", sw=1.2, rx=4)
    s.text(x + w / 2, y + 15, title, fill=T2, size=9, weight="600", anchor="middle")
    # rails
    s.line(gnd_x, rail_top, gnd_x, rail_bottom, GND, 3.5, cap=None)
    s.line(plus_x, rail_top, plus_x, rail_bottom, RED, 3.5, cap=None)
    for r in rows:
        ry = r["y"]
        # J1 (control input) — IN + "−"
        s.rect(x + 4, ry - 13, 38, 26, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=3)
        s.text(x + 23, ry - 2, "J1 IN", fill=T2, size=7, weight="600", anchor="middle")
        s.text(x + 23, ry + 9, "J1 −", fill=T2, size=7, weight="600", anchor="middle")
        s.line(x + 42, ry + 6, gnd_x, ry + 6, GND, 1.5, cap=None)
        tc = r.get("colour", GRN_T)
        s.text(gnd_x + 8, ry - 2, r["name"], fill=tc, size=9, weight="600")
        s.text(gnd_x + 8, ry + 10, r["sub"], fill=T3, size=8)
        # J2 (load output) — "+" and "−"
        s.rect(x + w - 42, ry - 13, 38, 26, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=3)
        s.text(x + w - 23, ry - 2, "J2 +", fill=RED_T, size=7, weight="600", anchor="middle")
        s.text(x + w - 23, ry + 9, "J2 −", fill=GRN_T, size=7, weight="600", anchor="middle")
        s.line(plus_x, ry - 5, x + w - 42, ry - 5, RED, 1.5, cap=None)


def load_pair(s, x1, y, x2, label=None, label_x=None, label_y=None, plus_dy=-5, minus_dy=6):
    """+ (red) and switched − (green) pair from J2 to a load."""
    s.line(x1, y + plus_dy, x2, y + plus_dy, RED, 2)
    s.line(x1, y + minus_dy, x2, y + minus_dy, GRN, 2)
    if label:
        s.text(label_x, label_y, label, fill=T2, size=8)


def callout(s, x, y, w, h, lines, stroke=YEL, title_fill=YEL_T):
    s.rect(x, y, w, h, fill=BG, stroke=stroke, sw=0.8, rx=4, dash="3,2")
    for i, (t, bold) in enumerate(lines):
        s.text(x + 8, y + 13 + i * 12, t, fill=title_fill if bold else TL, size=8, weight="700" if bold else None)


def legend(s, x, y, w, h, extra=(), purple=False):
    s.comment("═══════ LEGEND ═══════")
    s.rect(x, y, w, h, fill=CARD, stroke=EDGE, sw=1)
    s.text(x + 14, y + 20, "Legend", fill=T1, size=11, weight="600")
    c1, c2 = x + 14, x + w / 2 + 6
    rows1 = [(RED, None, "RED = +12 V (and 3V3 on the QT cable)", RED_T),
             ("#1e1e1e", "#6b7280", "BLACK = GND / 12 V −", GND_T),
             (GRN, None, "GREEN = GPIO signal / switched (drain) side", GRN_T),
             (BLUE, None, "BLUE = SDA, YELLOW = SCL (STEMMA QT)", BLUE_T)]
    rows2 = [(AC, None, "ORANGE = 120 V AC cord (power strip)", AC_T),
             (USB, None, "CYAN = USB 5 V power cable", USB_T),
             (WIFI, "dash", "dashed = WiFi / MQTT, no wire", WIFI),
             (None, "grommet", "= cable through the chamber wall", T2)]
    if purple:
        rows1.append((PUR, None, "PURPLE = new in Tier 3 (HX711 / reed signals)", PUR_T))
    for col, rows in ((c1, rows1), (c2, rows2)):
        for i, (colr, extra_style, label, tc) in enumerate(rows):
            ly = y + 40 + i * 18
            if extra_style == "grommet":
                s.grommet(col, ly - 6, 30, 12)
            elif extra_style == "dash":
                s.line(col, ly, col + 30, ly, colr, 2, dash="5,3")
            else:
                s.line(col, ly, col + 30, ly, colr, 3)
                if extra_style:
                    s.rect(col, ly - 2, 30, 4, fill="none", stroke=extra_style, sw=0.5, rx=1)
            s.text(col + 38, ly + 4, label, fill=tc, size=9)
    n = max(len(rows1), len(rows2))
    for i, t in enumerate(extra):
        s.text(x + 14, y + 40 + n * 18 + 8 + i * 14, t, fill=T2, size=9)


def channel_detail(s, y0, title, sub, psu_label, gpio_label, fuse_label, load_title, load_sub, lead_top, lead_bottom,
                   lead_note, plus_wire, minus_wire, lead_colour=T2):
    """The 'one channel end to end' panel (x 16..1004, height 262) starting at y0."""
    s.comment("═══════ ONE CHANNEL, END TO END ═══════")
    o = y0 - 1044  # geometry below was laid out for y0 = 1044
    s.rect(16, 1044 + o, 988, 262, fill=PANEL, stroke=EDGE, sw=1)
    s.text(30, 1066 + o, title, fill=T1, size=12, weight="700")
    s.text(30, 1081 + o, sub, fill=T2, size=9)
    YP, YS, YG = 1106 + o, 1186 + o, 1262 + o
    s.rect(30, 1096 + o, 90, 178, fill=CARD, stroke=RED, sw=1.5)
    s.text(75, 1176 + o, psu_label, fill=RED_T, size=10, weight="700", anchor="middle")
    s.text(75, 1190 + o, "PSU", fill=T2, size=9, anchor="middle")
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
    s.fuse(290, YP - 8, 46, 16, fuse_label)
    s.line(336, YP, 690, YP, RED, 2.5)
    s.text(520, YP - 6, "+12 V bus → J2 +", fill=RED_T, size=8, weight="600", anchor="middle")
    s.rect(690, 1094 + o, 34, 90, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=3)
    s.text(707, 1090 + o, "J2", fill=T2, size=8, weight="600", anchor="middle")
    s.text(707, YP + 4, "+", fill=RED_T, size=10, weight="700", anchor="middle")
    s.text(707, 1174 + o, "−", fill=GRN_T, size=10, weight="700", anchor="middle")
    s.line(724, YP, 850, YP, RED, 2.5)
    s.line(724, 1170 + o, 850, 1170 + o, GRN, 2.5)
    s.text(787, YP - 6, plus_wire, fill=RED_T, size=8, anchor="middle")
    s.text(787, 1164 + o, minus_wire, fill=GRN_T, size=8, anchor="middle")
    s.text(787, 1140 + o, lead_top, fill=lead_colour, size=8, weight="600", anchor="middle")
    s.text(787, 1151 + o, lead_bottom, fill=lead_colour, size=8, weight="600", anchor="middle")
    s.text(787, 1190 + o, lead_note, fill=T3, size=7, anchor="middle")
    s.rect(850, 1092 + o, 140, 92, fill=CARD, stroke=GRN_T, sw=1, rx=4)
    s.text(920, 1126 + o, load_title, fill=T1, size=10, weight="600", anchor="middle")
    for i, t in enumerate(load_sub):
        s.text(920, 1141 + o + i * 14, t, fill=CHAMBER_T if i == len(load_sub) - 1 else T2, size=8, anchor="middle")
    s.line(676, YP, 676, 1170 + o, "#94a3b8", 1.5, cap=None)
    s.raw(f'  <path d="M 668 {1152 + o} L 684 {1152 + o} L 676 {1138 + o} Z" fill="#94a3b8"/>')
    s.line(668, 1136 + o, 684, 1136 + o, "#e2e8f0", 2, cap=None)
    s.circle(676, YP, 3, RED)
    s.circle(676, 1170 + o, 3, GRN)
    s.text(666, 1136 + o, "UF4007", fill=TL, size=8, weight="600", anchor="end")
    s.text(666, 1147 + o, "band to +12 V", fill=T3, size=7, anchor="end")
    s.rect(560, 1152 + o, 70, 52, fill=CARD, stroke=YEL, sw=1.5, rx=4)
    s.text(595, 1172 + o, "IRLZ44N", fill=YEL_T, size=9, weight="700", anchor="middle")
    s.text(566, 1190 + o, "G", fill=T3, size=7)
    s.text(620, 1174 + o, "D", fill=T3, size=7)
    s.text(591, 1200 + o, "S", fill=T3, size=7)
    s.line(630, 1170 + o, 690, 1170 + o, GRN, 2.5)
    s.text(650, 1164 + o, "drain", fill=T3, size=7, anchor="middle")
    s.line(595, 1204 + o, 595, YG, GND, 2.5)
    s.rect(400, 1166 + o, 40, 58, fill="#0f172a", stroke="#94a3b8", sw=0.8, rx=3)
    s.text(420, 1162 + o, "J1", fill=T2, size=8, weight="600", anchor="middle")
    s.text(420, YS + 3, "IN", fill=GRN_T, size=8, weight="600", anchor="middle")
    s.text(420, 1215 + o, "−", fill=GND_T, size=10, weight="700", anchor="middle")
    s.line(440, YS, 470, YS, GRN, 2)
    s.rect(470, YS - 8, 50, 16, fill=CARD, stroke=GRN_T, sw=1, rx=3)
    s.text(495, YS + 3, "100R", fill=GRN_T, size=8, weight="600", anchor="middle")
    s.text(495, YS - 12, "gate resistor", fill=T3, size=7, anchor="middle")
    s.line(520, YS, 560, YS, GRN, 2)
    s.circle(540, YS, 3, GRN)
    s.line(540, YS, 540, 1214 + o, "#94a3b8", 1.5, cap=None)
    s.rect(531, 1214 + o, 18, 30, fill=CARD, stroke="#94a3b8", sw=1, rx=2)
    s.text(540, 1232 + o, "10K", fill=TL, size=7, weight="600", anchor="middle", rotate=-90)
    s.line(540, 1244 + o, 540, YG, GND, 1.5)
    s.text(527, 1232 + o, "pull-down", fill=T3, size=7, anchor="end")
    s.path([(440, 1212 + o), (460, 1212 + o), (460, YG)], GND, 2.5)
    s.line(240, YG, 600, YG, GND, 3.5)
    s.text(300, YG - 6, "18 AWG black → GND bus", fill=GND_T, size=8)
    s.rect(270, 1138 + o, 90, 88, fill=CARD, stroke=EDGE, sw=1.5)
    s.text(315, 1155 + o, "ESP32", fill=T1, size=10, weight="600", anchor="middle")
    s.text(315, 1168 + o, "relay node", fill=T2, size=8, anchor="middle")
    s.text(354, YS + 3, gpio_label, fill=GRN_T, size=7, weight="600", anchor="end")
    s.text(354, 1215 + o, "GND", fill=GND_T, size=7, weight="600", anchor="end")
    s.circle(360, YS, 3.5, GRN)
    s.circle(360, 1212 + o, 3.5, "#1e1e1e", stroke="#9ca3af", sw=1)
    s.line(360, YS, 400, YS, GRN, 2)
    s.line(360, 1212 + o, 400, 1212 + o, GND, 3)
    s.text(380, YS - 5, "Dupont", fill=GRN_T, size=7, anchor="middle")
    s.line(250, 1200 + o, 270, 1200 + o, USB, 2.5)
    s.text(258, 1194 + o, "USB", fill=USB_T, size=7, anchor="middle")
    s.rect(356, 1203 + o, 48, 18, fill="none", stroke=YEL, sw=1, rx=3, dash="3,2")
    s.pill(330, 1228 + o, 100, 14, "COMMON GROUND", "#2a1f00", YEL, YEL_T, size=7)
    s.text(30, 1296 + o, "COMMON GROUND: ESP32 GND → J1 − → GND bus → WAGO 221-415 → PSU −. Leave it out and the gate "
           "has no reference — the channel never switches. Do it on both boards.", fill=YEL_T, size=9, weight="600")


def steps(s, y0, h, cols, footnote=None):
    s.comment("═══════ WIRING STEPS ═══════")
    s.rect(16, y0, 1568, h, fill=PANEL, stroke=EDGE, sw=1)
    s.text(30, y0 + 22, "Wiring Steps", fill=T1, size=13, weight="700")
    for x, head, colour, lines in cols:
        s.text(x, y0 + 44, head, fill=colour, size=10, weight="700")
        for i, t in enumerate(lines):
            s.text(x, y0 + 62 + i * 15, t, fill=TL, size=9)
    if footnote:
        s.text(footnote[0], y0 + h - 8, footnote[1], fill=T2, size=9, italic=True)
