// SporePrint — Raspberry Pi 5 + Active Cooler dimension library
//
// Library file: constants and modules only, NO top-level geometry.
//
//     include <lib/pi5_dims.scad>
//
// (The Builder download endpoint inlines lib/ includes, so a single
// downloaded model still renders on its own.)
//
// Every number below is read off the official Raspberry Pi drawings,
// measured from the vector PDFs (1:1 @ A4, so 1 pt = 25.4/72 mm):
//
//   * Raspberry Pi 5 mechanical drawing (Raspberry Pi Ltd, Oct 2023)
//     https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf
//     (one drawing for every RAM option: 1/2/4/8/16 GB per the April 2026
//     product brief)
//   * Raspberry Pi Active Cooler (SKU SC1148) mechanical drawing
//     https://datasheets.raspberrypi.com/cooling/raspberry-pi-active-cooler-mechanical-drawing.pdf
//   * Cross-checked against the official Raspberry Pi 5 3D model
//     RP-010083-CA-1 "rpi-5 3D STEP - No Graphics" (Product Information
//     Portal, pip.raspberrypi.com, category 892, file dated May 2026): every
//     solid's bounding box was extracted with OpenCascade. Where the STEP
//     and the drawing differ the envelope below is the UNION of both.
//     STEP facts used: PCB 1.336 thick; no underside part within r 4.4 of
//     any mounting hole; deepest underside part 1.45; USB-A stacks
//     y 21.75-36.25 / 39.75-54.25; RJ45 y 2.285-18.215, front 88.05;
//     USB-C shell +0.10..+3.26 above the PCB top; micro-HDMI flange
//     -0.25..+3.35; power-button actuator 0.45 proud, +0.70..+2.70.
//   * PCN 44 (Jan 2026): new MagJack reaches 0.3 mm further INTO the board
//     (outside dimensions unchanged). PCN 22: Rev 4 PCB / D0 stepping has
//     no mechanical change.
//
// Board frame used everywhere in this file:
//   origin  = PCB corner where the USB-C / micro-HDMI long edge meets the
//             microSD / power-button short edge (drawing bottom-left)
//   +x      = along the 85 mm edge, towards Ethernet + USB-A
//   +y      = along the 56 mm edge, towards the 40-pin GPIO header
//   top-side z is measured UP from the PCB top face,
//   underside z is measured DOWN (negative) from the PCB bottom face.
//
// Dimensioned on the drawing: 85 x 56 outline, holes 3.5 in on a 58 x 49
// pattern (Ø2.7), cooler holes Ø3 6 mm inboard of two mounting holes,
// USB-C / HDMI0 / HDMI1 centres 11.2 / 25.8 / 39.2, Ethernet / USB / USB
// centres 10.2 / 29.1 / 47, ports overhanging the edge by 3, GPIO header
// 29 mm from hole 1, connector heights 3.2 / 3.4 / 4.1 / 4.4.
// Envelope corners, header / jack / stack heights, microSD protrusion and
// button / LED positions are measured from the same vector drawing. Values
// tagged "est." are NOT on any drawing: they are deliberately generous
// estimates (heights of small connectors, plug overmolds, cable paths).

// ── PCB ──────────────────────────────────────────────────────────────
PI5_PCB_W        = 85;     // mm, long edge
PI5_PCB_L        = 56;     // mm, short edge
PI5_PCB_T_DRAWN  = 1.41;   // mm, as drawn (cases use 1.6 to cover tolerance)
PI5_PCB_T_STEP   = 1.336;  // mm, official STEP model
PI5_PCB_T_MIN    = min(PI5_PCB_T_DRAWN, PI5_PCB_T_STEP);  // thinnest board seen
PI5_PCB_R        = 3;      // mm, corner radius
PI5_HOLES        = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];
PI5_HOLE_D       = 2.7;    // M2.5 clearance
PI5_PAD_D        = 6.0;    // copper pad ring drawn round each hole
// Official STEP: nothing on the UNDERSIDE within r 4.4 of a hole centre
// (nearest: a 1.25-deep part 4.40 from hole 4, PoE pin tails 4.41).
PI5_BOT_KEEPOUT_D = 8.8;

// Active Cooler push-pin holes (Ø3, 6 mm above hole 1 and below hole 4)
PI5_COOLER_HOLES = [[3.5, 9.5], [61.5, 46.5]];
PI5_COOLER_HOLE_D = 3.0;

// ── Top-side envelopes ───────────────────────────────────────────────
// [name, x0, x1, y0, y1, z0, z1]  (z from PCB top)
PI5_TOP = [
    ["usbc",      6.80, 15.60, -1.35,  6.00,  0.00,  3.20],
    ["hdmi0",    22.50, 29.10, -1.70,  6.90, -0.20,  3.40],
    ["hdmi1",    35.90, 42.50, -1.70,  6.90, -0.20,  3.40],
    ["rtc_bat",  16.96, 20.98,  3.30,  6.20,  0.00,  4.40],  // J5, 2-pin JST-SH
    ["uart",     29.64, 34.96,  2.30,  5.50,  0.00,  4.40],  // 3-pin JST-SH
    ["cam_disp0",47.19, 50.15,  0.70, 16.20,  0.00,  4.10],  // 22-pin FPC
    ["cam_disp1",53.39, 56.31,  0.70, 16.20,  0.00,  4.10],
    ["poe",      59.00, 64.00,  7.00, 12.00,  0.00,  8.50],  // 2x2 PoE+ header
    ["gpio",      7.08, 57.82, 49.96, 54.93,  0.00,  8.56],  // 40-pin header
    ["fan_hdr",  65.30, 69.70, 40.30, 47.70,  0.00,  4.30],  // 4-pin JST-SH, h est.
    ["j_tr",     65.20, 68.30, 49.00, 55.00,  0.00,  4.50],  // h est.
    ["button",    0.40,  3.05, 16.10, 20.70,  0.00,  3.30],  // side-push power
    ["button_act",-0.50, 0.40, 17.40, 19.40,  0.00,  3.30],  // its actuator, z est.
    ["led",       0.00,  1.80, 11.70, 14.90,  0.00,  1.50],  // edge status LED, h est.
    ["pcie_fpc",  1.24,  5.40, 24.74, 35.24,  0.00,  4.10],  // 16-pin PCIe FPC
    ["ethernet", 66.37, 88.05,  2.22, 18.22,  0.00, 13.88],  // x0: PCN 44 (+0.3 in)
    ["usb3",     70.47, 88.30, 21.74, 36.33,  0.00, 16.42],  // incl. EMI flare
    ["usb2",     70.33, 88.30, 39.67, 54.25,  0.00, 16.42],
];
// Anything not listed (SoC, RAM, RP1, PMIC, passives, M2.5 screw heads) is
// lower than the GPIO header; the proxy covers the whole board to this height.
PI5_TOP_GENERIC_H = 8.56;

// Port centre lines used to place case openings.
PI5_USBC_X    = 11.2;   PI5_USBC_ZC = 1.70;   // receptacle 8.8 x 3.2
PI5_HDMI_X    = [25.8, 39.2];  PI5_HDMI_ZC = 1.60;  // 6.6 x 3.4 (STEP: 1.55)
PI5_PORT_ZC_TOL = 0.05;   // drawing-vs-STEP spread of the port centre lines
PI5_ETH_YC    = 10.20;  PI5_ETH_W  = 15.96;  PI5_ETH_H  = 13.88;
PI5_USB3_YC   = 29.035; PI5_USB2_YC = 46.96;  // envelope centres (drawn 29.1 / 47)
PI5_USB_W     = 14.59;  PI5_USB_H  = 16.42;  // stack incl. front EMI flare
PI5_PORT_FRONT_X = 88.30;                    // furthest port overhang (+x)
PI5_BUTTON_YC = 18.40;  PI5_BUTTON_ZC = 1.65;
PI5_LED_YC    = 13.30;  PI5_LED_ZC    = 0.80;
PI5_PCIE_YC   = 29.99;  PI5_PCIE_W    = 10.50;
PI5_GPIO_XC   = 32.45;  PI5_GPIO_YC   = 52.445;
PI5_GPIO_L    = 50.74;  PI5_GPIO_WD   = 4.97;  PI5_GPIO_H = 8.56;
PI5_SOC_C     = [33.05, 24.01];             // BCM2712 centre (17 x 14.5 pkg)

// ── Underside envelopes ──────────────────────────────────────────────
// [name, x0, x1, y0, y1, z0, z1]  (z from PCB bottom, negative = down)
PI5_BOT = [
    ["sd_slot", -0.31, 14.00, 20.60, 35.60, -1.45, 0.00],   // socket; y span est. (wide)
    ["sd_card", -1.72, 14.00, 22.57, 33.57, -1.40, -0.30],  // card fully in
];
PI5_SD_YC      = 28.07;
PI5_SD_SOCKET_X0 = -0.31;           // socket lip beyond the PCB edge
PI5_SD_SOCKET_Y  = [20.60, 35.60];
PI5_SD_W       = 11.0;    // microSD card width
PI5_SD_PROTRUDE = 1.72;   // card end beyond the PCB edge (-x)
PI5_BOT_SMD_H  = 1.45;    // deepest underside part in the STEP
PI5_BOT_THT_H  = 2.0;     // through-hole tails (GPIO, PoE, jacks: 1.94 drawn)
PI5_BOT_THT_KEEPOUT_D = PI5_BOT_KEEPOUT_D;  // one keep-out for both layers

// ── Raspberry Pi Active Cooler (SC1148) ──────────────────────────────
// Footprint read from the drawing with its push pins on PI5_COOLER_HOLES:
// 63.5 x 42.5 outline, 30 x 30 blower, Ø21 intake. The drawing's overall
// 13.70 mm runs from the push-pin tips to the fan-screw heads; the heads
// sit 10.5 mm above the heatsink base, which rides ~2-3 mm above the PCB
// on the SoC and its thermal pad, so 13.70 above the PCB top is used as a
// deliberately conservative ceiling (installed height est. 12.5-13.2).
AC_BBOX      = [0.35, 64.24, 6.54, 49.65];  // [x0, x1, y0, y1]
AC_H         = 13.70;                        // envelope top above PCB top
AC_FAN       = [27.35, 57.20, 18.00, 47.90]; // blower body
AC_INTAKE_C  = [41.60, 33.60];               // blower intake centre
AC_INTAKE_D  = 21.0;
AC_PIN_D     = 3.6;     // split barb, drawn Ø3.3
AC_PIN_BELOW = 3.0;     // barb below the PCB bottom (est.)
AC_CABLE     = [57.00, 70.00, 40.00, 48.00, 0.00, 11.00];  // fan lead to FAN (est.)

// ── Plug / access envelopes (outside the board) ──────────────────────
// USB Type-C spec: recommended plug overmold max 12.35 x 6.5 mm.
PI5_USBC_PLUG = [12.35, 6.5];
// micro-HDMI has no overmold limit in its spec: 11.0 x 6.4 (est., typical).
PI5_HDMI_PLUG = [11.0, 6.4];
PI5_RJ45_BOOT = [15.0, 15.0];     // latch boot, wide/tall (est.)
PI5_USBA_PLUG = [17.0, 17.4];     // two stacked USB-A overmolds (est.)

// ── Proxy modules (for fit tests and the assembly preview) ───────────
// pcb_z : absolute z of the PCB BOTTOM face; pcb_t : PCB thickness.
// sweep : 0 = in place, +1 = swept straight up (to prove a drop-in
//         insertion is clear), -1 = swept straight down.

module _pi5_slab(x0, x1, y0, y1, z0, z1, sweep = 0) {
    zl = sweep < 0 ? z0 - 200 : z0;
    zh = sweep > 0 ? z1 + 200 : z1;
    translate([x0, y0, zl]) cube([x1 - x0, y1 - y0, zh - zl]);
}

module _pi5_outline2d(r = PI5_PCB_R) {
    hull() for (x = [r, PI5_PCB_W - r], y = [r, PI5_PCB_L - r])
        translate([x, y]) circle(r = r, $fn = 32);
}

module _pi5_extrude(z0, z1, sweep = 0) {
    zl = sweep < 0 ? z0 - 200 : z0;
    zh = sweep > 0 ? z1 + 200 : z1;
    translate([0, 0, zl]) linear_extrude(zh - zl) children();
}

// Bare board: PCB with its four M2.5 holes.
module pi5_pcb(pcb_z = 0, pcb_t = 1.6, sweep = 0) {
    _pi5_extrude(pcb_z, pcb_z + pcb_t, sweep)
        difference() {
            _pi5_outline2d();
            for (h = PI5_HOLES) translate(h) circle(d = PI5_HOLE_D, $fn = 24);
        }
}

// Every top-side and underside component envelope (no cooler).
module pi5_components(pcb_z = 0, pcb_t = 1.6, sweep = 0) {
    top = pcb_z + pcb_t;
    for (c = PI5_TOP)
        _pi5_slab(c[1], c[2], c[3], c[4], top + c[5], top + c[6], sweep);
    // generic top slab over the whole board (chips, passives, screw heads)
    _pi5_extrude(top, top + PI5_TOP_GENERIC_H, sweep) _pi5_outline2d();
    for (c = PI5_BOT)
        _pi5_slab(c[1], c[2], c[3], c[4], pcb_z + c[5], pcb_z + c[6], sweep);
    // underside: every part (SMD <= 1.45, THT tails <= 2.0) lies outside
    // the Ø8.8 keep-out round each mounting hole (official STEP)
    _pi5_extrude(pcb_z - PI5_BOT_THT_H, pcb_z, sweep)
        difference() {
            _pi5_outline2d();
            for (h = PI5_HOLES)
                translate(h) circle(d = PI5_BOT_THT_KEEPOUT_D, $fn = 48);
        }
}

// Active Cooler envelope, push-pin barbs and its fan lead.
module pi5_active_cooler(pcb_z = 0, pcb_t = 1.6, sweep = 0) {
    top = pcb_z + pcb_t;
    _pi5_slab(AC_BBOX[0], AC_BBOX[1], AC_BBOX[2], AC_BBOX[3],
              top, top + AC_H, sweep);
    for (p = PI5_COOLER_HOLES)
        _pi5_extrude(pcb_z - AC_PIN_BELOW, top, sweep)
            translate(p) circle(d = AC_PIN_D, $fn = 24);
    _pi5_slab(AC_CABLE[0], AC_CABLE[1], AC_CABLE[2], AC_CABLE[3],
              top + AC_CABLE[4], top + AC_CABLE[5], sweep);
}

// Mating plugs and finger / tool access paths, in place (no sweep).
// reach = how far out from the board the envelopes extend.
// zc_off shifts the USB-C / micro-HDMI plug centre lines (e.g. -0.05 for the
// STEP's lower HDMI centre); hdmi_plug overrides the HDMI overmold size.
module pi5_access(pcb_z = 0, pcb_t = 1.6, reach = 40, ffc = true,
                  zc_off = 0, hdmi_plug = PI5_HDMI_PLUG) {
    top = pcb_z + pcb_t;
    // USB-C plug overmold, seated against the receptacle face
    translate([PI5_USBC_X - PI5_USBC_PLUG[0] / 2, -1.35 - reach,
               top + PI5_USBC_ZC + zc_off - PI5_USBC_PLUG[1] / 2])
        cube([PI5_USBC_PLUG[0], reach, PI5_USBC_PLUG[1]]);
    // micro-HDMI plug overmolds
    for (x = PI5_HDMI_X)
        translate([x - hdmi_plug[0] / 2, -1.70 - reach,
                   top + PI5_HDMI_ZC + zc_off - hdmi_plug[1] / 2])
            cube([hdmi_plug[0], reach, hdmi_plug[1]]);
    // RJ45 plug boot
    translate([88.0, PI5_ETH_YC - PI5_RJ45_BOOT[0] / 2,
               top + PI5_ETH_H / 2 - PI5_RJ45_BOOT[1] / 2])
        cube([reach, PI5_RJ45_BOOT[0], PI5_RJ45_BOOT[1]]);
    // USB-A plug overmolds, both ports of each stack
    for (yc = [PI5_USB3_YC, PI5_USB2_YC])
        translate([PI5_PORT_FRONT_X, yc - PI5_USBA_PLUG[0] / 2, top - 0.5])
            cube([reach, PI5_USBA_PLUG[0], PI5_USBA_PLUG[1]]);
    // microSD: fingernail zone round the protruding card end
    translate([-reach, PI5_SD_YC - PI5_SD_W / 2, pcb_z - 2.2])
        cube([reach - PI5_SD_PROTRUDE, PI5_SD_W, 2.2]);
    // power button: Ø2.5 pen / paper-clip path to the actuator
    translate([-0.5, PI5_BUTTON_YC, top + PI5_BUTTON_ZC])
        rotate([0, -90, 0]) cylinder(d = 2.5, h = reach, $fn = 24);
    // status LED line of sight
    translate([-reach, PI5_LED_YC - 0.5, top + 0.3])
        cube([reach, 1.0, 1.0]);
    // PCIe FFC leaving the FPC connector through the short edge
    if (ffc)
        translate([-reach, PI5_PCIE_YC - 4.6, top + 0.6])
            cube([reach + 1.24, 9.2, 1.6]);
}

// GPIO header access straight up (Dupont housings / IDC plug).
module pi5_gpio_access(pcb_z = 0, pcb_t = 1.6, reach = 40) {
    top = pcb_z + pcb_t;
    translate([PI5_GPIO_XC - PI5_GPIO_L / 2, PI5_GPIO_YC - PI5_GPIO_WD / 2,
               top + PI5_GPIO_H])
        cube([PI5_GPIO_L, PI5_GPIO_WD, reach]);
}

// CAM/DISP 0 + 1 ribbons (22-way 0.5 mm FFC, ~12 wide) rising straight up
// out of the two FPC connectors.
PI5_CSI_X = [48.67, 54.85];     // connector slot centre lines
PI5_CSI_Y = [2.20, 14.70];      // cable width span
module pi5_csi_access(pcb_z = 0, pcb_t = 1.6, reach = 40) {
    top = pcb_z + pcb_t;
    for (x = PI5_CSI_X)
        translate([x - 0.5, PI5_CSI_Y[0], top + 4.1])
            cube([1.0, PI5_CSI_Y[1] - PI5_CSI_Y[0], reach]);
}

// M2.5 socket-head cap screws holding the board (shaft + head), for
// insert-engagement checks. len = nominal length under the head.
module pi5_mount_screws(pcb_z = 0, pcb_t = 1.6, len = 6) {
    top = pcb_z + pcb_t;
    for (h = PI5_HOLES) translate([h[0], h[1], 0]) {
        translate([0, 0, top - len]) cylinder(d = 2.5, h = len, $fn = 24);
        translate([0, 0, top]) cylinder(d = 4.5, h = 2.5, $fn = 24);
    }
}
