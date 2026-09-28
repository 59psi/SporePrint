// SporePrint MOSFET Channel Board (relay_board_mount)
// A printed "perfboard" chassis for the 4-channel IRLZ44N switch stage used
// TWICE in Tier 2/3: once by the relay node (FAE / EXH / CIRC / AUX fans)
// and once by the lighting node (WHT / BLU / RED / FR LED strips). Every
// part is through-hole: its leads/pins drop through the plate and are
// soldered point-to-point on the UNDERSIDE, inside a 6 mm deep tray formed
// by a perimeter rim, so no joint can touch the wall or a metal wire shelf.
// Each component sits in a shallow recessed seat that locates it while you
// solder.
//
// ── Fits (per channel; dimensions from the vendor drawings) ────────────────
//   Q  IRLZ44NPbF, TO-220AB (Infineon/IR datasheet "TO-220AB Package
//      Outline"): body 10.29-10.54 W, body+tab 14.84-15.24 L, 4.20-4.69
//      thick, tab hole Ø3.54-3.78, leads 13.47-14.09 long (1.15-1.40 wide
//      for the first 3.55-4.06, then 0.69-0.93; 0.46-0.55 thick; 2.54
//      pitch; lead plane 2.64-2.92 from the tab face). Stands UPRIGHT with
//      the tab in free air (it is the drain and gets hot — see Heat below):
//      seat 11.4 x 5.5 (≥0.43 / ≥0.40 per side), leads through an 8.3 x 2.6
//      slot. Order G-D-S left to right with the MARKING facing the FRONT
//      (tab to the back); the seat's "G" mark is the gate side.
//   J  2-position 5.08 mm screw terminal. Seats are sized to take EITHER
//      - generic KF301-2P / DG301 (Handson Technology KF301-2P drawing):
//        10.0 (5.0 pitch) / 10.16 (5.08 pitch) x 7.5 x 10.0 tall, Ø1.0 pins
//        4.5 long, pin row 4.0-4.2 from the back (non-wire) face, or
//      - Phoenix Contact MKDS 1,5/ 2-5,08 (1715721, PxC datasheet drawing):
//        10.16 x 9.8 x 13.8 tall, 0.9 x 0.9 pins 3.5 long, pin row 4.6
//        (or 5.2) from the back face.
//      Seat 11.0 x 10.6 (≥0.42 per side on the length, ≥0.4 on the
//      MKDS depth), OPEN to the plate edge on the wire side so the wire
//      and ferrule never touch the plate. Push each terminal against the
//      INNER (MOSFET-side) edge of its seat before soldering: the pin slot
//      (8.0 x 3.2) covers both families' pin rows from that stop.
//      J2 (back row) = load output: "+" pin → +12 V, "−" pin → drain.
//      J1 (front row, input_terminals=true) = control input: "IN" pin ←
//      ESP32 GPIO, "−" pin ← ESP32 GND.
//   R1 100 Ω gate resistor and R2 10 kΩ gate pull-down: 1/4 W axial
//      (Yageo MFR-25: body 6.3±0.5 x Ø2.4±0.2, leads Ø0.6) — lie flat on
//      the plate, leads bent to 10.16 mm (0.4") into Ø1.5 holes.
//   D1 flyback diode, DO-41 / DO-204AL (1N4007, UF4007, 1N5819; Vishay
//      outline: body ≤5.2 x Ø2.7, leads Ø0.86) — same 10.16 mm footprint,
//      cathode band toward the "+" side (engraved bar marks it). Resistive
//      LED loads don't need it (the lighting board takes no diodes);
//      fans/pumps/solenoids do.
//   Optional clip-on heatsink (heatsink=true): Aavid/Boyd 574502B00000G
//      ("slide on heat sink featuring spring action", Aavid board-level
//      catalog p.45): 21.84 W x 10.03 D x 19.05 H; the B03300G version's two
//      solder tabs (20.57 apart) go through the mosfet_tab_slot slots.
//      The channel pitch widens to 21.84 + 2.5 = 24.34 mm so neighbouring
//      heatsinks (each at its own DRAIN potential) never touch.
//
// ── Wiring (underside, per channel) ────────────────────────────────────────
//   J1 IN → R1 → Q gate;  R2 from Q gate to Q source;  Q source → GND bus;
//   J1 "−" → GND bus;  Q drain → J2 "−" and D1 anode;  D1 cathode → J2 "+";
//   J2 "+" → +12 V bus. Run the +12 V and GND buses (≥18 AWG) along the
//   underside and out through the rim openings at either end (PSU and
//   ESP32 GND). Trim every lead/pin to ≤ 3 mm below the plate after
//   soldering — the TO-220 legs are 13.5 mm long and MUST be cut (or bent
//   flat) or they hit the wall.
//
// ── Heat ────────────────────────────────────────────────────────────────────
//   The firmware PWMs every channel at 25 kHz; with a 3.3 V gate through
//   100 Ω an IRLZ44N can dissipate ~1 W or more on a 1-2 A LED strip. The
//   TO-220 stands in free air with its tab clear of plastic (only the body
//   foot and leads touch the seat). Print this part in PETG for the
//   lighting node or any channel above ~0.5 A. The clip-on heatsinks
//   (heatsink=true) are optional (recommended above ~1 A per channel,
//   required above ~2 A) and not in the BOM: an LED strip cut to closet
//   length stays around 1 A. Fans alone (≤0.1 A) are fine in PLA without
//   heatsinks.
//
// ── Construction / hardware to buy ─────────────────────────────────────────
//   ONE printed piece: no printed-to-printed joint, so no inserts are
//   needed for the part itself.
//   Wall/shelf mounting, pick one:
//     mount="screw" (default): 4 x Ø3.4 through holes in the corner feet —
//       M3 or #4 pan-head screws, length = 9 mm plate+foot + your anchor
//       (M3 x 16 into a wall plug / nut; #4 x 3/4" wood screw). Head Ø ≤ 7.
//     mount="insert": 4 x M3 brass heat-set inserts, M3 x 5.7 standard
//       (ruthex RX-M3x5.7 / CNC Kitchen M3x5.7, Ø4.0 pocket), pressed into
//       the foot faces (they face UP as printed — press them before
//       mounting). The plate then bolts FROM BEHIND through a panel:
//       4 x M3 socket/pan-head, length = panel thickness + 5.7 rounded
//       DOWN to stock (M3 x 8 for a 3 mm panel, M3 x 10 for 4-5 mm; the
//       value for your panel is sp_screw_len("M3", t, false), echoed for
//       3 mm at render time). Panel holes Ø3.4 on the corner-hole pitch
//       echoed at render time (90.8 x 39.3 mm for the 4-channel default).
//     Zip ties (either mode): ties ≤ 2.5 mm wide x ≤ 1.3 mm thick through
//       the two slot pairs in the end margins (15 mm apart, around a shelf
//       wire).
//   Per board: 4 x IRLZ44N, 4 x 100 Ω, 4 x 10 kΩ (1/4 W — 1/2 W bodies
//     don't fit the seats), 4 x DO-41 diode (relay board only; the
//     lighting board takes none),
//     4 x 2-pos 5.08 mm terminal (J2) + 4 more for J1 when
//     input_terminals=true (8 per board, 16 for Tier 3's two boards),
//     optional 4 x Aavid 574502B00000G (or B03300G) heatsinks.
//
// ── Printing ────────────────────────────────────────────────────────────────
//   PETG (lighting node / >0.5 A) or PLA (fans only), 0.2 mm layers,
//   3 walls, 20 % infill. Print exactly as rendered: COMPONENT FACE DOWN on
//   the bed (the labels are engraved into that face and come out crisp on
//   the plate), rim and feet pointing up. NO SUPPORTS: every seat is a
//   recess in the bed face, so the only overhangs are ≤ 11 mm bridges
//   over the terminal seats and ≤ 5.5 mm over the TO-220 seats. Press any
//   inserts while the part is still flipped (pockets face up).
//
// ── Presets / overrides (-D) ────────────────────────────────────────────────
//   -D node="relay"              default: FAE / EXH / CIRC / AUX, "Relay"
//   -D node="lighting"           WHT / BLU / RED / FR, "Light"
//   -D 'labels=["A","B","C","D"]'  any per-channel labels (overrides node)
//   -D heatsink=true             clip-on heatsink room (pitch → 24.34 mm)
//   -D input_terminals=false     no J1 row: solder the ESP32 signal wire to
//                                R1 (fed through the wire slots); 4 terminals
//   -D mount="insert"            M3 heat-set inserts in the feet (see above)
//   -D num_channels=2            1-8 channels (Tier 2 lighting uses 2 of 4)
//   -D channel_spacing=22        wider pitch (heatsink mode enforces ≥24.34)
//   -D standoff_h=8              deeper underside wiring tray
//   -D part="assembled"          show in mounted orientation (z = wall)
//   -D part="none"               render nothing (for include-ing this file)
//   SP_FASTENER="self_tap" (from lib/sp_inserts.scad) turns the insert
//   pockets into Ø2.5 pilot holes for M3 self-tappers.
//   Legacy parameters, all still honoured: mosfet_width / terminal_width /
//   terminal_depth size the seats; mosfet_depth is the standing TO-220
//   height envelope (checked ≥ 15.24 + 0.3); mosfet_tab_slot is the heatsink
//   solder-tab slot length; rail_height (the old loose-part retention wall
//   height) is now how deep every part sits in its seat (the plate thickens
//   automatically so 1.6 mm stays under a terminal); wall is the plate
//   thickness; screw_d / standoff_h / standoff_d / wire_slot / zt_* as
//   before (the wire slots now sit mid-gap BETWEEN channels).
//
// Coordinates (part="assembled"): z = 0 is the wall/shelf face (rim and
// feet), the component face is at z = standoff_h + plate thickness, +Y runs
// from the input row (front) to the load-output row (back).
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>

// ── Node / layout ──────────────────────────────────────────────
node            = "relay";   // [relay, lighting]
labels          = [];        // per-channel labels; [] = node preset
num_channels    = 4;         // 1-8 MOSFET channels
channel_spacing = 20;        // mm — channel pitch (heatsink=true enforces ≥ heatsink_w + heatsink_gap)
input_terminals = true;      // front row of 2-pos terminals (GPIO + GND) per channel
heatsink        = false;     // reserve room for clip-on TO-220 heatsinks
mount           = "screw";   // [screw, insert]
part            = "print";   // [print, assembled, none]

// ── TO-220 seat ────────────────────────────────────────────────
mosfet_width    = 11.4;  // mm — seat length along the leads' row (body 10.29-10.54)
mosfet_depth    = 16.0;  // mm — body+tab length envelope (14.84-15.24); the part stands, so this is its height
mosfet_thick    = 5.5;   // mm — seat width front-to-back (body 4.20-4.69)
mosfet_tab_slot = 4;     // mm — length of the heatsink solder-tab slots (heatsink=true)

// ── Screw terminal seat ────────────────────────────────────────
terminal_width  = 11.0;  // mm — seat length (terminal 10.0-10.2)
terminal_depth  = 10.6;  // mm — seat depth (KF301 7.5, Phoenix MKDS 9.8)

// ── Plate ──────────────────────────────────────────────────────
wall            = 3;     // mm — plate thickness (auto-thickened for deep seats)
rail_height     = 1.4;   // mm — seat recess depth (how far parts sit into the plate)
screw_d         = 3.4;   // mm — mounting hole (M3 / #4 clearance)
wire_slot       = 3;     // mm — width of the mid-gap wire pass-through slots
standoff_h      = 6;     // mm — underside wiring-tray depth (rim + feet height)
standoff_d      = 7;     // mm — corner foot diameter
end_margin      = 10;    // mm — plate beyond the outer channels (holes, zip ties)
rim_w           = 2;     // mm — underside rim thickness
cable_exit_w    = 8;     // mm — rim opening at each end for the bus wires

// ── Passives ───────────────────────────────────────────────────
passive_pitch   = 10.16; // mm — axial lead spacing (0.4")
lead_hole_d     = 1.5;   // mm — axial lead hole (DO-41 lead ≤ 0.86 → ≥0.32 per side)

// ── Optional clip-on heatsink (Aavid 574502B00000G) ─────────────
heatsink_w      = 21.84; // mm — across the leads
heatsink_d      = 10.03; // mm — front-to-back
heatsink_h      = 19.05; // mm — height
heatsink_gap    = 2.5;   // mm — air gap between neighbouring heatsinks
heatsink_tab_x  = 20.57; // mm — solder-tab spacing (574502B03300G)

// ── Zip ties ───────────────────────────────────────────────────
zt_width   = 3;    // mm — zip tie slot width (tie ≤ 2.5 mm)
zt_depth   = 1.5;  // mm — tie thickness allowance (slot = zt_depth + 0.8)
zt_spacing = 15;   // mm — distance between the two slots of a pair

// ── Part data (sourced above; used for clearances and assertions) ─
TO220_W        = 10.54;  // body width, max
TO220_L        = 15.24;  // body + tab, max
TO220_T        = 4.69;   // thickness, max
TO220_LEAD_BK0 = 2.64;   // lead plane from tab face, min
TO220_LEAD_BK1 = 2.92;   // lead plane from tab face, max
TO220_LEAD_THK = 0.55;   // lead thickness, max
TO220_SHLD_W   = 1.40;   // lead shoulder width, max
TO220_LEAD_TP  = 0.36;   // lead true-position tolerance (dia)
TERM_L_MAX     = 10.2;   // 2-pos 5.08 terminal length, max (generic)
TERM_D_MAX     = 9.8;    // Phoenix MKDS 1,5 depth
TERM_PIN_BK0   = 4.0;    // pin row from back face, min (KF301)
TERM_PIN_BK1   = 5.2;    // pin row from back face, max (MKDS)
TERM_PIN_R     = 0.64;   // half-diagonal of a 0.9 mm square pin (≥ Ø1.0 round)
PAS_D          = 2.8;    // axial body envelope Ø (MFR-25 2.6, DO-41 2.7)
PAS_L          = 6.8;    // axial body envelope length (MFR-25 6.8, DO-41 5.2)

FLOOR_T  = 1.6;   // plate left under a terminal seat (PCB-like pin stick-out)
GAP      = 0.8;   // gap between neighbouring footprints
BAND_H   = 5.5;   // label bands either side of the TO-220 row
ENGRAVE  = 0.6;   // engraving depth
FONT     = "Liberation Sans:style=Bold";
FIT_CLR  = 0.3;   // minimum clearance per side at every seat / slot

// ── Derived ────────────────────────────────────────────────────
pitch    = heatsink ? max(channel_spacing, heatsink_w + heatsink_gap) : channel_spacing;
plate_t  = max(wall, rail_height + FLOOR_T);
seat_t   = rail_height;
z_bot    = standoff_h;              // plate underside
z_top    = standoff_h + plate_t;    // component face
plate_w  = num_channels * pitch + 2 * end_margin;

// Front-to-back rows (Y): J1 | R1 | R2 | band A | Q | band B | D1 | J2
y1s       = input_terminals ? terminal_depth : 3;  // J1 stop (inner seat edge) / front margin
y_r1      = y1s + GAP + PAS_D / 2;
y_r2      = y_r1 + PAS_D + GAP;
bandA_lo  = y_r2 + PAS_D / 2;
q_seat_lo = bandA_lo + BAND_H;
q_seat_hi = q_seat_lo + mosfet_thick;
yqc       = q_seat_lo + mosfet_thick / 2;   // TO-220 centre
yqb       = yqc + TO220_T / 2;              // tab (back) face, nominal
y_d       = q_seat_hi + BAND_H + PAS_D / 2;
y2s       = y_d + PAS_D / 2 + GAP;          // J2 stop (inner seat edge)
plate_d   = y2s + terminal_depth;

// TO-220 lead slot: lead envelope + seat play + FIT_CLR
q_play_x  = (mosfet_width - TO220_W) / 2;
q_play_y  = (mosfet_thick - TO220_T) / 2;
q_slot_hx = 2.54 + TO220_SHLD_W / 2 + TO220_LEAD_TP / 2 + q_play_x + FIT_CLR;
q_slot_y0 = yqb - (TO220_LEAD_BK1 + TO220_LEAD_THK) - TO220_LEAD_TP / 2 - q_play_y - FIT_CLR;
q_slot_y1 = yqb - TO220_LEAD_BK0 + TO220_LEAD_TP / 2 + q_play_y + FIT_CLR;

// Terminal pin slot, measured from the seat's inner stop toward the wire side
t_play_x  = (terminal_width - 10.0) / 2;
t_slot_hx = 2.54 + TERM_PIN_R + t_play_x + FIT_CLR;
t_slot_a  = TERM_PIN_BK0 - TERM_PIN_R - 0.35;
t_slot_b  = TERM_PIN_BK1 + TERM_PIN_R + 0.35;

// Heatsink solder tabs: 5.33 mm from one face of a 10.03 mm body whose
// base sits 0.63 mm behind the tab → tab at yqb-4.70 .. yqb-3.06
hs_tab_yc = yqb - 3.88;

// Corner feet / holes
foot_d    = mount == "insert" ? max(standoff_d, sp_insert_boss_d("M3")) : standoff_d;
hole_in   = foot_d / 2 + 1;
hole_pos  = [[hole_in, hole_in], [plate_w - hole_in, hole_in],
             [hole_in, plate_d - hole_in], [plate_w - hole_in, plate_d - hole_in]];

node_labels = node == "lighting" ? ["WHT", "BLU", "RED", "FR"]
                                 : ["FAE", "EXH", "CIRC", "AUX"];
chan_labels = len(labels) > 0 ? labels : node_labels;
wordmark    = node == "lighting" ? "SporePrint Light" : "SporePrint Relay";

function cx(i) = end_margin + (i + 0.5) * pitch;
function chan_label(i) = i < len(chan_labels) ? chan_labels[i] : str("CH", i + 1);

// ── Sanity checks ──────────────────────────────────────────────
assert(num_channels >= 1 && num_channels <= 8, "num_channels must be 1-8");
assert(node == "relay" || node == "lighting", "node must be \"relay\" or \"lighting\"");
assert(mount == "screw" || mount == "insert", "mount must be \"screw\" or \"insert\"");
assert(mosfet_width >= TO220_W + 2 * FIT_CLR, "mosfet_width too small for a 10.54 mm TO-220 body");
assert(mosfet_thick >= TO220_T + 2 * FIT_CLR, "mosfet_thick too small for a 4.69 mm TO-220 body");
assert(mosfet_depth >= TO220_L + FIT_CLR, "mosfet_depth must be ≥ 15.54 (TO-220 body+tab 15.24)");
assert(terminal_width >= TERM_L_MAX + 2 * FIT_CLR, "terminal_width too small for a 10.2 mm terminal");
assert(terminal_depth >= TERM_D_MAX + 2 * FIT_CLR - 0.01, "terminal_depth too small for a 9.8 mm MKDS terminal");
assert(screw_d >= 3.3, "screw_d must clear an M3 shank (≥ 3.3)");
assert(pitch >= max(mosfet_width, terminal_width, passive_pitch + lead_hole_d) + wire_slot + 4,
       "channel_spacing too tight for the seats plus the wire slot");
assert(!heatsink || pitch >= heatsink_w + heatsink_gap, "heatsinks would touch");
assert(hole_in + 3.6 <= end_margin + pitch / 2 - max(mosfet_width, terminal_width) / 2,
       "end_margin too small for the corner screw heads");
assert(standoff_h >= 4, "standoff_h below 4 mm leaves no room for joints under the plate");
assert(mount != "insert" || z_top >= sp_insert_boss_h("M3"), "plate + foot too short for an M3 insert");
assert(rail_height >= 0.6, "rail_height (seat depth) must be ≥ 0.6");

if (plate_t > wall)
    echo(str("relay_board_mount: note — plate thickened from wall=", wall, " to ", plate_t,
             " mm so ", FLOOR_T, " mm stays under a ", rail_height, " mm deep terminal seat"));

// longest stock screw that does not exceed l
function stock_len(l) = max([for (s = [4, 5, 6, 8, 10, 12, 14, 16, 20, 25, 30]) if (s <= l) s]);

echo(str("relay_board_mount: plate ", plate_w, " x ", plate_d, " x ", z_top,
         " mm, channel pitch ", pitch, " mm, corner-hole pitch ", plate_w - 2 * hole_in, " x ",
         plate_d - 2 * hole_in, " mm", mount == "insert"
            ? str(", insert mode: M3 x ", stock_len(sp_screw_len("M3", 3, false)),
                  " for a 3 mm panel (panel + 5.7 rounded down)")
            : str(", screw mode: through length ", z_top, " mm")));

// ── Underside (tray rim, corner feet, zip-tie columns) ─────────
module rim() {
    difference() {
        cube([plate_w, plate_d, z_bot + 0.01]);
        translate([rim_w, rim_w, -1])
            cube([plate_w - 2 * rim_w, plate_d - 2 * rim_w, z_bot + 2]);
        // bus-wire exits at both ends
        for (x = [-1, plate_w - rim_w - 1])
            translate([x, plate_d / 2 - cable_exit_w / 2, -1])
                cube([rim_w + 2, cable_exit_w, z_bot + 1]);
    }
}

module standoffs() {
    for (p = hole_pos)
        translate([p[0], p[1], 0])
            cylinder(h = z_bot + 0.01, d = foot_d, $fn = 40);
}

zt_slot_y = zt_depth + 0.8;
zt_pos = [for (x = [end_margin / 2, plate_w - end_margin / 2])
             for (s = [-1, 1]) [x, plate_d / 2 + s * zt_spacing / 2]];

module zip_columns() {
    for (p = zt_pos)
        translate([p[0] - zt_width / 2 - 1.6, p[1] - zt_slot_y / 2 - 1.6, 0])
            cube([zt_width + 3.2, zt_slot_y + 3.2, z_bot + 0.01]);
}

// ── Cuts ───────────────────────────────────────────────────────
module through(x0, y0, sx, sy) {
    translate([x0, y0, -1]) cube([sx, sy, z_top + 2]);
}

module seat(x0, y0, sx, sy, depth) {
    translate([x0, y0, z_top - depth]) cube([sx, sy, depth + 1]);
}

module channel_cuts(i) {
    c = cx(i);
    // J1 — input terminal, open to the front edge
    if (input_terminals) {
        seat(c - terminal_width / 2, -1, terminal_width, y1s + 1, seat_t);
        through(c - t_slot_hx, y1s - t_slot_b, 2 * t_slot_hx, t_slot_b - t_slot_a);
    }
    // R1, R2, D1 lead holes
    for (y = [y_r1, y_r2, y_d], s = [-1, 1])
        translate([c + s * passive_pitch / 2, y, -1])
            cylinder(h = z_top + 2, d = lead_hole_d, $fn = 20);
    // Q — TO-220 seat + lead slot
    seat(c - mosfet_width / 2, q_seat_lo, mosfet_width, mosfet_thick, seat_t);
    through(c - q_slot_hx, q_slot_y0, 2 * q_slot_hx, q_slot_y1 - q_slot_y0);
    // heatsink solder-tab slots
    if (heatsink)
        for (s = [-1, 1])
            through(c + s * heatsink_tab_x / 2 - 1.1, hs_tab_yc - mosfet_tab_slot / 2,
                    2.2, mosfet_tab_slot);
    // J2 — load terminal, open to the back edge
    seat(c - terminal_width / 2, y2s, terminal_width, terminal_depth + 1, seat_t);
    through(c - t_slot_hx, y2s + t_slot_a, 2 * t_slot_hx, t_slot_b - t_slot_a);
}

module wire_slots() {
    // mid-gap between neighbouring channels, beside the resistor rows —
    // clear of every seat, so nothing is left unsupported over a void
    y0 = input_terminals ? y1s + GAP : y_r1 - PAS_D / 2;
    for (i = [1 : 1 : num_channels - 1])
        through(end_margin + i * pitch - wire_slot / 2, y0, wire_slot, bandA_lo - y0);
}

module mount_holes() {
    for (p = hole_pos)
        if (mount == "screw")
            translate([p[0], p[1], -1])
                cylinder(h = z_top + 2, d = screw_d, $fn = 32);
        else
            translate([p[0], p[1], 0])
                mirror([0, 0, 1]) sp_insert_pocket("M3");
}

module zip_slots() {
    for (p = zt_pos)
        through(p[0] - zt_width / 2, p[1] - zt_slot_y / 2, zt_width, zt_slot_y);
}

// ── Engraving (component face) ─────────────────────────────────
module engrave_text(t, size, x, y) {
    translate([x, y, z_top - ENGRAVE])
        linear_extrude(ENGRAVE + 1)
            text(t, size = size, font = FONT, halign = "center", valign = "center");
}

module engrave_minus(x, y) {
    translate([x - 1.3, y - 0.4, z_top - ENGRAVE]) cube([2.6, 0.8, ENGRAVE + 1]);
}

module engrave_plus(x, y) {
    engrave_minus(x, y);
    translate([x - 0.4, y - 1.3, z_top - ENGRAVE]) cube([0.8, 2.6, ENGRAVE + 1]);
}

module engravings() {
    ws = min(3.4, (plate_w - 8) / (0.66 * len(wordmark)));
    engrave_text(wordmark, ws, plate_w / 2, bandA_lo + 2.4);
    for (i = [0 : num_channels - 1]) {
        c = cx(i);
        side = max(mosfet_width, terminal_width) / 2 + 2.1;
        engrave_text(chan_label(i), 3.2, c, q_seat_hi + BAND_H / 2);
        engrave_text("G", 3, c - mosfet_width / 2 - 1.8, yqc);
        engrave_plus(c - side, y2s + terminal_depth / 2);
        engrave_minus(c + side, y2s + terminal_depth / 2);
        if (input_terminals) {
            engrave_text("IN", 2.8, c - side, y1s / 2);
            engrave_minus(c + side, y1s / 2);
        }
        // D1 cathode band (toward the "+" pin)
        translate([c - PAS_L / 2 + 0.6, y_d - PAS_D / 2, z_top - ENGRAVE])
            cube([0.8, PAS_D, ENGRAVE + 1]);
    }
}

// ── Assembly ───────────────────────────────────────────────────
module base_plate() {
    translate([0, 0, z_bot]) cube([plate_w, plate_d, plate_t]);
}

module relay_board_mount() {
    difference() {
        union() {
            base_plate();
            rim();
            standoffs();
            zip_columns();
        }
        for (i = [0 : num_channels - 1]) channel_cuts(i);
        wire_slots();
        mount_holes();
        zip_slots();
        engravings();
    }
}

// Print orientation: component face on the bed, rim and feet up.
module relay_board_mount_print() {
    translate([0, plate_d, z_top]) rotate([180, 0, 0]) relay_board_mount();
}

// ── Render ─────────────────────────────────────────────────────
if (part == "print") relay_board_mount_print();
else if (part == "assembled") relay_board_mount();
