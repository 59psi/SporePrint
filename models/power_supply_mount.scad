// SporePrint 12V Power Supply Mounting Bracket
// Wall-mountable bracket for a standard barrel-jack 12V DC power supply
// Fits common "brick" style adapters (adjustable width via parameters)
// Print: PLA or PETG, 0.2mm layer height, no supports needed
// Mount to wall with M3 or M4 screws
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters (adjust for your PSU brick) ────────────────────
psu_w         = 50;    // mm — PSU width
psu_l         = 110;   // mm — PSU length
psu_h         = 30;    // mm — PSU height (thickness)
wall          = 3;     // mm — bracket wall thickness
tolerance     = 1;     // mm — extra clearance around PSU
lip_h         = 8;     // mm — retention lip height (holds PSU in)
lip_overhang  = 3;     // mm — how far lip extends over PSU
strap_w       = 15;    // mm — Velcro/zip-tie strap slot width
strap_h       = 3;     // mm — strap slot height
cable_slot_w  = 15;    // mm — cable exit slot width
cable_slot_h  = 10;    // mm — cable exit slot height
screw_d       = 4;     // mm — M4 wall mount screws (use M3 for lighter loads)
base_thick    = 3;     // mm — base plate thickness
corner_r      = 3;     // mm — corner radius for aesthetics

// ── Derived ───────────────────────────────────────────────────
cradle_w = psu_w + tolerance * 2 + wall * 2;
cradle_l = psu_l + tolerance * 2 + wall * 2;
cradle_h = base_thick + lip_h;

// ── Rounded rectangle helper ──────────────────────────────────
module rounded_rect(w, l, h, r) {
    hull() {
        for (x = [r, w - r])
            for (y = [r, l - r])
                translate([x, y, 0])
                    cylinder(h = h, r = r, $fn = 20);
    }
}

// ── Base cradle ───────────────────────────────────────────────
module psu_cradle() {
    difference() {
        union() {
            // Base plate (rounded rectangle)
            rounded_rect(cradle_w, cradle_l, base_thick, corner_r);

            // Left wall
            translate([0, 0, 0])
                cube([wall, cradle_l, cradle_h]);

            // Right wall
            translate([cradle_w - wall, 0, 0])
                cube([wall, cradle_l, cradle_h]);

            // Front wall (partial — with cable exit)
            cube([cradle_w, wall, cradle_h]);

            // Back wall
            translate([0, cradle_l - wall, 0])
                cube([cradle_w, wall, cradle_h]);

            // Retention lips (overhang to hold PSU down)
            // Left lip
            translate([wall, 0, cradle_h - wall])
                cube([lip_overhang, cradle_l, wall]);
            // Right lip
            translate([cradle_w - wall - lip_overhang, 0, cradle_h - wall])
                cube([lip_overhang, cradle_l, wall]);
        }

        // PSU cavity
        translate([wall, wall, base_thick])
            cube([psu_w + tolerance * 2, psu_l + tolerance * 2, cradle_h + 1]);

        // Cable exit slot (front wall, centered)
        translate([cradle_w / 2 - cable_slot_w / 2, -1, base_thick])
            cube([cable_slot_w, wall + 2, cable_slot_h]);

        // Cable exit slot (back wall, centered — for DC output)
        translate([cradle_w / 2 - cable_slot_w / 2, cradle_l - wall - 1, base_thick])
            cube([cable_slot_w, wall + 2, cable_slot_h]);

        // Strap slots (for Velcro or zip-tie securing)
        for (y_pos = [cradle_l * 0.3, cradle_l * 0.7]) {
            // Left side strap slot
            translate([-1, y_pos - strap_w / 2, base_thick + lip_h / 2])
                cube([wall + 2, strap_w, strap_h]);
            // Right side strap slot
            translate([cradle_w - wall - 1, y_pos - strap_w / 2, base_thick + lip_h / 2])
                cube([wall + 2, strap_w, strap_h]);
        }

        // Bottom ventilation holes (PSU heat dissipation)
        for (x = [wall + 5 : 8 : cradle_w - wall - 5])
            for (y = [wall + 5 : 8 : cradle_l - wall - 5])
                translate([x, y, -1])
                    cylinder(h = base_thick + 2, d = 3, $fn = 12);
    }
}

// ── Wall mount plate ──────────────────────────────────────────
module wall_mount() {
    mount_w = cradle_w + 20;  // wider than cradle for screw tabs
    mount_l = cradle_l;

    difference() {
        union() {
            // Mount plate (behind cradle)
            translate([-10, 0, -wall])
                rounded_rect(mount_w, mount_l, wall, corner_r);
        }

        // Mounting screw holes (four corners of plate)
        for (pos = [[-5, wall + 10],
                     [-5, cradle_l - wall - 10],
                     [cradle_w + 5, wall + 10],
                     [cradle_w + 5, cradle_l - wall - 10]])
            translate([pos[0], pos[1], -wall - 1])
                cylinder(h = wall + 2, d = screw_d, $fn = 16);

        // Countersink for screw heads
        for (pos = [[-5, wall + 10],
                     [-5, cradle_l - wall - 10],
                     [cradle_w + 5, wall + 10],
                     [cradle_w + 5, cradle_l - wall - 10]])
            translate([pos[0], pos[1], -wall - 0.5])
                cylinder(h = 1.5, d1 = screw_d + 4, d2 = screw_d, $fn = 16);

        // Keyhole slots (for tool-free hanging on screws)
        for (x_pos = [cradle_w / 4, cradle_w * 3 / 4])
            translate([x_pos, cradle_l / 2, -wall - 1]) {
                // Wide entry
                cylinder(h = wall + 2, d = screw_d + 3, $fn = 16);
                // Narrow slot
                translate([0, -5, 0])
                    cylinder(h = wall + 2, d = screw_d + 0.5, $fn = 16);
                // Connecting channel
                translate([-screw_d / 4 - 0.25, -5, 0])
                    cube([screw_d / 2 + 0.5, 5, wall + 2]);
            }
    }
}

// ── Full assembly ─────────────────────────────────────────────
module power_supply_mount() {
    psu_cradle();
    wall_mount();
}

// ── Render ─────────────────────────────────────────────────────
power_supply_mount();
