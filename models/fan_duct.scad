// SporePrint 80mm Fan Duct Adapter
// Adapts an 80mm PC fan to a 4-inch (102mm) flexible duct
// for directing FAE into or out of a grow chamber
// Print: PETG or PLA, 0.2mm layer height, no supports needed
// Attach fan with M4 screws, duct with hose clamp
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters ────────────────────────────────────────────────
fan_size       = 80;    // mm — fan frame outer dimension
fan_hole_d     = 4.3;   // mm — M4 fan screw hole diameter
fan_hole_inset = 3.6;   // mm — screw hole center from fan edge
fan_opening    = 75;    // mm — fan blade opening diameter
duct_od        = 102;   // mm — 4-inch duct outer diameter
duct_id        = 100;   // mm — 4-inch duct inner diameter
duct_insert    = 30;    // mm — how deep the duct slides in
transition_h   = 40;    // mm — height of square-to-round transition
wall           = 2;     // mm — wall thickness
flange_depth   = 3;     // mm — fan mounting flange thickness
barb_height    = 2;     // mm — duct retention barb height
barb_width     = 1;     // mm — duct retention barb thickness

// ── Derived ───────────────────────────────────────────────────
fan_r          = fan_opening / 2;
duct_r         = duct_od / 2;
total_h        = flange_depth + transition_h + duct_insert;

// ── Fan mounting flange (square) ──────────────────────────────
module fan_flange() {
    difference() {
        // Square plate matching fan frame
        translate([-fan_size / 2, -fan_size / 2, 0])
            cube([fan_size, fan_size, flange_depth]);

        // Central opening (circular, matches fan blade area)
        translate([0, 0, -1])
            cylinder(h = flange_depth + 2, r = fan_r, $fn = 64);

        // Fan screw holes (four corners)
        for (x = [-1, 1])
            for (y = [-1, 1])
                translate([x * (fan_size / 2 - fan_hole_inset),
                           y * (fan_size / 2 - fan_hole_inset), -1])
                    cylinder(h = flange_depth + 2, d = fan_hole_d, $fn = 16);

        // Corner radius (cosmetic, matches typical fan frame)
        for (x = [-1, 1])
            for (y = [-1, 1])
                translate([x * fan_size / 2, y * fan_size / 2, -1])
                    cylinder(h = flange_depth + 2, r = 4, $fn = 16);
    }
}

// ── Square-to-round transition ────────────────────────────────
module transition() {
    // Loft from square opening to round duct
    // Uses hull between slices at different heights
    steps = 20;
    step_h = transition_h / steps;

    for (i = [0 : steps - 1]) {
        t = i / steps;           // 0..1 interpolation
        t_next = (i + 1) / steps;
        z = flange_depth + i * step_h;
        z_next = flange_depth + (i + 1) * step_h;

        hull() {
            // Bottom slice
            _transition_slice(t, z);
            // Top slice
            _transition_slice(t_next, z_next);
        }
    }
}

module _transition_slice(t, z) {
    // Interpolate between square (t=0) and circle (t=1)
    // At t=0: square with rounded corners matching fan opening
    // At t=1: circle matching duct diameter
    r = fan_r + (duct_r - fan_r) * t;
    fn = 4 + floor(60 * t);  // 4 sides (square) -> 64 sides (circle)
    fn_clamped = max(fn, 4);

    translate([0, 0, z])
        // Use high $fn and interpolate corner radius for smooth transition
        difference() {
            cylinder(h = 0.01, r = r + wall, $fn = 64);
            translate([0, 0, -0.005])
                cylinder(h = 0.02, r = r, $fn = 64);
        }
}

// ── Duct collar (round, with retention barb) ──────────────────
module duct_collar() {
    z_start = flange_depth + transition_h;

    translate([0, 0, z_start]) {
        difference() {
            union() {
                // Outer collar wall
                cylinder(h = duct_insert, r = duct_r + wall, $fn = 64);

                // Retention barb ring (prevents duct from sliding off)
                translate([0, 0, duct_insert - barb_height * 2])
                    cylinder(h = barb_height, r1 = duct_r + wall,
                             r2 = duct_r + wall + barb_width, $fn = 64);
                translate([0, 0, duct_insert - barb_height])
                    cylinder(h = barb_height, r1 = duct_r + wall + barb_width,
                             r2 = duct_r + wall, $fn = 64);
            }

            // Inner bore (duct slides over this)
            translate([0, 0, -1])
                cylinder(h = duct_insert + 2, r = duct_r, $fn = 64);
        }
    }
}

// ── Mounting holes for optional bracket attachment ─────────────
module bracket_holes() {
    z = flange_depth + transition_h / 2;
    for (a = [0, 90, 180, 270])
        rotate([0, 0, a])
            translate([duct_r + wall + 3, 0, z])
                rotate([90, 0, 0])
                    cylinder(h = 1, d = 3.2, $fn = 16, center = true);
}

// ── Full assembly ─────────────────────────────────────────────
module fan_duct() {
    fan_flange();
    transition();
    duct_collar();
}

// ── Render ─────────────────────────────────────────────────────
fan_duct();
