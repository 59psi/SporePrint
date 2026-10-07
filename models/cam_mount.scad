// SporePrint Camera Mount — ESP32-CAM (AI-Thinker) seated on its ESP32-CAM-MB
// Closed camera housing (CRADLE + LID, 4 x M3 heat-set inserts) on an
// adjustable-tilt L-bracket ARM (one M5 pivot bolt threading into an M5
// heat-set insert, printed friction washer). Front-facing at substrate level
// or top-down (cam-02) under a shelf; the ARM base takes screws, zip ties or
// a suction cup.
//
// ── Parts it fits (deployed stack, camera looking out of the front plate) ─
//  AI-Thinker ESP32-CAM (ESP32-S, NOT an S3 board) — BOM kit AITRIP
//    B097BLT24K (2 x ESP32-CAM + 2 x ESP32-CAM-MB); HiLetgo/Aideepen clones
//    are the same board.
//    - PCB 27 x 40.5 x 4.5 (+/-0.2) mm: DFRobot DFR0602 datasheet (spec +
//      dimension diagram: header rows 22.86 mm apart, 2.54 mm pitch, pin 1
//      (5V / 3V3) 4.58 mm from the SD-card end, antenna at the other end).
//      Cavity = board + `tolerance` (0.4 mm) per side -> 27.8 x 41.3 mm.
//    - Header pins soldered pointing DOWN into the MB; their tips stick
//      ~2.3 mm out of the camera face along both long edges.
//    - Camera: OV2640 (or OV3660, same form factor) 8.6 mm module on its
//      21 mm FPC, taped on top of the microSD socket at the SD end. Lens
//      centre ~10.5 mm from the SD end, centred across the board (Handsontec
//      MDU1112 datasheet + its to-scale front drawing; VaTTeRGeR CAD says
//      9.5 mm) — hand-taped, so the window allows +/-1.5 mm. Lens top
//      <= 9 mm above the PCB (`cam_h`).
//    - Flash LED (GPIO 4): centre ~30.2 mm from the SD end, ~24.5 mm from the
//      5V edge (three measurements, 29.8-30.8 / 24.4-24.9: DFRobot DFR0602
//      ruler photo, Waveshare front photo). It is only ~2.5 mm from the
//      3V3-side edge, so its window is a 45 deg cone that also notches the
//      front edge of that side wall (see "How it goes together").
//  ESP32-CAM-MB (CH340 USB-serial / power board, micro-USB; USB-C MBs fit):
//    - PCB 27 x 39.8-40.5 x 1.6 mm (cults3d "Enclosure for ESP32-CAM+MB"
//      notes: 39.8 x 27; Cirkit Designer: 27 x 40.5). Its female headers sit
//      at the far end, so it overhangs the ESP32-CAM's antenna end by
//      0-3.5 mm (AITRIP / Waveshare / RNT product photos); the USB receptacle
//      overhangs the MB edge <= 1 mm. The cavity takes up to 44.5 mm from
//      the ESP32-CAM SD edge to the USB mouth (`mb_l`/`mb_shift`).
//    - IO0 and RST are SIDE-actuated SMD tact switches on the MB component
//      face, ~6-8.5 mm from the USB end; their plungers stick out ~1-1.25 mm
//      past BOTH long MB edges (VaTTeRGeR/ESP32-CAM-Enclosure FreeCAD model
//      Pad005: 2.5 x 29.5 x 3 mm; RNT ESP32-CAM-MB close-up photos). Both
//      long walls have a slot for them (`mb_btn_*`), which also lets you press
//      IO0/RST with a paperclip with the lid on.
//    - Boards 12.5 mm apart bottom-to-bottom = 11 mm header gap (2.5 mm male
//      spacer + 8.5 mm female header), THT stubs 3 mm under the MB (cults3d
//      notes; VaTTeRGeR FreeCAD model).
//    - USB cable plug overmould up to 13 x 8 mm: the end wall has a
//      15 x 9.5 mm notch (>= 1.0 / 0.75 mm per side) centred on the
//      receptacle, open to the rim so the stack drops straight in.
//  Whole stack: ~26 mm from lens top to MB stubs; housing 31.2 mm deep.
//
// ── How it goes together ────────────────────────────────────────────────
//  The stack drops camera-first into the CRADLE. The ESP32-CAM face rests
//  (0.1 mm float) on two corner pads at the SD end and a ledge across the
//  antenna end — the only component-free areas of that face — and a
//  shoulder stops it sliding toward the USB end. Two pads on the LID stop
//  0.4 mm short of the MB underside (the MB's only underside parts are THT
//  stubs and USB tabs, kept clear). If your stack rattles, stick a 1 mm
//  foam dot on each lid pad.
//  Openings: lens window 13.3 mm (auto, `lens_size`; 45 deg flare, 13.4 mm
//  body relief behind it); flash LED: a 45 deg cone, 15.4 mm across at the
//  plate's inner face, which also bites a 45 deg notch (~5 mm tall) out of
//  the front edge of the 3V3-side wall and the foot of the antenna-end
//  ledge, so the LED lights >= 40 deg off-axis in every direction (the
//  first design's 6 mm hole passed only ~19-34 deg); microSD card slot in
//  the SD-end wall (`sd_slot`); IO0 / RST slots in both long walls
//  (~13 x 9 mm, open to the rim, closed by the lid); USB notch in the end
//  wall; two lid vents.
//
// ── Buy (per mount) ─────────────────────────────────────────────────────
//  Heat-set inserts (brass, knurled; ruthex / CNC Kitchen sizes):
//    4 x M3 x 5.7 mm — in the 4 CRADLE corner columns (lid screws).
//    1 x M5 x 9.5 mm — in the CRADLE side pivot boss (pivot bolt).
//        (-D pivot_d=4: 1 x M4 x 8.1 insert instead; pivot_d=3: M3 x 5.7.)
//  Screws (ISO 4762 socket head):
//    4 x M3 x 6 mm  through the LID counterbores
//        (sp_screw_len = 6.5 -> stock M3x6, 5.2 mm of the 5.7 mm insert).
//    1 x M5 x 16 mm through the ARM hub + washer into the pivot insert
//        (sp_screw_len = 16.0 -> M5x16, full 9.5 mm engagement). With
//        pivot_d=4 buy 1 x M4 x 16 (full 8.1 mm), with pivot_d=3 1 x M3 x 16
//        (full 5.7 mm) — the hub counterbore deepens to suit. Add a drop of
//        blue (medium) threadlocker or a nylon washer under the head so
//        swinging the camera doesn't back the bolt out; tighten until the
//        camera holds its aim — that sets the friction.
//  Mounting (pick one): 2 x M3 or #6 flat-head screws (3.4 mm holes,
//    90 deg countersinks, >= 12 mm long into wood/plugs); or 2 x zip ties
//    <= 2.5 mm wide x <= 1.3 mm thick through the base tunnels; or one
//    ~30 mm mushroom-head suction cup (head <= 7.5 mm, neck <= 4.3 mm,
//    neck >= 2 mm long) in the base keyhole (an M4-stud cup + nut also fits
//    the 4.5 mm slot).
//  No inserts? -D 'SP_FASTENER="self_tap"' turns every pocket into a pilot
//    hole for a self-tapping screw of the same size.
//
// ── Print (PLA or PETG, 0.2 mm layers, 3+ walls) — NO supports ──────────
//  CRADLE: front plate down (as rendered). Only bridges: the 6.4 mm
//    horizontal M5 insert pocket and the 12.5 mm SD slot; the pivot boss is
//    a flat-bottomed "tombstone" that stands on the bed; the lens flare and
//    the flash cone / wall notch are 45 deg roofs. The IO0/RST slots and
//    the USB notch are open to the rim (nothing to bridge).
//  LID: printed outer face DOWN (already flipped in "all"/"lid"); the M3
//    counterbore steps are 1.4 mm annular overhangs — they print fine; the
//    counterbores keep a >= 1.2 mm wall all round.
//  ARM: tab lying flat, pivot face on the bed (smooth friction face), the
//    base plate standing up. Pivot hole + counterbore are vertical; the base
//    holes are horizontal (3.4 mm screw holes, 1.5 mm-wide tie tunnels, a
//    teardrop keyhole) and need nothing.
//  WASHER: print 2 (one spare), flat.
//  The SporePrint wordmark is engraved in the cradle's 3V3-side wall.
//
// ── Mounting ────────────────────────────────────────────────────────────
//  At tilt 0 the camera looks straight away from whatever the ARM base is
//  fixed to; the pivot tilts it +/-180 deg about the housing's short axis.
//  Top-down (cam-02): base under the shelf above the substrate (screws or
//    zip ties round a wire shelf), camera looking down, 15-30 cm away.
//  Front-facing: base on a post / wall / glass door (suction cup), camera
//    looking across at the substrate, tilted slightly up to catch pinning.
//  Swing: the housing stays within 34.2 mm of the pivot axis, the USB plug
//    (13 x 8 overmould + strain relief, 30 mm past the receptacle mouth,
//    `usb_plug_len`) within 53.0 mm. So the default arm_length = 60 lets the
//    camera turn a full circle with the cable plugged in; arm_length 35-53
//    still clears the housing but the plug meets the wall/shelf when the
//    USB end swings toward it (~255-285 deg). Keep the cable slack.
//  The 5V-side IO0/RST slot is partly behind the arm tab at tilt 0 on the
//    shortest MBs — reach it at an angle or swing the camera.
//
// ── Outputs / variants (-D) ─────────────────────────────────────────────
//  part = "all" (default print plate: cradle + flipped lid + arm + 2
//         washers) | "cradle" | "lid" | "arm" | "washer" | "assembled"
//         (preview, not for printing) | "none"
//  arm_length = 60   pivot height above the mounting face (see Swing).
//  arm_angle  = 0    "assembled" preview only: tilt of the camera.
//  pivot_d    = 5    pivot bolt/insert size: 5 (M5), 4 (M4) or 3 (M3).
//  pivot_screw_l = 16  stock pivot bolt length the hub is sized for.
//  cam_h      = 9    lens top above the ESP32-CAM PCB; taller aftermarket
//                    lenses (e.g. long 160 deg barrels) -> raise it.
//  cradle_h   = 0    0 = auto (fits the stack); any other value must be >=.
//  lens_size  = 0    0 = auto; any other value must be >= the assert's minimum.
//  flash_d    = 0    0 = auto 45 deg cone from the LED; else the window Ø at
//                    the plate's inner face (still a 45 deg flare).
//  tolerance  = 0.4  board clearance per side.
//  mb_l / mb_shift / usb_protrude — MB length, its inset from the SD end,
//                    receptacle overhang (defaults take the longest MB).
//  mb_end_min / mb_btn_out / mb_btn_y0 / mb_btn_y1 / mb_btn_h — MB button
//                    slot coverage (defaults cover every MB 39.8-43.5 long
//                    from the SD end, switches 1.5-9.5 mm from the USB end).
//  usb_x_off  = 0    if your MB's USB is off-centre.
//  sd_slot = true, lid_vents = true — set false to close them.
//  SP_FASTENER = "self_tap" / SP_INSERT_HOLE_TWEAK = -0.1 (lib/sp_inserts)
//  e.g. openscad -D 'part="cradle"' -o cam_cradle.stl cam_mount.scad
//  Compatibility: the pre-v5 defaults cradle_h = 15 and lens_size = 10 are
//  rejected ON PURPOSE by assertions (15 mm cannot hold the ESP32-CAM + MB
//  stack, a 10 mm window clips the hand-placed lens); drop those -D's.
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>

// ── Output ─────────────────────────────────────────────────────
part       = "all";   // all | cradle | lid | arm | washer | assembled | none
arm_angle  = 0;       // deg — camera tilt in the "assembled" preview

// ── ESP32-CAM (board coords: camera side toward you, SD end up;
//    x from the 5V-pin long edge, y from the SD-card end) ─────────
cam_w      = 27;     // mm — ESP32-CAM PCB width
cam_l      = 40.5;   // mm — ESP32-CAM PCB length (DFR0602: 40.5 +/-0.2)
cam_h      = 9.0;    // mm — lens top above the ESP32-CAM PCB camera face
cam_pcb_t  = 1.2;    // mm — ESP32-CAM PCB thickness (1.0-1.6 fit; at 1.6 the lid pads just touch)
cam_body   = 8.6;    // mm — square camera module
cam_lens_d = 7.5;    // mm — lens barrel diameter
cam_place  = 1.5;    // mm — hand-taped camera placement tolerance (each way)
cam_body_h = 6.5;    // mm — top of the square module above the PCB (SD socket + tape + holder)
lens_x     = 13.5;   // mm — lens centre from the 5V-side edge
lens_y     = 10.5;   // mm — lens centre from the SD-card end
flash_x    = 24.5;   // mm — flash LED centre from the 5V-side edge (measured 24.4-24.9)
flash_y    = 30.2;   // mm — flash LED centre from the SD-card end (measured 29.8-30.8)
led_h      = 1.6;    // mm — flash LED height above the PCB face
sd_h       = 2.0;    // mm — microSD socket height on the camera face

// ── ESP32-CAM-MB below it ──────────────────────────────────────
hdr_gap      = 11.0; // mm — ESP32-CAM back face to MB component face
mb_pcb_t     = 1.6;  // mm — MB PCB thickness
mb_l         = 40.5; // mm — MB PCB length (39.8-40.5 in the wild)
mb_shift     = 3.0;  // mm — MB far edge inset from the ESP32-CAM SD end
usb_protrude = 1.0;  // mm — USB receptacle overhang past the MB edge
usb_zc       = 1.5;  // mm — USB receptacle centre, from the MB component face toward the camera
usb_x_off    = 0;    // mm — USB centre offset from the board centreline
mb_under     = 3.5;  // mm — THT stubs under the MB (3.0) + clearance
// IO0 / RST are SIDE-actuated SMD tact switches on the MB component face
// near the USB end; their plungers stick out past BOTH long MB edges.
mb_btn_out   = 1.5;  // mm — plunger overhang past each long MB edge (VaTTeRGeR CAD 1.25)
mb_btn_y0    = -9.5; // mm — switch zone start, from the MB USB-end edge (CAD -8.5, photo ~-9)
mb_btn_y1    = -1.5; // mm — switch zone end,   from the MB USB-end edge (CAD -6.0; margin for other MBs)
mb_btn_h     = 3.5;  // mm — switch height off the MB component face (CAD 3.0)
mb_end_min   = 39.8; // mm — shortest MB USB-end position from the ESP32-CAM SD end
                     //      (39.8 mm MB mounted flush); the side slots cover it up to mb_shift + mb_l

// ── Housing ────────────────────────────────────────────────────
wall       = 2;      // mm — side/end wall thickness
front_t    = 2.4;    // mm — front plate thickness
lid_t      = 4;      // mm — lid thickness (flush M3 counterbores)
tolerance  = 0.4;    // mm — board clearance per side
cradle_h   = 0;      // mm — cradle height incl. front plate; 0 = auto
lens_size  = 0;      // mm — lens window Ø at the plate's inner face; 0 = auto (13.3 at
                     //      tolerance 0.4); an explicit value must pass the assert below
lens_protrude = 1.5; // mm — lens top may sit this far inside the front window
lens_relief   = 1.0; // mm — depth of the camera-body relief behind the window
flash_d    = 0;      // mm — flash window Ø at the plate's inner face; 0 = auto: a 45 deg
                     //      cone from the LED (also notches the near side wall's front edge)
flash_r0   = 1.0 + 2 * tolerance; // mm — auto cone radius at the LED top (LED position spread + float)
usb_w      = 15;     // mm — USB plug notch width  (13 mm overmould + 1.0/side)
usb_h      = 9.5;    // mm — USB plug notch height (8 mm overmould + 0.75/side)
usb_plug_len = 30;   // mm — plug overmould + strain relief past the receptacle mouth
                     //      (only used for the swing-radius echo / arm_length advice)
sd_slot    = true;   // microSD access slot in the SD-end wall
sd_slot_w  = 12.5;   // mm
lid_vents  = true;   // two vent slots in the lid
stop_gap   = 0.1;    // mm — front stops below the ESP32-CAM face (float)
pad_gap    = 0.4;    // mm — lid pads short of the MB underside (float)
lid_pad    = 5;      // mm — lid pad size
min_wall   = 1.2;    // mm — thinnest printed wall around a counterbore
wm_size    = 4;      // mm — wordmark height
wm_depth   = 0.5;    // mm — wordmark engrave depth

// ── Pivot + arm ────────────────────────────────────────────────
pivot_d       = 5;   // mm — pivot bolt (5 = M5 insert + M5x16; 4/3 also valid)
pivot_screw_l = 16;  // mm — stock pivot bolt length the hub is sized for
washer_t      = 1.5; // mm — friction washer thickness
washer_d      = 14;  // mm — friction washer OD
arm_length    = 60;  // mm — pivot axis height above the mounting face
arm_width     = 20;  // mm — tab + base width
arm_t         = 5;   // mm — tab thickness
hub_d         = 16;  // mm — pivot hub on the tab
gusset        = 8;   // mm — tab-to-base gusset leg
gusset_w      = 5;   // mm
base_len      = 58;  // mm — mounting base length
base_t        = 5;   // mm — mounting base thickness
screw_d       = 3;   // mm — wall screws (M3 / #6)

// Zip tie parameters (tunnels through the base, across its width)
zt_width   = 3;      // mm — tunnel width  (tie width + clearance)
zt_depth   = 1.5;    // mm — tunnel height (tie thickness + clearance)
zt_spacing = 15;     // mm — distance between the two tunnels

// Suction cup parameters (keyhole in the base)
sc_diameter = 30;    // mm — suction cup diameter (sets the keyhole position)
sc_depth    = 2;     // mm — keyhole lip = cup neck length it grips
sc_head_d   = 8;     // mm — keyhole head hole (cup head <= 7.5)
sc_neck_w   = 4.5;   // mm — keyhole slot (cup neck / M4 stud)
sc_slot_len = 6;     // mm — slot travel from the head hole toward the tab

// ── Derived ────────────────────────────────────────────────────
psize = pivot_d == 3 ? "M3" : pivot_d == 4 ? "M4" : pivot_d == 5 ? "M5" : undef;
assert(psize != undef, "pivot_d must be 3, 4 or 5 (matching heat-set insert)");
LID_SIZE = "M3";

pocket_w     = cam_w + 2 * tolerance;                  // 27.8
cam_pocket_l = cam_l + 2 * tolerance;                  // 41.3 — shoulder here
usb_mouth_y  = mb_shift + mb_l + usb_protrude;         // board y of the USB mouth
pocket_l     = max(cam_pocket_l, usb_mouth_y + 2 * tolerance);   // 45.3

front_gap = cam_h - lens_protrude;                     // front plate -> PCB face
assert(front_gap >= cam_body_h + 0.5,
       str("cam_h=", cam_h, " leaves < 0.5 mm over the camera body; raise cam_h"));
// window must pass the barrel wherever the tape (+/-cam_place in x AND y)
// and the board float (+/-tolerance in x AND y) put it — diagonal worst case
lens_min = cam_lens_d + 2 * ((cam_place + tolerance) * sqrt(2) + 0.2);
lens_win = lens_size > 0 ? lens_size : ceil(lens_min * 10) / 10;
assert(lens_win >= lens_min - 0.001,
       str("lens_size=", lens_size, " too small for a ", cam_lens_d, " mm barrel placed +/-", cam_place,
           "; need >= ", lens_min));
lens_relief_w = cam_body + 2 * (cam_place + tolerance) + 1.0;   // 13.4 — body relief behind the window

z_cam_top  = front_t + front_gap;      // ESP32-CAM camera face
z_cam_back = z_cam_top + cam_pcb_t;    // ESP32-CAM back face
z_mb_top   = z_cam_back + hdr_gap;     // MB component face
z_mb_back  = z_mb_top + mb_pcb_t;      // MB underside
rim_auto   = z_mb_back + mb_under;
rim_h      = cradle_h == 0 ? rim_auto : cradle_h;
assert(rim_h >= rim_auto - 0.001,
       str("cradle_h=", cradle_h, " is too short for the ESP32-CAM + MB stack; need >= ", rim_auto));
housing_h  = rim_h + lid_t;

// ESP32-CAM corner (5V side, SD end) in the pocket, nominal
bx0 = tolerance;
by0 = tolerance;
lens_cx  = bx0 + lens_x;
lens_cy  = by0 + lens_y;
flash_cx = bx0 + flash_x;
flash_cy = by0 + flash_y;
// Flash window: one 45 deg cone (widening toward the outer face) whose
// diameter at the plate's inner face is flash_ap. Auto = a cone from the LED
// top with radius flash_r0 there, so the LED sees >= 40 deg off-axis
// everywhere; the side wall 3 mm away gets a 45 deg notch at its front edge.
z_led     = z_cam_top - led_h;
flash_ap  = flash_d > 0 ? flash_d : 2 * (flash_r0 + z_led - front_t);
flash_d0  = flash_ap + 2 * front_t;                       // at the outer face
flash_d1  = max(0.2, flash_ap - 2 * (z_led - front_t));   // at the LED top
flash_hc  = (flash_d0 - flash_d1) / 2;                    // cone height (45 deg)
usb_cx   = bx0 + cam_w / 2 + usb_x_off;
usb_cz   = z_mb_top - usb_zc;

// Front stops (only the component-free areas of the camera face)
pad_w    = 3.4;                          // SD-end corner pads, across
pad_l    = 3.2;                          // SD-end corner pads, along
ledge_y0 = 2 * tolerance + cam_l - 4.5;  // antenna-end ledge start: board y >= 36 even floated fully toward the USB end
shoulder_h = 2.0;                        // shoulder above the ESP32-CAM back face
lid_pad_y  = [10, 30];                   // lid pads, board y (MB underside)

// Lid screw columns: diagonal off each pocket corner, clear of the cavity.
// Sized for >= min_wall around the lid counterbore (the insert pocket then
// has more than the library's 1.6 mm wall).
col_d   = max(sp_insert_boss_d(LID_SIZE), sp_screw_head_d(LID_SIZE) + 2 * min_wall);
col_off = (col_d / 2 + 0.6) / sqrt(2);
col_pts = [[-col_off, -col_off], [pocket_w + col_off, -col_off],
           [-col_off, pocket_l + col_off], [pocket_w + col_off, pocket_l + col_off]];

cradle_outer_w = pocket_w + 2 * wall;
cradle_outer_l = pocket_l + 2 * wall;

// Pivot boss on the 5V-side wall, M5 insert pocket axis along x
pivot_boss_d = max(washer_d, sp_insert_boss_d(psize));
pivot_boss_p = sp_insert_boss_h(psize) - wall;          // protrusion past the wall
pivot_face_x = -wall - pivot_boss_p;                    // insert mouth / washer face
pivot_y      = pocket_l / 2;
pivot_z      = housing_h / 2;
washer_id    = sp_screw_clearance_d(psize) + 0.3;
under_head   = pivot_screw_l - sp_insert_len(psize) - washer_t;
hub_t        = sp_screw_head_h(psize) + under_head;     // tab + hub at the pivot
assert(under_head >= 2 && hub_t >= arm_t,
       "pivot_screw_l too short for the tab + washer + insert");

// MB button slots: through BOTH long walls, open to the rim (the stack drops
// in past them, the lid closes the top). They cover the switch zone of every
// MB from mb_end_min to mb_shift + mb_l, plus the stack float + 0.3 mm.
btn_slot_y0 = by0 + mb_end_min + mb_btn_y0 - tolerance - 0.3;
btn_slot_y1 = by0 + mb_shift + mb_l + mb_btn_y1 + tolerance + 0.3;
btn_slot_z0 = z_mb_top - mb_btn_h - tolerance;
// (the MB edge floats 0..2*tolerance off the pocket wall, so a plunger
// reaches at most mb_btn_out into the slot — keep it inside the wall)
assert(mb_btn_out <= wall - 0.3,
       str("mb_btn_out=", mb_btn_out, " pokes out of the ", wall, " mm side wall; raise wall"));
// the 5V-side slot must not cut into the pivot boss
_boss_r   = pivot_boss_d / 2;
_boss_dz  = btn_slot_z0 - pivot_z;
_boss_ymax = pivot_y + (_boss_dz >= _boss_r ? -1e3 : _boss_dz > 0 ? sqrt(_boss_r * _boss_r - _boss_dz * _boss_dz) : _boss_r);
assert(btn_slot_y0 >= _boss_ymax + 0.2,
       str("MB button slot (y ", btn_slot_y0, ") runs into the pivot boss (y ", _boss_ymax, ")"));
// ... nor into the lid-screw columns at the USB end
assert(btn_slot_y1 <= pocket_l + col_off - col_d / 2 - 0.5,
       "MB button slot runs into the USB-end lid-screw columns");
// swing radius about the pivot (informational): housing corners, and a
// USB plug (13 x 8 overmould) reaching usb_plug_len past the receptacle mouth
_swing_house = max([for (y = [-col_off - col_d / 2, pocket_l + col_off + col_d / 2])
                    for (z = [0, housing_h]) norm([y - pivot_y, z - pivot_z])]);
_swing_plug  = max([for (z = [usb_cz - 4, usb_cz + 4])
                    norm([by0 + usb_mouth_y + usb_plug_len - pivot_y, z - pivot_z])]);

// Arm base layout (distances from the tab's pivot face, along the base)
zip_a   = arm_t + 5;
scr1    = arm_t + gusset + 5.5;
scr2    = base_len - 5;
key_x   = base_len - sc_diameter / 2 - 2;

lid_screw_l   = sp_screw_len(LID_SIZE, lid_t, true);
pivot_screw_c = sp_screw_len(psize, hub_t + washer_t, true);
echo(str("cam_mount: stack depth ", rim_h, " mm + lid ", lid_t, " = ", housing_h,
         " mm; lid screws 4x ", LID_SIZE, " (sp_screw_len ", lid_screw_l, ") into 4x ",
         LID_SIZE, "x", sp_insert_len(LID_SIZE), " inserts; pivot 1x ", psize, "x",
         pivot_screw_l, " (sp_screw_len ", pivot_screw_c, ") into 1x ", psize, "x",
         sp_insert_len(psize), " insert"));
echo(str("cam_mount: MB button slots y ", btn_slot_y0, "..", btn_slot_y1, " z ", btn_slot_z0,
         "..rim; flash window ", flash_ap, " mm at the plate (", flash_d0, " outside); swing radius housing ",
         _swing_house, " / with USB plug ", _swing_plug, " vs arm_length ", arm_length));

// ── Reusable mounting modules (cutters) ────────────────────────

// Two parallel zip-tie tunnels, centred on the origin, running along y.
module zip_tie_slot(width = 3, depth = 1.5, spacing = 15, length = 22) {
    for (x = [-spacing / 2, spacing / 2])
        translate([x, 0, 0])
            cube([width, length, depth], center = true);
}

// 2D teardrop (tip toward -x) so a horizontal hole prints without support.
module teardrop2d(d) {
    hull() {
        circle(d = d, $fn = 40);
        translate([-d / 2 * sqrt(2), 0]) square(0.01, center = true);
    }
}

// Keyhole for a mushroom-head suction cup, cutting a plate that spans
// z = 0 (mounting face) .. h. Head hole at the origin, neck slot toward +x,
// head channel above a `lip`-thick lip.
module suction_cup_keyhole(head_d = 8, neck_w = 4.5, lip = 2, slot = 6, h = 5) {
    translate([0, 0, -0.01]) linear_extrude(h + 0.02) teardrop2d(head_d);
    translate([0, 0, -0.01]) linear_extrude(h + 0.02)
        hull() { circle(d = neck_w, $fn = 32); translate([slot, 0]) circle(d = neck_w, $fn = 32); }
    translate([0, 0, lip]) linear_extrude(h)
        hull() { circle(d = head_d, $fn = 40); translate([slot, 0]) circle(d = head_d, $fn = 40); }
}

// Countersunk wall-screw hole through a plate z = 0 .. h (head on the z = h side).
module wall_screw_hole(h = 5) {
    hole = screw_d + 0.4;
    cs_d = 2 * screw_d + 1;
    translate([0, 0, -0.01]) cylinder(h = h + 0.02, d = hole, $fn = 24);
    translate([0, 0, h - (cs_d - hole) / 2]) cylinder(h = (cs_d - hole) / 2 + 0.01, d1 = hole, d2 = cs_d, $fn = 32);
}

// ── Camera cradle (front tray) — assembled frame = print frame ─
//  Pocket x 0..pocket_w, y 0..pocket_l (SD end at y = 0), front plate
//  outer face at z = 0, lid on top at z = rim_h.
module lid_outline() {
    union() {
        translate([-wall, -wall]) square([cradle_outer_w, cradle_outer_l]);
        for (p = col_pts) translate(p) circle(d = col_d, $fn = 64);
    }
}

module pivot_boss() {
    // tombstone: round at the pivot, flat down to the bed -> support-free
    translate([-wall + 0.01, pivot_y, 0])
        rotate([0, -90, 0])
            linear_extrude(pivot_boss_p + 0.01)
                hull() {
                    translate([pivot_z, 0]) circle(d = pivot_boss_d, $fn = 48);
                    translate([0, -pivot_boss_d / 2]) square([0.01, pivot_boss_d]);
                }
}

// Flash LED window: one 45 deg cone from the LED out through the plate, the
// front edge of the near (3V3) side wall and the foot of the antenna-end
// ledge. Every cut face is a 45 deg roof, so it prints without support; the
// ledge keeps its full top face (the cone is below z_led there).
module flash_cutter() {
    intersection() {
        translate([flash_cx, flash_cy, -0.01])
            cylinder(h = flash_hc + 0.01, d1 = flash_d0 + 0.02, d2 = flash_d1, $fn = 64);
        translate([-wall - 1, 0, -1]) cube([pocket_w + 2 * wall + 2, pocket_l, z_cam_top - stop_gap - 0.5 + 1]);
    }
}

module front_stops() {
    difference() {
        front_stop_blocks();
        flash_cutter();
    }
}

module front_stop_blocks() {
    top = z_cam_top - stop_gap;
    // SD-end corner pads (outside the SD socket and pin 1)
    for (x = [0, pocket_w - pad_w])
        translate([x, 0, front_t - 0.01])
            cube([pad_w, pad_l, top - front_t + 0.01]);
    // antenna-end ledge (blank "ESP32-CAM" strip), full width
    translate([0, ledge_y0, front_t - 0.01])
        cube([pocket_w, cam_pocket_l - ledge_y0 + 0.01, top - front_t + 0.01]);
    // shoulder: stops the ESP32-CAM sliding toward the USB end; stays
    // below the MB overhang and the USB plug
    if (pocket_l > cam_pocket_l)
        translate([0, cam_pocket_l, front_t - 0.01])
            cube([pocket_w, pocket_l - cam_pocket_l + 0.01,
                  z_cam_back + shoulder_h - front_t + 0.01]);
}

module cam_cradle() {
    difference() {
        union() {
            translate([-wall, -wall, 0])
                cube([cradle_outer_w, cradle_outer_l, rim_h]);
            for (p = col_pts)
                translate([p[0], p[1], 0]) cylinder(h = rim_h, d = col_d, $fn = 64);
            pivot_boss();
        }

        // board pocket
        translate([0, 0, front_t]) cube([pocket_w, pocket_l, rim_h]);

        // lens window: cylinder + 45 deg outward flare, body relief behind
        translate([lens_cx, lens_cy, -0.01])
            cylinder(h = front_t + 0.02, d = lens_win, $fn = 64);
        translate([lens_cx, lens_cy, -0.01])
            cylinder(h = front_t - lens_relief + 0.01,
                     d1 = lens_win + 2 * (front_t - lens_relief), d2 = lens_win, $fn = 64);
        translate([lens_cx - lens_relief_w / 2, lens_cy - lens_relief_w / 2, front_t - lens_relief])
            cube([lens_relief_w, lens_relief_w, lens_relief + 0.01]);

        flash_cutter();

        // MB IO0 / RST button slots through both long walls, open to the rim
        for (x = [-wall - 0.01, pocket_w - 0.01])
            translate([x, btn_slot_y0, btn_slot_z0])
                cube([wall + 0.02, btn_slot_y1 - btn_slot_y0, rim_h]);

        // microSD access slot (card mouth is at the SD-end edge)
        if (sd_slot)
            translate([bx0 + cam_w / 2 - sd_slot_w / 2, -wall - 1, z_cam_top - sd_h - 0.2])
                cube([sd_slot_w, wall + 2, sd_h + 0.4]);

        // USB plug notch, open to the rim (lid closes the top)
        translate([usb_cx - usb_w / 2, pocket_l - 1, usb_cz - usb_h / 2])
            cube([usb_w, wall + 2, rim_h]);

        // lid-screw insert pockets (mouth at the rim)
        for (p = col_pts)
            translate([p[0], p[1], rim_h]) sp_insert_pocket(LID_SIZE);

        // pivot insert pocket (mouth on the boss face, into the boss)
        translate([pivot_face_x, pivot_y, pivot_z])
            rotate([0, -90, 0]) sp_insert_pocket(psize);

        // wordmark, engraved in the 3V3-side wall
        translate([pocket_w + wall - wm_depth, pocket_l / 2, rim_h / 2])
            rotate([90, 0, 90])
                linear_extrude(wm_depth + 1)
                    text("SporePrint", size = wm_size, halign = "center",
                         valign = "center", font = "Liberation Sans");
    }
    front_stops();
}

// ── Lid — assembled frame (inner face on the rim) ──────────────
module cam_lid() {
    difference() {
        union() {
            translate([0, 0, rim_h]) linear_extrude(lid_t) lid_outline();
            // pads that stop just short of the MB underside
            for (y = lid_pad_y)
                translate([bx0 + cam_w / 2 - lid_pad / 2, by0 + y - lid_pad / 2, z_mb_back + pad_gap])
                    cube([lid_pad, lid_pad, rim_h - z_mb_back - pad_gap + 0.01]);
        }
        for (p = col_pts)
            translate([p[0], p[1], rim_h + lid_t])
                sp_screw_clearance(LID_SIZE, lid_t, true);
        if (lid_vents)
            for (x = [bx0 + 5.5, bx0 + cam_w - 5.5])
                translate([x - 1, by0 + 8, rim_h - 0.01])
                    cube([2, 28, lid_t + 0.02]);
    }
}

// Lid on the bed, outer face down.
module lid_print() {
    translate([0, pocket_l, rim_h + lid_t]) rotate([180, 0, 0]) cam_lid();
}

// ── Friction washer (print 2) ──────────────────────────────────
module friction_washer() {
    difference() {
        cylinder(h = washer_t, d = washer_d, $fn = 48);
        translate([0, 0, -0.5]) cylinder(h = washer_t + 1, d = washer_id, $fn = 32);
    }
}

module washer_assembled() {
    translate([pivot_face_x, pivot_y, pivot_z]) rotate([0, -90, 0]) friction_washer();
}

// ── Mounting arm (L-bracket) — arm frame ───────────────────────
//  Tab pivot face at x = 0 (the camera hangs on the +x side), pivot axis
//  along x at (y 0, z arm_length). Base plate z = 0 (mounting face) ..
//  base_t, running from the tab toward -x.
module mount_arm() {
    difference() {
        union() {
            // tab with a rounded pivot end
            hull() {
                translate([-arm_t, -arm_width / 2, 0]) cube([arm_t, arm_width, 0.01]);
                translate([-arm_t, 0, arm_length])
                    rotate([0, 90, 0]) cylinder(h = arm_t, d = arm_width, $fn = 64);
            }
            // hub around the pivot (takes the counterbored bolt head)
            translate([-arm_t + 0.01, 0, arm_length])
                rotate([0, -90, 0]) cylinder(h = hub_t - arm_t + 0.01, d = hub_d, $fn = 64);
            // mounting base
            translate([-base_len, -arm_width / 2, 0]) cube([base_len, arm_width, base_t]);
            // gusset
            translate([0, gusset_w / 2, 0])
                rotate([90, 0, 0])
                    linear_extrude(gusset_w)
                        polygon([[-arm_t + 0.01, base_t - 0.01],
                                 [-arm_t - gusset, base_t - 0.01],
                                 [-arm_t + 0.01, base_t + gusset]]);
        }
        // pivot: M5 clearance + socket-head counterbore from the hub face
        translate([-hub_t, 0, arm_length])
            rotate([0, -90, 0]) sp_screw_clearance(psize, hub_t, true);
        // zip-tie tunnels across the base
        translate([-(zip_a + zt_spacing / 2), 0, base_t / 2])
            zip_tie_slot(width = zt_width, depth = zt_depth, spacing = zt_spacing,
                         length = arm_width + 2);
        // wall screws (countersunk from the tab side of the base)
        for (x = [scr1, scr2])
            translate([-x, 0, 0]) wall_screw_hole(base_t);
        // suction-cup keyhole, slot toward the tab
        translate([-key_x, 0, 0])
            suction_cup_keyhole(head_d = sc_head_d, neck_w = sc_neck_w, lip = sc_depth,
                                slot = sc_slot_len, h = base_t);
    }
}

// Arm on the bed: tab flat (pivot face down), base standing up.
module arm_print() { rotate([0, 90, 0]) mount_arm(); }

// Arm in the assembled position; angle tilts the camera about the pivot.
// At 0 the base is behind the lid, camera looking away from the mount.
module arm_assembled(angle = 0) {
    translate([pivot_face_x - washer_t, pivot_y, pivot_z])
        rotate([angle, 0, 0])
            rotate([180, 0, 0])
                translate([0, 0, -arm_length]) mount_arm();
}

// ── Render ─────────────────────────────────────────────────────
if (part == "all") {
    cam_cradle();
    translate([50, 0, 0]) lid_print();
    translate([95, 10, 0]) arm_print();
    translate([115, 40, 0]) friction_washer();
    translate([135, 40, 0]) friction_washer();
} else if (part == "cradle") {
    cam_cradle();
} else if (part == "lid") {
    lid_print();
} else if (part == "arm") {
    arm_print();
} else if (part == "washer") {
    friction_washer();
} else if (part == "assembled") {
    cam_cradle();
    cam_lid();
    washer_assembled();
    arm_assembled(arm_angle);
}
