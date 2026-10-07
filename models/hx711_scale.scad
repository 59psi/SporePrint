// SporePrint Load-Cell Scale (HX711 + 5 kg straight-bar load cell)
// Two-part harvest scale for the Tier 3 "HX711 + 5kg Load Cell" BOM line.
// Classic single-point sandwich: the load cell's FIXED (wire) end bolts down
// onto a riser on the BASE, its FREE end carries the PLATFORM, and the grow
// block sits on the platform. The two printed pieces touch ONLY through the
// load cell (that is the load path the cell measures), so they are joined by
// the cell's own threaded holes, never to each other. weight_g rides in
// relay-node telemetry once tared + calibrated.
//
// ── Fits (select with -D cell="..." and -D hx_board="...") ─────────────────
//   LOAD CELL
//   cell="bar75" (DEFAULT, BOM pick) — Adafruit 4541 "Strain Gauge Load Cell
//       - 5Kg" and the generic Amazon "HX711 + 5 kg" kit bars. Source:
//       Adafruit drawing C14641+C14642+C14643 (cdn-shop.adafruit.com/
//       product-files/4541/): 75.0 x 12.7 x 12.7 mm, 4 x M4 THREADED holes,
//       spacing 10 / 44 / 10 mm -> holes 5.5 and 15.5 mm from EACH end.
//       4 x Ø0.8 x 200 mm wires leave a potting blob on one SIDE face
//       (~15-30 mm from the wire end, ~2 mm proud) and run along that face
//       past the wire end. Gauge potting is ~2 mm proud of the top and bottom
//       faces over the flexure. The wire end is the FIXED end (M4 x 25).
//   cell="tal220" — HTC Sensor TAL220 80 mm bar, as in existing builds:
//       SparkFun SEN-13329 (10 kg) and Amazon "YZC-133" 80 mm kits
//       (B0CRCY863F). Source: HTC TAL220 datasheet (cdn.sparkfun.com/
//       datasheets/Sensors/ForceFlex/TAL220M4M5Update.pdf): 80 x 12.7 x
//       12.7 mm, 2 x M5 at the wire (FIXED) end, 2 x M4 at the force (FREE)
//       end, holes 5 and 20 mm from each end; wires exit the fixed end face.
//   NOT SUPPORTED: SparkFun SEN-14729 (TAL220B, 55 mm long, ONE M5 per end).
//       (The previous header wrongly called the 80 mm bar a SEN-14729.)
//
//   HX711 BOARD (one bay fits all three outlines; the preset picks the mounts)
//   hx_board="ada5974" (DEFAULT, BOM pick) — Adafruit 5974 "HX711 24-bit
//       ADC". Source: Adafruit Eagle board file (github.com/adafruit/
//       Adafruit-HX711-24-bit-ADC-PCB) + product page: 25.4 x 22.86 mm PCB
//       (listed 25.5 x 23.0 x 12.1 mm), 4 x Ø2.5 plated holes 2.54 mm in from
//       each edge (20.32 x 17.78 pitch), PRE-SOLDERED 6-pos 2.54 mm terminal
//       block along one long edge (10.5 mm above the PCB, wire entries facing
//       the edge), 6-pin 0.1" header row along the other long edge. Terminal
//       block faces the bar. Held by 2 x M2.5 screws into inserts on the
//       header-row holes + 2 Ø1.8 locating pegs (0.3 mm/side in the ~Ø2.4
//       plated hole) on collars at the terminal-block holes (its pads sit
//       2.9 mm from those holes and its body 0.3 mm from where a screw head
//       would go, so those two holes take pegs, not screws).
//   hx_board="sfe13879" — SparkFun SEN-13879 HX711 breakout. Source: SparkFun
//       Eagle board file (github.com/sparkfun/HX711-Load-Cell-Amplifier):
//       30.48 x 22.86 mm, 4 x Ø3.3 holes 2.54 mm in (25.4 x 17.78 pitch),
//       5-pin 0.1" rows on both short edges. 4 x M3 screws into inserts.
//   hx_board="generic" — generic green HX711 module, outline -D gen_L x
//       gen_W (default 35 x 21), 6 + 4 pin rows on the short edges, no
//       standard hole pattern. Sits on a plinth inside 4 corner locators
//       (built around gen_L x gen_W), held by double-sided foam tape (~1 mm).
//       Fit-proven sizes: 33.5 x 20.3 (otronic.nl) to 35 x 21 (tinytronics.nl,
//       probots ~34 x 21) with the defaults (a smaller board has ≤1.5 mm of
//       slop, the tape holds it); Amowell "big" 38 x 21 with -D gen_L=38 (the
//       bay grows); Amowell "small" 24.3 x 16 with -D gen_L=24.3 -D gen_W=16
//       (outline only: its pin rows are ASSUMED on the short edges like the
//       big boards — check yours).
//   (The previous header's "38 x 22 mm, Soldered 333005" outline was wrong;
//   the old 22.8 mm-wide pocket fitted none of these boards.)
//   Board posts: the PCB sits hx_stand (3.5 mm) above the bay floor so
//   clipped through-hole leads (≤2 mm) clear it. The top hx_relief (2.5 mm)
//   of each screw post is a collar relieved 0.6 mm around every nearby
//   through-hole pad, with any sliver thinner than 0.8 mm removed. The
//   heat-set insert sits BELOW that zone (mouth 2.9 mm under the PCB), with
//   the full library minimum wall all round, and goes in through a Ø5.2
//   access bore in the collar: 0.3 mm a side over the Ø4.6 knurl of the
//   ruthex RX-M2.5x5.7 / RX-M3x5.7 and CNC Kitchen M2.5x4 / M3x5.7 inserts
//   (vendor tables, d1 / D1 = 4.6 for all four; the 4 mm CNC Kitchen M2.5
//   leaves 4.0 mm engaged on a x 10 screw). The post grows with the
//   bore (Ø7.4: a 1.1 mm collar ring round the bore), so -D hx_access_fit
//   never thins the collar away. A screw-tip hole (M2.5 Ø2.9 / M3 Ø3.4
//   clearance) continues below each pocket down to 1 mm above the bed, so
//   x 10 and x 12 board screws both fit.
//
//   Wiring: load-cell wires -> the HX711 E+/E-/A-/A+ terminals; HX711 DOUT ->
//   relay-node GPIO 32, SCK -> GPIO 33, VIN/VCC -> 3V3, GND -> GND. SOLDER the
//   relay-node wires into the header pads. Adafruit only: a straight header
//   soldered pointing UP also fits (not with Dupont housings on it — they do
//   not fit under the platform). SparkFun / generic: wires only, no header.
//   Load-cell wires enter the bay through the front notch (bar side); the
//   relay-node cable (≤Ø5) leaves through the back notch and is zip-tied to
//   the anchor behind the bay so it cannot tug on the board or the platform.
//
// ── Assembly ────────────────────────────────────────────────────────────────
//   1. Press the inserts. Platform: 4 x M4 into the boss tips, flush.
//      Base (board posts): drop each insert (small end down) down the
//      collar's Ø5.2 access bore onto the pocket's chamfer and press it in
//      until its top is level with the bottom of the bore, 2.9 mm below the
//      post top. Use a narrow M2.5 / M3 insert tip (the stepped CNC Kitchen /
//      ruthex tips reach down the bore); ≤1 mm deeper is harmless.
//   2. Bar: WIRE end on the base riser, the arrow on the bar pointing DOWN.
//      Bolt it from under the base (washers under the heads).
//   3. Board on its posts/pegs (terminal block toward the bar), wire it, tie
//      the cable down. Nothing but the bar may touch the platform.
//   4. Thread the 4 M4 x 8 set screws into the boss tips until flush
//      (retracted; the 9.1 mm pocket lets them sink up to 1.1 mm deeper).
//   5. Platform onto the bar's free end, 2 x M4 x 16 + washers from the top.
//   6. Set the overload stops (below), then tare + calibrate in firmware.
//   Size: base 76 x 91 mm (tal220: 76 x 96), 19 mm tall at the riser;
//   platform 92 x 107 mm (tal220: 92 x 112); weighing surface 40.7 mm up.
//   The 4 platform bosses are overload STOPS, not legs: they hang 3 mm
//   above the base.
//
// ── Overload stop ───────────────────────────────────────────────────────────
//   Four M4 set screws in heat-set inserts at the tips of the platform's
//   corner bosses. Set them once: put ~110 % of the cell's rating on the
//   platform centre (5.5 kg for a 5 kg cell, 11 kg for SEN-13329 10 kg),
//   reach each screw with a 2 mm hex key through the access hole in the
//   platform top, turn it DOWN (clockwise) until it just touches the base,
//   remove the weight. Shock loads then land on the base, not the cell.
//   (No weight handy: unloaded, slip a 0.5 mm shim — 5 sheets of printer
//   paper — under each screw, turn it down onto the shim, pull the shim.)
//   With the screws backed off, the boss tips still stop the platform at
//   stop_gap_nom (3 mm) above the base. (The previous version's "stop" was
//   the bar's free end hitting the base after 9 mm — far past the few tenths
//   of a mm at which these cells are overloaded, so it protected nothing.)
//
// ── Hardware to buy (defaults; exact values are echoed at render time) ──────
//   Load cell, fixed end (bolted up from under the base, into the cell):
//     bar75 : 2 x M4 x 25 socket-head cap screw (ISO 4762) + 2 x M4 washer
//             (DIN 125 / ISO 7089, Ø9 x 0.8)  -> 10.4 mm thread engagement
//     tal220: 2 x M5 x 25 SHCS + 2 x M5 washer (Ø10 x 1.0) -> 11.4 mm engaged
//   Load cell, free end (down through the platform, into the cell), both:
//             2 x M4 x 16 SHCS + 2 x M4 washer (Ø9 x 0.8)  -> 11.4 mm engaged
//     (bolts never reach the far face of the 12.7 mm bar; use the washers,
//     they spread the clamp load so PLA does not creep; snug, ~0.8 N·m)
//     (washers need the default m4_head_d / m5_head_d counterbores; a
//     smaller value, e.g. the old 8.0 / 9.5, or -D lc_washers=false, drops
//     them: bare heads, same bolt lengths — the echo says which)
//   Overload stops (platform): 4 x M4 heat-set insert, 8.1 mm long (ruthex
//     RX-M4x8.1 / CNC Kitchen M4x8.1) + 4 x M4 x 8 set screw (ISO 4026
//     flat point or ISO 4029 cup point). Retracted it sits flush inside the
//     9.1 mm pocket; extended the full 3 mm it still has 5 mm of thread in
//     the insert. Lock it with a nylon-patch set screw or a drop of medium
//     threadlocker on the thread (keep threadlocker off the plastic).
//   HX711 board (base; insert mouth 2.9 mm below the PCB, see "Board posts"):
//     ada5974 : 2 x M2.5 insert, 5.7 mm (RX-M2.5x5.7) + 2 x M2.5 x 10 SHCS
//               (5.5 mm of the 5.7 mm insert engaged). x 12 also fits (its
//               tip runs 1.8 mm past the insert into the tip hole); x 8
//               engages only 3.5 mm (< 1.5 d): do not use it.
//     sfe13879: 4 x M3 insert, 5.7 mm (RX-M3x5.7)     + 4 x M3 x 10 SHCS
//               (5.5 mm engaged; x 12 also fits; x 8 is too short)
//     (the echo gives the exact range for non-default stacks)
//     generic : no inserts; ~20 x 12 mm double-sided foam tape (≈1 mm)
//   Cable: 1 zip tie ≤3.6 mm wide through the anchor behind the bay
//     (tunnel 4.8 x 2.4 mm under a 1.8 mm roof, 2 mm legs).
//   Optional: 4 adhesive rubber bumpers, Ø ≤ foot_w, in the underside rings.
//
// ── Printing (PLA or PETG, 0.2 mm layers, flat on the bed, NO SUPPORTS) ─────
//   part="all" lays both pieces out for one bed (base left, platform right).
//   BASE prints as rendered: flat underside on the bed. The fixed-end bolt
//     counterbores open on the bed face; their ceilings print over two
//     0.2 mm sacrificial bridge layers (built into the geometry), so no
//     supports. Insert pockets and their access bores open upward; the
//     zip-tie tunnel is a 4.8 mm bridge.
//   PLATFORM prints weighing-face DOWN (as rendered by part="platform"):
//     rim, ribs, pedestal and stop bosses all grow straight up; its bolt
//     counterbores use the same bridge layers; stop-insert pockets open at
//     the boss tips (upward). Flip it over for use.
//   Strength: the riser (base) and pedestal (platform) carry the whole load
//     through bolt clamping. Use 5 walls and ≥40 % infill, or a modifier
//     with 100 % infill over the riser / pedestal. 3 walls minimum.
//   Heat-set inserts: iron ~230 °C (PLA) / ~245 °C (PETG); stop inserts
//     flush with the boss tips, board inserts 2.9 mm down (assembly step 1).
//
// ── Presets / overrides (-D) ────────────────────────────────────────────────
//   -D cell="bar75"          default: Adafruit 4541 / generic 75 mm kit bar
//   -D cell="tal220"         80 mm TAL220 / SEN-13329 / YZC-133 (M5 fixed end)
//   -D hx_board="ada5974"    default: Adafruit 5974, 2 x M2.5 inserts + pegs
//   -D hx_board="sfe13879"   SparkFun SEN-13879, 4 x M3 inserts
//   -D hx_board="generic"    generic green module, plinth + tape
//   -D gen_L=35 -D gen_W=21  generic module outline (the bay grows past 35 x 23)
//   -D part="all"|"base"|"platform"|"assembly"   (assembly = preview only)
//   -D hx_stand=3.5          board height above the bay floor (min 2.5: the
//                            under-board lead stubs need it)
//   -D plat_margin=8         platform overhang past the base on every side
//   -D stop_gap_nom=3        boss-tip gap above the base (set screws refine)
//   -D stop_screw_len=8      stop set-screw length (≤ 9.1: must retract flush)
//   -D lc_washers=false      bare bolt heads, no DIN 125 washers
//   -D SP_FASTENER="self_tap"  pilot holes instead of insert pockets (board
//                            posts take self-tappers; tap the stop holes M4)
//   -D SP_INSERT_HOLE_TWEAK=-0.1  tighten / loosen every insert pocket
//   -D hx_access_fit=0.6     access-bore Ø over the board insert's knurl OD
//                            (the post grows with it; raise it for a
//                            fatter clone insert)
//   Every dimension below can be overridden the same way. Asserts stop the
//   render on impossible combinations, notably: foot_h + base_th + hx_floor
//   ≥ 7.1 mm (the recessed board inserts need the slab; the old foot_h=0
//   now needs -D base_th=7.1), and the bay's tallest part (10.6 mm above the
//   PCB) must clear the platform ribs by 0.5 mm at the full stop_gap_nom
//   drop (3.0 mm to spare by default: hx_floor + hx_stand ≤ 6, or raise
//   riser_h / lower stop_gap_nom to match).
//
// ── Changes from the previous version (all old parameters still exist) ──────
//   * Base: was a plate bridging ~60 x 76 mm between 6 mm corner feet (not
//     printable without supports) -> now a solid slab printed flat; foot_h is
//     the under-plate layer holding the bolt heads, foot_w the bumper rings.
//   * Platform covers the whole base (+plat_margin on all 4 sides), ribbed,
//     with the overload-stop bosses. Its bolt counterbores used to open at the
//     pedestal/bar interface; they now open on the weighing surface.
//   * Bolt lengths were wrong (M5 x 12 into a 9 mm riser engaged 3 mm) ->
//     computed from the stack, washers added. m4_head_d / m5_head_d are still
//     the counterbore Ø; the defaults (9.6 / 10.6) now take a washer, and a
//     value too small for the washer (the old 8.0 / 9.5) drops the washer.
//   * lc_* / riser_len follow the cell preset; hx_w / hx_l are the board zone
//     that fits every supported board; hx_floor (0) is an optional raised bay
//     floor; tol (0.5) is the riser/pedestal inset from the bar's sides.
//
// github.com/sporeprint — open-source mushroom cultivation platform

include <lib/sp_inserts.scad>

// ── Presets ────────────────────────────────────────────────────
cell     = "bar75";    // "bar75" | "tal220"
hx_board = "ada5974";  // "ada5974" | "sfe13879" | "generic"
part     = "all";      // "all" | "base" | "platform" | "assembly"

// ── Load-cell parameters (preset-derived; override any with -D) ─
lc_len        = cell == "tal220" ? 80 : 75;   // mm — bar length
lc_w          = 12.7;                         // mm — bar width
lc_h          = 12.7;                         // mm — bar height
lc_hole_end   = cell == "tal220" ? 5 : 5.5;   // mm — outer hole, from each end
lc_hole_pitch = cell == "tal220" ? 15 : 10;   // mm — outer -> inner hole
lc_fix_size   = cell == "tal220" ? "M5" : "M4";  // thread at the fixed (wire) end
lc_load_size  = "M4";                            // thread at the free (force) end
m5_clear      = 5.5;   // mm — clearance hole, M5 bolt shank
m4_clear      = 4.5;   // mm — clearance hole, M4 bolt shank
m5_head_d     = 10.6;  // mm — counterbore Ø: M5 SHCS (Ø8.5) on a Ø10 washer
m4_head_d     = 9.6;   // mm — counterbore Ø: M4 SHCS (Ø7.0) on a Ø9 washer
lc_washers    = true;  // DIN 125 washers under the cell-bolt heads; dropped
                       //   automatically where the counterbore is < washer Ø + 0.3
cb_recess     = 0.4;   // mm — bolt heads sit this far below the outer face

// ── Build parameters ───────────────────────────────────────────
wall         = 2.5;   // mm — base margin outside the HX711 bay
base_th      = 4;     // mm — base plate thickness (above the head zone)
foot_h       = 6;     // mm — solid under-plate layer holding the bolt heads
foot_w       = 10;    // mm — Ø of the 4 rubber-bumper locator rings (0 = none)
riser_h      = 9;     // mm — fixed-end riser = clearance under the bar
riser_len    = cell == "tal220" ? 26 : 21;  // mm — riser/pedestal length along
                      //   the bar: covers both holes, stops short of the flexure
plat_th      = 3;     // mm — platform plate thickness
plat_ped_h   = 6;     // mm — pedestal: plate underside -> top of the bar
plat_margin  = 8;     // mm — platform overhang past the base, every side
side_margin  = 6;     // mm — gap between the bar and the HX711 bay
end_margin   = 8;     // mm — base margin past each end of the bar
tol          = 0.5;   // mm — riser/pedestal inset from the bar's side faces

// Platform stiffening (hangs under the plate in use; up as printed)
rib_h        = plat_ped_h;  // mm — rim/rib depth below the plate
rib_t        = 2.4;   // mm — rim/rib thickness
rib_off      = 5;     // mm — flank ribs' gap to the bar's side faces

// Overload stops (platform corner bosses + M4 set screws)
stop_size    = "M4";
stop_inset   = 7;     // mm — stop axis inset from the base edges
stop_gap_nom = 3;     // mm — boss tip above the base top (screws retracted)
stop_screw_len = 8;   // mm — M4 set screw (≤ pocket depth 9.1 so it retracts flush)
stop_key_d   = 3.0;   // mm — hex-key access bore (2 mm key for M4 set screw)
lc_side_env  = 2.5;   // mm — potting blob / wires proud of the bar's side

// ── HX711 bay parameters ───────────────────────────────────────
gen_L        = 35.0;  // mm — generic module length (hx_board="generic")
gen_W        = 21.0;  // mm — generic module width
hx_w         = hx_board == "generic" ? max(23.0, gen_W) : 23.0;  // mm — board zone
                      //   width  (widest board: Adafruit 23.0)
hx_l         = hx_board == "generic" ? max(35.0, gen_L) : 35.0;  // mm — board zone
                      //   length (longest: generic 35.0)
hx_fit       = 1.0;   // mm — total fit clearance on the board zone
hx_wall      = 2;     // mm — bay wall thickness
hx_floor     = 0;     // mm — raised bay floor pad (0 = the base plate)
hx_stand     = 3.5;   // mm — post height: bay floor -> underside of the PCB
hx_relief    = 2.5;   // mm — post-top relief depth under nearby THT pads
hx_relief_gap = 0.6;  // mm — relief clearance around each pad's copper
hx_min_feat  = 0.8;   // mm — relieved collars keep no sliver thinner than this
hx_insert_sink = 0.4; // mm — full-boss band between the relief zone and the
                      //   board insert's mouth (2 layers)
hx_access_fit = 0.6;  // mm — access bore Ø over the board insert's knurl OD
                      //   (0.3 mm a side: printed holes run ~0.1 mm small)
hx_collar_wall = 1.1; // mm — collar ring left round the access bore (the
                      //   screw post is sized from the bore, not the library
                      //   minimum boss, so a wider bore never eats the collar)
hx_tip_floor = 1.0;   // mm — screw-tip hole below each board pocket stops this
                      //   far above the bed (lets x 12 board screws in)
peg_d        = 1.8;   // mm — Adafruit locating peg (Ø2.5 plated hole ≈ Ø2.4)
anchor_tun_w = 4.8;   // mm — zip-tie tunnel width  (ties ≤3.6 mm wide)
anchor_tun_h = 2.4;   // mm — zip-tie tunnel height
anchor_leg   = 2.0;   // mm — anchor legs either side of the tunnel
anchor_gap   = 3;     // mm — anchor to the bay's back wall (cable ramp)
hx_gut_cell  = 7;     // mm — gutter on the bar side (terminal-block wires)
hx_gut_out   = 4;     // mm — gutter on the outer side (header wires)
hx_gut_end   = 5;     // mm — gutter at each short end (header rows)
wire_ch      = 5;     // mm — load-cell wire notch width
cable_d      = 5;     // mm — relay-node cable OD (notch = cable_d + 1)
tape_th      = 1.0;   // mm — foam tape under a "generic" board
hx_top_env   = 10.6;  // mm — tallest envelope above the PCB (Ada terminal
                      //   block; also wires up to header height, any board)
pcb_th       = 1.6;   // mm — HX711 PCB thickness

// ── Derived: vertical stack (assembled, z = 0 on the table) ────
base_top = foot_h + base_th;          // top face of the base plate
z_cb     = base_top + riser_h;        // underside of the bar
z_ct     = z_cb + lc_h;               // top of the bar
z_pb     = z_ct + plat_ped_h;         // platform plate underside
z_ptop   = z_pb + plat_th;            // weighing surface
z_tip    = base_top + stop_gap_nom;   // stop-boss tips
z_pcb    = base_top + hx_floor + hx_stand;  // HX711 PCB underside

// ── Derived: plan layout (bar runs along +Y, fixed end at low Y) ─
stop_r   = sp_insert_boss_d(stop_size) / 2;
cell_x   = max(side_margin, stop_inset + stop_r + lc_side_env + 1.5);
cell_cx  = cell_x + lc_w / 2;
cell_y0  = end_margin;                         // fixed end face
cell_y1  = end_margin + lc_len;                // free end face
base_l   = lc_len + end_margin * 2;

bay_in_w = hx_gut_cell + hx_w + hx_fit + hx_gut_out;   // X
bay_in_l = hx_gut_end * 2 + hx_l + hx_fit;             // Y
bay_out_w = bay_in_w + hx_wall * 2;
bay_out_l = bay_in_l + hx_wall * 2;
bay_x    = cell_x + lc_w + side_margin;
base_w   = bay_x + bay_out_w + wall;
// Bay centred in Y between the front and back stop landings
stop_ys  = [stop_inset, base_l - stop_inset];
stop_xs  = [stop_inset, base_w - stop_inset];
bay_free0 = stop_inset + stop_r + 1;
bay_free1 = base_l - stop_inset - stop_r - 1;
bay_y    = (bay_free0 + bay_free1) / 2 - bay_out_l / 2;
bay_wall_top = z_pcb + pcb_th + 2;
// Board zone centre (boards: long axis along +Y, short axis along X)
hx_cx    = bay_x + hx_wall + hx_gut_cell + (hx_w + hx_fit) / 2;
hx_cy    = bay_y + hx_wall + hx_gut_end + (hx_l + hx_fit) / 2;
lc_notch_x = bay_x + hx_wall + 1;                          // wire notch, front wall
esp_notch_x = bay_x + hx_wall + bay_in_w * 0.55;           // cable notch, back wall
anchor_w = 6;                                         // along X (tie direction)
anchor_l = anchor_tun_w + 2 * anchor_leg;              // along Y (cable direction)
anchor_h = anchor_tun_h + 1.8;                         // roof 1.8 mm over the tunnel
anchor_c = [esp_notch_x + (cable_d + 1) / 2, bay_y + bay_out_l + anchor_gap + anchor_l / 2];

// Hole Y positions along the bar
function fix_ys()  = [cell_y0 + lc_hole_end, cell_y0 + lc_hole_end + lc_hole_pitch];
function load_ys() = [cell_y1 - lc_hole_end - lc_hole_pitch, cell_y1 - lc_hole_end];

// Platform footprint: the whole base plus plat_margin on every side
plat_w   = base_w + plat_margin * 2;
plat_l   = base_l + plat_margin * 2;
ped_y0   = cell_y1 - riser_len;        // pedestal spans ped_y0 .. cell_y1 + 2
ped_x0   = cell_x - 3;
ped_w    = lc_w + 6;

// ── Bolts into the load cell ───────────────────────────────────
lc_stock = [8, 10, 12, 16, 20, 25, 30, 35, 40];
function lc_nom(s)       = s == "M5" ? 5 : 4;
function lc_clear_d(s)   = s == "M5" ? m5_clear : m4_clear;
function lc_cb_d(s)      = s == "M5" ? m5_head_d : m4_head_d;
function lc_head_d(s)    = s == "M5" ? 8.5 : 7.0;   // ISO 4762 dk
function lc_head_h(s)    = s == "M5" ? 5 : 4;       // ISO 4762 k
function lc_washer_d(s)  = s == "M5" ? 10 : 9;      // DIN 125-A
// Washer only where the counterbore takes it (else a bare head on plastic;
// the grip, and so the bolt length, is the same either way).
function lc_washer_on(s) = lc_washers && lc_cb_d(s) >= lc_washer_d(s) + 0.3;
function lc_washer_th(s) = lc_washer_on(s) ? (s == "M5" ? 1.0 : 0.8) : 0;
function lc_cb_depth(s)  = cb_recess + lc_head_h(s) + lc_washer_th(s);
// Grip = under-head face -> bar face (washer + plastic).
function lc_grip(s, stack) = stack - cb_recess - lc_head_h(s);
// Longest stock length that stays 0.5 mm short of the bar's far face.
function lc_pick_len(s, stack) =
    max([for (L = lc_stock) if (L - lc_grip(s, stack) <= lc_h - 0.5) L]);
function lc_engage(s, stack, L) = L - lc_grip(s, stack);

fix_stack  = foot_h + base_th + riser_h;
load_stack = plat_th + plat_ped_h;
fix_len    = lc_pick_len(lc_fix_size, fix_stack);
load_len   = lc_pick_len(lc_load_size, load_stack);
fix_eng    = lc_engage(lc_fix_size, fix_stack, fix_len);
load_eng   = lc_engage(lc_load_size, load_stack, load_len);

// ── HX711 board data (board-local: u = long axis, v = short axis) ─
// Pads: [u, v, du, dv] copper extents of through-hole pads that can carry
// lead stubs / solder under the board. Holes: [u, v, "screw" | "peg"].
function _row(u0, v0, du, dv, n, p, alongv) =
    [for (k = [0 : n - 1]) alongv ? [u0, v0 + k * p, du, dv] : [u0 + k * p, v0, du, dv]];
function hx_L() = hx_board == "sfe13879" ? 30.48 : hx_board == "generic" ? gen_L : 25.4;
function hx_W() = hx_board == "sfe13879" ? 22.86 : hx_board == "generic" ? gen_W : 22.86;
function hx_screw() = hx_board == "sfe13879" ? "M3" : "M2.5";
function hx_hole_d() = hx_board == "sfe13879" ? 3.3 : 2.5;
function hx_holes() =
    hx_board == "sfe13879" ? [[2.54, 2.54, "screw"], [27.94, 2.54, "screw"],
                              [2.54, 20.32, "screw"], [27.94, 20.32, "screw"]]
  : hx_board == "generic"  ? []
  :                          [[2.54, 2.54, "screw"], [22.86, 2.54, "screw"],
                              [2.54, 20.32, "peg"],  [22.86, 20.32, "peg"]];
function hx_pads() =
    hx_board == "sfe13879" ? concat(_row(1.27, 6.35, 1.88, 1.88, 5, 2.54, true),
                                    _row(29.21, 6.35, 1.88, 1.88, 5, 2.54, true),
                                    _row(21.59, 8.89, 1.88, 1.88, 2, 2.54, true))
  : hx_board == "generic"  ? concat(_row(1.3, gen_W / 2 - 6.35, 1.8, 1.8, 6, 2.54, true),
                                    _row(gen_L - 1.3, gen_W / 2 - 3.81, 1.8, 1.8, 4, 2.54, true))
  :                          concat(_row(6.35, 2.54, 1.78, 1.78, 6, 2.54, false),     // JP1
                                    _row(6.35, 19.431, 1.8, 3.4, 6, 2.54, false));   // TB
peg_collar_d = 4.4;   // mm — Adafruit peg collar (clears the TB pads by ≥0.7)

// Board inserts: pocket mouth BELOW the relieved collar, so the insert keeps
// the library's full minimum wall; the collar only carries an access bore.
hx_ins_mouth = z_pcb - hx_relief - hx_insert_sink;     // assembled z of the mouth
// Knurl OD (d1 / D1) of the specified inserts. Vendor tables: ruthex
// RX-M2.5x5.7 and RX-M3x5.7 d1 = 4.6; CNC Kitchen M2.5x4 and M3x5.7 D1 = 4.6.
function hx_insert_od(s) = s == "M3" ? 4.6 : s == "M2.5" ? 4.6 : sp_insert_hole_d(s) + 0.6;
// Insert access bore. The post is sized from it in BOTH fastener modes, so
// the part outline never changes with SP_FASTENER (library convention).
function hx_ins_access_d() = hx_insert_od(hx_screw()) + hx_access_fit;
function hx_access_d() = SP_FASTENER == "self_tap" ? sp_screw_clearance_d(hx_screw())
                                                   : hx_ins_access_d();
function hx_post_d() = max(sp_insert_boss_d(hx_screw()), hx_ins_access_d() + 2 * hx_collar_wall);
// Board screws: SHCS head on the PCB, through the PCB + access bore, into
// the insert. Longest stock length that stays inside the insert.
hx_stock   = [4, 5, 6, 8, 10, 12, 16, 20];
hx_grip    = pcb_th + (z_pcb - hx_ins_mouth);
hx_scr_len = max([for (L = hx_stock)
                  if (L <= sp_screw_len(hx_screw(), hx_grip, false) + 0.001) L]);
hx_scr_eng = hx_scr_len - hx_grip;
// Screw-tip hole: clearance Ø (pilot Ø in self_tap mode) from the pocket
// floor down to hx_tip_floor (none when the pocket floor is already that low).
hx_pocket_floor = hx_ins_mouth - sp_insert_depth(hx_screw());
hx_tip_bot = min(hx_tip_floor, hx_pocket_floor);
// Range of stock lengths that work: ≥ 1.5 d engaged, tip ≥ 0.5 mm above
// the bottom of the tip hole.
hx_scr_d   = hx_screw() == "M3" ? 3 : 2.5;
hx_scr_min = min([for (L = hx_stock) if (L - hx_grip >= 1.5 * hx_scr_d - 0.001) L]);
hx_scr_max = max([for (L = hx_stock) if (L - hx_grip <= hx_ins_mouth - hx_tip_bot - 0.5 + 0.001) L]);

// Board-local -> assembled: u along +Y, v along -X, centred on the zone.
module at_board(z = z_pcb) {
    translate([hx_cx, hx_cy, z]) rotate([0, 0, 90])
        translate([-hx_L() / 2, -hx_W() / 2, 0]) children();
}

// ── Sanity checks ──────────────────────────────────────────────
assert(cell == "bar75" || cell == "tal220", str("unknown cell preset: ", cell));
assert(hx_board == "ada5974" || hx_board == "sfe13879" || hx_board == "generic",
       str("unknown hx_board preset: ", hx_board));
assert(hx_stand >= 2.5, "hx_stand must be >= 2.5 mm: THT lead stubs hang ~2 mm under the HX711");
assert(hx_L() <= hx_l + 0.01 && hx_W() <= hx_w + 0.01, "hx_board larger than the bay zone");
assert(fix_eng >= 1.5 * lc_nom(lc_fix_size), "fixed-end bolt engagement too short");
assert(load_eng >= 1.5 * lc_nom(lc_load_size), "free-end bolt engagement too short");
assert(bay_y + bay_out_l <= bay_free1 + 0.01, "base too short for the HX711 bay between the stops");
assert(riser_len >= lc_hole_end + lc_hole_pitch + lc_cb_d(lc_fix_size) / 2,
       "riser_len must cover the inner bolt's counterbore");
assert(rib_h <= plat_ped_h + 0.01, "rib_h deeper than the pedestal: the cross rib would hit the bar");
assert(z_tip + 0.5 < z_cb, "stop_gap_nom too large: stop bosses must reach below the bar");
for (s = [lc_fix_size, lc_load_size])
    assert(lc_cb_d(s) >= lc_head_d(s) + 0.5,
           str(s, " counterbore (m4_head_d / m5_head_d = ", lc_cb_d(s),
               ") too small for the socket head Ø", lc_head_d(s)));
assert(stop_screw_len <= sp_insert_depth(stop_size) + 0.001,
       "stop_screw_len longer than the stop pocket: the set screw could not retract flush");
assert(stop_screw_len - stop_gap_nom >= 4,
       "stop_screw_len too short: < 4 mm of thread left in the insert when extended stop_gap_nom");
assert(hx_board == "generic" || hx_scr_eng >= 1.5 * (hx_screw() == "M3" ? 3 : 2.5),
       "board screw engagement < 1.5 d");
assert(hx_ins_mouth - sp_insert_depth(hx_screw()) >= 1.0 - 0.001,
       str("base slab too thin for the recessed board inserts: foot_h + base_th + hx_floor must be ≥ ",
           1.0 + sp_insert_depth(hx_screw()) + hx_relief + hx_insert_sink - hx_stand,
           " mm (raise foot_h or base_th; raising hx_floor / hx_stand also lifts the",
           " terminal block toward the platform)"));
assert(gen_L >= 20 && gen_W >= 14, "gen_L / gen_W below any known HX711 module");
assert(hx_collar_wall >= hx_min_feat - 0.001,
       str("hx_collar_wall must be >= hx_min_feat (", hx_min_feat, " mm): the collar ring would be opened away"));
assert(hx_access_fit >= 0.2,
       "hx_access_fit < 0.2: the access bore would not pass the insert's knurl once printed");
assert(hx_tip_floor >= 0.6, "hx_tip_floor < 0.6 mm: the screw-tip hole would break through the underside");
assert(hx_board == "generic" || hx_scr_len <= hx_scr_max,
       str("board screw x ", hx_scr_len, " would bottom out in the screw-tip hole (longest that fits: x ",
           hx_scr_max, "; lower hx_tip_floor or raise the slab)"));
// Tallest thing in the bay (Adafruit terminal block 10.6 mm, or wires up to
// header height on any board) must clear the platform's ribs by 0.5 mm even
// with the platform dropped the full stop_gap_nom (set screws backed off).
assert(z_pcb + pcb_th + hx_top_env + 0.5 <= z_pb - rib_h - stop_gap_nom + 0.001,
       str("HX711 bay too high for the platform ribs at full overload drop (short by ",
           z_pcb + pcb_th + hx_top_env + 0.5 - (z_pb - rib_h - stop_gap_nom),
           " mm): lower hx_floor / hx_stand, or raise riser_h, or reduce stop_gap_nom"));

echo(str("hx711_scale: base ", base_w, " x ", base_l, " mm (riser top z=", z_cb,
         "), platform ", plat_w, " x ", plat_l, " mm (", z_ptop - z_tip,
         " mm tall as printed), weighing surface z=", z_ptop));

function _wtxt(s) = lc_washer_on(s) ? " + washer"
    : str(" + NO washer (", lc_washers ? "counterbore too small" : "lc_washers=false", ")");
echo(str("hx711_scale: cell=", cell, " fixed end 2 x ", lc_fix_size, " x ", fix_len,
         _wtxt(lc_fix_size), " (", fix_eng, " mm engaged); free end 2 x ", lc_load_size,
         " x ", load_len, _wtxt(lc_load_size), " (", load_eng, " mm engaged); stops 4 x ",
         stop_size, " insert + ", stop_size, " x ", stop_screw_len, " set screw"));
function _hx_nscr() = len([for (h = hx_holes()) if (h[2] == "screw") 1]);
hx_scr_ok = [for (L = hx_stock) if (L >= hx_scr_min && L <= hx_scr_max) L];
function _hx_join(v, i = 0) = i >= len(v) ? "" : str(i > 0 ? " / " : "", "x ", v[i], _hx_join(v, i + 1));
function _hx_range() =
    str("; ", len(hx_scr_ok) > 1 ? str(_hx_join(hx_scr_ok), len(hx_scr_ok) == 2 ? " both fit" : " all fit")
                                 : str("exactly x ", hx_scr_len),
        ": shorter engages < 1.5 d, longer bottoms out");
echo(str("hx711_scale: hx_board=", hx_board,
         hx_board == "generic" ? str(" (", gen_L, " x ", gen_W, ") -> foam tape, no screws")
         : SP_FASTENER == "self_tap"
         ? str(" -> ", _hx_nscr(), " x Ø", sp_insert_hole_d(hx_screw()), " pilot hole (top ",
               hx_ins_mouth, ", ", z_pcb - hx_ins_mouth, " mm below the PCB, under a Ø",
               hx_access_d(), " clearance bore) + ", _hx_nscr(), " x self-tapping ", hx_screw(),
               " x ", hx_scr_len, " (", hx_scr_eng, " mm engaged", _hx_range(), ")")
         : str(" -> ", _hx_nscr(), " x ", hx_screw(), " insert (mouth ", hx_ins_mouth, ", ",
               z_pcb - hx_ins_mouth, " mm below the PCB, down a Ø", hx_access_d(),
               " access bore in a Ø", hx_post_d(), " post) + ", _hx_nscr(), " x ", hx_screw(),
               " x ", hx_scr_len, " SHCS (", hx_scr_eng, " mm engaged", _hx_range(), ")")));

// Axis-aligned box between two plan corners p and q, z = 0 .. h.
module box2(p, q, h) {
    translate([min(p[0], q[0]), min(p[1], q[1]), 0])
        cube([abs(q[0] - p[0]), abs(q[1] - p[1]), h]);
}

// ── Shared cutters ─────────────────────────────────────────────
// Counterbored bolt holes opening on a face at z = 0 with material toward
// +z. Two 0.2 mm sacrificial bridge layers sit on the counterbore ceiling so
// it prints with the face on the bed and no supports. pts: [[x, y], ...]
// (all on one line along Y).
module bridged_counterbores(pts, cb_d, depth, hole_d, thru, layer = 0.2) {
    y0 = min([for (p = pts) p[1]]) - cb_d / 2;
    y1 = max([for (p = pts) p[1]]) + cb_d / 2;
    for (p = pts) translate([p[0], p[1], 0]) {
        translate([0, 0, -1]) cylinder(h = thru + 2, d = hole_d, $fn = 32);
        translate([0, 0, -0.01]) cylinder(h = depth + 0.01, d = cb_d, $fn = 48);
        // layer 2: square as wide as the hole
        translate([-hole_d / 2, -hole_d / 2, depth - 0.01])
            cube([hole_d, hole_d, layer * 2 + 0.01]);
    }
    // layer 1: one strip across all counterbores, as wide as the hole
    translate([pts[0][0] - hole_d / 2, y0, depth - 0.01])
        cube([hole_d, y1 - y0, layer + 0.01]);
}

// ── BASE ───────────────────────────────────────────────────────
module hx_board_mounts() {
    zf = base_top + hx_floor;
    h  = z_pcb - zf;
    if (hx_board == "generic") {
        // plinth for foam tape, clear of both pad rows
        at_board(zf) translate([5, 3, 0])
            cube([hx_L() - 10, hx_W() - 6, h - tape_th]);
        // four L-shaped corner locators just outside the outline: 2 mm
        // thick legs running 2.5 mm in along each edge, 0.6 mm proud of the
        // PCB top so wires bent over the short edges (≥1.2 mm up) pass over
        g  = hx_fit / 2;
        lh = h + pcb_th + 0.6;
        at_board(zf)
            for (c = [[0, 0, -1, -1], [hx_L(), 0, 1, -1], [0, hx_W(), -1, 1],
                      [hx_L(), hx_W(), 1, 1]]) {
                // c = [corner u, corner v, outward su, outward sv]
                box2([c[0] + c[2] * (g + 2), c[1] + c[3] * (g + 2)],
                     [c[0] - c[2] * 2.5,     c[1] + c[3] * g], lh);
                box2([c[0] + c[2] * (g + 2), c[1] + c[3] * (g + 2)],
                     [c[0] + c[2] * g,       c[1] - c[3] * 2.5], lh);
            }
    } else {
        for (hl = hx_holes()) if (hl[2] == "screw") hx_screw_post(hl);
        else at_board(zf) translate([hl[0], hl[1], 0]) {
            cylinder(h = h, d = peg_collar_d, $fn = 32);
            // locating pin through the PCB hole, chamfered tip
            cylinder(h = h + pcb_th + 0.6, d = peg_d, $fn = 24);
            translate([0, 0, h + pcb_th + 0.6])
                cylinder(h = 0.4, d1 = peg_d, d2 = peg_d - 0.8, $fn = 24);
        }
    }
}

// Through-hole pad keep-out (board-local 2D): copper + hx_relief_gap.
module hx_relief_2d() {
    for (p = hx_pads()) translate([p[0], p[1]])
        offset(r = hx_relief_gap, $fn = 16) square([p[2], p[3]], center = true);
}
// Collar cross-section of a screw post: boss ring around the access bore,
// minus the pad keep-out.
module hx_collar_raw_2d(hl) {
    difference() {
        translate([hl[0], hl[1]]) circle(d = hx_post_d(), $fn = 48);
        translate([hl[0], hl[1]]) circle(d = hx_access_d(), $fn = 48);
        hx_relief_2d();
    }
}
// Screw post (Ø hx_post_d): full boss (insert zone) up to the relief zone, then the
// relieved collar with every sliver thinner than hx_min_feat opened away.
module hx_screw_post(hl) {
    zf = base_top + hx_floor;
    zr = max(zf, z_pcb - hx_relief);
    t  = hx_min_feat / 2;
    if (zr > zf + 0.001)
        at_board(zf) translate([hl[0], hl[1], 0])
            cylinder(h = zr - zf + 0.01, d = hx_post_d(), $fn = 48);
    at_board(zr) linear_extrude(z_pcb - zr)
        intersection() {
            offset(r = t, $fn = 24) offset(r = -t, $fn = 24) hx_collar_raw_2d(hl);
            hx_collar_raw_2d(hl);
        }
}

module hx_board_cuts() {
    // Insert pockets (mouth at hx_ins_mouth) + access bores up to the PCB
    if (hx_board != "generic")
        for (hl = hx_holes()) if (hl[2] == "screw")
            at_board(hx_ins_mouth) translate([hl[0], hl[1], 0]) {
                sp_insert_pocket(hx_screw());
                translate([0, 0, -0.01])
                    cylinder(h = z_pcb - hx_ins_mouth + 1, d = hx_access_d(), $fn = 48);
                // screw-tip hole below the pocket (a x 12 screw's tip lands
                // here); never wider than the pocket / pilot above it, so its
                // top is an upward ledge, not an overhang
                if (hx_pocket_floor - hx_tip_bot > 0.001)
                    translate([0, 0, hx_tip_bot - hx_ins_mouth])
                        cylinder(h = hx_pocket_floor - hx_tip_bot + 0.02,
                                 d = min(sp_screw_clearance_d(hx_screw()), sp_insert_hole_d(hx_screw())),
                                 $fn = 32);
            }
    // Relieve post tops under through-hole pads (lead stubs + solder)
    for (p = hx_pads())
        at_board(z_pcb - hx_relief) translate([p[0], p[1], 0])
            linear_extrude(hx_relief + 0.01)
                offset(r = hx_relief_gap, $fn = 16) square([p[2], p[3]], center = true);
}

module bay_walls() {
    difference() {
        translate([bay_x, bay_y, base_top - 0.01])
            cube([bay_out_w, bay_out_l, bay_wall_top - base_top + 0.01]);
        translate([bay_x + hx_wall, bay_y + hx_wall, base_top])
            cube([bay_in_w, bay_in_l, 50]);
        // load-cell wire notch (front wall, bar side), full depth
        translate([lc_notch_x, bay_y - 1, base_top])
            cube([wire_ch, hx_wall + 2, 50]);
        // relay-node cable notch (back wall), full depth
        translate([esp_notch_x, bay_y + bay_out_l - hx_wall - 1, base_top])
            cube([cable_d + 1, hx_wall + 2, 50]);
    }
    if (hx_floor > 0)
        translate([bay_x + hx_wall, bay_y + hx_wall, base_top - 0.01])
            cube([bay_in_w, bay_in_l, hx_floor + 0.01]);
}

// Zip-tie anchor: a bridge over a tunnel along X (the tie's path); the
// relay-node cable runs along Y over its roof. Legs anchor_leg (2 mm) thick.
module cable_anchor() {
    translate([anchor_c[0] - anchor_w / 2, anchor_c[1] - anchor_l / 2, base_top - 0.01])
        difference() {
            cube([anchor_w, anchor_l, anchor_h + 0.01]);
            translate([-1, anchor_leg, -1]) cube([anchor_w + 2, anchor_tun_w, anchor_tun_h + 1.01]);
        }
}

module base() {
    difference() {
        union() {
            cube([base_w, base_l, base_top]);
            // Fixed-end riser, inset from the bar's side faces so the side
            // potting / wires never rest on it
            translate([cell_x + tol, cell_y0, base_top - 0.01])
                cube([lc_w - 2 * tol, riser_len, riser_h + 0.01]);
            bay_walls();
            hx_board_mounts();
            cable_anchor();
        }
        // Fixed-end bolts: counterbores open on the underside (bed face)
        bridged_counterbores([for (y = fix_ys()) [cell_cx, y]],
                             lc_cb_d(lc_fix_size), lc_cb_depth(lc_fix_size),
                             lc_clear_d(lc_fix_size), z_cb);
        hx_board_cuts();
        // Rubber-bumper locator rings (0.4 mm) on the underside corners
        if (foot_w > 0)
            for (x = [foot_w / 2 + 2, base_w - foot_w / 2 - 2],
                 y = [foot_w / 2 + 2, base_l - foot_w / 2 - 2])
                translate([x, y, -0.01]) difference() {
                    cylinder(h = 0.41, d = foot_w + 1, $fn = 48);
                    translate([0, 0, -1]) cylinder(h = 2, d = foot_w - 1, $fn = 48);
                }
        // Wordmark engraved in the top face, past the bar's free end
        translate([base_w / 2, (cell_y1 + base_l) / 2, base_top - 0.6])
            linear_extrude(1)
                text("SporePrint", size = 4.5, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

// ── PLATFORM ───────────────────────────────────────────────────
// Modelled in its in-use frame: weighing surface at z = 0, everything else
// hangs below (z < 0). x/y are platform-local (base x/y + plat_margin).
// platform_print() flips it (rotate 180° about X) onto the bed.
module platform_local() {
    m = plat_margin;
    ped_d = plat_th + plat_ped_h;           // pedestal: surface -> bar top
    boss_d = z_ptop - z_tip;                // stop boss: surface -> tip
    lx = m + cell_x - rib_off - rib_t;      // left flank rib x
    rx = m + cell_x + lc_w + rib_off;       // right flank rib x
    difference() {
        union() {
            translate([0, 0, -plat_th]) cube([plat_w, plat_l, plat_th]);
            // perimeter rim
            translate([0, 0, -plat_th - rib_h]) difference() {
                cube([plat_w, plat_l, rib_h + 0.01]);
                translate([rib_t, rib_t, -1])
                    cube([plat_w - 2 * rib_t, plat_l - 2 * rib_t, rib_h + 2]);
            }
            // flank ribs along the bar (never over the bar itself)
            for (x = [lx, rx]) translate([x, 0, -plat_th - rib_h])
                cube([rib_t, plat_l, rib_h + 0.01]);
            // transverse ribs: full width over the pedestal; elsewhere only
            // outboard of the flank ribs (the bar's fixed end stays clear)
            translate([0, m + ped_y0 + riser_len / 2 - rib_t / 2, -plat_th - rib_h])
                cube([plat_w, rib_t, rib_h + 0.01]);
            for (y = [m + cell_y0 + riser_len / 2, m + base_l / 2 - 6])
                translate([0, y - rib_t / 2, -plat_th - rib_h]) {
                    cube([lx + 0.01, rib_t, rib_h + 0.01]);
                    translate([rx, 0, 0]) cube([plat_w - rx, rib_t, rib_h + 0.01]);
                }
            // free-end pedestal (bears on the bar's top face)
            // (pedestal and bosses stop at z = 0: the plate already overlaps
            // them, so nothing pokes past the bed plane when printed)
            translate([m + ped_x0, m + ped_y0, -ped_d])
                cube([ped_w, riser_len + 2, ped_d]);
            // overload-stop bosses
            for (x = stop_xs, y = stop_ys) translate([m + x, m + y, -boss_d])
                cylinder(h = boss_d, d = sp_insert_boss_d(stop_size), $fn = 40);
        }
        // Free-end bolts: counterbores open on the weighing surface
        mirror([0, 0, 1])
            bridged_counterbores([for (y = load_ys()) [m + cell_cx, m + y]],
                                 lc_cb_d(lc_load_size), lc_cb_depth(lc_load_size),
                                 lc_clear_d(lc_load_size), ped_d);
        // Stop inserts at the boss tips + hex-key access bores from the top
        for (x = stop_xs, y = stop_ys) translate([m + x, m + y, 0]) {
            translate([0, 0, -boss_d]) mirror([0, 0, 1]) sp_insert_pocket(stop_size);
            translate([0, 0, -boss_d + 1]) cylinder(h = boss_d + 1, d = stop_key_d, $fn = 24);
        }
        // Wordmark debossed into the underside, outboard of the bar, mirrored
        // so it reads correctly on the print (underside faces up there)
        translate([(rx + rib_t + plat_w - rib_t) / 2, m + base_l / 2 + 8, -plat_th - 0.01])
            mirror([0, 1, 0]) linear_extrude(0.51)
                text("SporePrint", size = 4.5, halign = "center",
                     valign = "center", font = "Liberation Sans");
    }
}

module platform_assembled() {
    translate([-plat_margin, -plat_margin, z_ptop]) platform_local();
}

module platform_print() {
    translate([0, plat_l, 0]) rotate([180, 0, 0]) platform_local();
}

// ── Render ─────────────────────────────────────────────────────
if (part == "all") {
    base();
    translate([base_w + 15, 0, 0]) platform_print();
} else if (part == "base") {
    base();
} else if (part == "platform") {
    platform_print();
} else if (part == "assembly") {
    base();
    platform_assembled();
    // preview-only ghost of the bar (ignored by STL export)
    %translate([cell_x, cell_y0, z_cb]) cube([lc_w, lc_len, lc_h]);
}
