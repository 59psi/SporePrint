// SporePrint Camera Mount (ESP32-CAM / ESP32-S3 CAM)
// Adjustable-angle mount, wall or shelf mountable
//
// Mounting options:
//   - M3 screw holes (for permanent wall mounting via arm)
//   - Zip tie slots (for shelf/wire/rail mounting)
//   - Suction cup mount (for glass door/smooth surfaces)
//
// Print settings: PLA, 0.2mm layer height, supports needed for pivot cylinders
// Designed for: 27x40mm ESP32-CAM / ESP32-S3 CAM boards
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters ─────────────────────────────────────────────────
cam_w      = 27;   // mm — ESP32-CAM PCB width
cam_l      = 40;   // mm — ESP32-CAM PCB length
cam_h      = 10;   // mm — component height
wall       = 2;    // mm — wall thickness
pivot_d    = 5;    // mm — pivot bolt diameter (M5)
arm_length = 60;   // mm — mounting arm length
arm_width  = 20;   // mm — mounting arm width
cradle_h   = 15;   // mm — cradle side wall height
tolerance  = 0.3;  // mm — fit clearance
lens_size  = 10;   // mm — camera lens cutout (square)
screw_d    = 3;    // mm — M3 wall mount screws

// Zip tie parameters
zt_width   = 3;    // mm — zip tie slot width
zt_depth   = 1.5;  // mm — zip tie slot depth
zt_spacing = 15;   // mm — distance between parallel zip tie slots

// Suction cup parameters
sc_diameter = 30;  // mm — standard suction cup diameter
sc_depth    = 2;   // mm — concave ring depth

// ── Derived ────────────────────────────────────────────────────
cradle_outer_w = cam_w + wall * 2 + tolerance * 2;
cradle_outer_l = cam_l + wall * 2 + tolerance * 2;
pivot_boss_d   = pivot_d + wall * 2 + 2;

// ── Reusable mounting modules ──────────────────────────────────

module zip_tie_slot(width=3, depth=1.5, spacing=15) {
    // Two parallel slots for zip tie pass-through
    for (x = [-spacing/2, spacing/2])
        translate([x, 0, 0])
            cube([width, 20, depth], center=true);
}

module suction_cup_mount(diameter=30, depth=2) {
    // Concave ring for standard suction cup press-fit
    difference() {
        cylinder(h=depth, d=diameter+4, $fn=32);
        translate([0, 0, -0.1])
            cylinder(h=depth+0.2, d=diameter, $fn=32);
    }
}

// ── Camera cradle ──────────────────────────────────────────────
module cam_cradle() {
    difference() {
        union() {
            // Base plate
            cube([cradle_outer_w, cradle_outer_l, wall]);

            // Left wall
            cube([wall, cradle_outer_l, cradle_h]);

            // Right wall
            translate([cradle_outer_w - wall, 0, 0])
                cube([wall, cradle_outer_l, cradle_h]);

            // Back wall
            translate([0, cradle_outer_l - wall, 0])
                cube([cradle_outer_w, wall, cradle_h]);

            // Front lip (low, holds board in)
            cube([cradle_outer_w, wall, wall + 3]);

            // Pivot bosses (one each side, centered vertically)
            for (x = [0, cradle_outer_w - wall])
                translate([x + wall / 2, -3, cradle_h / 2])
                    rotate([-90, 0, 0])
                        cylinder(h = 6, d = pivot_boss_d, $fn = 24);
        }

        // Camera lens cutout (bottom center of base plate)
        translate([cradle_outer_w / 2 - lens_size / 2,
                   cradle_outer_l / 2 - lens_size / 2, -1])
            cube([lens_size, lens_size, wall + 2]);

        // Pivot through-holes
        for (x = [0, cradle_outer_w - wall])
            translate([x + wall / 2, -4, cradle_h / 2])
                rotate([-90, 0, 0])
                    cylinder(h = 8, d = pivot_d + tolerance, $fn = 24);

        // USB port cutout (front face, centered)
        translate([cradle_outer_w / 2 - 6, -1, wall])
            cube([12, wall + 2, 7]);
    }

    // PCB support ledges
    for (x = [wall + tolerance, cradle_outer_w - wall - tolerance - 1])
        translate([x, wall + tolerance, wall])
            cube([1, cam_l, 1.5]);
}

// ── Mounting arm ───────────────────────────────────────────────
module mount_arm() {
    difference() {
        union() {
            // Arm body
            translate([-arm_width / 2, 0, 0])
                cube([arm_width, arm_length, wall]);

            // Pivot end (circular boss)
            cylinder(h = wall, d = pivot_boss_d, $fn = 24);

            // Mount end (circular boss)
            translate([0, arm_length, 0])
                cylinder(h = wall, d = arm_width, $fn = 24);

            // Suction cup mount at the arm base (for sticking to glass door)
            translate([0, arm_length, wall])
                suction_cup_mount(diameter=sc_diameter, depth=sc_depth);
        }

        // Pivot hole (M5)
        translate([0, 0, -1])
            cylinder(h = wall + sc_depth + 4, d = pivot_d + tolerance, $fn = 24);

        // Wall mount holes (two at mount end)
        for (dx = [-5, 5])
            translate([dx, arm_length, -1])
                cylinder(h = wall + sc_depth + 4, d = screw_d, $fn = 16);

        // Zip tie slots at mount end (for shelf rail attachment)
        translate([0, arm_length - 5, wall / 2])
            zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);

        // Angle index marks (small notches every 15 degrees)
        for (a = [0 : 15 : 90])
            translate([pivot_boss_d / 2 * cos(a), pivot_boss_d / 2 * sin(a), -1])
                cylinder(h = wall + 2, d = 1, $fn = 8);
    }
}

// ── Friction washer (print 2) ──────────────────────────────────
module friction_washer() {
    difference() {
        cylinder(h = 1, d = pivot_boss_d - 1, $fn = 24);
        translate([0, 0, -0.5])
            cylinder(h = 2, d = pivot_d + tolerance + 0.5, $fn = 24);
    }
}

// ── Render ──────────────────────────────────────────────────────
cam_cradle();

// Arm placed beside cradle for printing
translate([cradle_outer_w + 15, arm_width / 2, 0])
    mount_arm();

// Friction washers (print 2)
translate([cradle_outer_w + 15 + arm_width + 10, 5, 0])
    friction_washer();
translate([cradle_outer_w + 15 + arm_width + 10, 15, 0])
    friction_washer();
