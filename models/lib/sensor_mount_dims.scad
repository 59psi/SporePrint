// SporePrint — shared footprint of the climate sensor enclosure
//
// Library file: constants + functions only, NO top-level geometry and NO
// variables that an including model also assigns. Both
//     models/sensor_mount.scad    (the enclosure)
//     models/sensor_bracket.scad  (the shelf bracket it bolts onto)
// pull it in with
//
//     include <lib/sensor_mount_dims.scad>
//
// so each downloads and renders on its own (the Builder download endpoint
// inlines lib/ includes). This replaces the old `use <sensor_mount.scad>` in
// the bracket.
//
// Every footprint function takes the enclosure's tunables as explicit named
// arguments whose defaults are the SM_*_DEFAULT constants below. Those
// defaults MUST equal the literal defaults at the top of sensor_mount.scad:
// the bracket calls the functions with its own copies of the same knobs
// (defaulting to these constants), so a stock enclosure and a stock bracket
// line up, and `-D scd30=true` on both tracks automatically.
//
// ── Board data (sources) ───────────────────────────────────────────────
// Outlines, hole positions and part positions are read from Adafruit's own
// Eagle board files (github.com/adafruit/...), cross-checked against the
// "Product Dimensions" on each adafruit.com product page. Bay size uses the
// larger of the two. Origin = board corner at the JST-header-row edge
// (Eagle y = 0), x along the long axis.
//
//   Adafruit 2857 SHT31-D (STEMMA QT rev, 2021-04+)
//       Adafruit-SHT31-Sensor-Breakout-PCB / "Adafruit SHT31-D STEMMA QT
//       Breakout.brd": 25.40 x 17.78, 4x 2.5 mm plated holes at
//       (2.54, 2.54) (22.86, 2.54) (2.54, 15.24) (22.86, 15.24),
//       JST-SH4 at x = 2.60 / 22.80, y = 8.89 (mating faces 0.51 in from
//       the short edges). The old 18.0 x 12.7 figure on the product page is
//       the pre-2021 board and is NOT what ships.
//   Adafruit 5665 SHT45 / 5776 SHT41 / 4885 SHT40
//       Adafruit-SHT40-PCB "Adafruit SHT41.brd": same 25.40 x 17.78 outline
//       and holes, JST at x = 3.17 / 22.23. Page: 25.5 x 17.7 x 4.8.
//   Adafruit 5190 SCD-41 / 5187 SCD-40
//       Adafruit-SCD-4x-PCB "Adafruit SCD-41.brd": 25.40 x 22.86, 4x 3.0 mm
//       plated holes at (2.54, 2.54) (22.86, 2.54) (2.54, 20.32)
//       (22.86, 20.32), SCD4x body 10.1 x 10.1 x 6.5 (Sensirion datasheet)
//       centred at (12.70, 12.19), JST at x = 2.54 / 22.86, y = 11.43.
//       Page: 25.5 x 22.8 x 7.7.
//   Pimoroni PIM587 SCD41: "approx 24 x 21 x 8" (Pimoroni page), one Qw/ST
//       port, no published hole drawing — rests on the SCD4x posts.
//   Adafruit 4867 SCD-30
//       Adafruit-SCD-30-PCB "Adafruit SCD30.brd": 50.80 x 25.40, 4x 2.5 mm
//       holes at (2.54, 2.54) (48.26, 2.54) (2.54, 22.86) (48.26, 22.86),
//       SCD30 module 35 x 23 x 7 (Sensirion) at x 8.38..43.38,
//       y 1.14..24.14; BOTH JST ports on the x = 0 edge (y = 8.89, 16.51).
//       Page: 51.0 x 25.4 x 8.8.
//   Adafruit 4681 BH1750
//       Adafruit-BH1750-PCB "Adafruit BH1750.brd": 25.40 x 17.78, holes as
//       the SHT boards, BH1750 (WSOF-6, 3.0 x 1.6 x 0.7) centred at
//       (12.70, 8.89), JST at x = 2.54 / 22.86. Page: 25.3 x 17.7 x 4.5.
//   JST SH (STEMMA QT) — JST eSH.pdf: SM04B-SRSS-TB side-entry header
//       6.0 W x 4.25 D x 2.9 H; SHR-04V-S-B plug 7.0 W (with protrusions)
//       x 5.0 L x 2.8 H; mated length 6.25 -> plug body ends ~2.0 mm past
//       the header face, i.e. ~1.5 mm past the board edge.

// ── Enclosure footprint defaults (keep == sensor_mount.scad literals) ──
SM_WALL_DEFAULT      = 2;     // mm — shell / rib thickness
SM_FIT_DEFAULT       = 1.0;   // mm — total board clearance (0.5 per side)
SM_QT_CLEAR_DEFAULT  = 6.0;   // mm — extra room past each short board edge
                              //      for a mated STEMMA QT plug + wire bend
SM_GALLERY_DEFAULT   = 9;     // mm — cable gallery depth (sensor_mount notch_w)
SM_EAR_LEN_DEFAULT   = 12;    // mm — end-ear length
SM_EAR_T_DEFAULT     = 4.5;   // mm — end-ear thickness (M3 counterbore + 1.3)

// ── Fasteners ──────────────────────────────────────────────────────────
SM_PCB_SCREW     = "M2.5";   // board -> post (Adafruit 2.5 / 3.0 mm holes)
SM_LID_SCREW     = "M3";     // lid -> body corner bosses
SM_TIEDOWN_SCREW = "M3";     // enclosure ear -> bracket saddle

SM_PCB_T = 1.6;              // mm — Adafruit breakout PCB thickness

// ── Board records ──────────────────────────────────────────────────────
// [0] L  bay length along X (long axis, QT ports on the short edges)
// [1] D  bay depth along Y
// [2] label engraved on the enclosure front
// [3] mounting-hole centres [[x, y], ...] in board coordinates
// [4] mounting-hole Ø
// [5] light-sensor centre [x, y] (BH1750 only, else undef)
// [6] vendor / SKU note
SM_BOARD_SHT = [25.5, 17.8, "SHT3x/4x",
    [[2.54, 2.54], [22.86, 2.54], [2.54, 15.24], [22.86, 15.24]], 2.5,
    undef, "Adafruit 2857 SHT31-D / 5665 SHT45 / 5776 SHT41 / 4885 SHT40"];
SM_BOARD_SCD4X = [25.5, 22.9, "SCD4x",
    [[2.54, 2.54], [22.86, 2.54], [2.54, 20.32], [22.86, 20.32]], 3.0,
    undef, "Adafruit 5190 SCD-41 / 5187 SCD-40 (Pimoroni PIM587 rests on posts)"];
SM_BOARD_SCD30 = [51.0, 25.4, "SCD30",
    [[2.54, 2.54], [48.26, 2.54], [2.54, 22.86], [48.26, 22.86]], 2.5,
    undef, "Adafruit 4867 SCD-30"];
SM_BOARD_BH1750 = [25.5, 17.8, "BH1750",
    [[2.54, 2.54], [22.86, 2.54], [2.54, 15.24], [22.86, 15.24]], 2.5,
    [12.70, 8.89], "Adafruit 4681 BH1750"];

// Bay table, left to right. First three fields stay [w, d, label] so older
// callers of sm_slots() keep working.
function sm_slots(wide = false) = [
    SM_BOARD_SHT,
    wide ? SM_BOARD_SCD30 : SM_BOARD_SCD4X,
    SM_BOARD_BH1750,
];

// ── Footprint functions ────────────────────────────────────────────────
// Bay i spans [plug zone | board + fit | plug zone] along X.
function sm_bay_w(wide = false, i = 0, fit = SM_FIT_DEFAULT,
                  qt = SM_QT_CLEAR_DEFAULT) =
    sm_slots(wide)[i][0] + fit + 2 * qt;

// Inner left face of bay i (x), shell origin at the outer front-left corner.
function sm_bay_x(wide = false, i = 0, fit = SM_FIT_DEFAULT,
                  wall = SM_WALL_DEFAULT, qt = SM_QT_CLEAR_DEFAULT) =
    i == 0 ? wall
           : sm_bay_x(wide, i - 1, fit, wall, qt)
             + sm_bay_w(wide, i - 1, fit, qt) + wall;

// Depth of the board zone behind the cable gallery (deepest board + fit).
function sm_zone_d(wide = false, fit = SM_FIT_DEFAULT) =
    max([for (s = sm_slots(wide)) s[1]]) + fit;

function sm_outer_w(wide = false, fit = SM_FIT_DEFAULT,
                    wall = SM_WALL_DEFAULT, qt = SM_QT_CLEAR_DEFAULT) =
    let (n = len(sm_slots(wide)))
    sm_bay_x(wide, n - 1, fit, wall, qt) + sm_bay_w(wide, n - 1, fit, qt) + wall;

function sm_outer_l(wide = false, fit = SM_FIT_DEFAULT,
                    wall = SM_WALL_DEFAULT, gallery = SM_GALLERY_DEFAULT) =
    wall + gallery + sm_zone_d(wide, fit) + wall;

function sm_ear_len(ear = SM_EAR_LEN_DEFAULT) = ear;

// Centre-to-centre pitch of the two end-ear tie-down holes.
function sm_ear_hole_pitch(wide = false, fit = SM_FIT_DEFAULT,
                           wall = SM_WALL_DEFAULT, qt = SM_QT_CLEAR_DEFAULT,
                           ear = SM_EAR_LEN_DEFAULT) =
    sm_outer_w(wide, fit, wall, qt) + ear;

// Board-coordinate origin of bay i's board in shell coordinates [x, y].
function sm_board_origin(wide = false, i = 0, fit = SM_FIT_DEFAULT,
                         wall = SM_WALL_DEFAULT, qt = SM_QT_CLEAR_DEFAULT,
                         gallery = SM_GALLERY_DEFAULT) =
    [sm_bay_x(wide, i, fit, wall, qt) + qt + fit / 2,
     wall + gallery + fit / 2];
