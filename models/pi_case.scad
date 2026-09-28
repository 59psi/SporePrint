// SporePrint Raspberry Pi 5 Case
// Two-piece screwed enclosure (base + lid) for a Raspberry Pi 5 wearing the
// official Active Cooler. Every port, the microSD card, the power button,
// the status LED, the PCIe FFC and the 40-pin header stay reachable with
// the lid screwed shut.
//
// FITS (every number lives in lib/pi5_dims.scad with its source)
//   * Raspberry Pi 5 (Raspberry Pi Ltd), every RAM option 1/2/4/8/16 GB
//     (product brief RP-008348-DS-6, April 2026), Rev 4 / D0 boards
//     included (PCN 22: no mechanical change) and the 2026 MagJack
//     (PCN 44: 0.3 mm further into the board only). Product-portal SKUs
//     for the Pi 5 family: SC1110, SC1111, SC1112, SC1113, SC1431, SC1432.
//     Sources: mechanical drawing RP-008347-DS
//       datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf
//     measured from the vector PDF, cross-checked against the official 3D
//     model RP-010083-CA-1 (STEP, May 2026, per-solid bounding boxes);
//     where they differ the envelope is the union of both.
//     PCB 85 x 56, 1.336 (STEP) / 1.41 (drawing) thick - the case is built
//     for 1.6 and every opening also covers 1.336. Holes Ø2.7 on 58 x 49,
//     3.5 from the corner; nothing on the underside within r 4.4 of a hole.
//     Long y=0 edge: USB-C / micro-HDMI0 / micro-HDMI1 centred at
//     x = 11.2 / 25.8 / 39.2. Right short edge: RJ45 (y 2.2-18.2, 13.9
//     tall) and two USB-A stacks (y 21.7-36.3, 39.7-54.3 incl. EMI flare,
//     16.4 tall), ~3 mm overhang. Left short edge: microSD on the underside
//     (card end 1.72 beyond the PCB), power button y = 18.4, status LED
//     y = 13.3, PCIe FPC y 24.7-35.2. 40-pin header centred at x = 32.45,
//     8.56 tall. CAM/DISP FPCs at x 47.2-56.3.
//   * Raspberry Pi Active Cooler, SKU SC1148:
//     datasheets.raspberrypi.com/cooling/raspberry-pi-active-cooler-mechanical-drawing.pdf
//     63.5 x 42.5 on the two Ø3 push-pin holes (3.5,9.5)/(61.5,46.5),
//     Ø21 blower intake at (41.6,33.6). Its 13.70 drawing height is used as
//     the envelope above the PCB top (conservative; installed ~12.5-13.2).
//     Lid: grille + shroud ending 1 mm above that envelope feeds the intake;
//     the fins exhaust -x through the left-wall slots (from 3 mm above the
//     PCB top; 4.1-6.2 beside the LED / button / PCIe openings).
//   * Plugs: USB-C overmold <= 12.35 x 6.5 (USB Type-C spec maximum; covers
//     the official 27 W PSU SC1153), micro-HDMI overmold <= 11.2 x 6.6,
//     USB-A overmolds <= 17.0 wide, RJ45 boots <= 15 x 15. The RJ45 and
//     USB-A jacks stand proud of the outer wall face (x 87.5): 0.28-0.55
//     per the STEP (USB2 87.78, USB3 88.00, RJ45 88.05), 0.4-0.8 per the
//     drawing, so a plug always seats on its jack before its overmold can
//     reach the case. Board-to-wall gap 0.5; the fit test proves >= 0.3 mm
//     laterally to every part, plug and access path on 1.336, 1.41 and
//     1.6 mm boards.
//
// PIECES (2 printed parts, joined with brass heat-set inserts)
//   base : tray, 9.3 tall. Pi on four Ø6.6 M2.5-insert standoffs (full
//          library boss up to the board: the official STEP shows nothing on
//          the underside within r 4.4 of a hole, so the boss only touches
//          bare board round the Ø6 pad); four M3-insert corner towers;
//          floor vents; optional wall-mount / zip-tie ears.
//   lid  : walls + roof, 20 tall above the parting line (at the PCB top).
//          Four counterbored M3 towers, port notches, roof slots, intake
//          grille (or 40 mm fan mount), side vent slots.
//   A 1.5 mm stepped lap joint round the rim only aligns the halves; the four
//   M3 screws hold the case shut. Outside 96.6 x 72.6 x 29.3 mm (114 wide
//   with the ears).
//
// HARDWARE TO BUY (per case)
//   Heat-set inserts, "standard" knurled brass (ruthex / CNC Kitchen):
//     4 x M2.5 x 5.7  (ruthex RX-M2.5x5.7) -> base standoffs (Pi holes);
//                        pocket Ø3.6 x 6.7 deep, 1.0 mm floor below it
//     4 x M3   x 5.7  (ruthex RX-M3x5.7, CNC Kitchen M3x5.7) -> base corner
//                        towers (lid screws); pocket Ø4.0 x 6.7 deep
//   Screws, ISO 4762 / DIN 912 socket-head cap:
//     4 x M2.5 x 6    -> Pi to base (engages 4.4 of the 5.7 insert; tip
//                        stays >= 2 mm above the pocket floor. M2.5 x 8
//                        would bottom out - an assert refuses it)
//     4 x M3   x 16   -> lid to base, from the top (head sits 9.7 deep in a
//                        Ø6.2 well; engages the full 5.7 insert). Only have
//                        M3 x 20? -D lid_screw_len=20 moves the seat up.
//   Wall mount (ears): 2 x M3 or #4 screws, or zip ties <= 4.8 x 1.5.
//   cooling="fan40": 40 x 40 x 10 fan + 4 x M3 x 16 screws and nuts (or the
//     fan's own self-tappers) through the roof - no printed-part joint.
//   No inserts? -D SP_FASTENER="self_tap" turns every pocket into a pilot
//   hole for self-tapping M2.5 / M3 screws of the same lengths.
//
// PRINT (Bambu / any FDM; PLA or PETG, 0.2 mm layers, 3 walls, 20 % infill)
//   Laid out flat as rendered: base floor-down, lid roof-down (the wordmark
//   is debossed into the lid's bed face). NO SUPPORTS: every wall opening
//   is a notch open at a part edge, wall vents are vertical slots (1.8 mm
//   bridge at one end), and the only overhang is the 1.4 mm annular ceiling
//   inside each lid screw well. Press inserts flush with the iron at
//   ~220-245 C. Default layout (both parts) 220.6 x 72.6 mm, 21.3 tall;
//   base alone 114 x 72.6, lid alone 96.6 x 72.6. Thinnest walls: 0.9 mm
//   lap tongue / skirt (left out over the microSD channel), 1.2 mm round
//   the screw-head wells, 1.5 mm web between the two micro-HDMI openings,
//   >= 1.6 mm between every vent slot and every port opening.
//
// ASSEMBLY
//   1. Press 4 x M2.5 and 4 x M3 inserts into the base.
//   2. Fit the Active Cooler to the Pi, plug its lead into FAN.
//   3. Drop the Pi straight into the base (microSD may stay in), fix with
//      4 x M2.5 x 6.
//   4. Lower the lid straight over the ports, drive 4 x M3 x 16.
//   Access, lid closed: microSD via the notch under the left edge; power
//   button with a pen / paper clip through the 3.5 mm slot; LED window;
//   PCIe FFC slot; GPIO roof slot; CAM/DISP roof slot (csi_slot=true).
//
// PRESETS (-D on the command line; every one renders manifold, 0 warnings)
//   part="print"        both pieces laid out for printing (default)
//   part="base"         base only;  part="lid"  lid only (print orientation)
//   part="assembly"     both pieces assembled (+ Pi 5 ghost in F5 preview)
//   cooling="active"    official Active Cooler: intake grille + shroud (default)
//   cooling="fan40"     40 mm fan on the roof over the SoC (for a bare Pi)
//   cooling="none"      passive roof slots over the SoC
//   gpio_slot=false     solid roof over the 40-pin header
//   pcie_slot=false     no PCIe FFC slot in the left wall
//   csi_slot=true       roof slot for CAM/DISP ribbons (not with fan40)
//   mount_ears=false    no wall-mount / zip-tie ears
//   lid_screw_len=20    M3 x 20 lid screws instead of M3 x 16
//   tolerance=0.3       tighter board-to-wall gap (default 0.5; 0.3 minimum)
//   SP_FASTENER="self_tap"     pilot holes instead of insert pockets
//   SP_INSERT_HOLE_TWEAK=-0.1  tune insert pockets to your printer
//   (part="none" renders nothing - for include / fit-test use only)
//
// Example:  openscad -D 'cooling="fan40"' -o pi_case_fan40.stl pi_case.scad
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>
include <lib/pi5_dims.scad>

// ── Build selection ───────────────────────────────────────────────
part       = "print";   // print | base | lid | assembly | none
cooling    = "active";  // active | fan40 | none
gpio_slot  = true;      // roof slot over the 40-pin header
pcie_slot  = true;      // FFC exit slot at the PCIe FPC connector
csi_slot   = false;     // roof slot over the CAM/DISP FPC connectors
mount_ears = true;      // wall-mount / zip-tie ears on the short sides

// ── Parameters (Raspberry Pi 5 dimensions) ────────────────────────
board_w     = 85;    // mm — Pi 5 PCB width (long edge)
board_l     = 56;    // mm — Pi 5 PCB length (short edge)
board_h     = 16.5;  // mm — tallest part above PCB top (USB-A stacks 16.42)
pcb_thick   = 1.6;   // mm — PCB thickness the case is built for (drawing 1.41,
                     //      STEP 1.336; every opening also covers 1.336)
wall        = 2;     // mm — wall and roof thickness
tolerance   = 0.5;   // mm — PCB edge to inner wall, per side
lid_lip     = 1.5;   // mm — lap-joint depth (alignment only)
screw_d     = 3;     // mm — wall-mount screw size in the ears (M3)
vent_d      = 3;     // mm — floor ventilation hole diameter

// Port openings (wall cut-outs). Widths/heights are the opening sizes:
// the part (or its plug overmold) plus >= 0.35 mm per side.
usbc_w      = 13.2;  // mm — USB-C plug overmold 12.35 + clearance
usbc_h      = 7.4;   // mm — USB-C plug overmold 6.5 + clearance
hdmi_w      = 11.9;  // mm — micro-HDMI overmold <= 11.2 at 0.35/side (1.5 web)
hdmi_h      = 7.4;   // mm — micro-HDMI overmold <= 6.6 at 0.4/side
usba_w      = 15.3;  // mm — USB-A stack incl. EMI flare 14.59 + 0.35/side
usba_h      = 17.0;  // mm — opening top above PCB top (stack 16.42)
ethernet_w  = 17.0;  // mm — RJ45 jack 15.96 + clearance
ethernet_h  = 14.4;  // mm — opening top above PCB top (jack 13.88)
port_relief = 0.4;   // mm — right-hand notches start this far below the
                     //      top of the thinnest (1.336) board
usba_plug_w = 17.8;  // mm — room for USB-A overmolds <= 17.0 wide, cut into
                     //      the corner lobes OUTSIDE the wall face only

// microSD (underside, left short edge) — notch below the PCB
sd_w        = 12.2;  // mm — card 11.0 + finger clearance
sd_h        = 3.5;   // mm — notch depth below the PCB bottom

// GPIO header (top edge) — roof slot
gpio_w      = 52.2;  // mm — slot length (header 50.74)
gpio_h      = 8.56;  // mm — header height with pins (informational: only
                     //      checked against board_h, the slot is open)
gpio_slot_w = 6.2;   // mm — slot width (header 4.97)

// Left-edge access
button_w    = 3.5;   // mm — power-button access slot (pen / paper clip)
button_h    = 4.5;
led_w       = 3.0;   // mm — status LED window
pcie_w      = 11.6;  // mm — PCIe FFC slot (connector 10.5)
pcie_h      = 4.6;   // mm — above PCB top

// Pi mounting holes (from board corner, Pi 5 spec)
hole_inset_x = 3.5;  // mm — from board edge
hole_inset_y = 3.5;  // mm — from board edge
hole_dx      = 58;   // mm — horizontal spacing
hole_dy      = 49;   // mm — vertical spacing
hole_d       = 2.7;  // mm — Pi's M2.5 mounting holes (informational: the
                     //      board's hole, checked >= 2.6 for the screw)

// Base / standoffs
floor_t           = 2.0;    // mm
standoff_h        = 5.7;    // mm — floor top to PCB bottom; the insert
                            //      pocket (6.7) runs 1.0 into the floor
pi_insert         = "M2.5";
pi_screw_len      = 6;      // mm — M2.5 x 6 socket head (asserted to engage
                            //      >= half the insert and clear the floor)

// Lid screws
lid_insert    = "M3";
lid_screw_len = 16;         // mm — M3 x 16 (20 also works)
tower_off     = [1.5, 4.0]; // mm — tower centre beyond the PCB corner (x, y)
head_clear    = 1.5;        // mm — roof underside above board_h

// Cooling
cooler_h        = AC_H;     // mm — Active Cooler envelope above PCB top
intake_d        = 23;       // mm — intake grille / shroud bore (fan Ø21)
shroud_t        = 1.2;      // mm
shroud_gap      = 1.0;      // mm — shroud end above the cooler envelope
fan_size        = 40;       // mm — cooling="fan40"
fan_hole_pitch  = 32;       // mm
fan_screw_clear = 3.4;      // mm
fan_grille_d    = 38;       // mm

// CAM/DISP ribbon slot (csi_slot=true): both 22-pin FPC connectors
csi_slot_x = [46.2, 57.3];  // mm — connectors x 47.19-56.31
csi_slot_y = [1.7, 15.2];   // mm — ribbons y 2.2-14.7

// Vents
vent_slot_w   = 1.8;   // mm — wall vent slot width
vent_pitch    = 4;     // mm
vent_z0       = 3.0;   // mm — lowest vent start above the PCB top
vent_web      = 1.6;   // mm — solid web kept round every port opening

// Zip tie / ear parameters
zt_width   = 3;    // mm — zip tie width the slot takes
zt_depth   = 1.5;  // mm — zip tie thickness the slot takes
zt_spacing = 15;   // mm — distance between the two slots in an ear
ear_l      = 12;   // mm — ear reach beyond the wall
ear_t      = 3;    // mm

$fn = 48;

// ── Derived dimensions ────────────────────────────────────────────
inner_w  = board_w + tolerance * 2;
inner_l  = board_l + tolerance * 2;
outer_w  = inner_w + wall * 2;
outer_l  = inner_l + wall * 2;

pcb_z    = floor_t + standoff_h;          // PCB bottom (absolute z)
pcb_top  = pcb_z + pcb_thick;
z_split  = pcb_top;                       // base / lid parting plane
roof_bot = pcb_top + board_h + head_clear;
roof_top = roof_bot + wall;
base_h   = z_split;                       // base height (lap tongue on top)
lid_h    = roof_top - z_split;            // lid height above the parting plane

lap_clr  = 0.2;
lap_in   = wall / 2 - lap_clr / 2;
corner_r = wall;

pi_holes = [for (i = [0, 1], j = [0, 1])
            [hole_inset_x + i * hole_dx, hole_inset_y + j * hole_dy]];

towers = [[-tower_off[0], -tower_off[1]],
          [board_w + tower_off[0], -tower_off[1]],
          [-tower_off[0], board_l + tower_off[1]],
          [board_w + tower_off[0], board_l + tower_off[1]]];
tower_d   = max(sp_insert_boss_d(lid_insert), sp_screw_head_d(lid_insert) + 2 * 1.2);
lid_clamp = lid_screw_len - sp_insert_len(lid_insert) + sp_screw_head_h(lid_insert);

g = tolerance;

// Plan-view bounds (used for the print layout)
x_min = min(mount_ears ? -g - wall - ear_l : 0, -tower_off[0] - tower_d / 2, -g - wall);
x_max = max(mount_ears ? board_w + g + wall + ear_l : 0,
            board_w + tower_off[0] + tower_d / 2, board_w + g + wall);
y_min = -tower_off[1] - tower_d / 2;
y_max = board_l + tower_off[1] + tower_d / 2;

// ── Sanity checks ─────────────────────────────────────────────────
// M2.5 standoffs: the pocket is cut from the finished base (boss + floor),
// so its floor sits sp_insert_depth() below the PCB; keep >= 1 mm under it.
pi_pocket_floor = pcb_z - sp_insert_depth(pi_insert);
assert(pi_pocket_floor >= 1.0 - 0.001,
       "standoff_h too short: M2.5 insert pocket would break through the floor");
// Pi screw: through the thinnest board it must not reach the pocket floor
// (0.5 mm left for displaced plastic) and must engage >= half the insert.
pi_screw_tip = pcb_z + min(pcb_thick, PI5_PCB_T_MIN) - pi_screw_len;
assert(pi_screw_tip >= pi_pocket_floor + 0.5,
       str("M2.5 x ", pi_screw_len, " bottoms out in the standoff pocket - use M2.5 x 6"));
assert(pi_screw_len - pcb_thick >= sp_insert_len(pi_insert) / 2,
       str("M2.5 x ", pi_screw_len, " engages under half the insert - use M2.5 x 6"));
assert(z_split >= sp_insert_boss_h(lid_insert),
       "base too shallow for the M3 insert pocket");
assert(lid_clamp >= sp_screw_head_h(lid_insert) + 1.5 && lid_clamp <= lid_h - 1,
       "lid_screw_len does not fit the lid tower");
assert(abs(sp_screw_len(lid_insert, lid_clamp) - lid_screw_len) < 0.01,
       "lid screw would not fully engage its insert");
assert(board_h >= PI5_USB_H && board_h >= gpio_h && board_h >= cooler_h,
       "board_h lower than a Pi 5 component");
assert(usba_h < board_h + head_clear - 0.5 && ethernet_h < usba_h,
       "port openings reach the roof");
assert(hole_d >= 2.6, "Pi hole too small for the M2.5 screw");
assert(!(csi_slot && cooling == "fan40"), "csi_slot sits under the 40 mm fan");
for (t = towers) {
    cx = t[0] < board_w / 2 ? PI5_PCB_R : board_w - PI5_PCB_R;
    cy = t[1] < board_l / 2 ? PI5_PCB_R : board_l - PI5_PCB_R;
    assert(norm([t[0] - cx, t[1] - cy]) - PI5_PCB_R >= tower_d / 2 + g - 0.001,
           "screw tower hits the PCB corner");
}

lid_x_min = min(-tower_off[0] - tower_d / 2, -g - wall);
lid_x_max = max(board_w + tower_off[0] + tower_d / 2, board_w + g + wall);
layout_w  = (x_max - x_min) + 10 + (lid_x_max - lid_x_min);

echo(str("pi_case: base_h=", base_h, " lid_h=", lid_h, " total_h=", roof_top,
         " footprint=", x_max - x_min, "x", y_max - y_min,
         " print layout=", layout_w, "x", y_max - y_min,
         " lid screws M3x", sp_screw_len(lid_insert, lid_clamp),
         " pi screws M2.5x", pi_screw_len,
         " (engages ", pi_screw_len - pcb_thick, " of ", sp_insert_len(pi_insert),
         ", tip ", pi_screw_tip - pi_pocket_floor, " above pocket floor)"));

// ── 2D outlines ───────────────────────────────────────────────────
module cav_rect2d(extra = 0) {
    translate([-g - extra, -g - extra])
        square([inner_w + 2 * extra, inner_l + 2 * extra]);
}

// Board cavity: board + tolerance, minus the corner screw towers.
module cavity2d() {
    difference() {
        cav_rect2d();
        for (t = towers) translate(t) circle(d = tower_d);
    }
}

module outer_rect2d() {
    translate([-g - wall + corner_r, -g - wall + corner_r])
        offset(r = corner_r) square([outer_w - 2 * corner_r, outer_l - 2 * corner_r]);
}

// Corner lobes that carry the screw towers, clipped to stay out of the cavity.
module lobes2d() {
    difference() {
        for (t = towers) hull() {
            translate(t) circle(d = tower_d);
            translate([t[0] < 0 ? -g - wall + corner_r : board_w + g + wall - corner_r,
                       t[1] < 0 ? -g - wall + corner_r : board_l + g + wall - corner_r])
                circle(r = corner_r);
        }
        cavity2d();
    }
}

module outline2d() {
    union() { outer_rect2d(); lobes2d(); }
}

// Lap joint: base keeps the inner half of the wall, lid the outer half.
module lap_inner2d() {
    difference() { cav_rect2d(lap_in); cav_rect2d(); }
}
module lap_outer2d() {
    difference() {
        outer_rect2d();
        cav_rect2d(lap_in + lap_clr);
        offset(delta = lap_clr) lobes2d();
    }
}

// ── Openings ──────────────────────────────────────────────────────
// Each opening: [x0, x1, y0, y1, z0, z1] in board coordinates, z absolute.
// Wall-crossing depth covers the wall plus the lobes.
wall_in  = 0.6;               // reach into the cavity
wall_out = wall + 6;          // reach beyond the outer face

// y = 0 long wall (USB-C / HDMI). zc is the port centre above the PCB top:
// the top edge follows the nominal board, the bottom edge the thinnest
// (1.336) board and the lower STEP centre line, so both boards clear.
function _front(xc, w, zc, h) =
    [xc - w / 2, xc + w / 2, -g - wall_out, -g + wall_in,
     pcb_z + PI5_PCB_T_MIN + zc - PI5_PORT_ZC_TOL - h / 2, pcb_top + zc + h / 2];
function _right(yc, w, z0, z1) =  // x = board_w short wall (RJ45 / USB-A)
    [board_w + g - wall_in, board_w + g + wall_out, yc - w / 2, yc + w / 2, z0, z1];
function _left(yc, w, z0, z1) =   // x = 0 short wall (SD / button / LED / PCIe)
    [-g - wall_out, -g + wall_in, yc - w / 2, yc + w / 2, z0, z1];

port_z0 = pcb_z + PI5_PCB_T_MIN - port_relief;   // right-hand notch bottom

openings = concat(
    [_front(PI5_USBC_X, usbc_w, PI5_USBC_ZC, usbc_h)],
    [for (x = PI5_HDMI_X) _front(x, hdmi_w, PI5_HDMI_ZC, hdmi_h)],
    // The RJ45 shield overhang sits flush on the PCB top (STEP), the USB-A
    // stacks 0.57 above it; the notches start port_relief below the top of
    // the thinnest (1.336) board so every board thickness clears the rim.
    [_right(PI5_ETH_YC,  ethernet_w, port_z0, pcb_top + ethernet_h),
     _right(PI5_USB3_YC, usba_w,     port_z0, pcb_top + usba_h),
     _right(PI5_USB2_YC, usba_w,     port_z0, pcb_top + usba_h),
     // Overmold relief beyond the outer wall face: the STEP puts the USB2
     // stack front at x 87.78 (drawing 88.3), so a wide plug would come
     // within 0.2 of the top-right screw-tower lobe without it.
     // (overmold bottom taken as 0.5 below the thinnest board's top, + 0.4)
     [board_w + g + wall, board_w + g + wall_out,
      PI5_USB3_YC - usba_plug_w / 2, PI5_USB3_YC + usba_plug_w / 2,
      pcb_z + PI5_PCB_T_MIN - 0.9, pcb_top + PI5_USBA_PLUG[1] + 0.4],
     [board_w + g + wall, board_w + g + wall_out,
      PI5_USB2_YC - usba_plug_w / 2, PI5_USB2_YC + usba_plug_w / 2,
      pcb_z + PI5_PCB_T_MIN - 0.9, pcb_top + PI5_USBA_PLUG[1] + 0.4],
     _left(PI5_SD_YC, sd_w, pcb_z - sd_h, pcb_top),
     _left(PI5_BUTTON_YC, button_w, pcb_top + PI5_BUTTON_ZC - button_h / 2,
           pcb_top + PI5_BUTTON_ZC + button_h / 2),
     _left(PI5_LED_YC, led_w, pcb_top - 0.8, pcb_top + 2.5)],
    pcie_slot ? [_left(PI5_PCIE_YC, pcie_w, pcb_z + PI5_PCB_T_MIN, pcb_top + pcie_h)] : []
);

module _cut(b) { translate([b[0], b[2], b[4]])
                     cube([b[1] - b[0], b[3] - b[2], b[5] - b[4]]); }

// Base: cut as specified (an opening reaching the parting plane runs out
// through the base top). Lid: an opening that starts at or below the
// parting plane runs out through the lid's bottom edge, so no thin strip
// is left spanning it and the lid drops over the ports.
module base_openings() {
    for (b = openings)
        _cut([b[0], b[1], b[2], b[3], b[4],
              b[5] >= z_split - 0.01 ? z_split + lid_lip + 1 : b[5]]);
}
module lid_openings() {
    for (b = openings)
        if (b[5] > z_split - lid_lip)
            _cut([b[0], b[1], b[2], b[3],
                  b[4] <= z_split + 0.01 ? z_split - lid_lip - 1 : b[4], b[5]]);
}

// ── Reusable mounting modules ─────────────────────────────────────
// Two zip-tie pass-through slots, `spacing` apart along y (through-cutter).
module zip_tie_slot(width = 3, depth = 1.5, spacing = 15) {
    for (y = [-spacing / 2, spacing / 2])
        translate([0, y, 0])
            cube([width + 2, depth + 0.5, 20], center = true);
}

module ears() {
    ear_w = zt_spacing + zt_depth + 0.5 + 8;
    for (s = [0, 1]) {
        x0 = s == 0 ? -g - wall - ear_l : board_w + g + wall - 0.5;
        translate([x0, board_l / 2 - ear_w / 2, 0])
            cube([ear_l + 0.5, ear_w, ear_t]);
    }
}
module ear_cuts() {
    for (s = [0, 1]) {
        xc = s == 0 ? -g - wall - ear_l / 2 : board_w + g + wall + ear_l / 2;
        translate([xc, board_l / 2, 0]) {
            cylinder(d = screw_d + 0.4, h = 3 * ear_t, center = true);
            zip_tie_slot(width = zt_width, depth = zt_depth, spacing = zt_spacing);
        }
    }
}

// ── Base (bottom half) ────────────────────────────────────────────
// Channel behind the microSD socket: the drawing puts its lip 0.31 proud of
// the PCB edge, so the wall steps back (open to the rim, so the board still
// drops straight in) to keep >= 0.5 mm clear of it.
sd_rx     = PI5_SD_SOCKET_X0 - 0.5;
sd_chan   = sd_rx < -g;
sd_chan_y = [PI5_SD_SOCKET_Y[0] - 0.4, PI5_SD_SOCKET_Y[1] + 0.4];

// Over the channel the 0.9 lap tongue would be cut to 0.59 (below two
// perimeters), so the tongue is left out there; the lid skirt still closes
// the joint from outside.
module sd_tongue_gap2d() {
    if (sd_chan)
        translate([-g - lap_in - 0.1, sd_chan_y[0]])
            square([lap_in + 0.2, sd_chan_y[1] - sd_chan_y[0]]);
}

module pi_case_base() {
    difference() {
        union() {
            difference() {
                union() {
                    linear_extrude(z_split - lid_lip) outline2d();
                    translate([0, 0, z_split - lid_lip - 0.01])
                        linear_extrude(lid_lip + 0.01)
                            difference() {
                                union() { lap_inner2d(); lobes2d(); }
                                sd_tongue_gap2d();
                            }
                    if (mount_ears) ears();
                }

                // Board cavity
                translate([0, 0, floor_t])
                    linear_extrude(z_split + lid_lip) cavity2d();

                base_openings();

                if (sd_chan)
                    translate([sd_rx, sd_chan_y[0], floor_t])
                        cube([-g - sd_rx + 0.01, sd_chan_y[1] - sd_chan_y[0],
                              z_split + 1 - floor_t]);

                // Floor vents under the SoC / RAM / RP1 (clear of every standoff)
                for (x = [12 : 6 : 54], y = [10 : 6 : 46])
                    translate([x, y, -1]) cylinder(h = floor_t + 2, d = vent_d, $fn = 16);

                // M3 inserts in the corner towers (lid screws)
                for (t = towers) translate([t[0], t[1], z_split]) sp_insert_pocket(lid_insert);

                if (mount_ears) ear_cuts();
            }

            // Pi mounting posts: full library M2.5 boss (Ø6.6) from the bed
            // up to the PCB. The official STEP has nothing on the underside
            // within r 4.4 of a hole, so the boss (r 3.3) only meets bare
            // board just outside the Ø6 pad.
            for (h = pi_holes)
                translate([h[0], h[1], 0]) sp_insert_boss(pi_insert, pcb_z);
        }

        // M2.5 insert pockets, cut from the finished base so the 1 mm relief
        // below the seated insert reaches into the floor (floor at z = 1.0).
        for (h = pi_holes) translate([h[0], h[1], pcb_z]) sp_insert_pocket(pi_insert);
    }
}

// ── Lid (top half) ────────────────────────────────────────────────
module grille2d(d, bar = 1.2, pitch = 4, spokes = 3) {
    difference() {
        circle(d = d);
        for (r = [pitch : pitch : d / 2 - 1.5])
            difference() { circle(r = r + bar / 2); circle(r = r - bar / 2); }
        for (a = [0 : 180 / spokes : 179]) rotate(a) square([d + 2, bar], center = true);
    }
}

// Vent slots start vent_z0 above the PCB top (the Active Cooler's fins sit
// ~3.5-13 above it), except where a slot comes within vent_web of a port
// opening in the same wall: that slot starts vent_web above the opening.
front_ops = [for (b = openings) if (b[2] < -g - wall) b];   // y = 0 wall
left_ops  = [for (b = openings) if (b[0] < -g - wall) b];   // x = 0 wall
function _ovl_top(ops, a0, a1, ax) =
    let (t = [for (b = ops) if (b[2 * ax] < a1 && b[2 * ax + 1] > a0) b[5]])
    len(t) > 0 ? max(t) : -1e9;
function _vent_z0(ops, c, ax) =
    max(pcb_top + vent_z0,
        _ovl_top(ops, c - vent_slot_w / 2 - vent_web, c + vent_slot_w / 2 + vent_web, ax)
            + vent_web);

module wall_vents() {
    zhi = roof_bot - 1.5;
    // left short wall (Active Cooler fins exhaust towards -x)
    for (y = [4 : vent_pitch : board_l - 4]) {
        zlo = _vent_z0(left_ops, y, 1);
        translate([-g - wall - 1, y - vent_slot_w / 2, zlo])
            cube([wall + 1.6, vent_slot_w, zhi - zlo]);
    }
    // both long walls (only the y = 0 wall carries ports)
    for (x = [5 : vent_pitch : board_w - 5], side = [0, 1]) {
        zlo = side == 0 ? _vent_z0(front_ops, x, 0) : pcb_top + vent_z0;
        translate([x - vent_slot_w / 2,
                   side == 0 ? -g - wall - 1 : board_l + g - 0.6, zlo])
            cube([vent_slot_w, wall + 1.6, zhi - zlo]);
    }
}

module roof_cuts() {
    if (gpio_slot)
        translate([PI5_GPIO_XC - gpio_w / 2, PI5_GPIO_YC - gpio_slot_w / 2, roof_bot - 1])
            cube([gpio_w, gpio_slot_w, wall + 2]);

    if (cooling == "active")
        translate([AC_INTAKE_C[0], AC_INTAKE_C[1], roof_bot - 1])
            linear_extrude(wall + 2) grille2d(intake_d);
    else if (cooling == "fan40")
        translate([PI5_SOC_C[0], PI5_SOC_C[1], roof_bot - 1]) {
            linear_extrude(wall + 2) grille2d(fan_grille_d);
            for (dx = [-1, 1], dy = [-1, 1])
                translate([dx * fan_hole_pitch / 2, dy * fan_hole_pitch / 2, 0])
                    cylinder(h = wall + 2, d = fan_screw_clear, $fn = 24);
        }
    else
        for (x = [18 : 4 : 48])
            translate([x - 1, 12, roof_bot - 1]) cube([2, 26, wall + 2]);

    // CAM/DISP ribbons straight up through the roof
    if (csi_slot)
        translate([csi_slot_x[0], csi_slot_y[0], roof_bot - 1])
            cube([csi_slot_x[1] - csi_slot_x[0], csi_slot_y[1] - csi_slot_y[0], wall + 2]);

    // Engraved wordmark on the roof, right-hand strip (clear of all cut-outs)
    translate([72, 28, roof_top - 0.6])
        linear_extrude(1)
            rotate(90)
                text("SporePrint", size = 5, halign = "center", valign = "center",
                     font = "Liberation Sans");
}

module pi_case_lid() {
    difference() {
        union() {
            translate([0, 0, z_split]) linear_extrude(lid_h) outline2d();
            translate([0, 0, z_split - lid_lip + lap_clr])
                linear_extrude(lid_lip - lap_clr + 0.01) lap_outer2d();
        }

        // Cavity up to the roof
        translate([0, 0, z_split - lid_lip - 1])
            linear_extrude(roof_bot - z_split + lid_lip + 1) cavity2d();

        lid_openings();
        wall_vents();
        roof_cuts();

        // M3 screw path: clearance through the tower, counterbore, and a
        // head well from the roof so an M3 x lid_screw_len engages the
        // full insert in the base tower.
        for (t = towers) translate([t[0], t[1], 0]) {
            translate([0, 0, z_split + lid_clamp])
                sp_screw_clearance(lid_insert, thickness = lid_clamp, counterbore = true);
            translate([0, 0, z_split + lid_clamp - 0.01])
                cylinder(d = sp_screw_head_d(lid_insert), h = lid_h - lid_clamp + 1, $fn = 32);
        }
    }

    // Intake shroud: ducts the roof grille straight onto the blower intake.
    if (cooling == "active") {
        z0 = pcb_top + cooler_h + shroud_gap;
        assert(roof_bot - z0 >= 0.4, "no room for the intake shroud");
        translate([AC_INTAKE_C[0], AC_INTAKE_C[1], z0])
            difference() {
                cylinder(d = intake_d + 2 * shroud_t, h = roof_bot - z0 + 0.01);
                translate([0, 0, -1]) cylinder(d = intake_d, h = roof_bot - z0 + 2);
            }
    }
}

// ── Render ────────────────────────────────────────────────────────

module base_print() { translate([-x_min, -y_min, 0]) pi_case_base(); }
module lid_print(dx = 0) {   // roof on the bed
    translate([dx - lid_x_min, y_max, roof_top]) rotate([180, 0, 0]) pi_case_lid();
}

if (part == "print") {
    base_print();
    lid_print(x_max - x_min + 10);
} else if (part == "base") {
    base_print();
} else if (part == "lid") {
    lid_print();
} else if (part == "assembly") {
    pi_case_base();
    pi_case_lid();
    %union() {
        pi5_pcb(pcb_z, pcb_thick);
        pi5_components(pcb_z, pcb_thick);
        if (cooling == "active") pi5_active_cooler(pcb_z, pcb_thick);
    }
}
