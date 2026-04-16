// SporePrint Raspberry Pi 5 Case
// Snap-fit case with ventilation, GPIO access, SD card slot,
// USB/Ethernet/power port cutouts
//
// Mounting options:
//   - M3 screw holes (for permanent wall/shelf mounting via standoffs)
//   - Zip tie slots (for shelf/wire/rail mounting)
//
// Print settings: PLA or PETG, 0.2mm layer height, no supports needed
// Designed for: Raspberry Pi 5 (85x56mm PCB)
//
// Customization: adjust parameters at top of file
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters (Raspberry Pi 5 dimensions) ────────────────────
board_w     = 85;    // mm — Pi 5 PCB width
board_l     = 56;    // mm — Pi 5 PCB length
board_h     = 17;    // mm — max component height above PCB
pcb_thick   = 1.6;   // mm — PCB thickness
wall        = 2;     // mm — wall thickness
tolerance   = 0.3;   // mm — fit clearance
lid_lip     = 1.5;   // mm — snap-fit lip depth
screw_d     = 3;     // mm — M3 mounting screws
vent_d      = 3;     // mm — ventilation hole diameter

// Port cutout dimensions (left side, looking from top)
usbc_w      = 9;     // mm — USB-C power port width
usbc_h      = 4;     // mm — USB-C power port height
hdmi_w      = 7;     // mm — micro-HDMI port width (x2)
hdmi_h      = 3.5;   // mm — micro-HDMI port height

// Right side ports
usba_w      = 15;    // mm — USB-A double-stack width
usba_h      = 16;    // mm — USB-A double-stack height
ethernet_w  = 16;    // mm — Ethernet jack width
ethernet_h  = 14;    // mm — Ethernet jack height

// SD card slot (bottom edge)
sd_w        = 12;    // mm — SD card slot width
sd_h        = 3;     // mm — SD card slot height

// GPIO header (top edge)
gpio_w      = 51;    // mm — 40-pin GPIO header length
gpio_h      = 9;     // mm — GPIO header height (with pins)

// Pi mounting holes (from board corner, Pi 5 spec)
hole_inset_x = 3.5;  // mm — from board edge
hole_inset_y = 3.5;  // mm — from board edge
hole_dx      = 58;   // mm — horizontal spacing
hole_dy      = 49;   // mm — vertical spacing
hole_d       = 2.7;  // mm — M2.5 mounting holes

// Zip tie parameters
zt_width   = 3;    // mm — zip tie slot width
zt_depth   = 1.5;  // mm — zip tie slot depth
zt_spacing = 15;   // mm — distance between parallel zip tie slots

// ── Derived dimensions ────────────────────────────────────────
inner_w = board_w + tolerance * 2;
inner_l = board_l + tolerance * 2;
outer_w = inner_w + wall * 2;
outer_l = inner_l + wall * 2;
base_h  = wall + pcb_thick + 3;  // base holds PCB + small clearance below
lid_h   = board_h - 3 + wall;    // lid covers components above PCB

// ── Reusable mounting modules ──────────────────────────────────

module zip_tie_slot(width=3, depth=1.5, spacing=15) {
    // Two parallel slots for zip tie pass-through
    for (x = [-spacing/2, spacing/2])
        translate([x, 0, 0])
            cube([width, 20, depth], center=true);
}

// ── Base (bottom half) ────────────────────────────────────────
module pi_case_base() {
    difference() {
        union() {
            // Outer shell
            cube([outer_w, outer_l, base_h + lid_lip]);

            // Corner standoffs for wall mounting (external)
            for (pos = [[wall / 2, wall / 2],
                         [outer_w - wall / 2, wall / 2],
                         [wall / 2, outer_l - wall / 2],
                         [outer_w - wall / 2, outer_l - wall / 2]])
                translate([pos[0], pos[1], 0])
                    cylinder(h = base_h, d = screw_d * 2.5, $fn = 20);
        }

        // Inner cavity
        translate([wall, wall, wall])
            cube([inner_w, inner_l, base_h + lid_lip + 1]);

        // SD card slot (front edge — bottom of Pi)
        translate([wall + tolerance + board_w / 2 - sd_w / 2, -1, wall])
            cube([sd_w, wall + 2, sd_h]);

        // USB-C power cutout (left side as viewed from top)
        translate([-1, wall + tolerance + 7, wall + pcb_thick])
            cube([wall + 2, usbc_w, usbc_h]);

        // Micro-HDMI cutouts (left side, two ports)
        translate([-1, wall + tolerance + 21, wall + pcb_thick])
            cube([wall + 2, hdmi_w, hdmi_h]);
        translate([-1, wall + tolerance + 34, wall + pcb_thick])
            cube([wall + 2, hdmi_w, hdmi_h]);

        // USB-A double-stack cutout (right side)
        translate([outer_w - wall - 1, wall + tolerance + 2, wall + pcb_thick])
            cube([wall + 2, usba_w, usba_h]);

        // Ethernet cutout (right side)
        translate([outer_w - wall - 1, wall + tolerance + 28, wall + pcb_thick])
            cube([wall + 2, ethernet_w, ethernet_h]);

        // Bottom ventilation grid
        for (x = [wall + 5 : 6 : outer_w - wall - 5])
            for (y = [wall + 5 : 6 : outer_l - wall - 5])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_d, $fn = 12);

        // Wall mount screw holes through standoffs
        for (pos = [[wall / 2, wall / 2],
                     [outer_w - wall / 2, wall / 2],
                     [wall / 2, outer_l - wall / 2],
                     [outer_w - wall / 2, outer_l - wall / 2]])
            translate([pos[0], pos[1], -1])
                cylinder(h = base_h + 2, d = screw_d, $fn = 16);

        // Zip tie slots on left side (for shelf/wire mounting)
        translate([0, outer_l / 2, base_h / 2])
            rotate([0, 90, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);

        // Zip tie slots on right side
        translate([outer_w, outer_l / 2, base_h / 2])
            rotate([0, 90, 0])
                zip_tie_slot(width=zt_width, depth=zt_depth, spacing=zt_spacing);
    }

    // Pi mounting posts (M2.5 standoffs)
    for (dx = [0, hole_dx])
        for (dy = [0, hole_dy])
            translate([wall + tolerance + hole_inset_x + dx,
                       wall + tolerance + hole_inset_y + dy, wall])
                difference() {
                    cylinder(h = pcb_thick + 2, d = 5, $fn = 16);
                    translate([0, 0, -0.5])
                        cylinder(h = pcb_thick + 3, d = hole_d, $fn = 16);
                }
}

// ── Lid (top half) ────────────────────────────────────────────
module pi_case_lid() {
    snap_w = inner_w - 0.4;
    snap_l = inner_l - 0.4;

    difference() {
        union() {
            // Top plate
            cube([outer_w, outer_l, wall]);

            // Snap-fit lip
            translate([wall + 0.2, wall + 0.2, -lid_lip])
                difference() {
                    cube([snap_w, snap_l, lid_lip]);
                    translate([wall, wall, -0.5])
                        cube([snap_w - wall * 2, snap_l - wall * 2, lid_lip + 1]);
                }
        }

        // GPIO header slot (back edge)
        translate([wall + tolerance + board_w / 2 - gpio_w / 2,
                   outer_l - wall - 1, -lid_lip - 1])
            cube([gpio_w, wall + 2, lid_lip + wall + 2]);

        // Top ventilation grid (over SoC area)
        for (x = [wall + 15 : 5 : wall + 45])
            for (y = [wall + 10 : 5 : wall + 40])
                translate([x, y, -1])
                    cylinder(h = wall + 2, d = vent_d, $fn = 12);

        // Fan mount holes (40mm fan, centered over SoC)
        for (dx = [-16, 16])
            for (dy = [-16, 16])
                translate([wall + tolerance + 30 + dx,
                           wall + tolerance + 25 + dy, -1])
                    cylinder(h = wall + 2, d = screw_d, $fn = 16);
    }
}

// ── Render ─────────────────────────────────────────────────────
pi_case_base();

// Lid placed beside the base for printing
translate([outer_w + 10, 0, 0])
    pi_case_lid();
