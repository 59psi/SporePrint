// SporePrint ESP32 DevKit Case
// Enclosure for the climate / relay / lighting node's 38-pin ESP32 DevKit:
// two printed pieces (BASE tub + LID) joined by 4 x M3 brass heat-set inserts.
//
// ── Boards it fits  (-D 'preset="..."') ──────────────────────────────────
//  narrow_usbc  DEFAULT. ESP32-WROOM-32 38-pin "narrow" DevKit, USB-C +
//               CP2102 — what the BOM search / HiLetgo 3-pack (Amazon
//               B0CNYK7WT2) ships. PCB 52 x 25.5 mm (listings say 51.0-52;
//               the cavity is sized for 52), pin rows 22.86 mm (0.9 in)
//               apart, headers PRE-SOLDERED pointing DOWN (2.5 mm plastic +
//               6 mm pins = 8.5 mm below the PCB), NO mounting holes.
//               Sources: 2026-09 BOM audit measurement; probots.co.in listing
//               (51.0 x 25.5 mm); Espressif ESP32-WROOM-32 datasheet (module
//               18 x 25.5 x 3.1 mm); 16-pin top-mount USB-C receptacle
//               8.94 x 7.35 x 3.26 mm.
//  devkitc_v4   Espressif ESP32-DevKitC V4 (official, micro-USB). PCB
//               27.94 x 48.26 mm + WROOM module overhanging the end 6.04 mm
//               = 54.30 mm overall; rows 25.40 mm; micro-USB centred,
//               overhanging the PCB edge 1.0 mm. Source: Espressif
//               esp32_devkitc_v4_dimensions.dxf (dl.espressif.com), measured.
//  wide_usbc    Generic "wide" 38-pin USB-C clones (~55 x 28 mm, rows
//               25.4 mm, DevKitC-V4 layout). Source: vendor listings
//               (e.g. DIYables "approx. 55 x 28 mm") — measure yours.
//  s3_devkitc1  Espressif ESP32-S3-DevKitC-1 v1.1 (firmware env node_esp32s3).
//               PCB 25.40 x 62.87 mm + WROOM-1 overhang 6.28 = 69.15 mm
//               overall; rows 22.86 mm; 22 pins/row starting 6.69 mm from
//               the USB edge; TWO micro-USB ports (UART centred 6.0 mm, USB
//               centred 19.4 mm from the left edge) overhanging 0.92 mm, so
//               the USB opening is 26 mm wide. Because that opening is wider
//               than the board, two stop posts under the PCB catch the
//               header ends so pulling a cable cannot drag the board out.
//               Source: Espressif DXF_ESP32-S3-DevKitC-1_V1.1_20220429.dxf.
//  Any other board: pick the closest preset and override board_w/board_l/
//  pcb_l/pin_row_spacing/usb_dx/... individually (every -D wins over the
//  preset). The cavity keeps `tolerance` (0.5 mm) per side around the PCB.
//
// ── What else goes inside ───────────────────────────────────────────────
//  - Cables: USB-A -> USB-C data cable (BOM), plug overmould up to 13 x 7 mm;
//    micro-USB overmould up to 11.5 x 7 mm for the micro presets. The USB
//    opening is an open-top notch centred on the connector axis (the lid
//    closes it), so the board drops straight in with the plug unplugged.
//  - Wires: the BOM's Adafruit 4397 STEMMA QT -> female-socket cable and the
//    gate jumpers push onto the DOWNWARD header pins. The base has a bay
//    under the board for those 2.54 mm sockets (14.5 mm housings) plus room
//    to bend the wires, and a 10 x 5 mm wire window at floor level with a
//    zip-tie bar beside it for strain relief (wire_exit = usb|far|both|none).
//    Nothing plugged on the pins? -D dupont=false builds the compact case.
//  - The board rests on two ribs between the header rows (it has no holes),
//    and pads under the lid stop 0.3 mm above the module shield and USB
//    receptacle so it cannot lift. EN/BOOT buttons are not reachable with
//    the lid on (flash over USB auto-reset or OTA).
//
// ── Buy (per case) ──────────────────────────────────────────────────────
//  4 x M3 x 5.7 mm brass heat-set inserts (ruthex RX-M3x5.7 / CNC Kitchen
//      M3x5.7), pressed into the four corner columns of the BASE.
//  4 x M3 x 6 mm socket-head cap screws (ISO 4762) through the LID
//      (sp_screw_len = 6.9 mm -> stock M3x6, 4.8 mm thread engagement).
//  Mounting (pick any): M3 or #4 wood screws through the 4 flange holes;
//      zip ties <= 3.6 mm wide x 1.5 mm thick through the flange slots;
//      one mushroom-head suction cup (~30 mm, head <= 7 mm, neck <= 4 mm Ø,
//      neck ~2 mm long) in the floor keyhole.
//  No inserts? -D 'SP_FASTENER="self_tap"' turns the pockets into M3 pilots.
//
// ── Print ────────────────────────────────────────────────────────────────
//  PLA or PETG, 0.2 mm layers, 3+ walls. NO supports needed:
//  - BASE: upright, floor on the bed. Only bridges: wire window (10 mm) and
//    zip-tie bar (4 mm).
//  - LID: printed top-face DOWN (the "lid"/"both" outputs are already
//    flipped); the wordmark is engraved in that face. The screw counterbore
//    steps are 1.4 mm annular overhangs — they print fine.
//
// ── Outputs / variants (-D) ─────────────────────────────────────────────
//  part = "both" (default print plate: base + flipped lid) | "base" | "lid"
//         | "assembled" (preview only) | "none"
//  preset = "narrow_usbc" | "devkitc_v4" | "wide_usbc" | "s3_devkitc1"
//  dupont = true (default, bay for push-on sockets) | false (compact)
//  wire_exit = "usb" (default) | "far" | "both" | "none"
//  mount_tabs / zip_tie / suction / strain_relief = true | false
//  e.g. openscad -D 'part="base"' -D 'preset="s3_devkitc1"' -o base.stl esp32_case.scad
//
//  Outer size (W x L x H, closed; the flanges add 2 x 7 mm to W):
//    narrow_usbc 41.9 x 61.2 x 37.2   (dupont=false: x 23.3)
//    devkitc_v4  44.3 x 63.5 x 37.0   (23.1)
//    wide_usbc   44.4 x 64.2 x 37.2   (23.3)
//    s3_devkitc1 41.8 x 78.4 x 37.0   (23.1)
//
//  Older parameters still work: board_w/board_l/usb_w/usb_h/pcb_thick/wall/
//  lid_lip as before; board_h = tallest part above the PCB (default now 4);
//  tolerance = PCB clearance per side (default now 0.5); zt_width/zt_depth/
//  zt_spacing size the flange zip-tie slots; sc_diameter/sc_depth describe the
//  suction cup (sc_depth = floor thickness at its keyhole). The old S3 advice
//  (board_l=72 usb_w=20) clipped the second plug — use the s3_devkitc1 preset.
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>

// ── Board presets ────────────────────────────────────────────────────────
//  name, board_w, board_l (overall, incl. module overhang), pcb_l,
//  pin_row_spacing, header_pins, header_y0 (header start from USB edge),
//  usb_dx (connector centres from board centre), usb receptacle w/d/h,
//  usb_overhang, usb_w, usb_h (opening), plug_w, plug_h (overmould)
_ESP32_PRESETS = [
    ["narrow_usbc", 25.5,  52.00, 52.00, 22.86, 19, 0.00, [0],
                    8.94, 7.35, 3.3, 1.00, 14.0, 9.0, 13.0, 7.0],
    ["devkitc_v4",  27.94, 54.30, 48.26, 25.40, 19, 0.00, [0],
                    7.5,  5.0,  3.0, 1.00, 13.0, 9.0, 11.5, 7.0],
    ["wide_usbc",   28.0,  55.00, 49.00, 25.40, 19, 0.00, [0],
                    8.94, 7.35, 3.3, 1.00, 14.0, 9.0, 13.0, 7.0],
    ["s3_devkitc1", 25.4,  69.15, 62.87, 22.86, 22, 6.69, [-6.7, 6.7],
                    7.5,  5.0,  3.0, 0.92, 26.0, 9.0, 11.5, 7.0],
];

function _esp32_preset(name, i = 0) =
    i >= len(_ESP32_PRESETS) ? undef :
    _ESP32_PRESETS[i][0] == name ? _ESP32_PRESETS[i] : _esp32_preset(name, i + 1);

// ── Parameters (customize for your board) ──────────────────────────────
preset = "narrow_usbc";   // see the table above
_P = _esp32_preset(preset);
assert(_P != undef, str("esp32_case: unknown preset ", preset));

part = "both";            // both | base | lid | assembled | none

// Board (defaults come from the preset; any -D overrides it)
board_w         = _P[1];  // mm — PCB width
board_l         = _P[2];  // mm — overall length incl. any module/antenna overhang
pcb_l           = _P[3];  // mm — PCB length alone (ribs stay under it)
pin_row_spacing = _P[4];  // mm — centre-to-centre of the two header rows
header_pins     = _P[5];  // pins per row
header_y0       = _P[6];  // mm — header plastic start, from the USB edge
usb_dx          = _P[7];  // mm — USB connector centre(s) from the board centre
usb_conn_w      = _P[8];  // mm — receptacle width
usb_conn_d      = _P[9];  // mm — receptacle depth
usb_conn_h      = _P[10]; // mm — receptacle height above the PCB
usb_overhang    = _P[11]; // mm — receptacle overhang past the PCB edge
usb_w           = _P[12]; // mm — USB opening width (all plugs + overmoulds)
usb_h           = _P[13]; // mm — USB opening height, centred on the plug axis
plug_w          = _P[14]; // mm — cable overmould width  (fit proof / docs)
plug_h          = _P[15]; // mm — cable overmould height (fit proof / docs)
board_h   = 4.0;   // mm — max component height above the PCB (buttons, caps)
pcb_thick = 1.6;   // mm — PCB thickness
module_w  = 18.0;  // mm — WROOM module (ESP32-WROOM-32 / -S3-WROOM-1)
module_l  = 25.5;  // mm
module_h  = 3.3;   // mm — 3.1 nominal + tolerance/solder

// Under-board space
header_below     = 8.6;   // mm — header plastic + pins below the PCB
header_plastic_h = 2.5;   // mm — header spacer height
dupont           = true;  // bay for push-on 2.54 mm sockets on the pins
dupont_len       = 14.5;  // mm — female socket housing length
wire_bay         = 6.0;   // mm — below the sockets to bend the wires

// Enclosure
wall      = 2;     // mm — minimum wall / floor thickness
tolerance = 0.5;   // mm — PCB-to-wall clearance per side
lid_lip   = 1.5;   // mm — alignment lip depth under the lid
lid_t     = 4.4;   // mm — lid plate (fits a recessed M3 cap head)
hold_gap  = 0.3;   // mm — lid pads stop this far above the module / USB
wire_exit     = "usb"; // usb | far | both | none — floor-level wire window
wire_slot_w   = 10;    // mm
wire_slot_h   = 5;     // mm
strain_relief = true;  // zip-tie bar beside each wire window

// External mounting
mount_tabs = true;   // side flanges with 4 x M3 screw holes
tab_w      = 7;      // mm — flange width
tab_t      = 3;      // mm — flange thickness
zip_tie    = true;   // zip-tie slots in the flanges
zt_width   = 4;      // mm — zip tie slot, across the tie width
zt_depth   = 2;      // mm — zip tie slot, across the tie thickness
zt_spacing = 15;     // mm — distance between the paired slots
suction     = true;  // keyhole for one mushroom-head suction cup
sc_diameter = 30;    // mm — suction cup Ø (footprint only, echoed)
sc_depth    = 2;     // mm — floor thickness at the keyhole (cup neck length)
sc_head_d   = 7.0;   // mm — mushroom head Ø
sc_neck_d   = 4.0;   // mm — neck Ø

LID_SCREW = "M3";

// ── Derived dimensions ─────────────────────────────────────────────────
_usb_x  = [for (o = usb_dx) board_w / 2 + o];     // board coords
_usb_cx = (min(_usb_x) + max(_usb_x)) / 2;
_pin_x  = (board_w - pin_row_spacing) / 2;       // pin centre from each long edge

col_r    = sp_insert_boss_d(LID_SCREW) / 2;      // insert column radius
corner_r = max(col_r, sp_screw_head_d(LID_SCREW) / 2 + 1.0, wall);
side_wall = col_r + corner_r;                    // pocket keeps min wall to the cavity
end_wall  = corner_r;

cav_w = board_w + 2 * tolerance;
cav_l = board_l + 2 * tolerance;
cav_x0 = side_wall;
cav_y0 = end_wall;
outer_w = cav_w + 2 * side_wall;
outer_l = cav_l + 2 * end_wall;

floor_t = wall;
under_h = dupont ? header_plastic_h + dupont_len + wire_bay : header_below + 0.5;
z_pcb_bot = floor_t + under_h;
z_pcb_top = z_pcb_bot + pcb_thick;

// Board origin (USB edge, left edge, PCB underside) in case coordinates
bx0 = cav_x0 + tolerance;
by0 = cav_y0 + tolerance;

usb_axis_z  = z_pcb_top + usb_conn_h / 2;
usb_open_z0 = usb_axis_z - usb_h / 2;
usb_open_z1 = usb_axis_z + usb_h / 2;

// Split plane = lid underside: clears board_h + lip, and the USB opening
z_split = max(z_pcb_top + board_h + 0.5 + lid_lip, usb_open_z1);
outer_h = z_split + lid_t;

// Support ribs (between the header rows, under the PCB only)
rib_t   = 2.0;
rib_sep = 11;   // centre-to-centre
rib_y0  = 13;   // board coords — leaves room at the ends for wires
rib_y1  = min(board_l - 13, pcb_l - 2);

// Column / screw centres (the rounded-corner centres)
_cols = [[corner_r, corner_r], [outer_w - corner_r, corner_r],
         [corner_r, outer_l - corner_r], [outer_w - corner_r, outer_l - corner_r]];

// USB opening wider than the board leaves no wall behind the PCB edge
_bear = min(_usb_cx - usb_w / 2, board_w - (_usb_cx + usb_w / 2));
_need_stops = _bear < 2;

_exits = wire_exit == "usb" ? [0] : wire_exit == "far" ? [1]
       : wire_exit == "both" ? [0, 1] : [];

_STOCK = [3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 25, 30];
function _stock_len(l) = max([for (s = _STOCK) if (s <= l + 0.001) s]);
lid_screw_len = _stock_len(sp_screw_len(LID_SCREW, lid_t, true));

assert(_bear >= 2 || header_y0 >= 2,
       "esp32_case: USB opening is as wide as the board and there is no header clearance for end stops");
assert(rib_y1 - rib_y0 >= 10, "esp32_case: board too short for the support ribs");

echo(str("esp32_case ", preset, ": outer ", outer_w, " x ", outer_l, " x ", outer_h,
         " mm (flanges add ", mount_tabs ? 2 * tab_w : 0, " mm width); PCB underside at z=",
         z_pcb_bot, "; lid screws 4 x ", LID_SCREW, " x ", lid_screw_len,
         " into 4 x ", LID_SCREW, " x ", sp_insert_len(LID_SCREW), " inserts",
         suction ? str("; keyhole for one Ø", sc_diameter, " mm suction cup") : ""));

// ── Reusable mounting modules ──────────────────────────────────────────

// Paired zip-tie slots (subtract): tie width along x, thickness along y.
module zip_tie_slot(width = 4, depth = 2, spacing = 15, h = 10) {
    for (y = [-spacing / 2, spacing / 2])
        translate([0, y, 0])
            cube([width, depth, h], center = true);
}

// Keyhole for a mushroom-head suction cup (subtract). Origin = keyhole
// centre on the underside; the cup head goes in the big hole and slides
// toward -y. `depth` = floor thickness left at the slot (neck length).
module suction_cup_mount(diameter = 30, depth = 2) {
    big   = sc_head_d + 0.6;
    slot  = sc_neck_d + 0.4;
    translate([0, 3.5, -1]) cylinder(h = floor_t + 2, d = big, $fn = 40);
    hull() {
        translate([0,  3.5, -1]) cylinder(h = floor_t + 2, d = slot, $fn = 32);
        translate([0, -3.5, -1]) cylinder(h = floor_t + 2, d = slot, $fn = 32);
    }
    if (floor_t > depth + 0.05)
        hull() {
            translate([0,  3.5, depth]) cylinder(h = floor_t, d = sc_head_d + 1, $fn = 40);
            translate([0, -3.5, depth]) cylinder(h = floor_t, d = sc_head_d + 1, $fn = 40);
        }
}

module _outline2d() {
    hull()
        for (p = _cols)
            translate(p) circle(r = corner_r, $fn = 64);
}

module _mount_flanges() {
    r = 2;
    for (s = [0, 1])
        translate([s == 0 ? 0 : outer_w, 0, 0])
            mirror([s, 0, 0])
                linear_extrude(tab_t)
                    hull() {
                        translate([-tab_w + r, corner_r + r]) circle(r = r, $fn = 24);
                        translate([-tab_w + r, outer_l - corner_r - r]) circle(r = r, $fn = 24);
                        translate([-0.01, corner_r]) square([1, outer_l - 2 * corner_r]);
                    }
}

module _flange_cuts() {
    for (x = [-tab_w / 2, outer_w + tab_w / 2]) {
        for (y = [cav_y0 + 8, outer_l - cav_y0 - 8])
            translate([x, y, -1])
                cylinder(h = tab_t + 2, d = sp_screw_clearance_d("M3"), $fn = 24);
        if (zip_tie)
            translate([x, outer_l / 2, tab_t / 2])
                zip_tie_slot(width = zt_width, depth = zt_depth, spacing = zt_spacing,
                             h = tab_t + 2);
    }
}

// ── Base (bottom tub) ──────────────────────────────────────────────────
module _ribs() {
    for (s = [-1, 1])
        translate([outer_w / 2 + s * rib_sep / 2 - rib_t / 2, by0 + rib_y0, floor_t - 0.01])
            cube([rib_t, rib_y1 - rib_y0, z_pcb_bot - floor_t + 0.01]);
}

// Zip-tie bar: a 4 mm arch the tie threads under (along x), cinching the
// wire bundle that runs along the centre line to the window.
module _tie_bar(y0) {
    x0 = outer_w / 2 + 3.0;
    open_h = 2.5;
    for (dy = [0, 5.5])
        translate([x0, y0 + dy, floor_t - 0.01])
            cube([2.5, 1.5, open_h + 1.6 + 0.01]);
    translate([x0, y0, floor_t + open_h])
        cube([2.5, 7.0, 1.6]);
}

// Posts that catch the header ends when the USB opening spans the board.
// They stop 0.8 mm under the PCB: clear of the plug overmould, still 1.7 mm
// of contact with the 2.5 mm header spacer (or the first socket housing).
module _usb_end_stops() {
    ylen = by0 + header_y0 - 0.35 - (cav_y0 - 0.01);
    for (s = [0, 1]) {
        x0 = s == 0 ? cav_x0 - 0.01 : bx0 + board_w - 1.2;
        x1 = s == 0 ? bx0 + 1.2 : cav_x0 + cav_w + 0.01;
        translate([x0, cav_y0 - 0.01, floor_t - 0.01])
            cube([x1 - x0, ylen, z_pcb_bot - 0.8 - floor_t + 0.01]);
    }
}

module _floor_vents() {
    xa = cav_x0 + 1.0;
    xb = outer_w / 2 - rib_sep / 2 - rib_t / 2 - 1.0;
    if (xb - xa > 2)
        for (s = [0, 1], i = [-2 : 2])
            translate([s == 0 ? xa : outer_w - xb, cav_y0 + cav_l / 2 + i * 5 - 1, -1])
                cube([xb - xa, 2, floor_t + 2]);
}

module esp32_case_base() {
    difference() {
        union() {
            linear_extrude(z_split) _outline2d();
            if (mount_tabs) _mount_flanges();
        }

        // Board cavity
        translate([cav_x0, cav_y0, floor_t])
            cube([cav_w, cav_l, z_split]);

        // Heat-set insert pockets, mouths on the split plane
        for (p = _cols)
            translate([p[0], p[1], z_split]) sp_insert_pocket(LID_SCREW);

        // USB opening — open-top notch, the lid closes it
        translate([bx0 + _usb_cx - usb_w / 2, -1, usb_open_z0])
            cube([usb_w, cav_y0 + 1.01, z_split - usb_open_z0 + 1]);

        // Floor-level wire window(s)
        for (e = _exits)
            translate([outer_w / 2 - wire_slot_w / 2,
                       e == 0 ? -1 : outer_l - end_wall - 0.01, floor_t])
                cube([wire_slot_w, end_wall + 1.01, wire_slot_h]);

        _floor_vents();

        if (suction)
            translate([outer_w / 2, cav_y0 + cav_l / 2, 0])
                suction_cup_mount(diameter = sc_diameter, depth = sc_depth);

        if (mount_tabs) _flange_cuts();
    }

    _ribs();
    if (strain_relief)
        for (e = _exits)
            _tie_bar(e == 0 ? by0 + 2.0 : by0 + board_l - 9.0);
    if (_need_stops) _usb_end_stops();
}

// ── Lid (top) — modelled with its underside at z = 0 ───────────────────
module _lid_lip() {
    c = 0.25;   // clearance to the cavity wall
    t = 1.2;
    difference() {
        translate([cav_x0 + c, cav_y0 + c, -lid_lip])
            cube([cav_w - 2 * c, cav_l - 2 * c, lid_lip + 0.01]);
        translate([cav_x0 + c + t, cav_y0 + c + t, -lid_lip - 1])
            cube([cav_w - 2 * (c + t), cav_l - 2 * (c + t), lid_lip + 2]);
        // open behind the USB notch so a flush receptacle's plug clears
        translate([bx0 + _usb_cx - usb_w / 2 - 0.5, cav_y0 - 1, -lid_lip - 1])
            cube([usb_w + 1, c + t + 2, lid_lip + 2]);
    }
}

module _lid_pads() {
    zm = z_pcb_top + module_h + hold_gap - z_split;         // module shield
    translate([outer_w / 2 - 6, by0 + board_l - module_l + 5, zm])
        cube([12, 8, -zm + 0.01]);
    zu = z_pcb_top + usb_conn_h + hold_gap - z_split;       // USB receptacle(s)
    for (ux = _usb_x)
        translate([bx0 + ux - 2.5, by0 + 1.0, zu])
            cube([5, 2.5, -zu + 0.01]);
}

// Fills the notch down to the opening top when board_h pushes the lid up.
module _lid_tongue() {
    th = z_split - usb_open_z1;
    if (th > 0.3)
        translate([bx0 + _usb_cx - usb_w / 2 + 0.2, 0, -th])
            cube([usb_w - 0.4, cav_y0, th + 0.01]);
}

module _lid_vents() {
    yc0 = by0 + board_l - module_l + 1.5;
    for (dx = [-7.5, -3.75, 0, 3.75, 7.5], y = [yc0 : 3.5 : by0 + board_l - 3])
        if (!(abs(dx) < 7.2 && y > by0 + board_l - module_l + 3.9
                            && y < by0 + board_l - module_l + 14.1))
            translate([outer_w / 2 + dx, y, -1])
                cylinder(h = lid_t + 2, d = 2.2, $fn = 16);
}

module esp32_case_lid() {
    difference() {
        union() {
            linear_extrude(lid_t) _outline2d();
            _lid_lip();
            _lid_pads();
            _lid_tongue();
        }
        for (p = _cols)
            translate([p[0], p[1], lid_t])
                sp_screw_clearance(LID_SCREW, thickness = lid_t, counterbore = true);
        _lid_vents();
        // Engraved wordmark on the front strip of the top face
        translate([outer_w / 2, by0 + 12, lid_t - 0.4])
            linear_extrude(0.5)
                text("SporePrint", size = 4, halign = "center", valign = "center",
                     font = "Liberation Sans");
    }
}

// Lid flipped top-face-down for printing, footprint on [0,outer_w]x[0,outer_l].
module esp32_case_lid_print() {
    translate([0, outer_l, lid_t]) rotate([180, 0, 0]) esp32_case_lid();
}

// ── Render ──────────────────────────────────────────────────────────────
if (part == "both") {
    esp32_case_base();
    translate([outer_w + (mount_tabs ? tab_w : 0) + 8, 0, 0])
        esp32_case_lid_print();
} else if (part == "base") {
    esp32_case_base();
} else if (part == "lid") {
    esp32_case_lid_print();
} else if (part == "assembled") {
    esp32_case_base();
    translate([0, 0, z_split]) esp32_case_lid();
}
