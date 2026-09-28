# SporePrint 3D-Printable Models

OpenSCAD sources for every printable enclosure, mount and bracket in the
SporePrint hardware guide. Every part is parametric, carries an engraved
`SporePrint` wordmark, and prints flat on a hobby FDM printer (Bambu or any
other) in PLA or PETG at 0.2 mm layers **without supports**. The one
exception is `sensor_bracket` with a non-zero `tilt_angle`.

Each `.scad` file starts with a header that lists the exact parts it fits
(vendor, SKU and dimension source), the print orientation, the hardware to
buy, and every `-D` preset. This README summarises those headers. When the
two disagree, the file header is correct.

Any enclosure made of more than one printed piece is held together by
**brass heat-set threaded inserts** and machine screws. Snap lips and laps
only align the pieces. Boards with mounting holes screw into inserts of the
matching size. See [Heat-set inserts](#heat-set-inserts) and the
[shopping list](#shopping-list-inserts-and-screws).

## Contents

| File | Fits | Printed pieces | Inserts (default) | Tier |
|------|------|----------------|-------------------|------|
| [`pi_case.scad`](#pi_casescad) | Raspberry Pi 5 + official Active Cooler SC1148 | 2 (base + lid) | 4 × M2.5, 4 × M3 | every tier |
| [`esp32_case.scad`](#esp32_casescad) | ESP32-WROOM-32 38-pin DevKit (narrow USB-C default; DevKitC V4, wide clones, ESP32-S3-DevKitC-1 presets) | 2 (base + lid) | 4 × M3 | every tier |
| [`sensor_mount.scad`](#sensor_mountscad--sensor_bracketscad) | SHT31-D/SHT4x + SCD-41/SCD-40 (or SCD-30) + BH1750 on one STEMMA QT chain | 2 (body + lid) | 4 × M3, 6 × M2.5 | every tier |
| [`sensor_bracket.scad`](#sensor_mountscad--sensor_bracketscad) | Carries `sensor_mount` on wire-shelf wires | 1 | 2 × M3 (enclosure joint) | every tier |
| [`cam_mount.scad`](#cam_mountscad) | AI-Thinker ESP32-CAM on its ESP32-CAM-MB | 5 (cradle, lid, arm, 2 washers) | 4 × M3, 1 × M5 | Recommended, All the Things |
| [`hx711_scale.scad`](#hx711_scalescad) | 5 kg straight-bar load cell + HX711 board | 2 (base + platform) | 4 × M4, 2 × M2.5 | All the Things |
| [`pump_bracket.scad`](#pump_bracketscad) | Adafruit 1150 / Kamoer NKP peristaltic pump | 1 | 2 × M2.5 (pump flange) | All the Things |
| [`relay_board_mount.scad`](#relay_board_mountscad) | 4-channel IRLZ44N switch board (relay **and** lighting node) | 1 | none (4 × M3 with `mount="insert"`) | Recommended, All the Things |
| [`power_supply_mount.scad`](#power_supply_mountscad) | 12 V desktop PSU brick (Facmogu 5 A default) | 1 | none | Recommended, All the Things |
| [`fan_duct.scad`](#fan_ductscad) | 80 mm fan (Noctua NF-A8 / Arctic P8) → 4-inch flex duct | 1 | 4 × M4 (fan screws) | Recommended, All the Things |

Shared library files live in [`lib/`](#lib--shared-openscad-files). They are
included by the models and are not printable parts.

## Downloading and rendering

### From the SporePrint UI / API

| Endpoint | Returns |
|----------|---------|
| `GET /api/builder/models` | The printable models: top-level `*.scad` files only. `lib/` files are not listed. |
| `GET /api/builder/models/<file>.scad` | **A single self-contained file.** Every `include <lib/NAME.scad>` is replaced by the content of `models/lib/NAME.scad` (recursively), between `// ── inlined from lib/NAME.scad ──` and `// ── end of inlined lib/NAME.scad ──` comments. The file renders on its own with no `lib/` folder beside it, and gives the same STL as the repo copy. |
| `GET /api/builder/models-bundle.zip` | `sporeprint-models/`: every model, `lib/` and this README, unmodified and in the repo layout. |

### From a git checkout

The models `include <lib/...>`, so keep the `lib/` folder next to them.

```bash
cd models

# one model (default preset)
openscad -o sensor_mount.stl sensor_mount.scad

# a preset: override any top-of-file parameter with -D (quote strings)
openscad -D scd30=true -o sensor_mount_scd30.stl  sensor_mount.scad
openscad -D scd30=true -o sensor_bracket_scd30.stl sensor_bracket.scad
openscad -D 'preset="s3_devkitc1"' -D 'part="base"' -o esp32_s3_base.stl esp32_case.scad

# everything (lib/ files are not matched by *.scad at this level)
for f in *.scad; do openscad -o "${f%.scad}.stl" "$f"; done
```

The files were verified with an OpenSCAD 2026.09 development snapshot using
`--backend=Manifold`: every shipped part and preset gave exit code 0, no
warnings, no errors and a manifold mesh. Manifold is much faster than CGAL.
The 2021.01 stable release was not tested.

**How the fit was checked.** Every part was fit-tested in OpenSCAD against
dimensioned proxies built from the sourced drawings: PCB outlines,
connectors, headers, plugs and overmoulds, and screw shafts. The proxies
were placed in their assembled positions, and every intersection of a proxy
with a printed piece was empty. The same test showed that each insert boss
lines up with its clearance hole, and that each closed lid clears everything
inside it. **Nothing has been physically printed yet.** Dimensions that are
estimates rather than drawing values are listed under "Check before
printing" for each model.

## The models

### `pi_case.scad`

**Fits:**
- **Raspberry Pi 5**, every RAM option (1/2/4/8/16 GB), including Rev 4 / D0
  boards (PCN 22) and the 2026 MagJack revision (PCN 44). Product-portal SKU
  family: SC1110, SC1111, SC1112, SC1113, SC1431, SC1432.
- The official **Active Cooler SC1148** is fitted by default.
- The Pi 4 does **not** fit: its Ethernet and USB positions are swapped.

**Dimensions and sources:**
- PCB 85 × 56 mm. Holes Ø2.7 on a 58 × 49 pattern, 3.5 mm from the corners.
- Every opening fits boards from 1.336 to 1.6 mm thick.
- Sources: Raspberry Pi 5 mechanical drawing RP-008347-DS, measured from the
  vector PDF, cross-checked against the official STEP model RP-010083-CA-1
  (May 2026). Where the two differ, the envelope is the union of both. Also
  PCN 44 and the Active Cooler mechanical drawing.
- All numbers live in `lib/pi5_dims.scad`.
- Plug limits:
  - USB-C overmould up to 12.35 × 6.5 (Type-C spec maximum; covers the
    official 27 W PSU SC1153)
  - micro-HDMI up to 11.2 × 6.6
  - USB-A up to 17.0 wide
  - RJ45 boot up to 15 × 15

**Pieces:**
- **Base:** a 9.3 mm tray. The Pi sits on 4 full Ø6.6 M2.5-insert standoffs.
  The base also has 4 M3-insert corner towers, floor vents and optional ears
  (M3 hole + 2 zip-tie slots each).
- **Lid:** walls and roof, 20 mm above the parting line. It has 4
  counterbored M3 towers, port notches, a GPIO roof slot and the cooler
  intake grille and shroud.
- Outside size 96.6 × 72.6 × 29.3 mm (114 mm wide with the ears).
- With the lid screwed shut you can still reach every port, the microSD
  card, the power button (with a pen), the LED, the PCIe FFC and the GPIO
  header.

**Hardware per case:**

| Qty | Part | Where |
|-----|------|-------|
| 4 | M2.5 × 5.7 heat-set insert (ruthex RX-M2.5x5.7) | base standoffs (Pi holes) |
| 4 | M3 × 5.7 heat-set insert (ruthex RX-M3x5.7 / CNC Kitchen M3x5.7) | base corner towers |
| 4 | M2.5 × 6 socket-head cap screw (ISO 4762) | Pi to base. Engages 4.4 mm. **Not M2.5 × 8**: it would bottom out, and an assert refuses it. |
| 4 | M3 × 16 socket-head cap screw | lid to base, from the top. Engages the full 5.7 mm. For M3 × 20, render with `-D lid_screw_len=20`. |
| opt. | 2 × M3 / #4 screws, or zip ties up to 4.8 × 1.5 | wall-mount ears |
| opt. | 40 × 40 × 10 fan + 4 × M3 × 16 + nuts | `cooling="fan40"` only |

**Presets:**

| Group | Values |
|-------|--------|
| Output | `part="print"` (default: both pieces, 220.6 × 72.6 mm) \| `"base"` \| `"lid"` \| `"assembly"` \| `"none"` |
| Cooling | `cooling="active"` (default, Active Cooler intake + shroud) \| `"fan40"` (40 mm roof fan over the SoC, for a bare Pi) \| `"none"` (passive roof slots) |
| Openings | `gpio_slot=false`, `pcie_slot=false`, `csi_slot=true` (CAM/DISP roof slot; not allowed with `fan40`) |
| Mounting | `mount_ears=false` |
| Fit | `lid_screw_len=20`, `tolerance=0.3` (default 0.5), `pcb_thick=1.41` |
| Pi screws | `pi_screw_len=5` (5 or 6 allowed; 4 and ≥ 8 are refused) |
| Inserts | `SP_FASTENER="self_tap"`, `SP_INSERT_HOLE_TWEAK=±x` |

**Print:**
- Base floor-down, lid roof-down, exactly as laid out. No supports.
- The only overhang is a 1.4 mm annular seat in each lid screw well.
- Thinnest features:
  - 0.9 mm lap tongue and skirt
  - 1.2 mm wall round the screw-head wells
  - 1.5 mm web between the two micro-HDMI openings

**Check before printing:** these are estimates, not drawing values:
- the installed height of the Active Cooler (the drawing's 13.70 mm maximum
  is used)
- the micro-HDMI, RJ45 and USB-A overmould sizes

### `esp32_case.scad`

**Fits** (choose with `-D 'preset="..."'`):

| Preset | Board | Dimensions (source) |
|--------|-------|---------------------|
| `narrow_usbc` (default) | ESP32-WROOM-32 38-pin narrow DevKit, USB-C + CP2102: HiLetgo 3-pack, Amazon **B0CNYK7WT2** (BOM pick) | PCB 52 × 25.5 × 1.6, rows 22.86 mm apart, headers pre-soldered pointing **down**, no mounting holes. Source: BOM-audit measurement and listings (51–52 × 25.5); ESP32-WROOM-32 datasheet (module 18 × 25.5 × 3.1). Not from a vendor drawing. |
| `devkitc_v4` | Espressif ESP32-DevKitC V4 (micro-USB) | PCB 27.94 × 48.26 plus a 6.04 mm module overhang = 54.30 mm overall; rows 25.40 mm. Source: Espressif `esp32_devkitc_v4_dimensions.dxf`. |
| `wide_usbc` | Generic wide 38-pin USB-C clones (about 55 × 28) | Vendor listing ("approx 55 × 28"), DevKitC V4 layout assumed. Measure yours. |
| `s3_devkitc1` | Espressif ESP32-S3-DevKitC-1 v1.1 | PCB 25.40 × 62.87 plus a 6.28 mm module overhang = 69.15 mm overall; rows 22.86 mm; **two micro-USB** ports, so the opening is 26 mm. Source: Espressif DXF v1.1 (2022-04-29). |

Cables: a USB-C overmould up to 13 × 7 mm (micro-USB up to 11.5 × 7). The
Adafruit 4397 STEMMA QT cable and the gate jumpers push their female sockets
onto the downward header pins inside the case.

**Pieces:**
- **Base** (floor on the bed):
  - two ribs the board rests on (the board has no holes)
  - a bay under the board for the sockets
  - an open-top USB notch sized for the cable overmould
  - a 10 × 5 mm floor-level wire window with a zip-tie bar
  - vents, a keyhole for a suction cup, and side flanges with 4 M3 holes and
    zip-tie slots
- **Lid** (top face down):
  - 4 counterbored M3 holes
  - hold-down pads that stop 0.3 mm above the module and the USB receptacle
  - the wordmark
- The EN/BOOT buttons are covered by the lid. Flash over USB auto-reset or
  OTA.

**Hardware per case:**
- 4 × M3 × 5.7 heat-set inserts in the base corner columns
- 4 × M3 × 6 SHCS through the lid (4.8 mm engaged)
- Mounting, pick one:
  - M3 or #4 screws through the 4 flange holes
  - zip ties up to 3.6 × 1.5
  - a ~30 mm mushroom-head suction cup (head ≤ 7 mm, neck ≤ 4 mm)

**Presets:**
- `preset=...` (see the table above)
- `part="both"` (default print plate) | `"base"` | `"lid"` | `"assembled"` | `"none"`
- `dupont=false`: compact case for bare pins, about 23 mm tall instead of 37 mm
- `wire_exit="usb"` (default) | `"far"` | `"both"` | `"none"`
- `strain_relief=false`, `mount_tabs=false`, `zip_tie=false`, `suction=false`
- `SP_FASTENER="self_tap"`
- Every board dimension can be overridden with `-D`, and a `-D` value always
  wins over the preset.
- The old advice "S3: set `board_l=72 usb_w=20`" was wrong: it clipped the
  second plug. Use `s3_devkitc1` instead.

**Outer size** (W × L × H closed; the flanges add 14 mm to the width):

| Preset | Size | Height with `dupont=false` |
|--------|------|----------------------------|
| `narrow_usbc` | 41.9 × 61.2 × 37.2 | 23.3 |
| `devkitc_v4` | 44.3 × 63.5 × 37.0 | 23.1 |
| `wide_usbc` | 44.4 × 64.2 × 37.2 | 23.3 |
| `s3_devkitc1` | 41.8 × 78.4 × 37.0 | 23.1 |

**Print:**
- PLA/PETG, 3+ walls. No supports.
- The base's only bridges are the wire window (10 mm) and the zip-tie bar
  (4 mm).

**Check before printing:**
- The narrow board has no vendor drawing.
- Component heights beyond the module and USB are an assumed 4 mm envelope.
- The `wide_usbc` layout is assumed.

### `sensor_mount.scad` + `sensor_bracket.scad`

**Fits** (board outlines, holes and JST positions come from Adafruit's Eagle
`.brd` files, cross-checked with the product pages; data in
`lib/sensor_mount_dims.scad`):

| Bay | Board | Dimensions |
|-----|-------|------------|
| 1 (temp/RH) | Adafruit **2857** SHT31-D, current STEMMA QT revision. Drop-ins: **5665** SHT45, **5776** SHT41, **4885** SHT40 | 25.40 × 17.78, 4 × Ø2.5 holes on 20.32 × 12.70. The old "18.0 × 12.7" figure is the pre-2021 board. |
| 2 (CO2) | Adafruit **5190** SCD-41 / **5187** SCD-40, or Pimoroni **PIM587** | 25.40 × 22.86, Ø3.0 holes on 20.32 × 17.78, 7.7 mm tall (board file + product page). The PIM587 (about 24 × 21 × 8) has no published holes: it rests on the posts, needs a foam pad, and must be last on the chain. |
| 2 with `scd30=true` | Adafruit **4867** SCD-30 | 50.80 × 25.40, Ø2.5 holes on 45.72 × 20.32, 8.8 mm tall; both QT ports on one short edge |
| 3 (light) | Adafruit **4681** BH1750 | 25.40 × 17.78, holes as bay 1. The lid has a flared Ø20 window over the die. |

Cables: an Adafruit 4397 (QT to female sockets, 150 mm) comes in from the
ESP32 through the front U-notch. Adafruit 4210 (QT–QT, 100 mm) cables link
the boards. JST plug zones (sizes from JST eSH.pdf) and a 9 mm front cable
gallery keep plugs and wires clear of the sensors and vents. Leave the loose
header strips that ship with the boards unsoldered.

**Pieces:**
- **Enclosure body** (floor-down, 16.3 mm): 3 bays, M2.5 insert posts,
  4 M3 corner insert bosses, end ears (counterbored M3 hole + zip-tie slots),
  a cable gallery and chimney vents.
- **Enclosure lid** (top-face-down, 5.9 mm): counterbored M3 bosses,
  chimney vents and the BH1750 window.
- **Bracket** (1 piece, flat): C-clips that snap onto two shelf wires (Ø5 at
  25 mm pitch by default) with zip-tie slots, an arm, and a platform with
  2 insert saddles that hold the enclosure 4.7 mm above it so air reaches
  the floor vents.
- The bracket includes the same `lib/sensor_mount_dims.scad` footprint
  functions as the enclosure. It no longer `use`s `sensor_mount.scad`.
- Size: 123.5 × 36.9 × 20.7 mm, or 149 × 39.4 × 20.7 with the SCD-30, plus a
  12 mm ear at each end. The bracket platform is 157.5 × 46.9 (SCD-30:
  183 × 49.4).

**Hardware per enclosure + bracket:**

| Qty | Part | Where |
|-----|------|-------|
| 4 | M3 × 5.7 insert | body corner bosses (lid screws) |
| 6 | M2.5 × 5.7 insert | board posts, 2 diagonal per board (12 with `pcb_screws=4`; none in a PIM587 bay) |
| 2 | M3 × 5.7 insert | bracket saddles |
| 4 | M3 × 6 SHCS | lid to body (4.8 mm engaged) |
| 6 | M2.5 × 6 SHCS | boards to posts (4.4 mm engaged). **Socket heads, Ø4.5 max**: the ON LED sits right beside one hole. |
| 2 | M3 × 6 SHCS | enclosure ears to bracket saddles (4.7 mm engaged) |
| opt. | 2 zip ties ≤ 4.8 × 1.8 | through the bracket clip webs, over the shelf wires (recommended) |

**Presets:**
- Enclosure:
  - `scd30=true` (render the bracket with the same flag)
  - `part="print"` (default) | `"body"` | `"lid"` | `"assembly"` | `"none"`
  - `pcb_screws=4`
  - `SP_FASTENER="self_tap"`
- Bracket:
  - `scd30=true`
  - `num_clips=1` or `num_clips=3`
  - `suction_cup=false`
  - `clip_tie_slot=false`
  - `SP_FASTENER="self_tap"`
- The footprint knobs `fit`, `qt_clear`, `notch_w`, `ear_len` and `wall` must
  be passed identically to both files.

**Print:**
- PLA or PETG, no supports. PETG is preferred for the bracket's snap clips.
- A bracket with a non-zero `tilt_angle` lifts off the bed and **needs
  supports**.

**Check before printing:**
- PIM587 connector position and height are assumed.
- The QT plug wire-bend allowance is an engineering estimate.
- The SCD-30 underside pin length is not published (3 mm allowed).

### `cam_mount.scad`

**Fits:**
- **AI-Thinker ESP32-CAM** (ESP32-S, not S3) with OV2640/OV3660, seated on
  its **ESP32-CAM-MB** (CH340; micro-USB, or USB-C MBs). This is the BOM kit
  AITRIP **B097BLT24K**; HiLetgo and Aideepen clones are the same board.
- The housing is designed for the CAM + MB stack powered through the MB's
  USB.

**Dimensions and sources:**
- ESP32-CAM 27 × 40.5 × 4.5 (DFRobot DFR0602).
- MB 27 × 38.5–40.5 with an 11 mm header gap.
- Lens centre 10.5 mm from the SD end (Handsontec MDU1112; hand-taped, so
  ±1.5 mm is allowed).
- Flash LED at about (24.5, 30.2) mm, from three photo measurements.
- IO0/RST side plungers stick out 1.25 mm past each long MB edge
  (VaTTeRGeR FreeCAD model and RNT photos).
- USB plug overmould up to 13 × 8 mm.
- The housing is 31.2 mm deep.

**Pieces:**
- **Cradle** (front plate down): lens window, a 45° flash cone (it also
  notches the 3V3-side wall so the flash isn't shadowed), IO0/RST slots in
  both long walls (press them with a paperclip, lid on), a microSD slot, a
  USB notch, 4 M3 insert columns and the M5 pivot boss.
- **Lid** (outer face down): 4 counterbored M3 holes.
- **Arm**: an L-bracket with the pivot hub, 2 countersunk M3/#6 holes, 2
  zip-tie tunnels and a suction-cup keyhole.
- **Friction washer** ×2 (one spare).

**Hardware per mount:**

| Qty | Part | Where |
|-----|------|-------|
| 4 | M3 × 5.7 insert | cradle corner columns |
| 1 | M5 × 9.5 insert (ruthex RX-M5x9.5 / CNC Kitchen) | cradle pivot boss (horizontal) |
| 4 | M3 × 6 SHCS | lid to cradle (5.2 mm engaged) |
| 1 | M5 × 16 SHCS | arm hub + washer into the pivot insert (full 9.5 mm). Add blue threadlocker or a nylon washer. |
| pick one | 2 × M3/#6 flat-head ≥ 12 mm, 2 zip ties ≤ 2.5 × 1.3, or a ~30 mm mushroom-head suction cup | mounting |

With `pivot_d=4`, use an M4 × 8.1 insert and an M4 × 16 screw instead. With
`pivot_d=3`, use M3 × 5.7 and M3 × 16.

**Presets:**
- `part="all"` (default print plate) | `"cradle"` | `"lid"` | `"arm"` | `"washer"` | `"assembled"` | `"none"`
- `arm_length`: default 60. Keep it ≥ 54 for a full turn with the USB cable
  plugged in; ≥ 35 clears the housing alone.
- `pivot_d=5|4|3`
- `cam_h` (lens height)
- `cradle_h`, `lens_size`, `flash_d`: 0 means auto
- `tolerance`
- `mb_l`, `mb_shift`, `usb_x_off`, `mb_btn_*`
- `sd_slot=false`, `lid_vents=false`
- `SP_FASTENER`, `SP_INSERT_HOLE_TWEAK`
- The old values `cradle_h=15` and `lens_size=10` are rejected on purpose:
  they cannot hold the stack or see through the window.

**Print:**
- No supports.
- The cradle's only bridges are the 6.4 mm M5 pocket and the 12.5 mm SD slot.

**Check before printing:**
- The MB button position comes from one CAD model plus photos.
- The MB underside and the ESP32-CAM PCB thickness are unverified. If the
  stack rattles, add a 1 mm foam dot on each lid pad.

### `hx711_scale.scad`

**Fits:**

| Preset | Part | Dimensions (source) |
|--------|------|---------------------|
| `cell="bar75"` (default) | Adafruit **4541** 5 kg bar and generic 75 mm "HX711 + 5 kg" kit bars | 75.0 × 12.7 × 12.7, 4 × M4 threaded holes at 10/44/10 mm (Adafruit drawing C14641+C14642+C14643) |
| `cell="tal220"` | HTC TAL220 80 mm: SparkFun **SEN-13329**, Amazon YZC-133 80 mm kits **B0CRCY863F** | 80 × 12.7 × 12.7, 2 × M5 at the fixed end and 2 × M4 at the free end, holes 5 and 20 mm from each end (HTC TAL220 datasheet) |
| `hx_board="ada5974"` (default) | Adafruit **5974** HX711 | 25.4 × 22.86, 4 × Ø2.5 holes on 20.32 × 17.78, pre-soldered 6-pos terminal block 10.5 mm tall (Adafruit Eagle file) |
| `hx_board="sfe13879"` | SparkFun **SEN-13879** | 30.48 × 22.86, 4 × Ø3.3 holes on 25.4 × 17.78 (SparkFun Eagle file) |
| `hx_board="generic"` | Generic green HX711 module | `-D gen_L`, `-D gen_W` (default 35 × 21). Fit-proven sizes: 33.5 × 20.3 and 35 × 21 at the defaults; 38 × 21 and 24.3 × 16 with matching `gen_L` / `gen_W`. |

SparkFun **SEN-14729** (55 mm TAL220B) is **not supported**.

Wiring: DOUT → relay-node GPIO 32, SCK → GPIO 33.

**Pieces:**
- **Base:** a solid slab with the fixed-end riser, the HX711 bay and a
  zip-tie anchor.
- **Platform:** ribbed, printed weighing-face down, with 4 corner
  overload-stop bosses.
- The two pieces touch **only through the load cell**, which is the
  measured load path. They are not screwed to each other.
- Base 76 × 91 mm (tal220: 76 × 96). Platform 92 × 107 (92 × 112). Weighing
  surface 40.7 mm up.

**Hardware (defaults: bar75 + ada5974):**

| Qty | Part | Where |
|-----|------|-------|
| 2 | M4 × 25 SHCS + 2 × M4 DIN 125 washers | up through the base into the cell's fixed end (10.4 mm engaged) |
| 2 | M4 × 16 SHCS + 2 × M4 DIN 125 washers | down through the platform into the free end (11.4 mm engaged) |
| 4 | M4 × 8.1 insert (ruthex RX-M4x8.1 / CNC Kitchen) | platform stop bosses |
| 4 | M4 × 8 set screw (ISO 4026 flat or ISO 4029 cup point) | adjustable overload stops (use nylon-patch screws or medium threadlocker) |
| 2 | M2.5 × 5.7 insert | board posts, **recessed 2.9 mm** below the PCB and pressed down a Ø5.2 access bore (0.3 mm a side over the Ø4.6 knurl) |
| 2 | M2.5 × 10 SHCS | board to posts (5.5 mm engaged). × 12 also fits (a screw-tip hole continues below each pocket); × 8 engages < 1.5 d — do not use it |
| 1 | zip tie ≤ 3.6 mm | cable anchor |

Changes for other presets:
- `tal220`: 2 × M5 × 25 + 2 × M5 washers replace the M4 × 25 at the fixed
  end.
- `sfe13879`: 4 × M3 × 5.7 inserts + 4 × M3 × 10 SHCS (× 12 also fits)
  replace the M2.5 pair.
- `generic`: no board inserts; use about 20 × 12 × 1 mm double-sided foam
  tape.

**Presets:**
- `cell=...`, `hx_board=...`, `gen_L` / `gen_W`
- `part="all"` (default, both on one 183 × 107 bed) | `"base"` | `"platform"` | `"assembly"`
- `hx_stand` (≥ 2.5), `plat_margin`, `stop_gap_nom`, `stop_screw_len` (≤ 9.1)
- `lc_washers=false`, `hx_access_fit` (default 0.6 mm over the insert's knurl;
  the post grows with the bore — raise it for a fatter clone insert)
- `SP_FASTENER="self_tap"`: the board posts take self-tappers; the stop
  holes must be tapped M4
- `SP_INSERT_HOLE_TWEAK`
- Asserts stop impossible combinations:
  - `foot_h=0` now needs `base_th=7.1`.
  - `riser_h=6` needs `stop_gap_nom=2`.

**Print:**
- No supports. The bolt counterbores print over built-in 0.2 mm sacrificial
  bridge layers.
- The riser and pedestal carry the load: use **5 walls and ≥ 40 % infill**,
  or 100 % infill modifiers there. 3 walls minimum.

**Assembly:**
- Mount the bar with its wire end on the riser and the arrow pointing down.
- Set the stops once, with 110 % of the rated load or a 0.5 mm shim.
- Then tare and calibrate.

**Check before printing:** the potting and blob envelopes on the bar are
generous estimates.

### `pump_bracket.scad`

**Fits:**

| Preset | Pump | Dimensions (source) |
|--------|------|---------------------|
| `pump="adafruit_1150"` (default) | Adafruit **1150** 12 V peristaltic pump | Ø27 motor, 72 mm long, 2 × Ø2.7 flange holes at 50.0 mm c-c (product page). Flange and head envelopes are conservative estimates. |
| `pump="kamoer_nkp"` | Kamoer **NKP-DC** 12 V, straight plate (Amazon **B07GWJ78FN**) | plate 54.5 × 40.3, 2 × Ø3.2 at 48.5 mm c-c, motor Ø29 × 44 (Kamoer NKP drawings). Add `-D pump_d=30.5` if your can measures 30.5. |
| `pump="universal"` | either pump | 48.5–50.5 mm slots with captive M2.5 nuts |

The Adafruit pump is not a documented "Kamoer KMP-A1": Adafruit doesn't name
the OEM, and its 50 mm hole pitch doesn't match the NKP.

**Piece:**
- **One** printed L-bracket. It bolts through the pump's own flange holes.
- It has a Ø32 open-top motor slot, a 25 mm axis height, 3 mm flange
  stand-off pads, an optional zip-tie motor cradle, and 4 × Ø3.4 base holes
  plus zip-tie slots.
- Base 75 × 44 mm.

**Hardware:**
- Pump flange:
  - Default presets: 2 × M2.5 × 5.7 inserts in the pads + 2 × M2.5 × 8
    socket- or pan-head screws.
  - `universal` or `flange_nut=true`: no inserts. Use 2 × M2.5 × 12 screws
    + 2 × M2.5 DIN 934 hex nuts instead.
- Base: 4 × M3 × 12 + nuts through a panel, or 4 × #4 × ½" wood screws.
  Render with `screw_d=4` for #6 wood screws.
- Cradle: 1 zip tie ≤ 3.6 mm.

**Presets:**
- `pump=...`, `pump_d=30.5`
- `flange_nut=true`, `motor_cradle=false`
- `axis_h=28`
- `screw_d=4`
- `SP_FASTENER="self_tap"`, `SP_INSERT_HOLE_TWEAK`

**Print:**
- Base flat, face plate standing up. No supports.
- To press the inserts, clamp the base in a vise so the pad faces point up.

**Assembly:** the tube ports must point **up** or sideways, never down.

### `relay_board_mount.scad`

A printed "perfboard" chassis for the 4-channel IRLZ44N switch stage. The
same file serves both the **relay node** (`node="relay"`:
FAE/EXH/CIRC/AUX) and the **lighting node** (`node="lighting"`:
WHT/BLU/RED/FR). Every part is through-hole, soldered underneath inside a
6 mm rimmed tray.

**Fits** (from the vendor drawings):
- **IRLZ44NPbF** TO-220AB (Infineon/IR package outline), standing upright.
  Seat 11.4 × 5.5 for a body up to 10.54 × 4.69.
- 2-pos 5.08 mm screw terminals: generic **KF301-2P** / DG301 (5.0 or 5.08
  pitch; Handson Technology drawing) **or** Phoenix **MKDS 1,5/ 2-5,08
  (1715721)**. Seat 11.0 × 10.6, open on the wire side.
- 100 Ω + 10 kΩ ¼ W axial resistors (Yageo MFR-25) and a DO-41 flyback diode
  (1N4007 / UF4007 / 1N5819), all on 10.16 mm footprints.
- **Aavid/Boyd 574502B00000G** (or B03300G) clip-on heatsinks with
  `heatsink=true`: optional (recommended above ~1 A per channel, required
  above ~2 A) and not in the BOM.

**Piece:**
- **One** part: plate 100 × 48.5 × 9 mm at a 20 mm channel pitch (117.4 mm
  wide with `heatsink=true`).
- It prints component face down; the labels are engraved into that face.

**Hardware:**
- **No inserts by default.** Mount with 4 × M3 × 16 pan-head screws (into a
  wall plug or nut), or 4 × #4 × ¾" wood screws, through the corner feet
  (head Ø ≤ 7).
- `mount="insert"`: 4 × M3 × 5.7 inserts in the feet, bolted from behind a
  panel with 4 × M3 × 8 (3 mm panel) or M3 × 10 (4–5 mm panel). The panel
  holes are Ø3.4 on 90.8 × 39.3 mm.
- Zip ties ≤ 2.5 × 1.3 through the end slot pairs.
- Per board:
  - 4 × IRLZ44N
  - 4 × 100 Ω and 4 × 10 kΩ (¼ W — ½ W bodies don't fit the seats)
  - 4 × DO-41 diodes (relay board only: the lighting board's LED strips are
    resistive and take no flyback diodes)
  - 8 × 2-pos terminals (4 with `input_terminals=false`)

**Presets:**
- `node="relay"` or `node="lighting"`, `labels=[...]`
- `heatsink=true`: the pitch widens to 24.34 mm, so the drain-potential tabs
  never touch.
- `input_terminals=false`
- `mount="insert"`
- `num_channels=1..8`, `channel_spacing`, `standoff_h`, `rail_height`
- `part="print"` | `"assembled"` | `"none"`
- `SP_FASTENER="self_tap"`

**Print:**
- No supports. Bridges are at most 11 mm.
- Use **PETG** for the lighting node or any channel above about 0.5 A. PLA
  is fine for fans. A strip cut to closet length stays around 1 A per
  channel, where a bare upright TO-220 copes; fit the heatsinks above that
  (see Fits).

**Solder, then trim** every lead to ≤ 3 mm below the plate. The TO-220 legs
must be cut.

### `power_supply_mount.scad`

**Fits** (body W × L × H from each vendor's product-size drawing; 1 mm
clearance per side):

| Preset | Brick | Size |
|--------|-------|------|
| `psu="facmogu_5a"` (default, Tier 2) | Facmogu 12 V 5 A AL-1250, Amazon **B0711Q5B49**. Hard-wired AC cord, not a C7/C8 inlet. | 55 × 113 × 33 |
| `psu="facmogu_10a"` (Tier 3) | Facmogu 12 V 10 A AL-12100, Amazon **B087LY94T6** (C14 inlet) | 60 × 153 × 33 |
| `psu="alitove_5a"` | ALITOVE 12 V 5 A, **B01GEA8PQA** (corner C14) | 55 × 113 × 35 |
| `psu="sansun_5a"` | SANSUN 12 V 5 A (**B0B79WLSJJ** bundle) | 50 × 116 × 31 |
| `psu="meanwell_gst60a12"` | Mean Well GST60A12-P1J (C14) | 50 × 125 × 31.5 |
| `psu="alitove_10a"` | ALITOVE 12 V 10 A, **B07MXXXBV8** (corner C14) | 63 × 167 × 38 |
| `psu="custom"` | set `psu_w` / `psu_l` / `psu_h` | — |

**Piece:**
- **One** part (cradle and wall plate in one print). **No inserts.**
- Two hook-and-loop straps run through a floor channel and the side slots.
- Low corner end stops leave both ends open (≥ 36 mm, open to the top) for
  C13 plugs and cord boots.

**Hardware:**
- 2 × 3/4" × 12" (19–20 × 300 mm) hook-and-loop straps. The render echoes
  the length each preset needs.
- Wall mounting, pick one:
  - 4 × #8/M4 flat-head countersunk screws ≥ 25 mm (+ anchors)
  - 2 × #8/M4 pan-head screws (head ≤ Ø8.5 × 3.1) in the keyholes: set the
    head's underside 2.6–2.9 mm off the wall, hang the cradle with the +Y end
    up and slide it down
- Optional zip ties ≤ 4.8 mm through the flange slot pairs.

**Presets:**
- `psu=...`
- `psu_w` / `psu_l` / `psu_h` override single values; the old
  `-D psu_l=125 -D psu_h=32` still works.
- `tolerance`, `side_h`, `lip_h`, `part="none"`

**Print:**
- Wall face on the bed. No supports.
- PETG for the 10 A bricks.

**Check before printing:** C13 plug and cord-boot envelopes are generic
estimates. If your inlet sits low near a corner, set `lip_h=3`.

### `fan_duct.scad`

**Fits:**
- **Noctua NF-A8 PWM** 12 V (Amazon **B00NEMG62M**) or **Arctic P8 PWM PST**
  (Amazon **B07XR1KLLK**).
  - Fan 80 × 80 × 25 mm, holes on a 71.5 mm pattern, Ø76.3 opening.
  - Sources: the Noctua infosheet, and Arctic's P8 2D and mounting-hole
    drawings.
- Any 4-inch / 100 mm flexible duct that slides **over** the Ø97 spigot
  (Ø99 barb). Defaults: duct ID 100 / OD 102.

**Piece:**
- **One** part: an 86 × 86 mm flange with 4 M4 insert bosses, a hollow
  transition, a stop ring, the spigot, and 4 zip-tie guide fingers.
- Ø114 mm at the stop ring, 73 mm tall.
- The fan is a bought part: it bolts on from its far face.

**Hardware per duct:**
- 4 × M4 × 8.1 inserts, pressed in from the fan face.
- 4 × M4 × 35 screws, socket or button head, A2 stainless. M4 × 30 and
  M4 × 40 also fit.
- Duct retention, pick one:
  - 1 zip tie ≥ 360 mm (14") and ≤ 4.8 mm wide through the finger tunnels
  - a 4" worm-drive hose clamp
- Noctua's bundled self-tappers and anti-vibration mounts are **not** used.

**Presets:**
- `fan_mount="nut"`: 4 × M4 hex nuts (ISO 4032) instead of inserts
- `SP_FASTENER="self_tap"`: M4 plastite screws, no inserts
- `zip_tie_tabs=false`: for a hose clamp
- `duct_id=101.6 duct_od=104`: fat imperial duct
- `SP_INSERT_HOLE_TWEAK`

**Print:**
- Flange (fan face) on the bed. No supports.
- PETG preferred in the humid closet.

**Check before printing:** Noctua doesn't publish its hole Ø (every 80 mm
frame clears M4). Real flex-duct OD varies with the wire helix; at exactly
104 mm the fingers touch.

## Heat-set inserts

All insert geometry comes from [`lib/sp_inserts.scad`](lib/sp_inserts.scad).
The inserts are standard knurled brass inserts as sold by **ruthex** and
**CNC Kitchen** (and their clones); the M2.5 size is ruthex's RX-M2.5x5.7
(CNC Kitchen's M2.5 is × 4). What to buy is under the
[shopping list](#shopping-list-inserts-and-screws). Each pocket is the
vendor's pilot diameter plus 1.0 mm of extra depth, so displaced plastic has
somewhere to go. Each pocket mouth has a 0.5 mm lead-in chamfer so the insert self-centres.

| Size | Insert (L) | Example SKU | Pocket Ø × depth | Min wall | Min boss Ø × h | Clearance Ø | Counterbore Ø × depth | Self-tap pilot Ø |
|------|-----------|-------------|------------------|----------|----------------|-------------|-----------------------|------------------|
| M2   | 4.0 | ruthex RX-M2x4 | 3.2 × 5.0 | 1.5 | 6.2 × 6.0 | 2.4 | 4.4 × 2.2 | 1.7 |
| M2.5 | 5.7 | ruthex RX-M2.5x5.7 | 3.6 × 6.7 | 1.5 | 6.6 × 7.7 | 2.9 | 5.1 × 2.7 | 2.1 |
| M3   | 5.7 | ruthex RX-M3x5.7, CNC Kitchen M3x5.7 | 4.0 × 6.7 | 1.6 | 7.2 × 7.7 | 3.4 | 6.2 × 3.2 | 2.5 |
| M4   | 8.1 | ruthex RX-M4x8.1, CNC Kitchen M4x8.1 | 5.6 × 9.1 | 2.0 | 9.6 × 10.1 | 4.5 | 7.8 × 4.2 | 3.3 |
| M5   | 9.5 | ruthex RX-M5x9.5, CNC Kitchen M5x9.5 | 6.4 × 10.5 | 2.5 | 11.4 × 11.5 | 5.5 | 9.4 × 5.2 | 4.2 |

How to read the table:
- **Min boss** is the pocket Ø plus 2 × the minimum wall. Its height is the
  pocket depth plus a 1 mm floor.
- **Clearance and counterbore** are the hole in the mating piece, sized for
  an ISO 4762 socket-head cap screw. The counterbore depth is capped at the
  part thickness minus 0.8 mm.
- **Screw length:** `sp_screw_len(size, clamp)` gives the length under the
  head through the clamped piece plus the insert length. Buy the next stock
  length **at or below** it. Each model's header states the exact screw and
  how much thread it engages.

**Installing:**
1. Press every insert before assembly, into the finished print.
2. Use a soldering iron with an insert tip, at about 220–230 °C for PLA and
   about 245 °C for PETG.
3. Set the insert on the chamfered pocket mouth, small end down.
4. Let it sink under light, straight pressure. Don't force it: let the
   plastic melt.
5. Stop when it is flush. Press a flat metal object on top while it cools
   to square it up.

Special cases:
- In `hx711_scale` the HX711 board inserts go 2.9 mm **below** the post top,
  down a Ø5.2 access bore: drop each one in small end down and press it with
  a narrow M2.5 / M3 insert tip (the stepped ruthex / CNC Kitchen tips reach
  down the bore) until its top is level with the bottom of the bore.
- In `cam_mount` the M5 pivot insert goes in horizontally, into the side
  boss.
- In `pump_bracket`, clamp the part in a vise so the pads face up.

**`SP_INSERT_HOLE_TWEAK`** (mm, default 0) is added to every pocket Ø to
suit your printer:
- Inserts drop in loose or spin: tighten with `-D SP_INSERT_HOLE_TWEAK=-0.1`.
- Inserts crack the boss or need heavy force: loosen with `+0.1`.

The tweak also grows the boss, so wall thickness is kept.

**`SP_FASTENER="self_tap"`** (default `"insert"`) is for when you have no
inserts:
- Every pocket becomes a plain pilot hole of the size in the last column.
- Use self-tapping (thread-forming, "plastite"/PT-style) screws of the same
  nominal size and length.
- Part outlines don't change: the boss is always sized for the insert.
- Exception: the `hx711_scale` overload-stop holes then have to be tapped
  M4, because set screws don't self-tap.

```bash
openscad -D 'SP_FASTENER="self_tap"' -o esp32_case_selftap.stl esp32_case.scad
openscad -D SP_INSERT_HOLE_TWEAK=-0.1 -o pi_case.stl pi_case.scad
```

## Shopping list (inserts and screws)

Screws are ISO 4762 / DIN 912 socket-head cap screws unless noted.
Quantities are **per printed part at its default preset**.

| Model | Heat-set inserts | Screws / other fasteners |
|-------|------------------|--------------------------|
| `pi_case` | 4 × M2.5×5.7, 4 × M3×5.7 | 4 × M2.5×6, 4 × M3×16 |
| `esp32_case` | 4 × M3×5.7 | 4 × M3×6 |
| `sensor_mount` | 4 × M3×5.7, 6 × M2.5×5.7 | 4 × M3×6, 6 × M2.5×6 |
| `sensor_bracket` | 2 × M3×5.7 | 2 × M3×6 |
| `cam_mount` | 4 × M3×5.7, 1 × M5×9.5 | 4 × M3×6, 1 × M5×16 |
| `hx711_scale` | 4 × M4×8.1, 2 × M2.5×5.7 | 2 × M4×25, 2 × M4×16, 4 × M4 DIN 125 washers, 4 × M4×8 set screws, 2 × M2.5×10 |
| `pump_bracket` | 2 × M2.5×5.7 | 2 × M2.5×8 (socket or pan head) |
| `relay_board_mount` | — | — (mounting screws only; see below) |
| `power_supply_mount` | — | — (straps and wall screws only) |
| `fan_duct` | 4 × M4×8.1 | 4 × M4×35 (A2 stainless) |

**Totals.** The "All the Things" column uses the current BOM's counts:
- 1 Pi case
- 4 ESP32 cases (2 climate, relay and lighting nodes)
- 2 sensor mounts + 2 brackets
- 2 camera mounts
- 1 scale and 1 pump bracket
- 2 relay/lighting boards in screw mode
- 1 PSU mount
- 3 fan ducts

Adjust the counts if you print more or fewer.

| Item | One of each model | "All the Things" build |
|------|-------------------|------------------------|
| M2.5 × 5.7 insert | 14 | 20 |
| M3 × 5.7 insert | 18 | 40 |
| M4 × 8.1 insert | 8 | 16 |
| M5 × 9.5 insert | 1 | 2 |
| M2.5 × 6 SHCS | 10 | 16 |
| M2.5 × 8 SHCS (or pan head) | 2 | 2 |
| M2.5 × 10 SHCS | 2 | 2 |
| M3 × 6 SHCS | 14 | 36 |
| M3 × 16 SHCS | 4 | 4 |
| M4 × 8 set screw | 4 | 4 |
| M4 × 16 SHCS | 2 | 2 |
| M4 × 25 SHCS | 2 | 2 |
| M4 × 35 SHCS / button head | 4 | 12 |
| M5 × 16 SHCS | 1 | 2 |
| M4 washer, DIN 125 | 4 | 4 |

**Where to buy:** the **ruthex M2/M3/M4/M5 assortment** (Amazon B08K1BVGN9,
~$30) **+ a separate ruthex RX-M2.5x5.7 pack** — the assortment has no M2.5.
CNC Kitchen's M3/M4/M5 inserts match the pockets too, but CNC Kitchen's M2.5
is M2.5 × 4, too short for the M2.5 × 5.7 pockets.

Preset swaps:

| Preset | Instead of | Buy |
|--------|------------|-----|
| `hx711_scale` `cell="tal220"` | 2 × M4×25 + 2 M4 washers | 2 × M5×25 + 2 × M5 washers |
| `hx711_scale` `hx_board="sfe13879"` | M2.5 pair | 4 × M3×5.7 + 4 × M3×10 |
| `sensor_mount` `pcb_screws=4` | — | +6 × M2.5×5.7 and +6 × M2.5×6 |
| `pi_case` `lid_screw_len=20` | M3×16 | M3×20 |
| `cam_mount` `pivot_d=4` | M5 pair | M4×8.1 + M4×16 |
| `cam_mount` `pivot_d=3` | M5 pair | M3×5.7 + M3×16 |
| `pump_bracket` `pump="universal"` / `flange_nut=true` | inserts + M2.5×8 | 2 × M2.5×12 + 2 × M2.5 DIN 934 nuts |
| `fan_duct` `fan_mount="nut"` | inserts | 4 × M4 ISO 4032 nuts |
| `relay_board_mount` `mount="insert"` | — | 4 × M3×5.7 + 4 × M3×8 (3 mm panel) |

**Mounting hardware** (not in the totals; pick per location):
- `pi_case` ears: 2 × M3/#4 screws or zip ties.
- `esp32_case` flanges: M3/#4 screws, zip ties ≤ 3.6 mm, or a 30 mm
  suction cup.
- `sensor_bracket` clips: 2 zip ties ≤ 4.8 mm.
- `cam_mount` arm: 2 × M3/#6 flat-head ≥ 12 mm, zip ties ≤ 2.5 mm, or a
  suction cup.
- `hx711_scale`: 1 zip tie ≤ 3.6 mm.
- `pump_bracket`: 4 × M3×12 + nuts or #4 × ½" wood screws, plus 1–4 zip
  ties ≤ 3.6 mm.
- `relay_board_mount`: 4 × M3×16 pan head or #4 × ¾" wood screws.
- `power_supply_mount`: 2 × 3/4" × 12" hook-and-loop straps, plus
  4 × #8/M4 flat-head ≥ 25 mm or 2 × #8/M4 pan-head.
- `fan_duct`: 1 zip tie ≥ 360 mm or a 4" hose clamp.

## Print settings

- **Material:** PLA or PETG. PETG is preferred for:
  - `fan_duct` (humid closet)
  - the `relay_board_mount` lighting board or any channel above 0.5 A
  - the 10 A PSU cradle
  - the `sensor_bracket` snap clips
- **Layers and walls:** 0.2 mm layers, 3 walls, 20–25 % infill. For
  `hx711_scale`, use 5 walls and ≥ 40 % infill (or 100 % infill modifiers on
  the riser and pedestal).
- **Supports: none.** Every model is laid out flat and in print orientation
  as it renders. Multi-piece parts render as one print plate by default;
  export a single piece with `-D 'part="..."'`. The one exception is
  `sensor_bracket` with a non-zero `tilt_angle`, which needs supports.
- **Inserts:** press them into the finished prints before assembly (see
  [Heat-set inserts](#heat-set-inserts)).

## `lib/` — shared OpenSCAD files

These are included with `include <lib/NAME.scad>`. They contain constants,
functions and modules only, with **no top-level geometry**, so rendering one
on its own produces nothing. They are not models and are not listed by the
API. The single-file download inlines them, and the bundle ZIP ships them.

| File | Contents | Used by |
|------|----------|---------|
| `lib/sp_inserts.scad` | Insert pocket, boss, clearance/counterbore and screw-length helpers (`sp_insert_pocket`, `sp_insert_boss`, `sp_insert_boss_with_pocket`, `sp_screw_clearance`, `sp_screw_len`, …); `SP_FASTENER`, `SP_INSERT_HOLE_TWEAK` | every model with inserts |
| `lib/pi5_dims.scad` | Raspberry Pi 5 + Active Cooler dimension tables and access/proxy modules, with sources | `pi_case` |
| `lib/sensor_mount_dims.scad` | Sensor-enclosure footprint functions and board data shared by the enclosure and its bracket | `sensor_mount`, `sensor_bracket` |

Rules for new shared code:
- Put it in a new `lib/` file (functions, modules and constants only).
- `include` it from the model.
- Never `use <other_model.scad>`: single-file downloads only inline `lib/`.

## Not printed on purpose

- **Reed door switch.** It ships as a wired alarm-contact set in its own
  moulded housing; mount the magnet and switch with the adhesive or screws
  included. No print needed.
- **MH-Z19C UART CO2 alternate.** It is not a standalone BOM SKU (it is a
  config-flag alternate to the I2C SCD4x), and Winsen's own listings give
  inconsistent module dimensions. Rather than ship a holder built to an
  unverified size, there is none. Use the I2C trio in `sensor_mount`.
