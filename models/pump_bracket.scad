// SporePrint Peristaltic Pump Bracket
// L-bracket that bolts through the dosing pump's OWN two flange holes, for
// the Tier 3 "All the Things" misting / hydration pump. The motor passes
// through an open-top U slot in the face plate; the pump flange seats on two
// raised pads that carry M2.5 brass heat-set inserts; an optional zip-tie
// cradle under the motor damps vibration. The base screws (M3) or zip-ties
// to a wall, shelf or wire rack OUTSIDE the grow chamber.
//
// ── Fits (select with -D pump="...") ───────────────────────────────────────
//   "adafruit_1150" (DEFAULT, BOM pick) — Adafruit 1150 "Peristaltic Liquid
//       Pump with Silicone Tubing - 12V DC". Source: adafruit.com/product/1150
//       technical details: 27 mm diameter motor, 72 mm total length, mounting
//       holes 2.7 mm diameter at 50 mm centre-to-centre. Adafruit publishes no
//       drawing of the flange / head outline; the fit proof uses a flange
//       envelope of 57 x 42 x 3 mm and a head envelope of 40 x 44 mm, 20.5 mm
//       long, both larger than the Kamoer drawing below (same diamond-plate
//       pump family).
//   "kamoer_nkp" — Kamoer NKP-DC (12 V) micro peristaltic pump, flat "straight
//       plate" version (Amazon B07GWJ78FN). Source: Kamoer NKP product manual
//       A/2 and Kamoer doc CPBZ-NKP-01 edition A8 "Product Size" drawings:
//       diamond plate 54.5 x 40.3 mm, 2 x Ø3.2 holes at 48.5 ±0.15 mm c-c,
//       motor Ø29 x 44 mm behind the plate, head 23-23.5 mm in front, tube
//       ports on top of the head. (Some Kamoer listings quote a Ø30.5 can —
//       measure yours; if it is 30.5 add -D pump_d=30.5 or the cradle will
//       be 0.15 mm tight. The face-plate slot is Ø32 either way, only the
//       cradle follows pump_d.)
//   "universal" — fits BOTH pumps: the two flange holes become 48.5-50.5 mm
//       c-c slots with captive M2.5 hex nuts behind (inserts cannot slide, so
//       this preset uses nuts instead). Cradle sized for a Ø30.5 can — add a
//       2 mm foam/rubber strip under an Adafruit (Ø27) motor.
//   (Earlier revisions called the Adafruit pump a "Kamoer KMP-A1". No source
//   supports that: Adafruit does not publish the OEM, and its 50 mm hole
//   pitch differs from the Kamoer NKP's 48.5 mm — pick the matching preset.)
//
// Key dimensions: pump axis 25 mm above the mounting face; Ø32 open-top
// motor slot; flange seat (pad faces) 3 mm proud of the 5 mm face plate;
// base 75 x 44 mm (adafruit_1150), 73.5 x 44 (kamoer_nkp), 75.5 x 44
// (universal); 4 x Ø3.4 base holes, 2 x 2 zip-tie slots.
//
// Assembly: clip the pump head on with the TUBE PORTS POINTING UP (away from
// the base) or sideways — never down (the NKP head can be clipped in any of
// 4 orientations). Screw the bracket to the wall/shelf first, then lower the
// motor into the U slot, seat the flange on the pads and drive the two M2.5
// screws through the flange holes. Motor solder tabs point to the rear,
// clear of everything. The head/flange clears the mounting surface by ≥3 mm
// (4.85 mm with the Kamoer drawing's 40.3 mm plate).
//
// ── Hardware to buy ─────────────────────────────────────────────────────────
//   Pump flange, "adafruit_1150" / "kamoer_nkp" presets (default):
//     2 x M2.5 brass heat-set insert, 5.7 mm long (ruthex RX-M2.5x5.7 or
//         CNC Kitchen equivalent) — pressed into the two pads, from the front
//     2 x M2.5 x 8 mm socket-head or pan-head screw (for a 2-3.5 mm thick
//         flange 8 mm engages 4.5-6 mm of the 5.7 mm insert and cannot bottom
//         in the 6.7 mm pocket; the figure for your flange_th is echoed at
//         render time)
//   Pump flange, "universal" preset (or -D flange_nut=true):
//     2 x M2.5 x 12 mm screw + 2 x M2.5 hex nut (DIN 934, 5 mm AF, 2 mm)
//         — nuts drop into the hex pockets on the back of the face plate
//   Base: 4 x M3 pan-head (M3 x 12 through a ≤5 mm panel + nut) or 4 x #4
//         (2.9 mm) x 1/2" wood screw into a wall/shelf — for #6 / 3.5 mm wood
//         screws print with -D screw_d=4; OR 2-4 zip ties ≤3.6 mm wide
//         through the base slot pairs around a wire-shelf rod.
//   Cradle: 1 zip tie ≤3.6 mm wide (e.g. 2.5 x 150 mm) through the tunnel
//         under the saddle and over the motor — snug, not tight (the flange
//         screws locate the motor; the cradle only damps vibration). Optional
//         1 mm foam tape in the cradle; 2 mm under a Ø27 motor in "universal".
//   This is a SINGLE printed piece, so no piece-to-piece inserts are needed;
//   the inserts are only for the pump's own flange screws.
//
// ── Printing ────────────────────────────────────────────────────────────────
//   PLA or PETG, 0.2 mm layers, 3 walls, 25 % infill. Print exactly as
//   rendered: base flat on the bed, face plate standing up. NO SUPPORTS: the
//   motor slot is open at the top (lower half-circle only), the cradle is a
//   concave-up half pipe, the insert pockets / nut pockets are small (≤4 mm)
//   horizontal holes, and the cradle tie tunnel is a 5 mm bridge.
//   Heat-set the inserts before mounting: clamp the base in a vise (base
//   vertical, pad faces pointing straight up) and press each insert straight
//   down into its pad until flush, iron ~230 °C (PLA) / ~245 °C (PETG).
//
// ── Presets / overrides (-D) ────────────────────────────────────────────────
//   -D pump="adafruit_1150"     default — inserts at 50.0 mm c-c, cradle Ø27
//   -D pump="kamoer_nkp"        inserts at 48.5 mm c-c, cradle Ø29
//   -D pump="universal"         48.5-50.5 mm slots + captive nuts, cradle Ø30.5
//   -D pump_d=30.5              motor can Ø (cradle follows; slot stays ≥Ø32)
//   -D flange_nut=true          nuts instead of inserts on any preset
//   -D motor_cradle=false       omit the under-motor zip-tie cradle
//   -D axis_h=28                raise the pump (head/flange clearance)
//   -D SP_FASTENER="self_tap"   plain Ø2.1 pilot holes for M2.5 self-tappers
//   -D SP_INSERT_HOLE_TWEAK=-0.1  tighten / loosen the insert pockets
//   -D screw_d=4                Ø4 base holes for #6 / 3.5 mm wood screws
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>

// ── Pump preset ────────────────────────────────────────────────
pump = "adafruit_1150";  // [adafruit_1150, kamoer_nkp, universal]

// ── Parameters (defaults follow the preset; any can be -D overridden) ──
pump_d      = pump == "adafruit_1150" ? 27 : pump == "kamoer_nkp" ? 29 : 30.5;  // mm — motor can Ø
pump_len    = pump == "adafruit_1150" ? 72 : 67.5;  // mm — total length, head front to motor rear
head_len    = 23.5;  // mm — head + flange, front of head to flange back face (Kamoer drawing)
head_clear_h = 44;   // mm — tallest head/flange envelope to clear the mounting face (Adafruit est.)
flange_th   = 3;     // mm — pump flange thickness at the screw holes (screw length)
flange_cc   = pump == "adafruit_1150" ? 50 : pump == "kamoer_nkp" ? 48.5 : 49.5;  // mm — flange hole c-c
slot_travel = pump == "universal" ? 2.0 : 0;  // mm — c-c range the slots cover (flange_cc ± half), nut mode only
flange_nut  = pump == "universal";  // true = slots + M2.5 nuts, false = M2.5 heat-set inserts
flange_screw = "M2.5";

fit          = 0.6;   // mm — radial clearance, motor to cradle / slot
motor_slot_min = 32;  // mm — the face-plate U slot is never narrower than this
axis_h       = 25;    // mm — pump axis height above the mounting surface
standoff     = 3;     // mm — pads hold the flange this far off the plate (clip hooks, labels)
plate_th     = 5;     // mm — face plate thickness
pad_w        = 9;     // mm — width of each flange pad / ear
gusset_t     = 4;     // mm — gusset thickness
gusset_len   = 16;    // mm — gusset run along the base
wall         = 3;     // mm — cradle saddle wall thickness
base_th      = 4;     // mm — base plate thickness
motor_cradle = true;  // under-motor zip-tie cradle
saddle_w     = 8;     // mm — cradle thickness along the pump axis
saddle_gap   = 30;    // mm — flange seat (pad face) to cradle centre
end_margin   = 10;    // mm — base length behind the cradle
side_margin  = 8;     // mm — base width outboard of the face plate (M3 + tie slots)
screw_d      = 3.4;   // mm — M3 base mounting holes
cap_slot_w   = 2.6;   // mm — cradle tie tunnel height (tie thickness + slack)
cap_slot_l   = 5;     // mm — cradle tie tunnel width along the axis (tie width + slack)

// Zip tie parameters (base-to-shelf through-slots, one pair per side)
zt_width   = 3;    // mm — zip tie width the slots take (slot long side = zt_width + 1)
zt_depth   = 1.5;  // mm — zip tie thickness the slots take (slot short side = zt_depth + 0.5)
zt_spacing = 15;   // mm — distance between the two slots of a pair (rod runs between)

// Hex nut (nut mode): DIN 934 M2.5
nut_af = 5.0;      // mm — across flats
nut_h  = 2.0;      // mm — thickness
nut_clear = 0.4;   // mm — added to AF and depth of the nut pocket

// ── Derived ────────────────────────────────────────────────────
cradle_r    = pump_d / 2 + fit;
motor_len   = pump_len - head_len;                // can + solder tabs behind the flange
motor_slot_d = max(pump_d + 2 * fit, motor_slot_min);
hx_min      = (flange_cc - (flange_nut ? slot_travel / 2 : 0)) / 2;  // flange hole x (inner)
hx_max      = (flange_cc + (flange_nut ? slot_travel / 2 : 0)) / 2;  // flange hole x (outer)
plate_hw    = hx_max + pad_w / 2;                 // face plate half width
ear_top     = axis_h + pad_w / 2;                 // top of the ears / pads
seat_y      = -standoff;                          // flange rear face (pad front face)
gusset_x0   = motor_slot_d / 2 + 0.8;             // gusset inner face
saddle_y    = seat_y + saddle_gap;                // cradle centre
base_l      = saddle_y + saddle_w / 2 + end_margin; // base runs y = 0 .. base_l
base_hw     = plate_hw + side_margin;
base_w      = base_hw * 2;
mount_x     = plate_hw + side_margin / 2 + 0.25;  // M3 hole / tie slot x
mount_ys    = [4, base_l - 5];                    // M3 hole y (front, rear)
zt_y        = (mount_ys[0] + mount_ys[1]) / 2;    // tie slot pair centre y
word_y      = (plate_th + (saddle_y - saddle_w / 2)) / 2;
nut_ac      = (nut_af + nut_clear) / cos(30);     // nut pocket across corners
nut_depth   = nut_h + nut_clear;

// Flange screw length: largest stock length that engages the insert without
// bottoming in the pocket (insert mode), or passes fully through the nut.
function _stock_le(l, s = [4, 5, 6, 8, 10, 12, 14, 16, 20, 25]) =
    max([for (v = s) if (v <= l + 0.001) v]);
function _stock_ge(l, s = [4, 5, 6, 8, 10, 12, 14, 16, 20, 25]) =
    min([for (v = s) if (v >= l - 0.001) v]);
flange_screw_l = flange_nut
    ? _stock_ge(flange_th + standoff + plate_th - nut_depth + nut_h)  // through the nut
    : _stock_le(min(sp_screw_len(flange_screw, flange_th, false),
                    flange_th + sp_insert_depth(flange_screw) - 0.5));
flange_engage = flange_screw_l - flange_th;

// ── Sanity checks (all hold for every preset) ──────────────────
assert(pump == "adafruit_1150" || pump == "kamoer_nkp" || pump == "universal",
       str("unknown pump preset ", pump));
assert(pump != "universal" || flange_nut,
       "the universal preset needs flange_nut=true — inserts cannot slide along a slot");
assert(axis_h >= head_clear_h / 2 + 2, "axis_h too low: pump head/flange would hit the mounting surface");
assert(axis_h - pump_d / 2 >= base_th + 2, "axis_h too low for the motor over the base");
assert(hx_min - pad_w / 2 >= motor_slot_d / 2 + 2, "flange pads collide with the motor slot");
assert(flange_nut || standoff + plate_th >= sp_insert_depth(flange_screw) + 1,
       "pad + plate too thin for the M2.5 insert pocket");
assert(!flange_nut || plate_th - nut_depth >= 2, "plate too thin for the nut pocket");
assert(!flange_nut || gusset_x0 + gusset_t <= hx_min - nut_ac / 2 - 0.2,
       "gusset blocks the nut pocket");
assert(!motor_cradle || axis_h - cradle_r >= base_th + cap_slot_w + 1,
       "cradle tie tunnel does not fit under the motor bore");
assert(!motor_cradle || saddle_gap + saddle_w / 2 <= motor_len - 3,
       "cradle is past the end of the motor can");
assert(gusset_len + plate_th <= saddle_y - saddle_w / 2 - 1, "gusset runs into the cradle");

echo(str("pump_bracket: preset=", pump, "  motor Ø", pump_d, "  flange c-c ",
         flange_nut ? (hx_max > hx_min ? str(2 * hx_min, "-", 2 * hx_max, " (slots + nuts)")
                                       : str(flange_cc, " (holes + nuts)"))
                    : str(flange_cc, " (M2.5 inserts)"),
         "  flange screws: 2 x ", flange_screw, " x ", flange_screw_l,
         flange_nut ? " + 2 hex nuts" : str(" (", flange_engage, " mm into the insert)"),
         "  base ", base_w, " x ", base_l + standoff, " mm"));

// ── Reusable mounting module ───────────────────────────────────
// A pair of zip-tie through-slots, `spacing` apart along Y, centred on the
// origin; the shelf rod runs along X between them.
module zip_tie_slot(width = 3, depth = 1.5, spacing = 15) {
    for (y = [-spacing / 2, spacing / 2])
        translate([0, y, 0])
            cube([width + 1, depth + 0.5, 3 * base_th + 2], center = true);
}

// ── Flange fastener cut (one side, x = +/-) ────────────────────
module flange_fastener_cut(side) {
    if (!flange_nut) {
        // Insert pocket: mouth on the pad face, runs +Y into pad + plate.
        translate([side * (flange_cc / 2), seat_y, axis_h])
            rotate([90, 0, 0]) sp_insert_pocket(flange_screw);
    } else {
        // Clearance slot through pad + plate, spanning hx_min..hx_max.
        hull() for (x = [hx_min, hx_max])
            translate([side * x, seat_y - 1, axis_h])
                rotate([-90, 0, 0])
                    cylinder(h = standoff + plate_th + 2,
                             d = sp_screw_clearance_d(flange_screw), $fn = 24);
        // Hex nut pocket from the back face, flats top/bottom so the nut
        // cannot turn, slotted along X with the screw.
        hull() for (x = [hx_min, hx_max])
            translate([side * x, plate_th - nut_depth, axis_h])
                rotate([-90, 0, 0])
                    cylinder(h = nut_depth + 1, d = nut_ac, $fn = 6);
    }
}

// ── Face plate: ears + flange pads, open-top motor slot ────────
module face_plate() {
    difference() {
        union() {
            // Plate
            translate([-plate_hw, 0, 0]) cube([plate_hw * 2, plate_th, ear_top]);
            // Flange pads (stand the flange `standoff` proud of the plate so
            // head clip hooks / motor-mount details on its back face clear)
            for (s = [-1, 1])
                translate([s > 0 ? hx_min - pad_w / 2 : -plate_hw, seat_y, 0])
                    cube([plate_hw - (hx_min - pad_w / 2), standoff + 0.01, ear_top]);
        }
        // Motor slot: lower half-circle + straight sides open to the top
        hull() {
            translate([0, seat_y - 1, axis_h]) rotate([-90, 0, 0])
                cylinder(h = standoff + plate_th + 2, d = motor_slot_d, $fn = 96);
            translate([-motor_slot_d / 2, seat_y - 1, axis_h])
                cube([motor_slot_d, standoff + plate_th + 2, ear_top]);
        }
        for (s = [-1, 1]) flange_fastener_cut(s);
        // Chamfer the ear tops (outer corners)
        for (s = [-1, 1])
            translate([s * plate_hw, (seat_y + plate_th) / 2, ear_top])
                rotate([-90, 0, 0]) rotate([0, 0, 45])
                    cube([3, 3, standoff + plate_th + 2], center = true);
    }
}

// ── Gussets (tie the ears to the base, beside the motor) ───────
module gussets() {
    for (s = [-1, 1])
        translate([s > 0 ? gusset_x0 : -gusset_x0 - gusset_t, 0, 0])
            rotate([90, 0, 90])
                linear_extrude(gusset_t)
                    polygon([[plate_th - 0.01, 0], [plate_th + gusset_len, 0],
                             [plate_th + gusset_len, base_th],
                             [plate_th - 0.01, ear_top - 1]]);
}

// ── Motor cradle saddle (zip tie under the bore, over the motor) ──
module saddle(y) {
    difference() {
        translate([-(cradle_r + wall), y - saddle_w / 2, 0])
            cube([(cradle_r + wall) * 2, saddle_w, axis_h]);
        // Cradle bore — the lower half-pipe the motor rests in
        translate([0, y - saddle_w / 2 - 1, axis_h])
            rotate([-90, 0, 0])
                cylinder(h = saddle_w + 2, r = cradle_r, $fn = 96);
        // Tie tunnel under the bore, across the full saddle width
        translate([-(cradle_r + wall) - 0.01, y - cap_slot_l / 2, base_th])
            cube([(cradle_r + wall) * 2 + 0.02, cap_slot_l, cap_slot_w]);
    }
}

// ── Base plate ─────────────────────────────────────────────────
module base() {
    difference() {
        translate([-base_hw, 0, 0]) cube([base_w, base_l, base_th]);

        // M3 mounting holes (four corners, outboard of the face plate)
        for (x = [-mount_x, mount_x])
            for (y = mount_ys)
                translate([x, y, -1])
                    cylinder(h = base_th + 2, d = screw_d, $fn = 24);

        // Zip tie slot pairs (one per side, between the M3 holes)
        for (x = [-mount_x, mount_x])
            translate([x, zt_y, base_th / 2])
                zip_tie_slot(zt_width, zt_depth, zt_spacing);

        // Wordmark (engraved, base top, between face plate and cradle)
        translate([0, word_y, base_th - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 4, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

// ── Assembly ───────────────────────────────────────────────────
module pump_bracket() {
    union() {
        base();
        face_plate();
        gussets();
        if (motor_cradle) saddle(saddle_y);
    }
}

// ── Render ──────────────────────────────────────────────────────
pump_bracket();
