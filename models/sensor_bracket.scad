// SporePrint Universal Sensor Mounting Bracket
// Adjustable bracket that clips to a wire shelf, with a platform
// for the sensor mount enclosure
//
// Mounting options:
//   - Wire shelf clips (snap onto standard wire shelving)
//   - M3 screw holes (for permanent sensor enclosure attachment)
//   - Suction cup mount (for glass/smooth surface attachment)
//
// Print settings: PLA or PETG, 0.2mm layer height, no supports needed
// Designed for: Standard wire shelving (adjustable wire diameter)
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters ────────────────────────────────────────────────
wire_d          = 5;     // mm — wire shelf wire diameter (measure yours)
wire_spacing    = 25;    // mm — center-to-center wire spacing
platform_w      = 40;    // mm — sensor platform width
platform_l      = 50;    // mm — sensor platform length
platform_thick  = 3;     // mm — platform thickness
wall            = 3;     // mm — clip wall thickness
clip_depth      = 15;    // mm — how far clip extends below shelf wire
clip_gap        = 0.5;   // mm — extra clearance for clip fit
arm_length      = 50;    // mm — horizontal arm from shelf to platform
arm_width       = 15;    // mm — arm cross-section width
arm_thick       = 4;     // mm — arm cross-section thickness
screw_d         = 3;     // mm — M3 mounting holes (for sensor enclosure)
tilt_angle      = 0;     // degrees — platform tilt (0 = flat, adjust for airflow)
num_clips       = 2;     // number of wire clips (straddle 2 wires)
cable_slot_w    = 8;     // mm — cable routing slot width
gusset_size     = 10;    // mm — reinforcement gusset size

// Suction cup parameters
sc_diameter = 30;  // mm — standard suction cup diameter
sc_depth    = 2;   // mm — concave ring depth

// ── Derived ───────────────────────────────────────────────────
clip_inner_d = wire_d + clip_gap * 2;
clip_outer_d = clip_inner_d + wall * 2;
total_clip_w = (num_clips - 1) * wire_spacing + clip_outer_d;

// ── Reusable mounting modules ──────────────────────────────────

module suction_cup_mount(diameter=30, depth=2) {
    // Concave ring for standard suction cup press-fit
    difference() {
        cylinder(h=depth, d=diameter+4, $fn=32);
        translate([0, 0, -0.1])
            cylinder(h=depth+0.2, d=diameter, $fn=32);
    }
}

// ── Wire clip (C-shaped, snaps onto round wire) ───────────────
module wire_clip() {
    difference() {
        union() {
            // Main C-clip body
            difference() {
                cylinder(h = arm_width, d = clip_outer_d, $fn = 32);
                // Inner bore (wire sits here)
                translate([0, 0, -1])
                    cylinder(h = arm_width + 2, d = clip_inner_d, $fn = 32);
                // Opening gap (so it can snap on)
                translate([-clip_outer_d / 2, 0, -1])
                    cube([clip_outer_d, clip_outer_d, arm_width + 2]);
            }

            // Snap-in retention bumps (narrow the opening slightly)
            for (side = [-1, 1])
                translate([side * clip_inner_d / 2, 0, 0])
                    cylinder(h = arm_width, d = wall * 0.8, $fn = 12);

            // Vertical drop (extends below wire for stability)
            translate([-wall / 2, -clip_outer_d / 2, 0])
                cube([wall, clip_depth, arm_width]);
        }
    }
}

// ── Clip bridge (connects multiple clips) ─────────────────────
module clip_bridge() {
    for (i = [0 : num_clips - 1]) {
        translate([i * wire_spacing, 0, 0])
            wire_clip();
    }

    // Bridge bar connecting clips
    if (num_clips > 1) {
        translate([-wall / 2, -clip_outer_d / 2 - arm_thick, 0])
            cube([(num_clips - 1) * wire_spacing + wall,
                  arm_thick, arm_width]);
    }
}

// ── Horizontal arm ────────────────────────────────────────────
module arm() {
    // Main arm body
    translate([total_clip_w / 2 - arm_width / 2,
               -clip_outer_d / 2 - arm_thick, 0])
        cube([arm_width, -arm_length + arm_thick, arm_thick]);

    // Correction: arm extends in -Y direction from clip
    translate([total_clip_w / 2 - arm_width / 2,
               -clip_outer_d / 2 - arm_length, 0])
        cube([arm_width, arm_length, arm_thick]);

    // Reinforcement gusset (vertical triangle at clip junction)
    translate([total_clip_w / 2 - arm_width / 2,
               -clip_outer_d / 2 - arm_thick, 0])
        hull() {
            cube([arm_width, 0.1, arm_width]);
            cube([arm_width, gusset_size, 0.1]);
        }
}

// ── Sensor platform ───────────────────────────────────────────
module sensor_platform() {
    platform_x = total_clip_w / 2 - platform_w / 2;
    platform_y = -clip_outer_d / 2 - arm_length - platform_l + 5;

    translate([platform_x, platform_y, 0]) {
        rotate([tilt_angle, 0, 0]) {
            difference() {
                union() {
                    // Platform base
                    cube([platform_w, platform_l, platform_thick]);

                    // Raised edge rails (sensor retention)
                    cube([platform_w, 2, platform_thick + 3]);
                    translate([0, platform_l - 2, 0])
                        cube([platform_w, 2, platform_thick + 3]);
                    cube([2, platform_l, platform_thick + 3]);
                    translate([platform_w - 2, 0, 0])
                        cube([2, platform_l, platform_thick + 3]);

                    // Suction cup mount on bottom (alternative to shelf clip)
                    translate([platform_w / 2, platform_l / 2, -sc_depth + 0.1])
                        suction_cup_mount(diameter=sc_diameter, depth=sc_depth);
                }

                // Mounting screw holes (four positions)
                for (pos = [[8, 8],
                             [platform_w - 8, 8],
                             [8, platform_l - 8],
                             [platform_w - 8, platform_l - 8]])
                    translate([pos[0], pos[1], -1])
                        cylinder(h = platform_thick + 2, d = screw_d, $fn = 16);

                // Cable routing slot (front edge)
                translate([platform_w / 2 - cable_slot_w / 2, -1, -1])
                    cube([cable_slot_w, 4, platform_thick + 2]);

                // Ventilation holes (center area)
                for (x = [12 : 8 : platform_w - 12])
                    for (y = [12 : 8 : platform_l - 12])
                        translate([x, y, -1])
                            cylinder(h = platform_thick + 2, d = 2.5, $fn = 12);
            }
        }
    }
}

// ── Full assembly ─────────────────────────────────────────────
module sensor_bracket() {
    // Wire clips (oriented along Z for printing)
    rotate([90, 0, 0])
        translate([0, 0, -arm_width / 2])
            clip_bridge();

    // Horizontal arm
    arm();

    // Sensor platform
    sensor_platform();
}

// ── Render (print-friendly orientation) ───────────────────────
// Lay flat: arm horizontal, clips pointing up
sensor_bracket();
