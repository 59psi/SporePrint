"""Tiny SVG writer in the SporePrint wiring-diagram style (dark theme)."""
from xml.sax.saxutils import escape

FONT = "system-ui, -apple-system, sans-serif"

# palette (same as the existing diagrams) + the cabling additions
BG = "#0a0a0f"
PANEL = "#111827"
CARD = "#1e293b"
EDGE = "#475569"
T1 = "#e2e8f0"   # primary text
T2 = "#94a3b8"   # secondary
T3 = "#6b7280"   # muted
TL = "#d1d5db"   # light
RED, RED_T = "#ef4444", "#fca5a5"
GND, GND_T = "#4b5563", "#d1d5db"
BLUE, BLUE_T = "#3b82f6", "#93c5fd"
YEL, YEL_T = "#eab308", "#fde047"
GRN, GRN_T = "#22c55e", "#86efac"
PUR, PUR_T = "#a78bfa", "#c4b5fd"
WIFI = "#34d399"
AC, AC_T = "#f97316", "#fdba74"      # 120 V AC cords
USB, USB_T = "#22d3ee", "#67e8f9"    # USB 5 V cables
CHAMBER, CHAMBER_T = "#2dd4bf", "#5eead4"


class Svg:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.out = []

    def raw(self, s):
        self.out.append(s)

    def comment(self, s):
        self.out.append(f"\n  <!-- {s} -->")

    def rect(self, x, y, w, h, fill=CARD, stroke=EDGE, sw=1, rx=6, dash=None, opacity=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o = f' opacity="{opacity}"' if opacity is not None else ""
        s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.out.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s}{d}{o}/>')

    def text(self, x, y, s, fill=T2, size=10, weight=None, anchor=None, italic=False, rotate=None):
        a = f' text-anchor="{anchor}"' if anchor else ""
        wgt = f' font-weight="{weight}"' if weight else ""
        it = ' font-style="italic"' if italic else ""
        rot = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
        self.out.append(
            f'  <text x="{x}" y="{y}"{a} fill="{fill}" font-family="{FONT}" font-size="{size}"{wgt}{it}{rot}>'
            f"{escape(s)}</text>")

    def line(self, x1, y1, x2, y2, stroke, sw=2, dash=None, cap="round"):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        c = f' stroke-linecap="{cap}"' if cap else ""
        self.out.append(f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{c}{d}/>')

    def path(self, pts, stroke, sw=2, dash=None, cap="round", join="round"):
        """Polyline through pts; a ('hop', x, y, r, axis) entry draws a bridge
        over a crossing wire at (x, y)."""
        d = []
        for i, p in enumerate(pts):
            if p[0] == "hop":
                _, x, y, r, axis = p
                if axis == "h":   # travelling horizontally, hop up over a vertical wire
                    prev = pts[i - 1]
                    sign = 1 if x > prev[0] else -1
                    d.append(f"L {x - sign * r} {y} A {r} {r} 0 0 {1 if sign > 0 else 0} {x + sign * r} {y}")
                else:            # travelling vertically, hop right over a horizontal wire
                    prev = pts[i - 1]
                    sign = 1 if y > prev[1] else -1
                    d.append(f"L {x} {y - sign * r} A {r} {r} 0 0 {0 if sign > 0 else 1} {x} {y + sign * r}")
                continue
            d.append(("M" if i == 0 else "L") + f" {p[0]} {p[1]}")
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        self.out.append(f'  <path d="{" ".join(d)}" fill="none" stroke="{stroke}" stroke-width="{sw}" '
                        f'stroke-linecap="{cap}" stroke-linejoin="{join}"{dd}/>')

    def circle(self, cx, cy, r, fill, stroke=None, sw=0.5):
        s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.out.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"{s}/>')

    def pill(self, x, y, w, h, label, fill, stroke, tfill, size=8, weight="600"):
        self.out.append("  <g>")
        self.rect(x, y, w, h, fill=fill, stroke=stroke, sw=0.6, rx=4)
        self.text(x + w / 2, y + h / 2 + size * 0.36, label, fill=tfill, size=size, weight=weight, anchor="middle")
        self.out.append("  </g>")

    def fuse(self, x, y, w, h, label, vertical=False):
        """Inline blade-fuse holder symbol with its rating."""
        self.rect(x, y, w, h, fill="#2a0a0a", stroke=RED, sw=1.2, rx=3)
        if vertical:
            self.line(x + w / 2, y + 4, x + w / 2, y + h - 4, RED_T, 1, cap=None)
        else:
            self.line(x + 4, y + h / 2, x + w - 4, y + h / 2, RED_T, 1, cap=None)
        self.text(x + w / 2, y - 4, label, fill=RED_T, size=8, weight="700", anchor="middle")

    def grommet(self, x, y, w, h):
        self.rect(x, y, w, h, fill=BG, stroke="#94a3b8", sw=1.2, rx=min(w, h) / 2)

    def to_string(self, title_comment=""):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
                f'width="{self.w}" height="{self.h}">\n')
        if title_comment:
            head += f"  <!-- {title_comment} -->\n"
        head += f'\n  <!-- Background -->\n  <rect width="{self.w}" height="{self.h}" fill="{BG}"/>\n'
        return head + "\n".join(self.out) + "\n\n</svg>\n"
