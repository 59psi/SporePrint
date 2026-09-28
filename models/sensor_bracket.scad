// SporePrint Universal Sensor Mounting Bracket
// Snaps onto two wires of a wire shelf and carries the sensor_mount.scad
// climate enclosure out over the substrate on a flat platform.
//
// ── What it fits ───────────────────────────────────────────────────────
//   - sensor_mount.scad (both builds). The platform + tie-down positions
//     come from the SAME footprint functions the enclosure uses
//     (lib/sensor_mount_dims.scad — included, not `use`d, so this file
//     downloads and renders on its own). Render both parts with the same
//     -D scd30=... (and any footprint -D: fit, qt_clear, notch_w,
//     ear_len, enc_wall) and the saddle inserts land on the ear holes.
//   - Round shelf wire Ø wire_d (default 5 mm — measure yours) at
//     wire_spacing centres (default 25 mm). Wire runs along Y through
//     each C-clip; bore = wire + 2 x clip_gap; the mouth (facing up, as
//     printed) is snap_interference narrower than the wire so the bracket
//     snaps up onto the wires from below. The hanging load pulls the wire
//     toward that mouth, so also run a zip tie (<= 4.8 mm wide, <= 1.8 mm
//     thick) through the slot in each clip web and over the wire — the
//     snap locates, the tie holds.
//
// ── Enclosure joint (heat-set inserts) ─────────────────────────────────
//   Two saddles stand the enclosure's end ears enc_standoff above the
//   platform (air reaches the floor vents from all sides — the enclosure
//   must never sit on a solid surface). Each saddle carries one
//   M3 x 5.7 brass heat-set insert, mouth up, under the ear's counterbored
//   M3 hole. Screws go in from above — nothing overhangs the ear holes.
//   Buy: 2x M3 x 5.7 insert, 2x M3 x 6 socket head cap screw
//   (sp_screw_len(M3, ear_t 4.5) = 7.0 -> 6 mm stock). No inserts?
//   -D SP_FASTENER="self_tap" turns the pockets into M3 pilot holes.
//
// ── Mounting options ───────────────────────────────────────────────────
//   - Wire shelf C-clips (num_clips, snap onto wires below the shelf)
//   - Suction cup: Ø sc_diameter x sc_depth recess under the platform
//     centre for a standard 30 mm cup (suction_cup = false removes it)
//   - The enclosure's own ears also take zip ties (see sensor_mount.scad)
//
// ── Printing (PLA or PETG, 0.2 mm, NO supports) ───────────────────────
//   Renders flat as printed: arm, platform and clip bar on the bed, clips
//   opening upward. Clip flanks are within 10° of vertical, the bore lips
//   overhang < 1 mm, the clip tie slots are 5 mm bridges and the
//   suction-cup recess ceiling is a Ø30 bridge — no supports anywhere.
//   PETG preferred for the snap clips (PLA works with the default
//   0.4 mm snap_interference). tilt_angle != 0 lifts the platform off the
//   bed and then DOES need supports.
//
// ── Presets (-D) ───────────────────────────────────────────────────────
//   (none)                 SCD4x enclosure, 2 clips, suction recess
//   scd30=true             matches sensor_mount.scad -D scd30=true
//   num_clips=1 | 3        clip count
//   suction_cup=false      no recess under the platform
//   clip_tie_slot=false    no zip-tie slot in the clip webs
//   SP_FASTENER="self_tap" pilot holes instead of insert pockets
//   part="none"            geometry off (for including in a test rig)
//
// 2026-09 audit: the old render put the clip bar at z = -10 (arm and
// platform floating 10 mm off the bed), the clips' "vertical drop" fin ran
// straight through the wire bore, the gusset filled part of both bores,
// the arm sat 6 mm off the clip centre, the suction ring hung below the
// bed, and the enclosure bolted down through two bare M3 holes. All fixed.
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>
include <lib/sensor_mount_dims.scad>

// ── Parameters ────────────────────────────────────────────────────────
scd30 = false;   // match sensor_mount's variant (true widens the platform)
part  = "print"; // "print" | "none"

wire_d          = 5;     // mm — wire shelf wire diameter (measure yours)
wire_spacing    = 25;    // mm — center-to-center wire spacing
platform_thick  = 3;     // mm — platform thickness
wall            = 3;     // mm — clip ring wall + platform rim thickness
clip_depth      = 15;    // mm — wire centre height above the bed (the clip
                         //      web drops this far below the wire)
clip_gap        = 0.5;   // mm — radial clearance around the wire in the bore
snap_interference = 0.4; // mm — clip mouth this much narrower than the wire
arm_length      = 50;    // mm — horizontal arm from clips to platform
arm_width       = 34;    // mm — arm width (X) = clip length along the wire
arm_thick       = 4;     // mm — arm + clip bar thickness
screw_d         = 3;     // mm — tie-down screw size; fixed at 3 (M3) to
                         //      match sensor_mount's counterbored ear holes
tilt_angle      = 0;     // degrees — platform tilt (0 = flat; != 0 needs supports)
num_clips       = 2;     // number of wire clips (straddle 2 wires)
cable_slot_w    = 8;     // mm — cable routing slot width
gusset_size     = 4;     // mm — clip web flare each side at the bar (small
                         //      keeps the ring above the bore free to flex)
clip_tie_slot   = true;  // zip-tie slot through each clip web: a tie over
                         //      the wire closes the mouth (load-secure)
suction_cup     = true;  // recess for a suction cup under the platform
enc_standoff    = 4.7;   // mm — air gap under the enclosure floor

// Suction cup parameters
sc_diameter = 30;  // mm — standard suction cup diameter
sc_depth    = 2;   // mm — recess depth (capped to leave a 1.2 mm web)

// Enclosure footprint — must match sensor_mount.scad (defaults do).
fit       = SM_FIT_DEFAULT;       // 1.0
qt_clear  = SM_QT_CLEAR_DEFAULT;  // 6.0
notch_w   = SM_GALLERY_DEFAULT;   // 9
ear_len   = SM_EAR_LEN_DEFAULT;   // 12
ear_t     = SM_EAR_T_DEFAULT;     // 4.5 (screw length only)
enc_wall  = SM_WALL_DEFAULT;      // 2 (sensor_mount's `wall`)

// ── Derived ───────────────────────────────────────────────────────────
tie_screw = SM_TIEDOWN_SCREW;   // "M3"
assert(screw_d == 3, "screw_d must stay 3: sensor_mount.scad counterbores its ears for M3");

enc_w  = sm_outer_w(scd30, fit = fit, wall = enc_wall, qt = qt_clear);
enc_l  = sm_outer_l(scd30, fit = fit, wall = enc_wall, gallery = notch_w);
ear_hole_pitch = sm_ear_hole_pitch(scd30, fit = fit, wall = enc_wall,
                                   qt = qt_clear, ear = ear_len);

// Platform footprint = enclosure body + both end ears + a margin.
plat_margin  = 5;    // mm — platform border past the enclosure ears
ear_span     = enc_w + sm_ear_len(ear_len) * 2;
platform_w   = ear_span + plat_margin * 2;
platform_l   = enc_l + plat_margin * 2;
saddle_top   = max(platform_thick + enc_standoff, sp_insert_boss_h(tie_screw));

clip_inner_d = wire_d + clip_gap * 2;
clip_outer_d = clip_inner_d + wall * 2;
clip_mouth   = wire_d - snap_interference;
clip_zc      = max(clip_depth, arm_thick + clip_outer_d / 2);
clip_half    = max(clip_outer_d / 2, wall / 2 + gusset_size);
clip_tie_z   = (arm_thick + clip_zc - clip_inner_d / 2) / 2;  // slot centre
x_mid        = (num_clips - 1) * wire_spacing / 2;
total_clip_w = (num_clips - 1) * wire_spacing + 2 * clip_half;

plat_x0 = x_mid - platform_w / 2;
plat_y0 = -arm_length - platform_l + 5;   // overlaps the arm end by 5 mm

// Enclosure placement on the platform (platform-local coordinates)
enc_x0 = (platform_w - enc_w) / 2;
enc_y0 = plat_margin;

assert(clip_mouth < wire_d && clip_mouth > wire_d / 2,
       "snap_interference must keep the clip mouth between wire_d/2 and wire_d");

echo(str("sensor_bracket: ", scd30 ? "SCD-30" : "SCD4x", " platform ",
         platform_w, " x ", platform_l, " mm; tie-down pitch ",
         ear_hole_pitch, " mm; saddle top ", saddle_top, " mm; ",
         tie_screw, " inserts x 2, screws ", tie_screw, " x ",
         sp_screw_len(tie_screw, ear_t, true), " -> 6 mm stock x 2"));

// ── Wire clip profile (XZ), wire along Y ──────────────────────────────
module clip_profile_2d() {
    difference() {
        hull() {
            translate([0, clip_zc]) circle(d = clip_outer_d, $fn = 48);
            translate([-(wall / 2 + gusset_size), arm_thick - 0.01])
                square([wall + 2 * gusset_size, 0.01]);
        }
        translate([0, clip_zc]) circle(d = clip_inner_d, $fn = 48);
        translate([-clip_mouth / 2, clip_zc])
            square([clip_mouth, clip_outer_d]);
    }
}

// ── Clip block: bar on the bed + num_clips C-clips, y in [0, arm_width]
module clip_block() {
    translate([-clip_half, 0, 0])
        cube([total_clip_w, arm_width, arm_thick]);
    for (i = [0 : num_clips - 1])
        difference() {
            translate([i * wire_spacing, arm_width, 0])
                rotate([90, 0, 0])
                    linear_extrude(arm_width)
                        clip_profile_2d();
            // Zip-tie slot (along X) through the web under the bore: the
            // tie wraps up over the wire and closes the mouth. Its roof is
            // a zt_w bridge along Y.
            if (clip_tie_slot)
                translate([i * wire_spacing - clip_outer_d, arm_width / 2 - 2.5,
                           clip_tie_z - 1])
                    cube([clip_outer_d * 2, 5, 2]);
        }
}

// ── Horizontal arm ────────────────────────────────────────────────────
module arm() {
    translate([x_mid - arm_width / 2, -arm_length, 0])
        cube([arm_width, arm_length + 0.01, arm_thick]);
}

// ── Sensor platform ───────────────────────────────────────────────────
module sensor_platform() {
    translate([plat_x0, plat_y0, 0])
        rotate([tilt_angle, 0, 0])
            difference() {
                union() {
                    difference() {
                        union() {
                            cube([platform_w, platform_l, platform_thick]);
                            // Perimeter rim (stiffener)
                            difference() {
                                cube([platform_w, platform_l, platform_thick + 2]);
                                translate([wall, wall, -1])
                                    cube([platform_w - wall * 2,
                                          platform_l - wall * 2,
                                          platform_thick + 4]);
                            }
                        }

                        // Cable routing slot (front edge, under the
                        // enclosure's ESP32 cable notch)
                        translate([platform_w / 2 - cable_slot_w / 2, -1, -1])
                            cube([cable_slot_w, 4, platform_thick + 4]);

                        // Ventilation holes
                        for (x = [12 : 8 : platform_w - 12])
                            for (y = [wall + 5 : 8 : platform_l - wall - 5])
                                translate([x, y, -1])
                                    cylinder(h = platform_thick + 2, d = 3, $fn = 12);

                        // Suction cup recess (underside, centre)
                        if (suction_cup)
                            translate([platform_w / 2, platform_l / 2, -0.01])
                                cylinder(h = min(sc_depth, platform_thick - 1.2) + 0.01,
                                         d = sc_diameter + 0.4, $fn = 64);
                    }

                    // Saddles under the enclosure's end ears
                    for (sx = [enc_x0 - ear_len, enc_x0 + enc_w])
                        translate([sx, enc_y0, 0])
                            cube([ear_len, enc_l, saddle_top]);
                }

                // M3 heat-set insert pockets under the ear holes
                for (dx = [-ear_hole_pitch / 2, ear_hole_pitch / 2])
                    translate([platform_w / 2 + dx, enc_y0 + enc_l / 2, saddle_top])
                        sp_insert_pocket(tie_screw);
            }
}

// ── Full assembly (as printed) ────────────────────────────────────────
module sensor_bracket() {
    difference() {
        union() {
            clip_block();
            arm();
            sensor_platform();
        }
        // Wordmark engraved on the arm top
        translate([x_mid, -arm_length / 2, arm_thick - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 3.5, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

if (part == "print")
    sensor_bracket();
