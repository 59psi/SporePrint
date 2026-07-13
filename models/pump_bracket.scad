// SporePrint Peristaltic Pump Bracket
// Saddle clamp for the Tier 3 dosing pump — Adafruit 1150 (Kamoer KMP-A1
// / NKP-DC): a 27 mm diameter DC motor with the pump head on the end,
// 72 mm total length, 12 V, ~100 mL/min. The round body rolls and walks
// under tubing torque if it is just set down; this cradles the motor barrel
// in two saddles and a zip tie captures it from above.
//
// Verified against the Adafruit 1150 product page ("27mm diameter motor,
// 72mm total length"). Only the motor barrel (27 mm) is cradled — the pump
// head overhangs one saddle, which is correct: leave it clear so the inlet /
// outlet ports and silicone tubing route freely.
//
// Mounting options:
//   - M3 screw holes  (base, to a wall or the chamber-outside shelf)
//   - Zip tie slots   (base, to a shelf wire / rail)
//   - Capture tie     (one over-the-barrel zip tie through each saddle top)
//
// Print settings: PLA or PETG, 0.2mm layer height, no supports — each
//   cradle is a half-pipe (180 deg) opening straight up, a concave-up
//   valley with no overhang; the capture tie does the retaining.
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters (Adafruit 1150 Kamoer pump) ─────────────────────
pump_d       = 27;    // mm — motor barrel diameter
pump_len     = 72;    // mm — total pump length (barrel + head)
fit          = 0.6;   // mm — cradle fit clearance on the barrel
wall         = 3;     // mm — saddle + base wall thickness
base_th      = 3;     // mm — base plate thickness
saddle_w     = 8;     // mm — saddle thickness along the pump axis
saddle_gap   = 34;    // mm — centre-to-centre spacing of the two saddles
end_margin   = 8;     // mm — base length past each saddle
side_margin  = 5;     // mm — base width past the saddle each side
screw_d      = 3.2;   // mm — M3 base mounting holes
cap_slot_w   = 2.6;   // mm — capture zip-tie slot width
cap_slot_l   = 5;     // mm — capture zip-tie slot length

// Zip tie parameters (base-to-shelf)
zt_width   = 3;    // mm — zip tie slot width
zt_depth   = 1.5;  // mm — zip tie slot depth
zt_spacing = 15;   // mm — distance between parallel zip tie slots

// ── Derived ────────────────────────────────────────────────────
cradle_r   = pump_d / 2 + fit;
saddle_h   = base_th + cradle_r;   // block top sits at the bore centre
base_w     = pump_d + wall * 2 + side_margin * 2;
base_l     = saddle_gap + saddle_w + end_margin * 2;
saddle_cx  = base_w / 2;
saddle_ys  = [base_l / 2 - saddle_gap / 2, base_l / 2 + saddle_gap / 2];

// ── Reusable mounting module ───────────────────────────────────
module zip_tie_slot(width=3, depth=1.5, spacing=15) {
    for (x = [-spacing/2, spacing/2])
        translate([x, 0, 0])
            cube([width, 20, depth], center=true);
}

// ── One saddle (cradles the barrel, capture-tie slots either side) ──
module saddle(y) {
    difference() {
        // Saddle block — top face at the bore centre line
        translate([saddle_cx - (cradle_r + wall), y - saddle_w / 2, 0])
            cube([(cradle_r + wall) * 2, saddle_w, saddle_h]);

        // Cradle bore — the lower half of this cylinder is carved out of the
        // block, leaving a 180 deg half-pipe the barrel drops into.
        translate([saddle_cx, y - saddle_w / 2 - 1, saddle_h])
            rotate([-90, 0, 0])
                cylinder(h = saddle_w + 2, r = cradle_r, $fn = 48);

        // Capture zip-tie slots (a tie loops over the barrel, down each side)
        for (dx = [-(cradle_r + wall / 2), cradle_r + wall / 2])
            translate([saddle_cx + dx, y, base_th + cradle_r * 0.6])
                cube([cap_slot_w, cap_slot_l, cradle_r], center = true);
    }
}

// ── Base plate ─────────────────────────────────────────────────
module base() {
    difference() {
        cube([base_w, base_l, base_th]);

        // M3 mounting holes (four corners)
        for (x = [6, base_w - 6])
            for (y = [6, base_l - 6])
                translate([x, y, -1])
                    cylinder(h = base_th + 2, d = screw_d, $fn = 20);

        // Zip tie slots (both long edges, mid-span)
        translate([0, base_l / 2, base_th / 2])
            rotate([0, 90, 0]) zip_tie_slot(zt_width, zt_depth, zt_spacing);
        translate([base_w, base_l / 2, base_th / 2])
            rotate([0, 90, 0]) zip_tie_slot(zt_width, zt_depth, zt_spacing);

        // Wordmark (engraved, base top, between the saddles)
        translate([base_w / 2, base_l / 2, base_th - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 4, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

// ── Assembly ───────────────────────────────────────────────────
module pump_bracket() {
    base();
    for (y = saddle_ys) saddle(y);
}

// ── Render ──────────────────────────────────────────────────────
pump_bracket();
