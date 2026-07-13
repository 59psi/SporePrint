// SporePrint Load-Cell Scale (HX711 + TAL220 5 kg)
// Two-part print that turns the Tier 3 "HX711 + 5kg Load Cell" BOM line into
// a working harvest scale under the grow block. It is the classic bar-load-
// cell sandwich: the cell's FIXED end bolts down to the base pedestal, its
// FREE end lifts the platform, and the S-bend between them is what the HX711
// reads. weight_g rides in relay-node telemetry once tared + calibrated.
//
// Load cell — TAL220 / TAL220B straight-bar, 5 kg (SparkFun SEN-14729 form
// factor; the part Adafruit/SparkFun/Amazon ship as "5kg load cell"):
//   * body 80.0 x 12.7 x 12.7 mm, 4-wire, ~200-250 mm tail
//   * THREADED mounting holes (bolts thread INTO the bar), 15 mm pitch:
//       - FIXED end: 2 x M5, holes 5 mm and 20 mm from that end
//       - LOAD  end: 2 x M4, holes 5 mm and 20 mm from that end (force arrow)
//   * verified against the HTC Sensor TAL220 datasheet dimension drawing.
// The bolt holes here are CLEARANCE holes for the bolt shank (M5->5.5,
// M4->4.5); the threads live in the aluminium bar. Bolts: 4x M5x12 (base) +
// 2x M4x12 (platform). No heat-set inserts, no nuts.
//
// HX711 amplifier — generic green breakout, 38 x 22 mm (SparkFun / Soldered
// 333005 outline). Drops into the open bay on the base; two flex tabs retain
// it. A wire channel carries E+/E-/A+/A- to the cell and DOUT/SCK/VCC/GND
// out to the relay node (GPIO 32 = DOUT, GPIO 33 = SCK per the BOM wiring).
//
// Why two parts, printed flat, no supports:
//   * BASE prints on its underside; the fixed-end bolt heads live in the
//     6 mm clearance under the plate that the corner feet open up.
//   * PLATFORM prints pedestal-up; flip it over in use so the pedestal
//     reaches down onto the cell's free end. M4 bolt heads recess into the
//     open-top counterbores.
//   * The riser under the fixed end holds the whole cell clear of the base
//     so the free end can deflect DOWN under load (and bottoms out on the
//     base as mechanical overload protection before the cell is damaged).
//
// Print settings: PLA, 0.2mm layer height, no supports, 3+ perimeters (the
//   pedestals carry the full weighed load — don't print them sparse).
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Load-cell parameters (TAL220 5 kg) ─────────────────────────
lc_len       = 80;    // mm — bar length
lc_w         = 12.7;  // mm — bar width
lc_h         = 12.7;  // mm — bar height
lc_hole_end  = 5;     // mm — first hole, from each end
lc_hole_pitch = 15;   // mm — pitch to the second hole (so 5 mm and 20 mm)
m5_clear     = 5.5;   // mm — clearance hole for M5 bolt shank (fixed end)
m4_clear     = 4.5;   // mm — clearance hole for M4 bolt shank (load end)
m5_head_d    = 9.5;   // mm — M5 socket-head counterbore
m4_head_d    = 8.0;   // mm — M4 socket-head counterbore

// ── Build parameters ───────────────────────────────────────────
wall         = 2.5;   // mm — general wall thickness
base_th      = 4;     // mm — base plate thickness
foot_h       = 6;     // mm — corner-foot height = bolt-head clearance under base
foot_w       = 10;    // mm — corner-foot footprint
riser_h      = 9;     // mm — fixed-end riser height = free-end deflection gap
riser_len    = 26;    // mm — riser length along the bar (covers both M5 holes)
plat_th      = 3;     // mm — platform plate thickness
plat_ped_h   = 6;     // mm — platform pedestal height (spans plate->free-end top)
plat_margin  = 8;     // mm — platform overhang past the base footprint each side
side_margin  = 6;     // mm — base margin beside the cell
end_margin   = 8;     // mm — base margin past each end of the cell
tol          = 0.4;   // mm — general fit clearance

// ── HX711 bay parameters ───────────────────────────────────────
hx_w         = 22;    // mm — HX711 board width  (+ fit below)
hx_l         = 38;    // mm — HX711 board length (+ fit below)
hx_fit       = 0.8;   // mm — board fit clearance
hx_wall      = 2;     // mm — bay wall thickness
hx_floor     = 2;     // mm — bay floor thickness
hx_stand     = 2;     // mm — standoff lifting the board off the bay floor
wire_ch      = 5;     // mm — wire channel width

// ── Derived ────────────────────────────────────────────────────
// Cell runs along Y. Fixed (M5) end at low Y, free (M4/load) end at high Y.
bay_outer_w = hx_w + hx_fit + hx_wall * 2;
bay_outer_l = hx_l + hx_fit + hx_wall * 2;

base_w = lc_w + side_margin * 2 + bay_outer_w + wall;   // cell + gap + HX bay
base_l = lc_len + end_margin * 2;
cell_x = side_margin;                 // cell left edge X on the base
cell_cx = cell_x + lc_w / 2;          // cell centre X
cell_y0 = end_margin;                 // fixed end Y (cell starts here)
bay_x  = cell_x + lc_w + side_margin; // HX bay left edge X

// Hole Y positions (from the cell's fixed end at cell_y0)
function m5_ys() = [cell_y0 + lc_hole_end,
                    cell_y0 + lc_hole_end + lc_hole_pitch];
function m4_ys() = [cell_y0 + lc_len - lc_hole_end - lc_hole_pitch,
                    cell_y0 + lc_len - lc_hole_end];

// Platform footprint (covers the load end, floats over the base)
plat_w = base_w + plat_margin * 2;
plat_l = base_l * 0.62;               // covers the free half of the cell

// ── BASE ───────────────────────────────────────────────────────
module base() {
    difference() {
        union() {
            // Base plate (top face at z = foot_h + base_th)
            translate([0, 0, foot_h])
                cube([base_w, base_l, base_th]);

            // Corner feet (open the head-clearance gap under the plate)
            for (x = [0, base_w - foot_w])
                for (y = [0, base_l - foot_w])
                    translate([x, y, 0])
                        cube([foot_w, foot_w, foot_h]);

            // Fixed-end riser (cell's M5 end bolts down onto this)
            translate([cell_x - tol, cell_y0 - tol, foot_h + base_th])
                cube([lc_w + tol * 2, riser_len, riser_h]);

            // HX711 bay walls + floor
            translate([bay_x, cell_y0, foot_h + base_th])
                difference() {
                    cube([bay_outer_w, bay_outer_l, hx_floor + hx_stand + 6]);
                    // board pocket (open top)
                    translate([hx_wall, hx_wall, hx_floor])
                        cube([hx_w + hx_fit, hx_l + hx_fit, 20]);
                    // lighten the floor under the board (leave standoff ring)
                    translate([hx_wall + 4, hx_wall + 4, -1])
                        cube([hx_w + hx_fit - 8, hx_l + hx_fit - 8,
                              hx_floor + 1]);
                }
        }

        // M5 clearance holes + head counterbores (bolt from BELOW, up into
        // the cell). Counterbore opens on the base underside (z = foot_h).
        for (y = m5_ys()) {
            translate([cell_cx, y, -1])
                cylinder(h = foot_h + base_th + riser_h + 2, d = m5_clear,
                         $fn = 24);
            translate([cell_cx, y, foot_h - 0.01])
                cylinder(h = base_th, d = m5_head_d, $fn = 24);
        }

        // Wire channel from the HX bay across to the cell region (top of plate)
        translate([cell_x + lc_w, cell_y0 + 4, foot_h + base_th - wire_ch / 2])
            cube([side_margin * 2, wire_ch, wire_ch]);
    }

    // HX711 retention tabs (two flexy nubs over the board edges)
    for (y = [cell_y0 + bay_outer_l * 0.3, cell_y0 + bay_outer_l * 0.7])
        translate([bay_x + hx_wall - 0.5, y, foot_h + base_th + hx_floor + hx_stand + 3])
            cube([1.5, 4, 1.5]);
}

// ── PLATFORM (printed pedestal-up; flip over in use) ───────────
// Flat plate + two mounting pedestals, all pointing UP as printed so it
// needs no supports. In use you flip it: the pedestals drop onto the cell's
// free end (M4 bolts up through them), and the plate's smooth bed-side face
// becomes the flat weighing surface. No retention lip — a grow block is
// heavy and wide and will not slide off a flat plate.
module platform() {
    // Pedestals land over the free-end (M4) holes. The platform is centred
    // over the base in use, so map each base hole into platform-local coords.
    px = plat_margin + cell_cx;
    difference() {
        union() {
            // Platform plate
            cube([plat_w, plat_l, plat_th]);

            // Free-end pedestals (point UP as printed; down in use)
            for (y = m4_ys())
                translate([px, y - (cell_y0 + lc_len - plat_l) - end_margin, 0])
                    cylinder(h = plat_th + plat_ped_h, d = m4_head_d + 5,
                             $fn = 32);
        }

        // M4 clearance holes through plate + pedestal, with the socket-head
        // counterbore opening on the pedestal top (accessible when flipped).
        for (y = m4_ys()) {
            yy = y - (cell_y0 + lc_len - plat_l) - end_margin;
            translate([px, yy, -1])
                cylinder(h = plat_th + plat_ped_h + 2, d = m4_clear, $fn = 24);
            translate([px, yy, plat_th + plat_ped_h - 3])
                cylinder(h = 3.5, d = m4_head_d, $fn = 24);
        }

        // Wordmark debossed into the as-printed top face (the pedestal side).
        // Sits clear of both pedestals, between them along the plate centre.
        translate([plat_w / 2, plat_l / 2, plat_th - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 5, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

// ── Render (base + platform laid out for one print bed) ────────
base();

// Wordmark engraved into the base plate top, clear of the cell + bay
translate([base_w / 2, base_l - 5, foot_h + base_th - 0.4])
    linear_extrude(0.5)
        text("SporePrint", size = 5, halign = "center",
             font = "Liberation Sans");

translate([base_w + 15, 0, 0])
    platform();
