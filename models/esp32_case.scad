// SporePrint ESP32 DevKit Case
// Fits ESP32-WROOM-32 or ESP32-S3 DevKit (USB-C)
//
// Mounting options:
//   - M3 screw holes (for permanent mounting via external tabs)
//   - Zip tie slots (for shelf/wire/rail mounting)
//   - Suction cup mount (for glass/smooth surfaces)
//
// Print settings: PLA, 0.2mm layer height, no supports needed
// Designed for: 28x52mm ESP32 DevKit PCBs
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters (customize for your board) ──────────────────────
board_w   = 28;   // mm — DevKit PCB width
board_l   = 52;   // mm — DevKit PCB length
board_h   = 10;   // mm — max component height above PCB
wall      = 2;    // mm — wall thickness
usb_w     = 12;   // mm — USB connector cutout width
usb_h     = 7;    // mm — USB connector cutout height
pcb_thick = 1.6;  // mm — PCB thickness
tolerance = 0.3;  // mm — fit tolerance
lid_lip   = 1.5;  // mm — snap-fit lip depth

// Zip tie parameters
zt_width   = 3;    // mm — zip tie slot width
zt_depth   = 1.5;  // mm — zip tie slot depth
zt_spacing = 15;   // mm — distance between parallel zip tie slots

// Suction cup parameters
sc_diameter = 30;  // mm — standard suction cup diameter
sc_depth    = 2;   // mm — concave ring depth

// ── Derived dimensions ─────────────────────────────────────────
outer_w = board_w + wall * 2 + tolerance * 2;
outer_l = board_l + wall * 2 + tolerance * 2;
outer_h = board_h + wall * 2 + pcb_thick;

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

// ── Base (bottom half) ─────────────────────────────────────────
module esp32_case_base() {
    difference() {
        union() {
            // Main shell
            cube([outer_w, outer_l, outer_h / 2 + lid_lip]);

            // Mounting tabs (external, two sides)
            for (y = [wall + 8, outer_l - wall - 8])
                translate([-6, y - 4, 0])
                    cube([6, 8, wall]);
            for (y = [wall + 8, outer_l - wall - 8])
                translate([outer_w, y - 4, 0])
                    cube([6, 8, wall]);

            // Suction cup mount on back (bottom face for flat surface mounting)
            translate([outer_w / 2, outer_l / 2, -sc_depth + 0.1])
                suction_cup_mount(diameter=sc_diameter, depth=sc_depth);
        }

        // Board cavity
        translate([wall + tolerance, wall + tolerance, wall])
            cube([board_w, board_l, outer_h]);

        // USB port cutout (front face)
        translate([wall + tolerance + (board_w - usb_w) / 2, -1, wall + pcb_thick])
            cube([usb_w, wall + tolerance + 2, usb_h]);

        // Bottom ventilation slots
        for (x = [wall + 4 : 6 : outer_w - wall - 4])
            translate([x, outer_l / 2 - 10, -1])
                cube([2, 20, wall + 2]);

        // Mounting tab screw holes
        for (y = [wall + 8, outer_l - wall - 8]) {
            translate([-3, y, -1])
                cylinder(h = wall + 2, d = 3, $fn = 16);
            translate([outer_w + 3, y, -1])
                cylinder(h = wall + 2, d = 3, $fn = 16);
        }

        // Zip tie slots on back (for strapping to shelf wire/rail)
        translate([outer_w / 2, outer_l, outer_h / 4])
            rotate([90, 0, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);
    }

    // PCB ledge rails (board sits on these)
    for (x = [wall + tolerance, wall + tolerance + board_w - 1])
        translate([x, wall + tolerance, wall])
            cube([1, board_l, pcb_thick]);
}

// ── Lid (top half) ─────────────────────────────────────────────
module esp32_case_lid() {
    lid_inner_w = board_w + tolerance * 2 - 0.4;
    lid_inner_l = board_l + tolerance * 2 - 0.4;

    difference() {
        union() {
            // Top plate
            cube([outer_w, outer_l, wall]);

            // Snap-fit lip
            translate([wall + tolerance + 0.2, wall + tolerance + 0.2, -lid_lip])
                difference() {
                    cube([lid_inner_w, lid_inner_l, lid_lip]);
                    translate([1.5, 1.5, -0.5])
                        cube([lid_inner_w - 3, lid_inner_l - 3, lid_lip + 1]);
                }
        }

        // Top ventilation holes (over the ESP32 module area)
        for (x = [wall + 4 : 5 : outer_w - wall - 4])
            for (y = [outer_l - 20 : 5 : outer_l - wall - 3])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = 2, $fn = 12);
    }
}

// ── Render ──────────────────────────────────────────────────────
esp32_case_base();

// Lid placed beside the base for printing
translate([outer_w + 10, 0, 0])
    esp32_case_lid();
