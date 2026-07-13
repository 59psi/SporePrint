# SporePrint 3D-Printable Models

OpenSCAD sources for every printable enclosure, mount, and bracket in the
SporePrint hardware guide. Each part is parametric — the tunable dimensions
sit at the top of its `.scad` file — carries an engraved `SporePrint`
wordmark, and prints on a hobby FDM machine in PLA (a few in PETG) at 0.2 mm
layer height.

Parts are sized from the shipped Bill of Materials in
`server/app/builder/hardware_guides.py`. Board footprints come from the
vendor's own published "Product Dimensions", not guesswork.

## Rendering to STL

```bash
# one model
openscad -o sensor_mount.stl sensor_mount.scad

# a parametric variant (override any top-of-file parameter with -D)
openscad -D scd30=true -o sensor_mount_scd30.stl sensor_mount.scad

# everything (CI does this on every push — see
# .github/workflows/render-stl.yml in the parent repo)
for f in *.scad; do openscad -o "${f%.scad}.stl" "$f"; done
```

## The models

| File | Fits | Key dimensions (verified) | Tier | Notes |
|------|------|---------------------------|------|-------|
| `pi_case.scad` | Raspberry Pi 5 | 85 × 56 mm PCB | all | Snap-fit case, port cutouts, 40 mm fan mount, M2.5 standoffs. |
| `esp32_case.scad` | ESP32-WROOM-32 38-pin DevKitC | 55 × 28 mm PCB | all | USB cutout clears **both** micro-USB and USB-C. ESP32-S3-DevKitC-1 (~70 × 28 mm, dual USB-C): set `board_l=72 usb_w=20`. |
| `sensor_mount.scad` | Climate I2C trio: SHT31-D (18.0 × 12.7), SCD41 (25.5 × 22.8), BH1750 (25.3 × 17.7) | per-bay, from Adafruit 2857 / 5190 / 4681 | all | 3-bay chimney-vented enclosure + snap lid. **`scd30=true`** widens bay 2 for the SCD30 (Adafruit 4867, 51 × 25.4). Mounts to `sensor_bracket` via end-ear M3 holes. |
| `sensor_bracket.scad` | Carries `sensor_mount` over the substrate | platform derived from the enclosure footprint | all | Wire-shelf clip + arm + platform. `use <sensor_mount.scad>` — platform + tie-down holes track the enclosure (incl. `scd30`). |
| `fan_duct.scad` | 80 mm PC fan → 4-inch (102 mm) duct | 80 mm fan, 102 mm duct | Rec/All | FAE ducting. PETG or PLA. |
| `relay_board_mount.scad` | 4× IRLZ44N TO-220 + screw terminals | 4 channels @ 20 mm pitch | Rec/All | FAE / EXH / CIRC / AUX labelled bays, standoffs for airflow. |
| `power_supply_mount.scad` | 12 V PSU brick | 50 × 110 × 30 mm (adj.) | Rec/All | Wall cradle + keyhole hangers. Mean Well GST60A12: `psu_l=125 psu_h=32`. |
| `cam_mount.scad` | ESP32-CAM (AI-Thinker, OV2640) | 27 × 40 mm PCB | Rec/All | Adjustable-angle cradle + arm + friction washers. |
| `hx711_scale.scad` | **HX711 amp + TAL220 5 kg load cell** | bar 80 × 12.7 × 12.7, M4/M5 holes @ 15 mm pitch; HX711 38 × 22 | All | Two-part harvest scale (base + platform). Fixed end bolts to the base riser, free end lifts the platform; HX711 bay + wire channel to the relay node (DOUT→GPIO 32, SCK→GPIO 33). |
| `pump_bracket.scad` | **Peristaltic dosing pump (Adafruit 1150 Kamoer)** | 27 mm barrel, 72 mm long | All | Twin half-pipe saddle clamp + over-barrel capture ties. PLA or PETG. |

## Print settings

All parts: PLA, 0.2 mm layer height, no supports, unless the file header says
otherwise (`fan_duct` and `pump_bracket` are also happy in PETG;
`hx711_scale` pedestals want 3+ perimeters since they carry the weighed
load). Every model is laid out flat-on-bed as it renders.

## Not printed on purpose

- **Reed door switch** — ships as a wired alarm-contact set in its own
  moulded housing; magnet + switch mount with the adhesive/screws included.
  No print needed.
- **MH-Z19C UART CO2 alternate** — not a standalone BOM SKU (it is a config
  flag alternate to the I2C SCD4x), and its module dimensions are
  inconsistent across Winsen's own listings, so no holder is shipped rather
  than one built to an unverified size. Use the I2C trio in `sensor_mount`.
