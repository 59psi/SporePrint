// SporePrint Climate Sensor Mount
// Three-bay ventilated enclosure for the climate node's I2C breakout trio
// on a shared STEMMA QT daisy chain. Each bay is sized from the vendor's
// published "Product Dimensions", long axis along X so the QT connectors —
// which sit on each board's SHORT edges — face the wire notches in the ribs:
//
//   bay 1 — SHT31-D  18.0 x 12.7 x 2.6 mm  (Adafruit 2857)
//   bay 2 — SCD41    25.5 x 22.8 x 7.7 mm  (Adafruit 5190)  [default]
//        or SCD30    51.0 x 25.4 x 8.8 mm  (Adafruit 4867)  [scd30 = true]
//   bay 3 — BH1750   25.3 x 17.7 x 4.5 mm  (Adafruit 4681)
//
// 2026-07 audit — the 2026-06 "three-bay fix" was still wrong:
//   * SHT31-D and BH1750 sizes were transposed. Bay 1 was 26 mm wide for a
//     board that is 18.0 mm long; bay 3 was 19.5 mm wide for a board that is
//     25.3 mm long — so the BH1750 did not fit AT ALL. Same class of bug the
//     three-bay redesign was supposed to have retired.
//   * Every bay was cut to one uniform 23.5 mm depth. Only the SCD41 is that
//     deep, so the other two boards had no back wall to seat against and
//     could not span both support rails.
//   * The four corner "M3 holes" were centred 1 mm in from the edge with a
//     3 mm bit — they opened straight out through the 2 mm wall. Scallops,
//     not holes.
//   * The side zip-tie slots were pitched 15 mm apart on a 12.5 mm tall
//     wall, so both slots missed the body entirely. They cut nothing.
// All four are fixed below: per-bay width AND depth taken from the vendor
// pages, and the M3 + zip-tie options moved onto real end ears.
//
// The chimney venting (floor grid under each board, matching grid in the
// lid) is unchanged — it is what keeps the CO2 reading honest. Do not tape
// over it, and do not sit this straight on a solid surface: use
// sensor_bracket.scad, whose platform is slotted to breathe underneath.
//
// SCD30 builds: set scd30 = true. The BOM promotes the SCD30 (Adafruit
// 4867) as the in-stock SCD41 alternate — it autodetects on the same bus,
// but at 51 mm it is twice as long and will not go near the SCD41 bay. The
// flag widens bay 2; every derived dimension (shell, lid, ears, vents,
// labels) follows from the bay table.
//
// Mounting options:
//   - M3 screw holes  (one per end ear — mates with sensor_bracket.scad)
//   - Zip tie slots   (two per end ear — shelf wire / rail)
//   - Suction cup     (NOT on this part: the enclosure is 13.5 mm tall, too
//                      short to carry a 30 mm cup. sensor_bracket.scad has
//                      one on its platform — that is the suction path.)
//
// Print settings: PLA, 0.2mm layer height, no supports needed
//
// Customization: adjust the bay table + parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters ─────────────────────────────────────────────────
scd30 = false;   // true → wide bay 2 for the SCD30 (Adafruit 4867)

fit           = 0.8;  // mm — total X/Y clearance added to each board
rail_h        = 1.5;  // mm — PCB rail height (lifts the board off the vents)
board_clear   = 10;   // mm — headroom above rails (tallest board 8.8 + QT cable)
wall          = 2;    // mm — wall + rib thickness
notch_w       = 8;    // mm — STEMMA QT wire pass-through width in the ribs
notch_h       = 6;    // mm — wire notch height above the rails
vent_d        = 3;    // mm — ventilation hole diameter
vent_pitch    = 5;    // mm — ventilation grid pitch
vent_inset    = 3;    // mm — keep vents this far inside each bay
cable_slot    = 6;    // mm — front cable exit slot width
lid_tolerance = 0.3;  // mm — snap-fit clearance
lid_lip       = 1.5;  // mm — snap-fit lip depth

// End ears — these carry the M3 screw + zip tie mounting options
ear_len    = 12;   // mm — how far each ear sticks out from the shell
ear_t      = 3;    // mm — ear thickness
ear_hole_d = 3.2;  // mm — M3 clearance hole
zt_slot_w  = 2.4;  // mm — zip tie slot, across the tie's thickness (X)
zt_slot_l  = 4.5;  // mm — zip tie slot, across the tie's width (Y)
zt_slot_dy = 9;    // mm — zip tie slot offset from the ear centre

// ── Bay table + footprint helpers ──────────────────────────────
// Pure functions of the variant flag, so sensor_bracket.scad can
// `use <sensor_mount.scad>` and derive the identical footprint. That is
// deliberate: the bracket's platform was hard-coded at 40 x 50 mm while this
// enclosure was ~79 mm wide, and nothing caught it.
//
// [board_w (X, long axis), board_d (Y), label]
function sm_slots(wide = false) = [
    [18.0, 12.7, "SHT31"],
    wide ? [51.0, 25.4, "SCD30"] : [25.5, 22.8, "SCD41"],
    [25.3, 17.7, "BH1750"],
];

function _sum(v, i = 0) = i >= len(v) ? 0 : v[i] + _sum(v, i + 1);

function sm_outer_w(wide = false) =
    _sum([for (s = sm_slots(wide)) s[0] + fit])
    + wall * (len(sm_slots(wide)) + 1);

function sm_outer_l(wide = false) =
    max([for (s = sm_slots(wide)) s[1]]) + fit + wall * 2;

function sm_ear_len() = ear_len;   // the bracket needs this for its screw pitch

// ── Derived dimensions ─────────────────────────────────────────
slots = sm_slots(scd30);
n     = len(slots);

function bay_w(i) = slots[i][0] + fit;
function bay_d(i) = slots[i][1] + fit;
function bay_x(i) = i == 0 ? wall : bay_x(i - 1) + bay_w(i - 1) + wall;

outer_w = sm_outer_w(scd30);
outer_l = sm_outer_l(scd30);
outer_h = wall + rail_h + board_clear;

// ── Mounting ear cuts (M3 hole + two zip tie slots) ────────────
module ear_cuts(x_centre) {
    translate([x_centre, outer_l / 2, -1])
        cylinder(h = ear_t + 2, d = ear_hole_d, $fn = 24);

    for (dy = [-zt_slot_dy, zt_slot_dy])
        translate([x_centre, outer_l / 2 + dy, ear_t / 2])
            cube([zt_slot_w, zt_slot_l, ear_t + 2], center = true);
}

// ── Main enclosure ─────────────────────────────────────────────
module sensor_mount() {
    difference() {
        union() {
            // Outer shell
            cube([outer_w, outer_l, outer_h]);

            // End ears (flush with the floor so the part still sits flat)
            translate([-ear_len, 0, 0]) cube([ear_len, outer_l, ear_t]);
            translate([outer_w, 0, 0])  cube([ear_len, outer_l, ear_t]);
        }

        // Sensor bays — each sized to its own board, front-aligned so the
        // labels, the cable slot and the rib notches all line up.
        for (i = [0 : n - 1])
            translate([bay_x(i), wall, wall])
                cube([bay_w(i), bay_d(i), outer_h]);

        // Wire pass-through notches in the ribs (STEMMA QT daisy chain).
        // Placed inside the shallower of the two bays each rib separates.
        for (i = [1 : n - 1])
            translate([bay_x(i) - wall - 0.5,
                       wall + min(bay_d(i - 1), bay_d(i)) / 2 - notch_w / 2,
                       wall + rail_h])
                cube([wall + 1, notch_w, notch_h]);

        // Ventilation grid — floor of each bay only. Running it across the
        // whole footprint would drill blind pockets into the solid material
        // behind the shallow bays; per-bay keeps every hole a real
        // through-hole, and every through-hole under a board.
        for (i = [0 : n - 1])
            for (x = [bay_x(i) + vent_inset : vent_pitch :
                      bay_x(i) + bay_w(i) - vent_inset])
                for (y = [wall + vent_inset : vent_pitch :
                          wall + bay_d(i) - vent_inset])
                    translate([x, y, -1])
                        cylinder(h = wall + 2, d = vent_d, $fn = 16);

        // Cable routing slot (front face, centre bay)
        translate([outer_w / 2 - cable_slot / 2, -1, wall + rail_h])
            cube([cable_slot, wall + 2, notch_h]);

        // Snap-fit lid groove (shaves the top of the ribs + inner walls)
        translate([wall - lid_tolerance, wall - lid_tolerance,
                   outer_h - lid_lip])
            cube([outer_w - wall * 2 + lid_tolerance * 2,
                  outer_l - wall * 2 + lid_tolerance * 2,
                  lid_lip + 1]);

        // Mounting ear cuts
        ear_cuts(-ear_len / 2);
        ear_cuts(outer_w + ear_len / 2);

        // Bay labels (engraved, front face)
        for (i = [0 : n - 1])
            translate([bay_x(i) + bay_w(i) / 2, 0.4, outer_h / 2 - 1.5])
                rotate([90, 0, 0])
                    linear_extrude(0.5)
                        text(slots[i][2], size = 3, halign = "center",
                             font = "Liberation Sans");
    }

    // PCB support rails along the front + back edge of each bay. The board
    // rests on these, clear of the floor vents.
    for (i = [0 : n - 1])
        for (y = [wall, wall + bay_d(i) - 1])
            translate([bay_x(i), y, wall])
                cube([bay_w(i), 1, rail_h]);
}

// ── Snap-fit lid ───────────────────────────────────────────────
module sensor_lid() {
    lip_w = outer_w - wall * 2 + lid_tolerance * 2 - 0.2;
    lip_l = outer_l - wall * 2 + lid_tolerance * 2 - 0.2;

    difference() {
        union() {
            // Top plate
            cube([outer_w, outer_l, wall]);

            // Snap lip (drops into the groove)
            translate([wall - lid_tolerance + 0.1,
                       wall - lid_tolerance + 0.1, -lid_lip])
                difference() {
                    cube([lip_w, lip_l, lid_lip]);
                    translate([wall, wall, -0.5])
                        cube([lip_w - wall * 2, lip_l - wall * 2,
                              lid_lip + 1]);
                }
        }

        // Ventilation holes — a real cut through the top plate, forming the
        // chimney's outlet. Field starts past the wordmark strip.
        for (x = [wall + vent_inset : vent_pitch : outer_w - wall - vent_inset])
            for (y = [9 : vent_pitch : outer_l - wall - vent_inset])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_d, $fn = 16);

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
translate([0, outer_l + 10, 0])
    sensor_lid();
