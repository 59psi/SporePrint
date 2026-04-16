// SporePrint Relay Board Mount
// Mounting plate for 4x IRLZ44N MOSFETs with screw terminal blocks
// Print: PLA, 0.2mm layer height, no supports needed
// Mount to wall/shelf/DIN rail with M3 screws
//
// github.com/sporeprint — open-source mushroom cultivation platform

// ── Parameters ─────────────────────────────────────────────────
num_channels     = 4;     // number of MOSFET channels
channel_spacing  = 20;    // mm — center-to-center between channels
mosfet_width     = 10;    // mm — TO-220 package width
mosfet_depth     = 15;    // mm — TO-220 package depth (with legs)
mosfet_tab_slot  = 4;     // mm — width of heatsink tab slot
terminal_width   = 10;    // mm — screw terminal block width
terminal_depth   = 8;     // mm — screw terminal depth
wall             = 2;     // mm — base plate thickness
rail_height      = 5;     // mm — component retention rail height
screw_d          = 3;     // mm — M3 mounting holes
wire_slot        = 3;     // mm — wire routing channel width
standoff_h       = 4;     // mm — standoff height (airflow underneath)
standoff_d       = 6;     // mm — standoff outer diameter

// ── Derived ────────────────────────────────────────────────────
plate_width  = num_channels * channel_spacing + wall * 2 + 10;
plate_depth  = mosfet_depth + terminal_depth + 30;  // room for resistors + diodes
plate_height = wall;

// ── Base plate ─────────────────────────────────────────────────
module base_plate() {
    difference() {
        cube([plate_width, plate_depth, plate_height]);

        // Wire routing channels (between each channel)
        for (i = [1 : num_channels - 1]) {
            x = wall + 5 + i * channel_spacing;
            translate([x - wire_slot / 2, 5, -1])
                cube([wire_slot, plate_depth - 10, plate_height + 2]);
        }

        // Main cable entry slot (front edge, centered)
        translate([plate_width / 2 - 10, -1, -1])
            cube([20, wall + 2, plate_height + 2]);

        // Mounting screw holes (four corners)
        for (pos = [[screw_d, screw_d],
                     [plate_width - screw_d, screw_d],
                     [screw_d, plate_depth - screw_d],
                     [plate_width - screw_d, plate_depth - screw_d]])
            translate([pos[0], pos[1], -1])
                cylinder(h = plate_height + 2, d = screw_d, $fn = 16);

        // Label text area (engraved, front edge)
        translate([plate_width / 2 - 15, 1, plate_height - 0.4])
            linear_extrude(0.5)
                text("SporePrint Relay", size = 3, halign = "center", font = "Liberation Sans");
    }
}

// ── MOSFET slot (TO-220 retention clip) ────────────────────────
module mosfet_slot() {
    // Slot for TO-220 package legs
    translate([0, 0, plate_height])
        difference() {
            // Retention walls
            union() {
                // Left wall
                cube([1.5, mosfet_depth, rail_height]);
                // Right wall
                translate([mosfet_width + 1.5, 0, 0])
                    cube([1.5, mosfet_depth, rail_height]);
                // Back stop
                translate([0, mosfet_depth, 0])
                    cube([mosfet_width + 3, 1.5, rail_height]);
            }

            // Tab slot (heatsink tab passes through)
            translate([mosfet_width / 2 + 1.5 - mosfet_tab_slot / 2, mosfet_depth - 2, -1])
                cube([mosfet_tab_slot, 4, rail_height + 2]);
        }
}

// ── Screw terminal block holder ────────────────────────────────
module terminal_slot() {
    translate([0, 0, plate_height])
        difference() {
            // Retention walls
            union() {
                cube([1.5, terminal_depth, rail_height]);
                translate([terminal_width + 1.5, 0, 0])
                    cube([1.5, terminal_depth, rail_height]);
                translate([0, terminal_depth, 0])
                    cube([terminal_width + 3, 1.5, rail_height]);
            }
        }
}

// ── Standoffs (raise plate for airflow) ────────────────────────
module standoffs() {
    for (pos = [[screw_d, screw_d],
                 [plate_width - screw_d, screw_d],
                 [screw_d, plate_depth - screw_d],
                 [plate_width - screw_d, plate_depth - screw_d]])
        translate([pos[0], pos[1], -standoff_h])
            difference() {
                cylinder(h = standoff_h, d = standoff_d, $fn = 16);
                translate([0, 0, -1])
                    cylinder(h = standoff_h + 2, d = screw_d, $fn = 16);
            }
}

// ── Component label strips ─────────────────────────────────────
module channel_labels() {
    labels = ["FAE", "EXH", "CIRC", "AUX"];
    for (i = [0 : num_channels - 1]) {
        x = wall + 5 + i * channel_spacing + channel_spacing / 2;
        translate([x, plate_depth - 3, plate_height - 0.3])
            linear_extrude(0.4)
                text(labels[i], size = 3, halign = "center", font = "Liberation Sans");
    }
}

// ── Assembly ───────────────────────────────────────────────────
module relay_board_mount() {
    base_plate();
    standoffs();
    channel_labels();

    // Place MOSFET slots and terminal blocks for each channel
    for (i = [0 : num_channels - 1]) {
        x = wall + 5 + i * channel_spacing;

        // MOSFET slot (back row)
        translate([x, plate_depth - mosfet_depth - terminal_depth - 10, 0])
            mosfet_slot();

        // Output terminal (back edge)
        translate([x, plate_depth - terminal_depth - 3, 0])
            terminal_slot();

        // Input terminal (front edge)
        translate([x, 5, 0])
            terminal_slot();
    }
}

// ── Render ──────────────────────────────────────────────────────
relay_board_mount();
