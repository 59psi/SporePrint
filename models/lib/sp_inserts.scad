// SporePrint — shared fastener geometry for multi-piece prints
//
// Library file: functions, modules and constants only, NO top-level geometry.
// Models pull it in with
//
//     include <lib/sp_inserts.scad>
//
// (include, not use — the models read the SP_* constants). The Builder
// download endpoint (/api/builder/models/<file>.scad) inlines this file in
// place of that include line, so a single downloaded model still renders on
// its own.
//
// Every joint between two printed parts uses a brass heat-set ("push-in")
// threaded insert in one part and a counterbored clearance hole in the
// other. Inserts are pressed in with a soldering iron (tip ~220-245 °C for
// PLA/PETG) until flush; the pocket is deeper than the insert so displaced
// plastic has somewhere to go instead of blocking the thread.
//
// Insert sizes are the common "standard" knurled brass inserts sold by
// CNC Kitchen / ruthex (and their clones). Pocket diameters are the vendor-
// recommended pilot holes; wall is the recommended minimum around the pocket:
//
//   size  insert L  pocket Ø  min wall  |  source
//   M2      4.0      3.2       1.5      |  ruthex RX-M2x4, CNC Kitchen M2x3
//   M2.5    5.7      3.6       1.5      |  ruthex RX-M2.5x5.7
//   M3      5.7      4.0       1.6      |  ruthex RX-M3x5.7, CNC Kitchen M3x5.7
//   M4      8.1      5.6       2.0      |  ruthex RX-M4x8.1, CNC Kitchen M4x8.1
//   M5      9.5      6.4       2.5      |  ruthex RX-M5x9.5, CNC Kitchen M5x9.5
//
// Pocket depth = insert length + SP_INSERT_EXTRA_DEPTH. Printers vary: if an
// insert goes in too loose/tight, tune SP_INSERT_HOLE_TWEAK (mm, added to the
// pocket diameter) from the command line, e.g.
//     openscad -D SP_INSERT_HOLE_TWEAK=-0.1 -o esp32_case.stl esp32_case.scad
//
// No inserts on hand? Set SP_FASTENER = "self_tap" and every pocket becomes a
// plain pilot hole for a self-tapping screw of the same nominal size.

SP_FASTENER           = "insert";  // "insert" | "self_tap"
SP_INSERT_HOLE_TWEAK  = 0;         // mm added to every insert pocket Ø
SP_INSERT_EXTRA_DEPTH = 1.0;       // mm of pocket below the seated insert
SP_INSERT_CHAMFER     = 0.5;       // mm lead-in chamfer at the pocket mouth

//  [size, insert_len, pocket_d, min_wall, clearance_d, head_d, head_h, self_tap_pilot_d]
//  clearance_d / head_d / head_h are for an ISO 4762 socket-head cap screw
//  (head Ø M2 3.8, M2.5 4.5, M3 5.5, M4 7.0, M5 8.5) plus print clearance.
SP_INSERT_TABLE = [
    ["M2",   4.0, 3.2, 1.5, 2.4, 4.4, 2.2, 1.7],
    ["M2.5", 5.7, 3.6, 1.5, 2.9, 5.1, 2.7, 2.1],
    ["M3",   5.7, 4.0, 1.6, 3.4, 6.2, 3.2, 2.5],
    ["M4",   8.1, 5.6, 2.0, 4.5, 7.8, 4.2, 3.3],
    ["M5",   9.5, 6.4, 2.5, 5.5, 9.4, 5.2, 4.2],
];

function _sp_insert_row(size, i = 0) =
    i >= len(SP_INSERT_TABLE) ? undef :
    SP_INSERT_TABLE[i][0] == size ? SP_INSERT_TABLE[i] :
    _sp_insert_row(size, i + 1);

function _sp_row(size) =
    let (r = _sp_insert_row(size))
    assert(r != undef, str("sp_inserts: unknown fastener size ", size))
    r;

// Seated insert length (mm).
function sp_insert_len(size = "M3") = _sp_row(size)[1];

// Pocket (or self-tap pilot) diameter actually cut (mm).
function sp_insert_hole_d(size = "M3") =
    SP_FASTENER == "self_tap" ? _sp_row(size)[7]
                              : _sp_row(size)[2] + SP_INSERT_HOLE_TWEAK;

// Pocket depth (mm) — insert length plus relief for displaced plastic.
function sp_insert_depth(size = "M3") = sp_insert_len(size) + SP_INSERT_EXTRA_DEPTH;

// Minimum boss Ø (mm) that keeps the recommended wall around the pocket.
// Uses the insert pocket even in self_tap mode so a part's outline never
// changes with the fastener choice.
function sp_insert_boss_d(size = "M3") =
    _sp_row(size)[2] + SP_INSERT_HOLE_TWEAK + 2 * _sp_row(size)[3];

// Minimum boss height (mm) — the pocket plus a 1 mm floor.
function sp_insert_boss_h(size = "M3") = sp_insert_depth(size) + 1.0;

// Clearance hole Ø for the screw in the mating part (mm).
function sp_screw_clearance_d(size = "M3") = _sp_row(size)[4];

// Counterbore Ø / depth for a socket-head cap screw (mm).
function sp_screw_head_d(size = "M3") = _sp_row(size)[5];
function sp_screw_head_h(size = "M3") = _sp_row(size)[6];

// Insert pocket, to be subtracted. Mouth at z = 0, pocket extends DOWN
// (−z) by sp_insert_depth(). A 0.01 mm overshoot above z = 0 keeps the
// boolean clean. Includes a lead-in chamfer so the insert self-centres.
module sp_insert_pocket(size = "M3", $fn = 32) {
    d = sp_insert_hole_d(size);
    depth = sp_insert_depth(size);
    translate([0, 0, -depth])
        cylinder(h = depth + 0.01, d = d);
    if (SP_FASTENER == "insert")
        translate([0, 0, -SP_INSERT_CHAMFER])
            cylinder(h = SP_INSERT_CHAMFER + 0.01,
                     d1 = d, d2 = d + 2 * SP_INSERT_CHAMFER);
}

// Solid boss sized for an insert, standing UP from z = 0 to z = h.
// Default h is the minimum that fits the pocket.
module sp_insert_boss(size = "M3", h = undef, $fn = 32) {
    hh = h == undef ? sp_insert_boss_h(size) : h;
    assert(hh >= sp_insert_boss_h(size) - 0.001,
           str("sp_insert_boss: height ", hh, " < minimum ", sp_insert_boss_h(size), " for ", size));
    cylinder(h = hh, d = sp_insert_boss_d(size));
}

// Boss with its pocket already cut, mouth at the top (z = h).
module sp_insert_boss_with_pocket(size = "M3", h = undef, $fn = 32) {
    hh = h == undef ? sp_insert_boss_h(size) : h;
    difference() {
        sp_insert_boss(size, hh);
        translate([0, 0, hh]) sp_insert_pocket(size);
    }
}

// Screw path through the mating part, to be subtracted. The part's outer
// face is at z = 0 and the part occupies z < 0 down to z = −thickness.
// Cuts a clearance hole all the way through and, when counterbore = true,
// a socket-head counterbore from the outer face. Overshoots both faces.
module sp_screw_clearance(size = "M3", thickness = 3, counterbore = true, $fn = 32) {
    translate([0, 0, -thickness - 0.01])
        cylinder(h = thickness + 0.02, d = sp_screw_clearance_d(size));
    if (counterbore)
        translate([0, 0, -min(sp_screw_head_h(size), thickness - 0.8)])
            cylinder(h = sp_screw_head_h(size) + 0.01, d = sp_screw_head_d(size));
}

// Screw length (mm) that engages the full insert through a clamp of the
// given thickness — pick the next stock length at or below this.
function sp_screw_len(size = "M3", clamp_thickness = 3, counterbore = true) =
    let (under_head = counterbore
            ? clamp_thickness - min(sp_screw_head_h(size), clamp_thickness - 0.8)
            : clamp_thickness)
    under_head + sp_insert_len(size);
