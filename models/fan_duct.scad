// SporePrint 80mm Fan Duct Adapter
// Adapts an 80 mm PC fan to a 4-inch (100-102 mm) flexible duct
// for directing FAE into or out of a grow chamber.
//
// ── FITS (final BOM parts) ─────────────────────────────────────────────────
//   * Noctua NF-A8 PWM, 12 V (Amazon B00NEMG62M) — 80 x 80 x 25 mm,
//     71.5 x 71.5 mm hole pattern. Source: Noctua NF-A8 PWM infosheet
//     (cdn.noctua.at/media/noctua_nf_a8_pwm_infosheet_en_web.pdf) + Noctua
//     spec page. Noctua does not publish the hole Ø; like every 80 mm fan
//     it clears an M4 shank.
//   * Arctic P8 PWM PST (Amazon B07XR1KLLK, ACFAN00150A) — 80 x 80 x 25 mm,
//     71.5 mm hole pitch, Ø4.40 frame holes, 5.0 mm corner flanges.
//     Source: Arctic "P8 Series 2D Drawing" (rev 2024-03-12) and "80mm fan
//     mounting hole drawing" (Ø4.30 panel holes, Ø76.30 airflow cutout),
//     support.arctic.de/p8-pwm-pst/docs.
//   * Duct: any 4-inch / 100 mm flexible duct (foil, vinyl or PVC helix)
//     that slides OVER the spigot. Defaults assume ID 100 mm / OD 102 mm;
//     imperial 4" duct (ID 101.6) fits the defaults too. Measure yours and
//     set duct_id / duct_od if the fingers rub.
//
// ── HOW IT ASSEMBLES ───────────────────────────────────────────────────────
//   The fan's face sits flat on the flange face (the face printed on the
//   bed). Four M4 screws go in from the fan's FAR face, through the fan's
//   own corner holes, and thread into M4 brass heat-set inserts pressed
//   into the flange bosses from the fan side. The driver works from the
//   fan side, so nothing on the duct side (where the transition flares out
//   over the corners) is in the way. The duct slides over the spigot until
//   it hits the stop ring; one zip tie threaded through the four finger
//   tunnels (or a hose clamp above the fingers) cinches it down behind the
//   barb.
//   Either fan face can go against the flange (push into or pull out of
//   the duct). Noctua's bundled self-tapping fan screws and anti-vibration
//   mounts are meant for sheet-metal case panels and are NOT used here.
//   Default size: 86 x 86 mm flange (3 mm past the fan each side),
//   Ø114 mm max at the stop ring, 73 mm tall; spigot Ø97 (bore Ø93).
//
// ── BUY (per adapter) ──────────────────────────────────────────────────────
//   fan_mount = "insert" (default):
//     4x M4 heat-set insert, 8.1 mm long (ruthex RX-M4x8.1 / CNC Kitchen
//        M4x8.1) — press in from the fan face, ~230 °C iron, until flush.
//     4x M4 x 35 mm screw (ISO 4762 socket head or ISO 7380 button head,
//        A2 stainless for the humid closet). 25 mm fan + full 8.1 mm insert
//        engagement; the boss is open on top so M4 x 40 also fits.
//        M4 x 30 works too (5 mm of thread engaged).
//   fan_mount = "nut":
//     4x M4 hex nut (ISO 4032, 7 mm AF x 3.2 mm) dropped into the traps on
//        the duct side of each boss, + 4x M4 x 35 mm screw as above.
//   Duct retention: 1x zip tie >= 360 mm (14") long, <= 4.8 mm wide,
//     <= 1.4 mm thick (threads through the finger tunnels), or a 4"
//     worm-drive hose clamp (<= 12.7 mm band) on the bare spigot above the
//     fingers.
//   The echo() lines at render time repeat the screw length for the
//   current parameters.
//
// ── PRINT ──────────────────────────────────────────────────────────────────
//   Single piece. PETG (preferred in the humid closet) or PLA, 0.2 mm
//   layers, 3 perimeters. Print exactly as rendered: flange (fan face) flat
//   on the bed, spigot up. NO SUPPORTS: the stop-ring and barb undersides
//   are 45° chamfers, the transition leans ~12° off vertical, the finger
//   tunnel roofs bridge 2 mm, and the insert-pocket ceiling bridges a
//   0.55 mm annulus. After printing, flip the part and press the inserts
//   in from the fan face.
//
// ── PRESETS (-D) ───────────────────────────────────────────────────────────
//   (default)                  M4 heat-set inserts, zip-tie fingers.
//   -D 'fan_mount="nut"'       M4 hex-nut traps instead of inserts; bolt
//                              holes are fan_hole_d (Arctic's Ø4.30).
//   -D 'SP_FASTENER="self_tap"' insert pockets become Ø3.3 pilots for M4
//                              self-tapping (plastite) screws — no inserts.
//   -D zip_tie_tabs=false      plain spigot + stop ring, for a hose clamp.
//   -D duct_id=101.6 -D duct_od=104   imperial 4" flex duct (larger OD).
//   Any top-of-file parameter can be overridden the same way, e.g.
//   -D SP_INSERT_HOLE_TWEAK=-0.1 if inserts go in too loose.
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>

// ── Parameters ────────────────────────────────────────────────
fan_size       = 80;    // mm — fan frame outer dimension
fan_thickness  = 25;    // mm — fan frame depth (screw length calc)
fan_hole_d     = 4.3;   // mm — M4 bolt hole Ø (fan_mount="nut"); Arctic Ø4.30
fan_hole_inset = 4.25;  // mm — screw hole center from fan edge (71.5 mm pitch)
fan_opening    = 76.3;  // mm — airflow opening Ø (Arctic recommended cutout)
duct_od        = 102;   // mm — 4-inch duct outer diameter
duct_id        = 100;   // mm — 4-inch duct inner diameter
duct_clearance = 1.5;   // mm — radial slack, duct ID over the spigot OD
duct_insert    = 30;    // mm — how far the duct slides onto the spigot
transition_h   = 40;    // mm — height of square-to-round transition
wall           = 2;     // mm — wall thickness
flange_depth   = 3;     // mm — fan mounting flange thickness
flange_margin  = 3;     // mm — flange overhang past the fan frame, per side
flange_corner_r = 3.5;  // mm — flange corner radius
barb_height    = 2;     // mm — barb ramp length is 2 x this (axial)
barb_width     = 1;     // mm — barb radial height above the spigot
stop_h         = 2;     // mm — duct stop ring thickness

// Fan fastening
fan_mount      = "insert"; // "insert" (M4 heat-set) | "nut" (M4 hex-nut trap)
fan_insert     = "M4";     // insert/screw size (fan holes are Ø4.3-4.4)
fan_boss_d     = 12;       // mm — boss Ø (fits the M4 insert AND nut trap)
nut_af         = 7.0;      // mm — M4 hex nut across flats (ISO 4032)
nut_h          = 3.2;      // mm — M4 hex nut thickness
nut_clearance  = 0.3;      // mm — per side, nut in its trap

// Zip tie parameters
zip_tie_tabs = true; // four tie-guide fingers on the stop ring
zt_width     = 5.6;  // mm — zip tie slot width (axial) — 4.8 mm tie + 0.4/side
zt_height    = 2.0;  // mm — zip tie slot height (radial depth) — 1.4 mm tie
zt_tab_width = 10;   // mm — finger width (tangential)
zt_tab_depth = 4.4;  // mm — finger radial thickness (skin + slot + skin)
zt_gap       = 1.0;  // mm — radial gap, duct OD to finger inner face
zt_tie_z     = 3;    // mm — slot bottom above the duct stop face
zt_roof      = 2;    // mm — finger material above the slot

// ── Derived ───────────────────────────────────────────────────
fan_r          = fan_opening / 2;
duct_r         = duct_od / 2;
total_h        = flange_depth + transition_h + duct_insert;
flange_size    = fan_size + 2 * flange_margin;
fan_hole_spacing = fan_size - 2 * fan_hole_inset;          // 71.5
fan_hole_pos   = [for (x = [-1, 1]) for (y = [-1, 1])
                    [x * fan_hole_spacing / 2, y * fan_hole_spacing / 2]];
fan_boss_h     = sp_insert_boss_h(fan_insert);             // 10.1 for M4
nut_trap_af    = nut_af + 2 * nut_clearance;
nut_trap_ac    = nut_trap_af / cos(30);
nut_floor_z    = flange_depth + 1.5;                       // trap floor

collar_r       = duct_id / 2 - duct_clearance;             // spigot OD / 2
collar_ri      = collar_r - wall;                          // spigot bore
z_collar       = flange_depth + transition_h;              // duct stop face
zt_r_in        = duct_r + zt_gap;                          // finger inner face
zt_finger_h    = zt_tie_z + zt_width + zt_roof;
zt_skin        = (zt_tab_depth - zt_height) / 2;
stop_r         = zip_tie_tabs
                   ? sqrt(pow(zt_r_in + zt_tab_depth, 2) + pow(zt_tab_width / 2, 2)) + 0.3
                   : duct_r + 1;
// Transition wall: flares from the fan opening (tr_ri0/tr_ro0 at the flange
// top) to the spigot; the stop ring's 45° underside meets its outer wall at
// (r_ch, z_ch).
tr_ri0         = fan_r;
tr_ro0         = fan_r + wall;
tr_k           = (collar_r - tr_ro0) / transition_h;       // outer slope dr/dz
z_ch           = (stop_r - z_collar + stop_h - tr_ro0 + tr_k * flange_depth) / (tr_k - 1);
r_ch           = tr_ro0 + tr_k * (z_ch - flange_depth);

// Screw length for the current mode. The fan body is the clamped part (no
// counterbore). sp_screw_len() = 25 + 8.1 = 33.1 for full insert engagement;
// round UP to stock (5 mm steps) because the boss is open on top, so the
// extra run-out is harmless and the whole insert is engaged.
fan_screw_min  = fan_mount == "nut"
                   ? fan_thickness + nut_floor_z + nut_h + 1
                   : sp_screw_len(fan_insert, fan_thickness, counterbore = false);
fan_screw_len  = ceil(fan_screw_min / 5) * 5;

// ── Sanity checks ─────────────────────────────────────────────
assert(fan_mount == "insert" || fan_mount == "nut",
       str("fan_mount must be \"insert\" or \"nut\", got ", fan_mount));
assert(fan_boss_d >= sp_insert_boss_d(fan_insert) - 0.001,
       "fan_boss_d too small for the insert wall");
assert(fan_mount != "nut" || fan_boss_d >= nut_trap_ac + 2 * 1.2,
       "fan_boss_d too small for the nut trap");
assert(fan_hole_inset + flange_margin >= fan_boss_d / 2 + 0.8,
       "boss would break out of the flange edge — raise flange_margin");
// boss centre sits (flange_margin + fan_hole_inset) in from both edges;
// the corner arc must stay clear of it along the diagonal
assert(flange_corner_r <= flange_margin + fan_hole_inset &&
       (flange_margin + fan_hole_inset - flange_corner_r) * sqrt(2) + flange_corner_r
           >= fan_boss_d / 2 + 0.8,
       "flange corner radius would cut into a boss");
assert(fan_r + wall + (collar_r - fan_r - wall) * (fan_boss_h - flange_depth) / transition_h
           < fan_hole_spacing / 2 * sqrt(2) - fan_boss_d / 2,
       "transition wall runs into the fan bosses");
assert(zt_skin >= 0.8, "zt_tab_depth too thin around the tie slot");
// Everything above the bosses is open up to the stop-ring chamfer: room
// for the screw run-out (+5 mm for a longer screw) and for dropping nuts in.
assert(z_ch > max(fan_screw_len - fan_thickness + 5, fan_boss_h + nut_h + 3),
       "stop-ring chamfer too low over the fan screws — raise transition_h");

echo(str("fan_duct: 4x ", fan_insert, " x ", fan_screw_len, " mm ",
         fan_mount == "nut" ? "machine screws + 4x hex nuts" :
         SP_FASTENER == "self_tap" ? "self-tapping (plastite) screws, no inserts" :
         str("machine screws + 4x heat-set inserts (L ", sp_insert_len(fan_insert), " mm)"),
         ", driven in from the fan's far face"));

// ── Fan mounting flange (square) + fastener bosses ────────────
module fan_flange() {
    difference() {
        union() {
            // Plate overhanging the fan frame by flange_margin
            linear_extrude(flange_depth)
                offset(r = flange_corner_r)
                    square(flange_size - 2 * flange_corner_r, center = true);
            // Fastener bosses on the duct side, one per fan hole
            for (p = fan_hole_pos)
                translate([p[0], p[1], 0])
                    cylinder(h = fan_boss_h, d = fan_boss_d, $fn = 48);
        }

        // Central opening (matches the fan blade area)
        translate([0, 0, -1])
            cylinder(h = flange_depth + 2, r = fan_r, $fn = 128);

        // Fastener cut at each hole
        for (p = fan_hole_pos)
            translate([p[0], p[1], 0])
                fan_fastener_cut();
    }
}

// Screw path at one hole, fan face at z = 0, boss above.
module fan_fastener_cut() {
    if (fan_mount == "nut") {
        // Bolt hole through flange + boss, hex trap open to the duct side
        translate([0, 0, -0.01])
            cylinder(h = fan_boss_h + 0.02, d = fan_hole_d, $fn = 24);
        translate([0, 0, nut_floor_z])
            cylinder(h = fan_boss_h, d = nut_trap_ac, $fn = 6);
    } else {
        // Heat-set insert pocket, mouth on the fan face (pressed in from there)
        mirror([0, 0, 1]) sp_insert_pocket(fan_insert);
        // Screw run-out above the pocket so longer screws never bottom out
        translate([0, 0, sp_insert_depth(fan_insert) - 0.01])
            cylinder(h = fan_boss_h, d = sp_screw_clearance_d(fan_insert), $fn = 32);
    }
}

// ── Square-to-round transition (hollow funnel + duct stop ring) ──
// One revolved wall profile: flares from the fan opening to the spigot
// bore, then a stop ring whose underside is a 45° chamfer (no supports).
module transition() {
    rotate_extrude($fn = 128)
        polygon([
            [tr_ri0, 0],
            [tr_ro0, 0],
            [tr_ro0, flange_depth],
            [r_ch, z_ch],
            [stop_r, z_collar - stop_h],
            [stop_r, z_collar],
            [collar_ri, z_collar],
            [tr_ri0, flange_depth],
        ]);
}

// ── Duct spigot (round, with retention barb) ──────────────────
// The duct slides OVER this. Barb near the tip: gentle lead-in ramp,
// 45° back face; a tie cinched below it locks the duct on.
module duct_collar() {
    z_top    = total_h;
    tip_ch   = 0.8;                     // lead-in chamfer at the tip
    tip_land = 1.5;
    zb2 = z_top - tip_land;             // ramp top (back to spigot OD)
    zb1 = zb2 - 2 * barb_height;        // barb peak
    zb0 = zb1 - barb_width;             // 45° back face start
    rotate_extrude($fn = 128)
        polygon([
            [collar_ri, z_collar - 0.01],
            [collar_r, z_collar - 0.01],
            [collar_r, zb0],
            [collar_r + barb_width, zb1],
            [collar_r, zb2],
            [collar_r, z_top - tip_ch],
            [collar_r - tip_ch, z_top],
            [collar_ri, z_top],
        ]);
}

// ── Zip tie guide fingers (on the stop ring, outside the duct) ─
// Each finger has a tangential tunnel; one zip tie threads through all
// four and around the duct, so the tie can't walk off the duct.
module zt_retention_tabs() {
    for (a = [0, 90, 180, 270])
        rotate([0, 0, a])
            difference() {
                translate([zt_r_in, -zt_tab_width / 2, z_collar - 0.01])
                    cube([zt_tab_depth, zt_tab_width, zt_finger_h + 0.01]);
                // Zip tie tunnel (runs tangentially through the finger)
                translate([zt_r_in + zt_skin, -zt_tab_width / 2 - 1,
                           z_collar + zt_tie_z])
                    cube([zt_height, zt_tab_width + 2, zt_width]);
            }
}

// ── Full assembly ─────────────────────────────────────────────
module fan_duct() {
    fan_flange();
    transition();
    duct_collar();
    if (zip_tie_tabs) zt_retention_tabs();
}

// Wordmark engraved into the front edge of the square fan flange
// (the only flat face — the rest is the transition cone + collar).
module fan_duct_printable() {
    difference() {
        fan_duct();
        translate([0, -flange_size / 2 + 0.4, 0.5])
            rotate([90, 0, 0])
                linear_extrude(0.5)
                    text("SporePrint", size = 2, halign = "center",
                         font = "Liberation Sans");
    }
}

// ── Render ─────────────────────────────────────────────────────
fan_duct_printable();
