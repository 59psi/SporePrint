// SporePrint Climate Sensor Mount
// Three-bay chimney-vented enclosure for the climate node's I2C breakouts on
// one STEMMA QT daisy chain. Two printed pieces — body + lid — joined with
// M3 brass heat-set inserts; every board screws down onto M2.5 insert posts.
//
// ── What it fits (board data: lib/sensor_mount_dims.scad) ─────────────
//   bay 1  temp/RH  Adafruit 2857 SHT31-D, CURRENT STEMMA QT revision:
//                   25.40 x 17.78 mm, 4x Ø2.5 holes on 20.32 x 12.70 pitch
//                   (Adafruit board file "Adafruit SHT31-D STEMMA QT
//                   Breakout.brd"). Same outline + holes, so drop-ins:
//                   Adafruit 5665 SHT45, 5776 SHT41, 4885 SHT40.
//   bay 2  CO2      Adafruit 5190 SCD-41 / 5187 SCD-40: 25.40 x 22.86 mm,
//                   Ø3.0 holes on 20.32 x 17.78, 7.7 mm tall (board file
//                   "Adafruit SCD-41.brd" + product page).
//                   Pimoroni PIM587 (~24 x 21 x 8, Pimoroni page) fits the
//                   bay and rests on the posts — no published hole drawing,
//                   so fix it with a foam pad; it has ONE Qw/ST port, so it
//                   must be the last board on the chain.
//          scd30 = true -> Adafruit 4867 SCD-30: 50.80 x 25.40 mm, Ø2.5
//                   holes on 45.72 x 20.32, 8.8 mm tall; both of its QT
//                   ports are on ONE short edge (board file "Adafruit
//                   SCD30.brd").
//   bay 3  light    Adafruit 4681 BH1750: 25.40 x 17.78 mm (page: 25.3 x
//                   17.7 x 4.5), holes as bay 1. The lid has a flared Ø20
//                   aperture straight over the BH1750 die so it sees the
//                   grow light (±45° cone clear of the lid).
//   cables          Adafruit 4397 STEMMA QT -> female sockets (150 mm) from
//                   the ESP32 enters through the U-notch in the front wall;
//                   Adafruit 4210 QT-QT (100 mm) links the boards. JST-SH
//                   plugs (JST eSH.pdf: SHR-04V-S-B 7.0 x 5.0 x 2.8 mm)
//                   seat in the qt_clear zone beside each short board edge;
//                   wire slack coils in the front cable gallery (notch_w
//                   deep, runs the full length) — no cable crosses a
//                   sensor, the chimney vents or the BH1750 window.
//   Leave the loose 0.1" header strips that ship with the boards
//   UNSOLDERED — the QT connectors are the only wiring.
//
// ── Hardware to buy (per enclosure) ────────────────────────────────────
//   Heat-set inserts (lib/sp_inserts.scad table, ruthex / CNC Kitchen):
//     M3 x 5.7   x 4  body corner bosses (lid screws)
//     M2.5 x 5.7 x 6  board posts (2 diagonal per board; pcb_screws = 4
//                     -> x 12, see note on the SHT/BH ON LED below)
//     (+ M3 x 5.7 x 2 in sensor_bracket.scad's saddles)
//   Screws (ISO 4762 socket head cap):
//     M3 x 6     x 4  lid -> body   (sp_screw_len = 6.9 -> 6 mm stock)
//     M2.5 x 6   x 6  board -> post (sp_screw_len = 7.3 -> 6 mm stock)
//     M3 x 6     x 2  ear -> bracket saddle (sp_screw_len = 7.0 -> 6 mm)
//   Socket heads only (Ø4.5 max). On the 1.0 x 0.7 in boards the hole at
//   board (2.54, 15.24) — back-left as mounted — is 0.03 mm from the ON
//   LED under an Ø4.5 head, so the default diagonal pair (front-left +
//   back-right) skips it; with pcb_screws=4 use a Ø4.5-or-smaller head
//   there or leave that one out. No inserts? -D SP_FASTENER="self_tap".
//   The 4397 cable is 150 mm: the ESP32 must sit within ~10 cm of the
//   enclosure's front notch.
//
// ── Assembly ───────────────────────────────────────────────────────────
//   1. Press the inserts (iron ~220-245 °C). 2. Plug the QT cables into
//   the boards FIRST, then lower each board onto its posts and screw it
//   down. 3. Lay the ESP32 cable into the front U-notch, coil slack in the
//   gallery. 4. Lid on, four M3 x 6 from the top.
//
// ── Printing (Bambu / any FDM, PLA or PETG, 0.2 mm, NO supports) ───────
//   part = "print" lays both pieces flat: body floor-down, lid top-face-
//   down (its skirt, bosses and alignment tabs point up). The lid's
//   counterbores open onto the bed; their Ø6.2 -> Ø3.4 ceilings are a
//   1.4 mm annular bridge, fine without supports. Engraved wordmark and
//   labels print as recesses.
//
// ── Presets (-D) ───────────────────────────────────────────────────────
//   (none)                   SHT3x/4x + SCD4x (or PIM587) + BH1750
//   scd30=true               Adafruit 4867 SCD-30 in bay 2 (render
//                            sensor_bracket.scad with -D scd30=true too)
//   part="body" | "lid"      one piece only (print-oriented)
//   part="assembly"          lid in place, for viewing — not for printing
//   pcb_screws=4             insert pockets in all four posts per board
//   SP_FASTENER="self_tap"   pilot holes instead of insert pockets
//   part="none"              geometry off (for including in a test rig)
//   Sizes: SCD4x build 123.5 x 36.9 x 20.7 mm, SCD-30 build 149 x 39.4 x
//   20.7 mm, each + a 12 mm ear at both ends.
//
// Legacy knobs kept, with their current meaning: rail_h = PCB standoff
// height (min 5.7 for the M2.5 insert), notch_w = cable gallery depth (the
// ribs' STEMMA QT pass-through), notch_h / cable_slot = ESP32 U-notch
// depth / width, lid_lip / lid_tolerance = lid alignment tabs, ear_hole_d =
// minimum ear clearance hole, fit / board_clear / wall / vent_* / zt_* /
// ear_len / ear_t as named.
//
// ── History ────────────────────────────────────────────────────────────
// 2026-09 audit: bay 1 was 18.0 x 12.7 (the pre-2021 SHT31-D) — the
// shipping 25.4 x 17.8 STEMMA QT board did not fit; boards sat loose on
// rails; QT plugs from neighbouring boards met head-on in a 2.8 mm rib gap;
// the lid was a friction lip with no fasteners and printed floating; the
// bracket joint was two bare holes. All fixed here. The chimney venting
// (floor grid under each board, lid grid above) is unchanged in principle —
// it keeps the CO2 reading honest. Do not tape over it, and do not sit this
// on a solid surface: sensor_bracket.scad holds it on standoff saddles.
//
// Mounting options:
//   - M3 tie-down (one counterbored hole per end ear -> sensor_bracket.scad
//     saddle insert)
//   - Zip tie slots (two per end ear — shelf wire / rail)
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>
include <lib/sensor_mount_dims.scad>

// ── Parameters ─────────────────────────────────────────────────────────
scd30 = false;   // true -> wide bay 2 for the SCD-30 (Adafruit 4867)
part  = "print"; // "print" | "body" | "lid" | "assembly" | "none"

// Footprint knobs — keep equal to SM_*_DEFAULT in lib/sensor_mount_dims.scad
// (or pass the same -D to sensor_bracket.scad) so the bracket lines up.
fit           = 1.0;  // mm — total X/Y clearance added to each board (0.5/side)
wall          = 2;    // mm — wall, floor, rib and lid-plate thickness
qt_clear      = 6.0;  // mm — room past each short board edge for a mated
                      //      JST-SH plug + wire bend (plug ends ~1.5 mm out)
notch_w       = 9;    // mm — STEMMA QT pass-through: depth of the front
                      //      cable gallery that every rib stops short of
ear_len       = 12;   // mm — how far each ear sticks out from the shell
ear_t         = 4.5;  // mm — ear thickness (M3 counterbore 3.2 + 1.3 floor)

// Heights
rail_h        = 5.7;  // mm — PCB standoff above the floor (was a 1.5 mm
                      //      rail; raised to the M2.5 insert boss minimum)
board_clear   = 11;   // mm — PCB underside to lid underside (SCD-30 8.8 +
                      //      2.2 air; SCD4x 8.1 + 2.9)

// Cable + vents
notch_h       = 6;    // mm — ESP32 cable U-notch depth below the body rim
cable_slot    = 8;    // mm — ESP32 cable U-notch width (passes a 7.0 mm
                      //      SHR-04V-S-B plug with the lid off)
vent_d        = 3;    // mm — ventilation hole diameter
vent_pitch    = 5;    // mm — ventilation grid pitch
vent_inset    = 3;    // mm — keep vents this far inside each bay
bh_window_d   = 20;   // mm — BH1750 aperture Ø at the lid underside (±45°
                      //      view from the die clears the whole lid)
bh_window_flare = 45; // deg — aperture flares out through the lid plate

// Lid
lid_tolerance = 0.3;  // mm — alignment-tab clearance to the body walls
lid_lip       = 1.5;  // mm — alignment tabs reach this far below the rim

// PCB fastening
pcb_screws    = 2;    // 2 = diagonal pair per board, 4 = all four posts

// End ears — M3 tie-down + zip tie mounting options
ear_hole_d = 3.4;  // mm — M3 clearance hole (never smaller than the table)
zt_slot_w  = 2.4;  // mm — zip tie slot, across the tie's thickness (X)
zt_slot_l  = 4.5;  // mm — zip tie slot, across the tie's width (Y)
zt_slot_dy = 9;    // mm — zip tie slot offset from the ear centre

// ── Derived dimensions ─────────────────────────────────────────────────
slots   = sm_slots(scd30);
n       = len(slots);
gallery = notch_w;

pcb_screw = SM_PCB_SCREW;
lid_screw = SM_LID_SCREW;
tie_screw = SM_TIEDOWN_SCREW;

function bay_w(i)    = sm_bay_w(scd30, i, fit = fit, qt = qt_clear);
function bay_x(i)    = sm_bay_x(scd30, i, fit = fit, wall = wall, qt = qt_clear);
function board_o(i)  = sm_board_origin(scd30, i, fit = fit, wall = wall,
                                       qt = qt_clear, gallery = gallery);
// Posts that get an insert pocket: diagonal pair (holes list is BL, BR,
// TL, TR) or all four.
function screwed(k)  = pcb_screws >= 4 || k == 0 || k == 3;

outer_w = sm_outer_w(scd30, fit = fit, wall = wall, qt = qt_clear);
outer_l = sm_outer_l(scd30, fit = fit, wall = wall, gallery = gallery);
zone_y0 = wall + gallery;             // front edge of the board zone
zone_d  = sm_zone_d(scd30, fit = fit);

post_h  = max(rail_h, sp_insert_boss_h(pcb_screw) - wall);
pcb_z   = wall + post_h;              // PCB underside
lid_z   = pcb_z + board_clear;        // lid plate underside
outer_h = lid_z + wall;               // assembled height
lid_cap = sp_screw_head_h(lid_screw) + 1.2;  // lid thickness at a screw
rim_z   = outer_h - lid_cap;          // body rim = lid skirt joint

cb_r    = sp_insert_boss_d(lid_screw) / 2;   // corner boss radius
cb_c    = cb_r + 0.4;   // boss centre in from outside: 2.0 mm insert wall,
                         // 0.9 mm lid skin round the Ø6.2 counterbore
corners = [[cb_c, cb_c], [outer_w - cb_c, cb_c],
           [cb_c, outer_l - cb_c], [outer_w - cb_c, outer_l - cb_c]];
post_r  = sp_insert_boss_d(pcb_screw) / 2;
tab_t   = 1.2;                               // alignment tab thickness

ear_x   = [-ear_len / 2, outer_w + ear_len / 2];

function posts() = [for (i = [0 : n - 1]) for (k = [0 : len(slots[i][3]) - 1])
    [board_o(i)[0] + slots[i][3][k][0], board_o(i)[1] + slots[i][3][k][1],
     screwed(k) ? 1 : 0]];

function near_any(p, pts, r) =
    len([for (q = pts) if (norm([p[0] - q[0], p[1] - q[1]]) < r) 1]) > 0;

// BH1750 aperture centre (the bay whose record carries a light sensor).
bh_bays = [for (i = [0 : n - 1]) if (slots[i][5] != undef) i];
function bh_centre(i) = board_o(i) + slots[i][5];
bh_top_d = bh_window_d + 2 * wall * tan(bh_window_flare);

assert(qt_clear >= 5.5, "qt_clear < 5.5 mm: a mated JST-SH plug + wire bend will not fit");
assert(notch_w >= cb_c + cb_r - wall + 2.4,
       "notch_w too small: no cable path past the front corner bosses");

echo(str("sensor_mount: ", scd30 ? "SCD-30" : "SCD4x", " build ",
         outer_w, " x ", outer_l, " x ", outer_h, " mm (+ ", ear_len,
         " mm ears); lid screws ", lid_screw, " x ",
         sp_screw_len(lid_screw, lid_cap, true), " -> 6 mm stock; PCB screws ",
         pcb_screw, " x ", sp_screw_len(pcb_screw, SM_PCB_T, false),
         " -> 6 mm; ear screws ", tie_screw, " x ",
         sp_screw_len(tie_screw, ear_t, true), " -> 6 mm; inserts ",
         lid_screw, " x 4, ", pcb_screw, " x ",
         len([for (p = posts()) if (p[2] == 1) 1])));

// ── Body ───────────────────────────────────────────────────────────────
module ear_cuts(x_centre) {
    // Counterbored M3 clearance from the top (head sits below the ear top)
    translate([x_centre, outer_l / 2, ear_t])
        sp_screw_clearance(tie_screw, ear_t, true);
    translate([x_centre, outer_l / 2, -1])
        cylinder(h = ear_t + 2, d = ear_hole_d, $fn = 24);

    for (dy = [-zt_slot_dy, zt_slot_dy])
        translate([x_centre, outer_l / 2 + dy, ear_t / 2])
            cube([zt_slot_w, zt_slot_l, ear_t + 2], center = true);
}

module body_shell() {
    difference() {
        union() {
            cube([outer_w, outer_l, rim_z]);
            // End ears, flush with the floor so the part still sits flat
            translate([-ear_len, 0, 0]) cube([ear_len + 0.01, outer_l, ear_t]);
            translate([outer_w - 0.01, 0, 0]) cube([ear_len + 0.01, outer_l, ear_t]);
        }

        // One open interior: front cable gallery + the bays behind it
        translate([wall, wall, wall])
            cube([outer_w - 2 * wall, outer_l - 2 * wall, rim_z]);

        // Floor ventilation grid — under each bay (board + plug zones),
        // clear of posts and corner bosses so every hole is a through-hole
        for (i = [0 : n - 1])
            for (x = [bay_x(i) + vent_inset : vent_pitch :
                      bay_x(i) + bay_w(i) - vent_inset])
                for (y = [zone_y0 + vent_inset : vent_pitch :
                          zone_y0 + zone_d - vent_inset])
                    if (!near_any([x, y], posts(), post_r + vent_d / 2 + 0.4)
                        && !near_any([x, y], corners, cb_r + vent_d / 2 + 0.4))
                        translate([x, y, -1])
                            cylinder(h = wall + 2, d = vent_d, $fn = 16);

        // ESP32 cable entry: U-notch, front wall, open to the rim so the
        // cable (and its QT plug) drops in; the lid skirt closes the top
        translate([outer_w / 2 - cable_slot / 2, -1, rim_z - notch_h])
            cube([cable_slot, wall + 2, notch_h + 1]);

        ear_cuts(ear_x[0]);
        ear_cuts(ear_x[1]);

        // Bay labels (engraved, front face)
        for (i = [0 : n - 1])
            translate([bay_x(i) + bay_w(i) / 2, 0.4, rim_z / 2 - 2.5])
                rotate([90, 0, 0])
                    linear_extrude(0.5)
                        text(slots[i][2], size = 3, halign = "center",
                             font = "Liberation Sans");
    }
}

module sensor_mount() {
    difference() {
        union() {
            body_shell();

            // Ribs between bays — board zone only, so the gallery in front
            // is one continuous cable run (the STEMMA QT pass-through)
            for (i = [1 : n - 1])
                translate([bay_x(i) - wall, zone_y0, wall - 0.01])
                    cube([wall, outer_l - wall - zone_y0 + 0.01,
                          rim_z - wall + 0.01]);

            // PCB posts (M2.5 insert bosses) at each board's own holes
            for (p = posts())
                translate([p[0], p[1], 0])
                    sp_insert_boss(pcb_screw, pcb_z);

            // Lid corner bosses (M3 inserts), merged into the walls
            for (c = corners)
                translate([c[0], c[1], 0])
                    sp_insert_boss(lid_screw, rim_z);
        }

        // Insert pockets, cut after the union so no wall fills them
        for (p = posts())
            if (p[2] == 1)
                translate([p[0], p[1], pcb_z]) sp_insert_pocket(pcb_screw);
        for (c = corners)
            translate([c[0], c[1], rim_z]) sp_insert_pocket(lid_screw);
    }
}

// ── Lid (assembled position: skirt joint at rim_z, top face at outer_h) ─
module sensor_lid() {
    skirt_h = lid_z - rim_z;
    difference() {
        union() {
            // Top plate
            translate([0, 0, lid_z]) cube([outer_w, outer_l, wall]);

            // Skirt — the top lid_cap - wall of the side walls
            translate([0, 0, rim_z])
                difference() {
                    cube([outer_w, outer_l, skirt_h + 0.01]);
                    translate([wall, wall, -1])
                        cube([outer_w - 2 * wall, outer_l - 2 * wall,
                              skirt_h + 2]);
                }

            // Rib caps continue the bay separation up to the plate
            for (i = [1 : n - 1])
                translate([bay_x(i) - wall, zone_y0, rim_z])
                    cube([wall, outer_l - wall - zone_y0 + 0.01,
                          skirt_h + 0.01]);

            // Screw bosses over the body's corner bosses
            for (c = corners)
                translate([c[0], c[1], rim_z])
                    cylinder(h = skirt_h + 0.01, r = cb_r, $fn = 32);

            // Alignment tabs down inside both end walls (secondary to the
            // screws). Clear of the corner bosses; nothing tall sits there.
            for (s = [0, 1]) {
                x_in = s == 0 ? wall : outer_w - wall;
                y0   = cb_c + cb_r + lid_tolerance;
                y1   = outer_l - cb_c - cb_r - lid_tolerance;
                // upper part merged into the skirt
                translate([s == 0 ? x_in - 0.01
                                  : x_in - lid_tolerance - tab_t, y0, rim_z])
                    cube([lid_tolerance + tab_t + 0.01, y1 - y0, skirt_h + 0.01]);
                // lower part stands lid_tolerance off the body wall
                translate([s == 0 ? x_in + lid_tolerance
                                  : x_in - lid_tolerance - tab_t,
                           y0, rim_z - lid_lip])
                    cube([tab_t, y1 - y0, lid_lip + 0.01]);
            }
        }

        // M3 clearance + counterbore through the full lid_cap at each boss
        for (c = corners)
            translate([c[0], c[1], outer_h])
                sp_screw_clearance(lid_screw, lid_cap, true);

        // Chimney outlets — plate only, over each bay's board zone
        for (i = [0 : n - 1])
            for (x = [bay_x(i) + vent_inset : vent_pitch :
                      bay_x(i) + bay_w(i) - vent_inset])
                for (y = [zone_y0 + vent_inset : vent_pitch :
                          zone_y0 + zone_d - vent_inset])
                    if (!near_any([x, y], corners,
                                  sp_screw_head_d(lid_screw) / 2 + vent_d / 2 + 0.8)
                        && !near_any([x, y], [for (b = bh_bays) bh_centre(b)],
                                     bh_top_d / 2 + vent_d / 2 + 0.8))
                        translate([x, y, lid_z - 0.01])
                            cylinder(h = wall + 1, d = vent_d, $fn = 16);

        // BH1750 light aperture, flared so the lid plate does not narrow
        // the sensor's view
        for (b = bh_bays)
            translate([bh_centre(b)[0], bh_centre(b)[1], lid_z - 0.01])
                cylinder(h = wall + 0.02, d1 = bh_window_d, d2 = bh_top_d,
                         $fn = 48);

        // Wordmark (engraved, over the cable gallery strip)
        translate([outer_w / 2, zone_y0 / 2, outer_h - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 3.5, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

// ── Render ──────────────────────────────────────────────────────────────
module lid_print() {
    // Top face down on the bed (rotation, not a mirror: text stays right)
    translate([0, 2 * outer_l + 10, outer_h])
        rotate([180, 0, 0])
            sensor_lid();
}

if (part == "print") {
    sensor_mount();
    lid_print();
} else if (part == "body") {
    sensor_mount();
} else if (part == "lid") {
    lid_print();
} else if (part == "assembly") {
    sensor_mount();
    color("LightGreen", 0.6) sensor_lid();
}
