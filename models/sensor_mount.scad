// SporePrint Climate Sensor Mount
// For SHT31-D + BH1750 breakout boards (dual I2C sensor enclosure)
// Print: PLA, 0.2mm layer height, no supports needed
// Mount to wall or shelf with M3 screws
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

// ── Derived dimensions ─────────────────────────────────────────
inner_w = board_width;
inner_l = board_length * 2 + wall;  // two boards + divider
outer_w = inner_w + wall * 2;
outer_l = inner_l + wall * 2;
cavity_h = board_height + 8;        // room for components + wires
outer_h  = cavity_h + wall;

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
