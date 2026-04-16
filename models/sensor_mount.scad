// SporePrint Climate Sensor Mount
// For SHT31-D + SCD41 + BH1750 breakout boards (dual I2C sensor enclosure)
//
// Mounting options:
//   - M3 screw holes (for permanent mounting)
//   - Zip tie slots (for shelf/wire/rail mounting)
//   - Suction cup mount (for glass/smooth surfaces)
//
// Print settings: PLA, 0.2mm layer height, no supports needed
// Designed for: 25x15mm breakout boards (SHT31-D, BH1750, SCD41)
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters (customize for your breakouts) ──────────────────
board_width  = 25;   // mm — breakout board width
board_length = 15;   // mm — breakout board length
board_height = 3;    // mm — PCB thickness
wall         = 2;    // mm — wall thickness
vent_diameter = 3;   // mm — ventilation hole diameter
screw_diameter = 3;  // mm — M3 mounting screw holes
cable_slot   = 5;    // mm — cable routing channel width
lid_tolerance = 0.3; // mm — snap-fit clearance
lid_lip      = 1.5;  // mm — snap-fit lip depth

// Zip tie parameters
zt_width   = 3;    // mm — zip tie slot width
zt_depth   = 1.5;  // mm — zip tie slot depth
zt_spacing = 15;   // mm — distance between parallel zip tie slots

// Suction cup parameters
sc_diameter = 30;  // mm — standard suction cup diameter
sc_depth    = 2;   // mm — concave ring depth

// ── Derived dimensions ─────────────────────────────────────────
inner_w = board_width;
inner_l = board_length * 2 + wall;  // two boards + divider
outer_w = inner_w + wall * 2;
outer_l = inner_l + wall * 2;
cavity_h = board_height + 8;        // room for components + wires
outer_h  = cavity_h + wall;

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

// ── Main enclosure ─────────────────────────────────────────────
module sensor_mount() {
    difference() {
        // Outer shell
        cube([outer_w, outer_l, outer_h]);

        // Board cavity 1 (SHT31-D)
        translate([wall, wall, wall])
            cube([inner_w, board_length, cavity_h + 1]);

        // Board cavity 2 (BH1750)
        translate([wall, wall + board_length + wall, wall])
            cube([inner_w, board_length, cavity_h + 1]);

        // Ventilation grid (bottom face — airflow over sensors)
        for (x = [wall + 3 : 5 : outer_w - wall - 3])
            for (y = [wall + 3 : 5 : outer_l - wall - 3])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_diameter, $fn = 16);

        // Cable routing slot (front face)
        translate([outer_w / 2 - cable_slot / 2, -1, wall])
            cube([cable_slot, wall + 2, board_height + 4]);

        // Mounting screw holes (four corners)
        for (pos = [[wall / 2, wall / 2],
                     [outer_w - wall / 2, wall / 2],
                     [wall / 2, outer_l - wall / 2],
                     [outer_w - wall / 2, outer_l - wall / 2]])
            translate([pos[0], pos[1], -1])
                cylinder(h = outer_h + 2, d = screw_diameter, $fn = 16);

        // Zip tie slots — left side (for strapping to shelf wire)
        translate([0, outer_l / 2, outer_h / 2])
            rotate([0, 90, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);

        // Zip tie slots — right side
        translate([outer_w, outer_l / 2, outer_h / 2])
            rotate([0, 90, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);

        // Snap-fit lid groove (inner lip around top edge)
        translate([wall - lid_tolerance, wall - lid_tolerance, outer_h - lid_lip])
            cube([inner_w + lid_tolerance * 2, inner_l + lid_tolerance * 2, lid_lip + 1]);
    }

    // PCB support ledges (small rails inside each cavity)
    for (y_offset = [wall, wall + board_length + wall]) {
        // Left rail
        translate([wall, y_offset, wall])
            cube([1, board_length, 1.5]);
        // Right rail
        translate([wall + inner_w - 1, y_offset, wall])
            cube([1, board_length, 1.5]);
    }

    // Suction cup mount on back face (for sticking to glass/smooth surfaces)
    translate([outer_w / 2, outer_l + sc_depth - 0.1, outer_h / 2])
        rotate([90, 0, 0])
            suction_cup_mount(diameter=sc_diameter, depth=sc_depth);
}

// ── Snap-fit lid ───────────────────────────────────────────────
module sensor_lid() {
    lip_w = inner_w + lid_tolerance * 2 - 0.2;
    lip_l = inner_l + lid_tolerance * 2 - 0.2;

    // Top plate
    cube([outer_w, outer_l, wall]);

    // Snap lip (drops into groove)
    translate([wall - lid_tolerance + 0.1, wall - lid_tolerance + 0.1, -lid_lip])
        difference() {
            cube([lip_w, lip_l, lid_lip]);
            // Hollow out to save material
            translate([wall, wall, -0.5])
                cube([lip_w - wall * 2, lip_l - wall * 2, lid_lip + 1]);
        }

    // Ventilation holes in lid
    difference() {
        // (already built above)
        translate([0, 0, 0]) cube([0, 0, 0]); // no-op

        for (x = [wall + 3 : 5 : outer_w - wall - 3])
            for (y = [wall + 3 : 5 : outer_l - wall - 3])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_diameter, $fn = 16);
    }
}

// ── Render ──────────────────────────────────────────────────────
sensor_mount();

// Lid placed beside the base for printing
translate([outer_w + 10, 0, 0])
    sensor_lid();
