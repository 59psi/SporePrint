// SporePrint Climate Sensor Mount
// Three-bay enclosure for the canonical Adafruit breakout trio on a shared
// STEMMA QT / I2C daisy chain:
//   bay 1 — SHT31-D  (25.4 x 17.8 mm, Adafruit 2857)
//   bay 2 — SCD41    (25.4 x 22.9 mm, Adafruit 5190)
//   bay 3 — BH1750   (19.0 x 12.7 mm, Adafruit 4681)
//
// 2026-06 redesign: the previous two-bay version was sized for generic
// 25x15 mm breakouts — the canonical Adafruit SHT31-D and SCD41 did not
// fit, and the lid's ventilation holes were subtracted from a zero-size
// cube (a no-op) so printed lids were unvented. Both fixed: per-bay slot
// sizing below, and lid vents are a real difference() cut. Bottom + lid
// grids give chimney airflow over the sensors — critical for accurate
// CO2 readings (don't tape over them).
//
// Mounting options:
//   - M3 screw holes (for permanent mounting)
//   - Zip tie slots (for shelf/wire/rail mounting)
//   - Suction cup mount (for glass/smooth surfaces)
//
// Print settings: PLA, 0.2mm layer height, no supports needed
//
// Customization: adjust the slot list + parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters ─────────────────────────────────────────────────
// Bay widths (X) per board, with 0.6 mm fit clearance already added.
// [width, label] — board length (Y) is uniform (deepest board + clearance).
slots = [
    [26,   "SHT31"],   // SHT31-D 25.4 wide
    [26,   "SCD41"],   // SCD41  25.4 wide
    [19.5, "BH1750"],  // BH1750 19.0 wide
];
bay_d        = 23.5;  // mm — uniform bay depth (SCD41 22.9 + clearance)
rail_h       = 1.5;   // mm — PCB support rail height
board_clear  = 9;     // mm — headroom above rails for STEMMA QT cables
wall         = 2;     // mm — wall + rib thickness
notch_w      = 8;     // mm — wire pass-through notch width in ribs
notch_h      = 6;     // mm — wire notch height above rails
vent_diameter = 3;    // mm — ventilation hole diameter
screw_diameter = 3;   // mm — M3 mounting screw holes
cable_slot   = 6;     // mm — front cable exit slot width
lid_tolerance = 0.3;  // mm — snap-fit clearance
lid_lip      = 1.5;   // mm — snap-fit lip depth

// Zip tie parameters
zt_width   = 3;    // mm — zip tie slot width
zt_depth   = 1.5;  // mm — zip tie slot depth
zt_spacing = 15;   // mm — distance between parallel zip tie slots

// Suction cup parameters
sc_diameter = 30;  // mm — standard suction cup diameter
sc_depth    = 2;   // mm — concave ring depth

// ── Derived dimensions ─────────────────────────────────────────
function bay_x(i) = wall + (i == 0 ? 0 : slots[0][0] + wall +
                            (i == 1 ? 0 : slots[1][0] + wall));
inner_w = slots[0][0] + slots[1][0] + slots[2][0] + wall * 2; // ribs included
outer_w = inner_w + wall * 2;
outer_l = bay_d + wall * 2;
outer_h = wall + rail_h + board_clear;

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

        // Three sensor bays
        for (i = [0 : 2])
            translate([bay_x(i), wall, wall])
                cube([slots[i][0], bay_d, outer_h]);

        // Wire pass-through notches in the two ribs (STEMMA QT daisy chain)
        for (i = [1 : 2])
            translate([bay_x(i) - wall - 0.5, outer_l / 2 - notch_w / 2,
                       wall + rail_h])
                cube([wall + 1, notch_w, notch_h]);

        // Ventilation grid (bottom face — airflow over sensors)
        for (x = [wall + 3 : 5 : outer_w - wall - 3])
            for (y = [wall + 3 : 5 : outer_l - wall - 3])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_diameter, $fn = 16);

        // Cable routing slot (front face, center bay)
        translate([outer_w / 2 - cable_slot / 2, -1, wall + rail_h])
            cube([cable_slot, wall + 2, notch_h]);

        // Mounting screw holes (four corners, through the wall posts)
        for (pos = [[wall / 2, wall / 2],
                     [outer_w - wall / 2, wall / 2],
                     [wall / 2, outer_l - wall / 2],
                     [outer_w - wall / 2, outer_l - wall / 2]])
            translate([pos[0], pos[1], -1])
                cylinder(h = outer_h + 2, d = screw_diameter, $fn = 16);

        // Zip tie slots — left + right sides
        translate([0, outer_l / 2, outer_h / 2])
            rotate([0, 90, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);
        translate([outer_w, outer_l / 2, outer_h / 2])
            rotate([0, 90, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);

        // Snap-fit lid groove (inner lip around top edge)
        translate([wall - lid_tolerance, wall - lid_tolerance, outer_h - lid_lip])
            cube([inner_w + lid_tolerance * 2, bay_d + lid_tolerance * 2, lid_lip + 1]);

        // Bay labels (engraved, front face)
        for (i = [0 : 2])
            translate([bay_x(i) + slots[i][0] / 2, 0.4, outer_h / 2 - 1.5])
                rotate([90, 0, 0])
                    linear_extrude(0.5)
                        text(slots[i][1], size = 3, halign = "center",
                             font = "Liberation Sans");
    }

    // PCB support rails along the front + back of each bay
    for (i = [0 : 2])
        for (y = [wall, outer_l - wall - 1])
            translate([bay_x(i), y, wall])
                cube([slots[i][0], 1, rail_h]);

    // Suction cup mount on back face (for sticking to glass/smooth surfaces)
    translate([outer_w / 2, outer_l + sc_depth - 0.1, outer_h / 2])
        rotate([90, 0, 0])
            suction_cup_mount(diameter=sc_diameter, depth=sc_depth);
}

// ── Snap-fit lid ───────────────────────────────────────────────
module sensor_lid() {
    lip_w = inner_w + lid_tolerance * 2 - 0.2;
    lip_l = bay_d + lid_tolerance * 2 - 0.2;

    difference() {
        union() {
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
        }

        // Ventilation holes — a real cut through the top plate (chimney
        // airflow with the bottom grid). Vent field starts at y=9 to leave
        // a clear strip for the wordmark.
        for (x = [wall + 3 : 5 : outer_w - wall - 3])
            for (y = [9 : 5 : outer_l - wall - 3])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_diameter, $fn = 16);

        // Wordmark (engraved, front strip)
        translate([outer_w / 2, 2.5, wall - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 3.5, halign = "center",
                     font = "Liberation Sans");
    }
}

// ── Render ──────────────────────────────────────────────────────
sensor_mount();

// Lid placed beside the base for printing
translate([outer_w + 10, 0, 0])
    sensor_lid();
