// SporePrint 12V Power Supply Mounting Bracket
// Wall / shelf cradle for the 12 V "desktop brick" power supply that feeds
// the LED strips, fans and pump. The brick lies flat in an open-top cradle,
// is held down by two 20 mm (3/4") hook-and-loop straps that run under it
// in a floor channel and out through slots in both side walls, and is kept
// from sliding out of the ends by low corner end stops. Both ends are open
// between the stops (≥36 mm, open to the top) so an IEC C13 plug, a moulded
// cord boot or a right-angle DC plug leaves the cradle without touching it.
//
// ── Fits (select with -D psu="...") ────────────────────────────────────────
//   Dimensions are body W x L x H in mm, as printed on each vendor's own
//   "product size" drawing (the listing image named below).
//   "facmogu_5a" (DEFAULT, BOM Tier 2) — Facmogu 12V 5A 60W, model AL-1250,
//       Amazon B0711Q5B49 "2 Prong Plug": 55 x 113 x 33 ("PRODUCT SIZE"
//       image: 2.2"/5.5 cm x 4.5"/11.3 cm x 1.3"/3.3 cm). AC cord is
//       HARD-WIRED (40 cm, 2-prong) with a moulded boot, DC 5.5x2.5 plug on a
//       152 cm cord with a boot at the other end. (Not a C7/C8 inlet.)
//   "facmogu_10a" (BOM Tier 3) — Facmogu 12V 10A 120W, model AL-12100,
//       Amazon B087LY94T6: 60 x 153 x 33 ("SIZE" image: 6 cm x 15.3 cm x
//       3.3 cm). IEC C14 inlet on one end (90 cm C13 cord), 86 cm DC cord
//       with a right-angle 5.5x2.5 plug on the other end.
//   "alitove_5a" — ALITOVE 12V 5A 60W, Amazon B01GEA8PQA: 55 x 113 x 35
//       (listing image 5.5 cm x 11.3 cm x 3.5 cm). C14 inlet near one corner.
//   "sansun_5a" — SANSUN 12V 5A 60W desktop brick (Amazon B0B79WLSJJ bundle):
//       50 x 116 x 31 (listing image 1.97" x 4.56" x 1.22"). Hard-wired cords.
//   "meanwell_gst60a12" — Mean Well GST60A12-P1J: 50 x 125 x 31.5 (Mean Well
//       GST60A series spec, 125 x 50 x 31.5 mm L x W x H, as listed by Mouser /
//       TRC / Jameco). IEC320-C14 inlet, 5.5 x 2.1 mm DC plug.
//   "alitove_10a" — ALITOVE 12V 10A 120W, Amazon B07MXXXBV8: 63 x 167 x 38
//       (listing image 6.3 cm x 16.7 cm x 3.8 cm). C14 inlet near one corner.
//   Clearance: `tolerance` (1.0 mm) per side all round the body, so a brick
//   up to 1 mm over its drawing still has ≥0.5 mm per side. The end stops
//   are kept ≥0.5 mm below a 28 x 20 mm C13-plug envelope centred on the
//   brick's mid-height, anywhere across the width, so an inlet in any
//   position (centre or corner) and a plug either end clears. The brick goes
//   in either way round.
//
// ── Construction / hardware to buy ─────────────────────────────────────────
//   ONE printed piece (cradle and wall plate are a single print), so there
//   are no printed-to-printed joints and NO heat-set inserts.
//   Retention: 2 x hook-and-loop strap, 19-20 mm wide (3/4") x 300 mm (12")
//       — e.g. VELCRO ONE-WRAP 3/4" x 12" or back-to-back 20 mm tape cut to
//       300 mm (the length each preset needs, incl. 60 mm overlap, is
//       echoed at render time: 254-278 mm, 294 mm for alitove_10a). Thread
//       it in through one side slot, along the floor channel under the
//       brick, out the other slot, then up and over the brick and close.
//   Wall, pick ONE:
//     a) 4 x #8 (or M4) FLAT-head countersunk wood screw, ≥ 25 mm (1"), in
//        the four flange holes (countersunk from the front, head Ø ≤ 9 mm)
//        — plus anchors if going into drywall; or
//     b) 2 x #8 (or M4) PAN-head wood screw, head Ø ≤ 8.5 mm and ≤ 3.1 mm
//        tall, for the two keyhole slots under the brick. Drive them so the
//        UNDERSIDE of the head stands 2.6-2.9 mm off the wall, hook the
//        empty cradle over them and slide it DOWN (+Y end up), then strap
//        the brick in. The keyhole lip is 2.5 mm; the head sits in a Ø9
//        undercut below the brick.
//   Shelf / pegboard (optional): zip ties ≤ 4.8 mm wide through the two
//     slot pairs in the flanges (a back-face groove joins each pair so the
//     tie lies flush on a flat panel or pegboard).
//
// ── Printing ────────────────────────────────────────────────────────────────
//   PLA or PETG (PETG for the 10 A bricks, whose case runs warm), 0.2 mm
//   layers, 3 walls, 20 % infill. Print exactly as rendered: the wall face
//   flat on the bed. NO SUPPORTS: the keyhole undercuts, countersinks and
//   vents open upward; the only overhangs are the 22 mm bridges over the
//   strap slots in the side walls and 5.5 mm bridges over the zip-tie
//   grooves on the back face.
//
// ── Presets / overrides (-D) ────────────────────────────────────────────────
//   -D psu="facmogu_5a"          default, 55 x 113 x 33 (Tier 2)
//   -D psu="facmogu_10a"         60 x 153 x 33 (Tier 3)
//   -D psu="alitove_5a"          55 x 113 x 35
//   -D psu="sansun_5a"           50 x 116 x 31
//   -D psu="meanwell_gst60a12"   50 x 125 x 31.5
//   -D psu="alitove_10a"         63 x 167 x 38
//   -D psu="custom"              55 x 113 x 33 placeholder, set psu_w/l/h
//   -D psu_w=.. psu_l=.. psu_h=..   any other brick (each overrides only
//                                that value of the chosen preset; the old
//                                "-D psu_l=125 -D psu_h=32" still works)
//   -D tolerance=0.6             tighter/looser clearance per side
//   -D side_h=20                 side wall height above the floor (0 = auto)
//   -D lip_h=4                   end-stop height (auto-capped so plugs clear)
//   -D part="none"               render nothing (for include-ing this file)
//   Legacy parameters kept so older command lines still run: `lip_h`,
//   `lip_overhang` now size the corner end stops, `cable_slot_w` is the
//   minimum clear end opening, `strap_w`/`strap_h` size the strap slots,
//   `zt_*` size the flange zip-tie slots; `cable_slot_h` is no longer used
//   (the end openings are open to the top).
//
// Coordinates: z = 0 is the wall face (print bed); +Y is "up" for the
// keyhole slots when wall-hung with the brick vertical.
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Brick preset ───────────────────────────────────────────────
psu = "facmogu_5a";  // [facmogu_5a, facmogu_10a, alitove_5a, sansun_5a, meanwell_gst60a12, alitove_10a, custom]

//  [id, width, length, height, AC end, description]
//  AC end: "cord" = hard-wired cord with moulded boot, "c14" = IEC C14 inlet
PSU_PRESETS = [
    ["facmogu_5a",        55, 113, 33,   "cord", "Facmogu AL-1250 12V 5A (Amazon B0711Q5B49)"],
    ["facmogu_10a",       60, 153, 33,   "c14",  "Facmogu AL-12100 12V 10A (Amazon B087LY94T6)"],
    ["alitove_5a",        55, 113, 35,   "c14",  "ALITOVE 12V 5A 60W (Amazon B01GEA8PQA)"],
    ["sansun_5a",         50, 116, 31,   "cord", "SANSUN 12V 5A 60W (Amazon B0B79WLSJJ)"],
    ["meanwell_gst60a12", 50, 125, 31.5, "c14",  "Mean Well GST60A12-P1J"],
    ["alitove_10a",       63, 167, 38,   "c14",  "ALITOVE 12V 10A 120W (Amazon B07MXXXBV8)"],
    ["custom",            55, 113, 33,   "c14",  "custom brick (set psu_w / psu_l / psu_h)"],
];

function _psu_row(id, i = 0) =
    i >= len(PSU_PRESETS) ? undef :
    PSU_PRESETS[i][0] == id ? PSU_PRESETS[i] : _psu_row(id, i + 1);

function psu_preset(id) =
    let (r = _psu_row(id))
    assert(r != undef, str("power_supply_mount: unknown psu preset ", id))
    r;

// ── Parameters (defaults follow the preset; any can be -D overridden) ──
psu_w         = psu_preset(psu)[1];  // mm — brick width
psu_l         = psu_preset(psu)[2];  // mm — brick length (cord end to cord end, body only)
psu_h         = psu_preset(psu)[3];  // mm — brick height (thickness, lying flat)
wall          = 3;     // mm — side wall / end stop thickness
tolerance     = 1;     // mm — clearance per side between brick and cradle
lip_h         = 5;     // mm — corner end-stop height above the floor (capped so a C13 plug clears)
lip_overhang  = 8;     // mm — how far each corner end stop reaches in over the brick's end face
side_h        = 0;     // mm — side wall height above the floor; 0 = auto (half psu_h, ≥ 12)
strap_w       = 22;    // mm — strap slot width (19-20 mm hook-and-loop + clearance)
strap_h       = 3.5;   // mm — strap slot height through the side walls
strap_ch_d    = 2;     // mm — strap channel depth in the floor under the brick
cable_slot_w  = 36;    // mm — minimum clear opening at each end, between the end stops
cable_slot_h  = 10;    // mm — legacy, unused (end openings are open to the top)
screw_d       = 4;     // mm — wall screw nominal Ø (#8 or M4)
cs_head_d     = 9;     // mm — countersink Ø at the flange face (#8 / M4 flat head)
cs_inset      = 12;    // mm — countersunk holes, distance from each end
base_thick    = 3;     // mm — floor thickness on top of the wall-plate layer
corner_r      = 3;     // mm — plate corner radius
flange_w      = 14;    // mm — screw flange width each side of the cradle
flange_t      = 4;     // mm — screw flange thickness
kh_head_d     = 9;     // mm — keyhole entry / undercut Ø (pan head ≤ 8.5)
kh_head_h     = 3.1;   // mm — tallest pan head the undercut must hide
kh_lip_t      = 2.5;   // mm — keyhole lip the screw head hooks behind
kh_travel     = 8;     // mm — keyhole slot length (entry centre to hang point)

// Zip tie parameters (slot pairs in the flanges)
zt_width   = 5.5;  // mm — slot size across the tie band (ties ≤ 4.8 mm wide)
zt_thick   = 2.5;  // mm — slot size along the tie thickness
zt_depth   = 1.5;  // mm — depth of the back-face groove joining each pair
zt_spacing = 15;   // mm — distance between the two slots of a pair

vent_d     = 4;    // mm — floor vent hole Ø
vent_pitch = 9;    // mm — vent grid pitch

part = "cradle";   // [cradle, none]

// ── Derived ───────────────────────────────────────────────────
psu_ac    = psu_preset(psu)[4];
psu_label = str(psu_preset(psu)[5],
                (psu_w != psu_preset(psu)[1] || psu_l != psu_preset(psu)[2] ||
                 psu_h != psu_preset(psu)[3]) ? " [size overridden]" : "");

cav_w    = psu_w + tolerance * 2;          // cavity (brick + clearance)
cav_l    = psu_l + tolerance * 2;
cradle_w = cav_w + wall * 2;
cradle_l = cav_l + wall * 2;
total_w  = cradle_w + flange_w * 2;

// Floor: old wall-plate + floor stack, never thinner than the keyhole needs
floor_t  = max(wall + base_thick, kh_lip_t + kh_head_h + 0.8);
side_top = floor_t + (side_h > 0 ? side_h : max(12, round(psu_h / 2)));

// End stops: low enough that a 20 mm-tall C13 plug centred on the brick's
// mid-height clears them by 0.5 mm, and short enough (reach) that the end
// opening stays ≥ cable_slot_w.
stop_h     = min(lip_h, max(2, psu_h / 2 - 10.5));
stop_top   = floor_t + stop_h;
stop_reach = max(2, min(lip_overhang, (cav_w - cable_slot_w) / 2));
end_open_w = cav_w - 2 * stop_reach;

// Straps: channel bottom = strap slot bottom; flange stays below it
strap_z0     = floor_t - strap_ch_d;
flange_t_eff = min(flange_t, strap_z0);
strap_ys     = [for (f = [0.25, 0.75]) wall + cav_l * f];
strap_len    = 2 * (cradle_w + 4) + 2 * (floor_t + psu_h - strap_z0 + 2) + 60;

// Keyholes (under the brick, between the straps)
kh_xs = [cradle_w / 2 - cav_w / 4, cradle_w / 2 + cav_w / 4];
kh_y  = cradle_l / 2 - kh_travel / 2;       // entry centre; slides to kh_y + kh_travel

// Countersunk flange holes and zip-tie pairs
flange_xs = [-flange_w / 2, cradle_w + flange_w / 2];
cs_pts    = [for (x = flange_xs) for (y = [cs_inset, cradle_l - cs_inset]) [x, y]];
zt_ys     = [cradle_l / 2 - zt_spacing / 2, cradle_l / 2 + zt_spacing / 2];

// Floor vents: centred grid inside the brick footprint, clear of the strap
// channels and the keyholes
vent_keep = 2.5;
vent_nx   = floor((cav_w - 10 - vent_d) / vent_pitch) + 1;
vent_ny   = floor((cav_l - 10 - vent_d) / vent_pitch) + 1;
function _vent_ok(x, y) =
    len([for (s = strap_ys) if (abs(y - s) < strap_w / 2 + vent_keep + vent_d / 2) 1]) == 0 &&
    len([for (k = kh_xs)
            if (abs(x - k) < kh_head_d / 2 + vent_keep + vent_d / 2 &&
                y > kh_y - kh_head_d / 2 - vent_keep - vent_d / 2 &&
                y < kh_y + kh_travel + kh_head_d / 2 + vent_keep + vent_d / 2) 1]) == 0;
vent_pts = [for (i = [0 : 1 : vent_nx - 1]) for (j = [0 : 1 : vent_ny - 1])
               let (x = cradle_w / 2 + (i - (vent_nx - 1) / 2) * vent_pitch,
                    y = cradle_l / 2 + (j - (vent_ny - 1) / 2) * vent_pitch)
               if (_vent_ok(x, y)) [x, y]];

echo(str("power_supply_mount: ", psu_label, " ", psu_w, " x ", psu_l, " x ", psu_h,
         " mm (AC end: ", psu_ac, "); cavity ", cav_w, " x ", cav_l,
         "; footprint ", total_w, " x ", cradle_l, "; end opening ", end_open_w,
         " mm; end stops ", stop_h, " mm; strap length >= ", ceil(strap_len), " mm"));

// ── Helpers ───────────────────────────────────────────────────

// Rounded rectangle, corner at the origin
module rounded_rect(w, l, h, r) {
    hull() {
        for (x = [r, w - r])
            for (y = [r, l - r])
                translate([x, y, 0])
                    cylinder(h = h, r = r, $fn = 20);
    }
}

// One zip-tie slot pair (through slots) + the back-face groove joining them,
// centred on (0, 0); cut from a part whose back face is z = 0.
module zip_tie_slot(width = zt_width, depth = zt_depth, spacing = zt_spacing, thick = zt_thick) {
    for (y = [-spacing / 2, spacing / 2])
        translate([-width / 2, y - thick / 2, -1])
            cube([width, thick, 50]);
    translate([-width / 2, -spacing / 2, -1])
        cube([width, spacing, depth + 1]);
}

// Real keyhole: Ø head entry, shank slot through the lip, head undercut
// above the lip (opens into the floor under the brick).
module keyhole(head_d = kh_head_d, shank_d = screw_d + 0.6, travel = kh_travel,
               lip_t = kh_lip_t, h = 50) {
    translate([0, 0, -1]) cylinder(h = h, d = head_d, $fn = 36);
    hull() for (y = [0, travel])
        translate([0, y, -1]) cylinder(h = h, d = shank_d, $fn = 24);
    hull() for (y = [0, travel])
        translate([0, y, lip_t]) cylinder(h = h, d = head_d, $fn = 36);
}

// Countersunk wall-screw hole; head side at z = top (the flange face).
module countersunk_hole(top) {
    clr = screw_d + 0.5;
    translate([0, 0, -1]) cylinder(h = top + 2, d = clr, $fn = 24);
    translate([0, 0, top - (cs_head_d - clr) / 2])
        cylinder(h = (cs_head_d - clr) / 2 + 0.01, d1 = clr, d2 = cs_head_d, $fn = 36);
    translate([0, 0, top]) cylinder(h = 1, d = cs_head_d, $fn = 36);
}

// ── Solids ────────────────────────────────────────────────────

// Wall plate: full-length screw flanges either side of the cradle
module wall_mount() {
    translate([-flange_w, 0, 0])
        rounded_rect(total_w, cradle_l, flange_t_eff, corner_r);
}

// Cradle: floor, side walls, corner end stops
module psu_cradle() {
    cube([cradle_w, cradle_l, floor_t]);
    for (x = [0, cradle_w - wall])
        translate([x, 0, 0]) cube([wall, cradle_l, side_top]);
    for (y = [0, cradle_l - wall]) {
        translate([0, y, 0]) cube([wall + stop_reach, wall, stop_top]);
        translate([cradle_w - wall - stop_reach, y, 0]) cube([wall + stop_reach, wall, stop_top]);
    }
}

// Everything cut from the solid
module mount_cuts() {
    // Strap channel under the brick + slots through both side walls
    for (ys = strap_ys)
        translate([-flange_w - 1, ys - strap_w / 2, strap_z0])
            cube([total_w + 2, strap_w, strap_h]);

    // Keyholes
    for (x = kh_xs) translate([x, kh_y, 0]) keyhole();

    // Countersunk wall-screw holes (head on the front face of the flange)
    for (p = cs_pts) translate([p[0], p[1], 0]) countersunk_hole(flange_t_eff);

    // Zip-tie slot pairs in both flanges
    for (x = flange_xs) translate([x, cradle_l / 2, 0]) zip_tie_slot();

    // Floor vents, straight through
    for (p = vent_pts)
        translate([p[0], p[1], -1]) cylinder(h = floor_t + 2, d = vent_d, $fn = 20);
}

// Wordmark engraved into the outer right side wall, mid-span (between the
// strap slots, above the flange).
module wordmark() {
    translate([cradle_w - 0.4, cradle_l / 2, (flange_t_eff + side_top) / 2])
        rotate([90, 0, 90])
            linear_extrude(0.5)
                text("SporePrint", size = 3.5, halign = "center", valign = "center",
                     font = "Liberation Sans");
}

// ── Full part (one print) ─────────────────────────────────────
module power_supply_mount() {
    difference() {
        union() {
            wall_mount();
            psu_cradle();
        }
        mount_cuts();
        wordmark();
    }
}

// ── Render ─────────────────────────────────────────────────────
if (part == "cradle") power_supply_mount();
