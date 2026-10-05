# Changelog

All notable changes to the public SporePrint Pi-side repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The 2026-09 hardware + software audit: a live re-check of the whole bill of
materials, every enclosure re-fit to sourced part drawings and joined with
heat-set inserts, and ~180 verified software findings fixed test-first across
the server, firmware, broker/install scripts and dependencies. The wire
contract stays backward compatible: new payload keys are optional and the
signing vectors are unchanged. Firmware details are in
[`firmware/CHANGELOG.md`](firmware/CHANGELOG.md).

### Upgrade notes
- **Update a Docker Pi with `git pull && ./install.sh`** — `install.sh` writes
  the new `.env` keys; `git pull && docker compose up -d --build` alone does
  not. `install.sh` run inside a checkout no longer pulls by itself.
- **Secure MQTT nodes on the plaintext fallback start pinning the CA.** Under
  Docker `GET /api/provision/ca` used to return 404 (the server container had
  no `ca.crt`), so every node with Secure MQTT ticked ran on plaintext. Run
  `./install.sh` before the nodes see the new server: it re-issues the broker
  certificate with every Pi IPv4 in its names. Current firmware pins a fetched
  CA only after a TLS connection with it succeeds and otherwise stays on
  plaintext with a `tls_downgrade` alert that names the reason. **Firmware
  from before this release pins the CA at its next reboot without that
  check:** if the certificate does not cover the node's Pi address (an IP the
  old certificate lacks), that node loses MQTT, drops to safe mode after
  10 min, and needs physical access (portal gesture or factory reset). Point
  nodes at `sporeprint.local`, or update their firmware first.
- **Schedules move to local time.** `install.sh` writes the host's time zone
  into `.env` as `TZ` (compose passes `TZ=${TZ:-UTC}`) and warns. Rule times
  typed in UTC to compensate must be changed back, or set `TZ=UTC`. Use a
  canonical Region/City name: the server image has no legacy aliases, and an
  unknown zone silently runs on UTC. Bare metal: set `TZ` in the service
  environment, not in `server/.env`.
- **Command signing is on by default.** `install.sh` generates
  `SPOREPRINT_MQTT_HMAC_KEY` (reusing one an older `provision-node.sh` left in
  `server/.env`). A cloud-paired Pi without a key refuses every node command,
  so run `./install.sh` or `./scripts/provision-node.sh`, then
  `docker compose up -d server`, before pairing.
- **The database moves to incremental auto-vacuum** with one full `VACUUM`
  (duration logged). A database up to 32 MB converts at the end of startup,
  after MQTT, the rules engine, the re-armed safety watchdogs and the vendor
  drivers are running. A bigger one is not rewritten at boot (that stalled
  ingest and safety for minutes on an SD card): the nightly retention window
  converts it once at least a quarter of the file is free pages. The
  conversion needs free disk of 2 × the DB size + 64 MB; otherwise it is
  skipped with a WARNING and retried.
- **Tasmota plugs need Full Topic `tasmota/%topic%/%prefix%/`** and the `sp-3p`
  login. Plugs on Tasmota's default Full Topic never reached the Pi.
- **Coredumps moved** to `<DB dir>/coredumps` (Docker: `/data/db/coredumps`, on
  the data volume). Dumps in the old `data/coredumps` are no longer listed.
- **Built-in species profiles are read-only** (`PUT` returns 409): clone one to
  customize it.

### Hardware (Builder BOM, `GET /api/builder/tiers`)
- **Tier totals are now ~$290 / ~$745 / ~$960** (were ~$180 / ~$390 / ~$555),
  re-checked live on 2026-09-27, and now include the cabling, consumables,
  heat-set inserts and screws. A second chamber adds ~$62 / ~$316 / ~$527
  (the Pi side once, kits and spools in whole packs). They exclude the tri-spectrum
  strip's shipping and duty (~$10+) and tools. README and the build guide use
  the same numbers.
- **Cabling standard + consumables as BOM lines:** a UL-listed surge strip
  outside the chamber (6 / 12 / 12 + 2 USB-A outlets); 12 V distribution as
  14 AWG barrel pigtail → WAGO 221-413 (+12 V split) / 221-415 (GND join) →
  one inline ATC fuse per branch (relay 3 A; lighting 5 A on Recommended,
  7.5 A on All the Things) → the switch boards, every 12 V run in 18 AWG
  red/black; Noctua NA-SEC3 fan extensions (far end cut, pin 2 → J2 "+",
  pin 1 → J2 "−"); 22 AWG hookup wire for gate / GND jumpers; 22 AWG
  4-conductor runs for the HX711 (red 3V3 / black GND / yellow DOUT / white
  SCK) and the door contact; food-grade 2 × 4 mm pump tubing; adhesive-lined
  heat-shrink, UV zip ties, 18" (457 mm) duct ties, a VELCRO ONE-WRAP roll, a
  grommet kit, lead-free solder, and heat-set insert + stainless screw kits
  (ruthex M3 or M2–M5 assortment, uxcell M2.5). In-chamber boards get 6 ft USB
  cables (USB-C climate, micro-USB camera MBs). New optional field
  `Component.shared` and categories `wiring` / `hardware`; the wiring rows
  come from `_power_rows()`.
- New optional API fields `Component.pack_price` and `Component.pack_size`
  for pack-sold lines. `quantity` counts the units a tier needs per chamber,
  `price_approx` is the per-unit price inside the pinned pack, `pack_price`
  that pack's price and `pack_size` its units; N chambers buy
  `ceil(quantity x N / pack_size)` packs (`Component.line_cost(chambers)`,
  `HardwareTier.parts_cost(chambers)`), and `shared` lines never multiply.
  Every pack line now has this one shape. The camera 2-pack, USB charger
  2-packs, 1 ft USB-C 3-pack, micro-USB 2-pack, NA-SEC3 3-pack, DC pigtail
  2-pack, KF301 30-pack and door-contact 2-set used to count packs (so ×4
  chambers bought 8 cameras for 4), and the ESP32 / IRLZ44N / resistor /
  diode packs were bought once per chamber (×4 bought four 100-packs of
  resistors). One-chamber totals are unchanged. All the Things now lists 4
  ESP32 boards (the 6-pack leaves 2 spares) instead of 6. The inline fuse
  holders are two per chamber from a 10-pack instead of a shared line.
- **Kits and spools the chambers use up are per-chamber pack lines** (new
  optional API field `Component.shared_units`). They used to be `shared` —
  bought once whatever the chamber count — so a multi-chamber shopping list
  under-bought from ~3–4 chambers up: the WAGO 221 assortment (3 × 221-413 +
  3 × 221-415, one of each per chamber) stayed one kit at ×4 and ×12, and 12
  All the Things chambers got one ruthex assortment (100 M3 inserts) for 436.
  Now `quantity` counts what one chamber takes — inserts and screws from the
  `models/README.md` shopping list (a mixed kit counts the size the chambers
  use up first: M4 inserts on Recommended, M3 on All the Things; M2.5 × 6;
  M5 × 16; the M4 × 30/35/40 fan-duct screws), WAGO 221-413 + 221-415 pairs
  (3 per assortment), fuse sets (15 per box), M-F Dupont jumpers (40 per
  kit), VELCRO 12" straps (12 per roll), 18 AWG pair by the foot (~20 / ~35 ft
  a chamber), the 22/4 cable (~12 ft), 22 AWG hookup (~2 ft of black) and
  solder by the gram (~5 / ~7 g) — and `shared_units` is the Pi case's share of
  the same pack (4 M2.5 inserts, 4 M3 inserts, 4 M2.5 × 6), bought once: N
  chambers buy `ceil((quantity × N + shared_units) / pack_size)` packs. The
  bulk consumables are per-chamber pack lines too — zip ties (~25 a chamber
  of 400), heat-shrink (~15 / ~25 pieces of 400), large grommets (1 of the
  kit's ~20), 18" duct ties (one per fan of 100) — since one pack covering
  the 12-chamber preset still under-bought from 17 of the Builder's up to 99
  chambers. Only the Pi side and the bench breadboard stay shared (and Bare
  Bones' screw kit, which only the Pi lid draws on). One-chamber totals are unchanged;
  at ×4 / ×12 chambers the tiers come to $484.60 / $1,047.80,
  $1,733.38 / $4,618.18 and $2,613.78 / $7,154.87. The docs' "reusable kits"
  share (every shared line except the Pi side) is replaced by what a second
  chamber adds: ~$62 / ~$316 / ~$527.
- Setup steps name the Builder's current tabs (Firmware, Models) and the
  dashboard's Hardware page, and check a smart plug with
  `GET /api/automation/plugs` — the dashboard has no plug panel. The weather
  API's "unavailable" message names `SPOREPRINT_WEATHER_LON` in full, and the
  setup-step span check rejects name fragments such as `_LON`.
- New lines: Raspberry Pi Active Cooler (all tiers); Adafruit 4397 + 4210
  STEMMA QT cables (the climate node is now a no-solder daisy chain, replacing
  the M-F jumpers); USB-A to USB-C cables, USB-A to micro-USB cables (camera
  MBs) and UL-listed 5 V chargers — one per board; 100 Ω gate resistors;
  KF301-2P screw terminals for `relay_board_mount`; Dupont jumpers; a
  5.5 × 2.5 mm DC pigtail (Tiers 2/3).
- Changed lines: Pi 5 4GB $110 (PiShop), official 27 W PSU, 64 GB A1 card;
  ESP32-WROOM-32 is the narrow USB-C board (3-pack / 6-pack value options);
  ESP32-CAM is an AI-Thinker 2-pack **with ESP32-CAM-MB programmers**
  (OV2640, or OV3660 — both supported); flyback diode is the **UF4007**
  (1N4007 only on on/off channels); 5 m white roll; IP67 tri-spectrum strip
  with wire colours documented (blue 450 / red 660 / green 730); Facmogu 12 V
  5 A (Tier 2) and **10 A** (Tier 3) bricks with load budgets (≤ ~4 A / ≤ ~8 A);
  HX711 is Adafruit 5974 + 4541 (rate switch at 10 SPS); the reed switch is a
  weideer MC-31B wired **COM + alarm-NC**; Athom Tasmota US Plug V2 (Tasmota
  build, not the ESPHome twin).
- Quantities: IRLZ44N 6 / 8, 10 kΩ 6 / 9, diodes 4 / 4 (inductive channels
  only), Tasmota plugs 1 / 2 / 4.
- Setup steps (all tiers): `install.sh`; `./scripts/add-node-mqtt-user.sh
  <node_id>` before the portal, Node ID left blank; Tasmota User / Password /
  Topic / Full Topic; ESP32-CAM-MB flashing (hold IO0, tap RST if the upload
  won't start); print presets per part; heat-set insert and screw counts per
  tier; PSU load budgets; the S3 pin map wherever `node_esp32s3` is named.
- Setup steps wrap every shell command, file path, JSON payload, MQTT topic,
  env name and config key in backticks (`` `like this` ``), so the Builder can
  show them as copyable code. Component notes and wiring rows stay plain.
  `tests/test_hardware_guides.py` checks that each marked span exists in the
  repo: scripts (and that they are executable), pio envs, compose services and
  published ports, `/api` routes, the keys the node reads from `cmd/config`,
  OpenSCAD parameters and their values, the install URLs, and the broker ACL
  for the Tasmota topics. The weather step now spells out
  `SPOREPRINT_WEATHER_LON` (it said `_LON`), and the Tasmota step names the
  topic that the default Full Topic publishes (`stat/<topic>/POWER`).
- Capability bullets that described unimplemented features were removed (kWh,
  PID, timelapse, quiet hours, EXIF, sensor fallback/divergence, correlation
  reports, local CNN).

### Docs and wiring diagrams
- **All three tier wiring diagrams redrawn** to the cabling standard: inside vs
  outside the chamber with the wall grommet, the power strip and every AC
  cord, USB power paths with cable lengths, the 12 V PSU → pigtail → WAGO →
  fused branches with ratings, wire gauges on each run, the common ground
  (ESP32 GND → J1 "−") on every switch board, the STEMMA QT chain, fan
  extension leads, and on All the Things the HX711 / door-contact 22 AWG
  4-conductor runs, the 10 kΩ reed pull-up and the pump channel. Each has a
  one-channel end-to-end schematic. `wiring-overall-system.svg` marks what
  lives in the chamber and adds a power + cabling band.
- `docs/hardware-build-guide.md`: §7 is now *Power and cabling* (power strip,
  12 V distribution with fuse table, 5 V USB table, the chamber wall, and a
  table mapping every cabling / consumable BOM line to where it is used); the
  §5 channel schematic shows the fuse, wire gauges, the fan extension and the
  common ground; a *Tools you need* list; a 12 V pre-power check in the
  bring-up list; new troubleshooting rows (dead board, swapped fan wires).
- `models/README.md`: per-tier insert and screw totals; the BOM's insert and
  screw kits, the 18" (457 mm) duct tie and the VELCRO straps.
- `tests/test_docs_consistency.py` pins the new invariants: what a second
  chamber adds, fuse ratings, WAGO parts and wire gauges in the build guide and SVGs,
  the common ground in every guide and diagram, the strip sizes, and the
  per-tier insert sourcing.

### Dashboard (`ui/dist`)
- **The Builder page reads this Pi live.** `ui/dist` is rebuilt from the
  monorepo's pi-ui. The page now loads the BOM (`/api/builder/tiers` and
  `/tiers/{id}`), the models, the wiring diagrams and the firmware ZIPs from
  the Pi. If a request fails, that resource falls back to a copy generated
  from this repo at build time, and a pill at the top of the page says which
  data is on screen. This replaces the stale static copy, which had a
  pre-audit BOM with no cabling, "browse repo" and wiring links to
  `hardware/3d` and `hardware/wiring` (both 404), raw GitHub `.scad`
  downloads that cannot render without `models/lib/`, and a false
  "slicer-ready STL exports" claim.
- Shopping list: `shared` parts are bought once per installation and every
  other line's units scale with the chamber count; a pack-sold line buys whole
  packs (`pack_size`, above), so totals equal `parts_cost(N)`. The total shows
  the shared and chambered parts separately, and smart plugs, wiring and
  hardware have their own sections.
- Models: each card shows the title and description from the model's `.scad`
  header and downloads the Pi's self-contained file (`lib/` inlined). There is
  a "download all (.zip)" link, and "browse repo" opens `models/`.
- Wiring: the tier's SVG as the Pi serves it (click for full size), with a
  link to its GitHub source. The connection table uses the live wiring rows.
- Firmware: one card per image (unified node, camera), downloaded as the Pi's
  self-contained ZIP. An image is listed for a tier when one of its PlatformIO
  envs is a tier target, which covers `node_esp32s3_n32r16v`.
- Resources: the repo is labelled AGPL-3.0 (it said MIT). The dead forum
  link is removed, and the dead Discord invite is replaced by a plain-text
  "coming soon" placeholder with no link.
- **`scripts/sync_ui_builder_data.py` now verifies the bundle instead of
  patching a static copy.** `--check` confirms that the bundle requests
  `/api/builder/*` live and has none of the old static Builder's dead links or
  claims. It also confirms that the built-in copy matches this server: the
  tiers exactly as in `hardware_guides.py`, plus the models, diagrams and
  firmware envs. Without `--check`, the script rewrites only stale built-in
  data, in place. `tests/test_ui_builder_sync.py` enforces all of this and
  also checks the built-in copy against the API's actual responses.
- The rebuild also brings in the other pi-ui and design-package changes made
  in the monorepo since the previous `ui/dist` (cloud#73), from the v5.0.0
  release work and the fixes after it.
- **`ui/dist` rebuilt again: the Builder page fits a phone, and the Shopping
  List shows your build.** Checked in Chrome on every tier and tab, from 320
  to 1600 px wide: nothing sticks out of its box and the page never scrolls
  sideways.
  - Wiring: the tier diagram scales to its box's width, with an "open full
    size" link. If the Pi's SVG does not load, the page shows the same
    generated diagram from the bundle instead of the old hand-drawn sketch,
    which clipped labels, put pin labels under wires and cut off the legend.
    The firmware-file table scrolls inside its own box; the BOM and
    connection tables stack as cards on narrow screens (third rebuild below).
  - Setup: the backticked commands, paths and topics show as code with a copy
    button. On a plain-http Pi the button falls back to `execCommand("copy")`.
    Copying or selecting text no longer ticks the step. Ticks are now stored
    per step id instead of per position, so adding a step no longer moves
    them. Ticks saved by the released dashboard are carried over to the
    matching new steps.
  - Firmware: each image card lists the `pio run -t upload -e <env>` command
    for each board, with copy buttons.
  - "Send BOM to /shopping" now hands the tier and chamber count to the
    Shopping List. That page no longer shows demo rows or a restock banner:
    it lists the sent BOM (live from `/api/builder/tiers/{id}`, totals equal
    to the Builder's), grow supplies for each species with an active session
    (`/api/species/{id}/shopping-list`), and your custom items.
  - Below 768 px the navigation rail becomes a drawer behind a menu button,
    on every page.
- **`ui/dist` rebuilt after a second browser audit.**
  - Tables on Sessions, Transcripts, Inventory, Cultures and Contamination
    now scroll inside their own column. From 1180 to about 1600 px they ran
    under the right-hand panel.
  - Sessions shows a new session as day 0 (it showed "20710d"), and it
    counts toward the 30-day yield.
  - Timeline tags name the event (NEW, PHASE, …) instead of truncating it
    ("SESSI").
  - The transcript preview renders bold, italic and code. Species show their
    common names.
  - The CLOUD KPI no longer breaks mid-word.
  - The Shopping List's hardware tables now line up, and below 900 px each
    row becomes a card. "Open in builder →" keeps the build and chamber
    count.
  - Builder firmware file names are their download links, so the table fits
    a phone.
  - The wiring cards show a thumbnail with a readable "full-size svg →"
    label.
  - Single-column model cards no longer leave blank bands.
  - Cost captions use whole dollars, and the stale "Pi's estimate" clause is
    removed.
- **`ui/dist` rebuilt after a third browser audit.**
  - Pack-sold parts show units and the whole packs that buy them ("×4 · 2
    packs of 2", "$5.49 / pack of 100 · ~$0.05 ea") on the Builder's Shopping
    tab, the Shopping List and its CSV. Totals equal `parts_cost(N)` at every
    chamber count; the caption splits shared from chambered parts and says
    what whole packs save. The Overview counts BOM lines and units
    separately.
  - Builder: below 900 px the BOM and wiring-connection tables stack as cards
    instead of scrolling (the Buy link and wiring notes were cut off between
    1024 and 1340 px). The tier and chamber count stay in the URL, "Send BOM"
    is a real link (`/shopping?bom=…&chambers=…`), and offline the camera
    firmware card lists `cam_policy.h` as well as `main.cpp`.
  - Shopping List: one message when the sessions can't be read; a hand-set
    grow count shows as an override with a reset; a count change refetches
    only that species; the two 404s are told apart; the CSV defuses every
    formula-like cell (`-1+2`, a leading tab); custom items validate their
    name and link inline.
  - The phone drawer is a modal dialog (focus kept inside, page behind it
    inert, focus restored on close).
  - Species cards size to their content; Contamination pills follow one
    severity ladder (critical red, high amber) and list every entry; Sessions
    show the session name; Sessions and Transcripts pin their row action
    instead of scrolling the page; long automation conditions wrap.
- **`ui/dist` rebuilt after a fourth browser audit.**
  - The Builder and the Shopping List buy the per-chamber kits above in whole
    packs (`shared_units` included), so totals equal `parts_cost(N)` at any
    chamber count from 1 to 99: Bare Bones ×10 now buys two packs of M3
    inserts for 104. A count outside the presets shows as its own "×7" pill
    next to a − / + count box. Tier cards price the chosen count ("47 lines ·
    ~$1,733 for 4 chambers"), and the chamber caption names what is bought
    once: the Pi side, the bench breadboard and bulk packs that cover 12+
    chambers.
  - The Shopping tab, the Shopping List and its CSV word quantities one way
    ("4 · 2 packs of 2 · 1 spare"), and "(shared)" shows at every chamber
    count.
  - The wiring SVGs are their own 173 kB chunk, fetched only when the Wiring
    tab opens. The main bundle is 1,112 kB (323 kB gzipped), down from
    1,258 kB (340 kB). `tests/test_ui_builder_sync.py` follows references
    from `index.html` through the bundle, so that chunk and its source map
    count as shipped assets.
  - Offline, the Firmware tab lists files from a listing generated from this
    repo (raw GitHub links and sizes) instead of a hand-copied list.
  - Model cards end a cut description on a whole word, and "more" reads the
    full header from the `.scad` file (the Pi's download first, then GitHub).
  - Shopping List: notes grow with their text and print in full; a print
    stylesheet hides the navigation and prints dark on white; ticks and notes
    follow a part across builds; grow supplies are merged across species, one
    row per item (spawn stays one row per species).
  - Species: the 8 novelty species get a filter chip, so the category KPI
    adds up to the 74 shown; KPI labels fit one line; tags collapse to the 12
    most used behind an "all 129 tags" toggle; an opened card expands in
    place, so Tab order matches the screen. Contamination's upload buttons
    wrap at 390 px.
- **`ui/dist` rebuilt after a fifth browser audit.**
  - A printed Shopping List is a table again: the card layout (under 900 px
    of table) is screen-only, so a Letter or A4 sheet no longer prints one
    tall card per row (a 4-chamber list ran to 20 pages). The Buy column and
    the "notes & substitutes" disclosure stay off paper, cells are tighter
    and the columns size to their content.
  - Lines counted in something other than pieces say so (new optional API
    field `Component.unit`): "420 ft · 5 packs of 100 ft · 80 ft spare",
    "$26 / pack of 100 ft", "~$0.26 / ft"; the WAGO assortment reads "12
    chamber sets · 4 packs of 3 chamber sets"; solder in grams, VELCRO in
    straps, the insert and screw kits in the size they are counted in. The
    Overview counts packs and parts to buy instead of adding feet, grams and
    pieces, and uses the Shopping tab's "shared, bought once" caption. The
    CSV writes "×N" and "(shared)" as the table does, one supplier URL per
    cell, and "lb" for every pound.
  - The zip ties, heat-shrink, grommets and 18" duct ties are bought per
    chamber in whole packs (above), so a 17–99-chamber list no longer
    under-buys them.
  - Two open Shopping List tabs stay in step: a tick, note, custom item, grow
    count or build sent in one shows in the other, and every change is
    written into what is stored, so one tab no longer undoes the other's.
  - A link's out-of-range `?chambers=` opens on 99 instead of 1, and the URL
    says what the page shows; an unknown `?bom=` says so.
  - The sidebar footer (version, uptime) is no longer clipped; the Shopping
    List's note column is a fifth of the table; Species folds its filters
    behind one "filters" button on a phone, so the first card is on the
    first screen; a contamination check without a Claude key says so in
    words and links to Settings, and the log stacks on a phone.
  - A species with a session (`lions-mane`) and the same species picked by
    hand (`lions_mane`) is one grow target on the Shopping List, not two;
    an unknown `?bom=` link warns on a full page load too; the Overview's
    cost caption reads like the BOM totals at ×1.

### Enclosures (`models/`)
- **All 10 models re-fit** to sourced drawings (vendor drawings, STEP files,
  Eagle boards) and fit-checked in OpenSCAD against dimensioned proxies; every
  part and preset renders manifold with Manifold. Nothing has been printed
  yet; estimated dimensions are listed per model.
- **Brass heat-set inserts** join every multi-piece enclosure
  (`models/lib/sp_inserts.scad`: ruthex / CNC Kitchen sizes, pocket + boss +
  clearance helpers, `SP_INSERT_HOLE_TWEAK`, `SP_FASTENER="self_tap"` fallback).
  `models/README.md` has the per-part and per-tier shopping list.
- `pi_case` (Pi 5 + Active Cooler, full-height insert bosses, Pi 4 does not
  fit); `esp32_case` (narrow USB-C default, `devkitc_v4` / `wide_usbc` /
  `s3_devkitc1` presets, header clearance, lid over the USB receptacle);
  `sensor_mount` + `sensor_bracket` (current STEMMA QT board outlines, a QT
  cable gallery, insert-held lid, `scd30=true` on both); `cam_mount`
  (CAM + MB stack, IO0/RST reachable through side slots, M5 pivot insert);
  `hx711_scale` (Adafruit 4541 bar75 default + `tal220`, Adafruit 5974 /
  SparkFun / generic boards, recessed board inserts down a Ø5.2 access bore,
  × 10 or × 12 board screws); `pump_bracket` (bolts through the pump flange,
  presets `adafruit_1150` / `kamoer_nkp` / `universal`); `relay_board_mount`
  (through-hole chassis for 4 IRLZ44N channels with 100 Ω, 10 kΩ, DO-41 and
  KF301 footprints, `node="relay"|"lighting"`); `power_supply_mount` (Facmogu
  5 A / 10 A and other brick presets, strap retention); `fan_duct` (71.5 mm
  NF-A8 pitch, M4 inserts).
- Model downloads (`GET /api/builder/models/<file>.scad`) inline `lib/`
  includes so a single file renders on its own; `models-bundle.zip` ships the
  repo layout.

### Firmware (see `firmware/CHANGELOG.md`)
- Camera detects **OV2640 / OV3660 / OV5640** and tunes per sensor; flash stays
  on through the exposure; uploads default to the portal's Pi address; HTTPS
  uploads require the pinned Pi CA.
- **Reed invert** (portal checkbox / `cmd/config {"peripherals":
  {"reed_inv": true}}`) for door contacts wired on NO.
- New env **`node_esp32s3_n32r16v`** for the ESP32-S3-DevKitC-1-N32R16V (same
  pin map as `node_esp32s3`), built by CI and shipped as
  `node_esp32s3_n32r16v.zip` in every release (`node_esp32s3.zip` does not
  boot on that board).
- Heartbeat on its own clock (min(publish interval, 5 min)); Secure MQTT never
  downgrades silently (`tls_downgrade` alert, CA-fetch retries, optional
  "Require TLS"); heartbeat `tls` and `board` keys.
- **Secure MQTT verifies before it pins.** A fetched CA is only a candidate:
  the node tries TLS on 8883 with it from RAM and writes it to NVS only after
  the broker's CONNACK. A failed trial goes back to plaintext (or stays off
  MQTT with "Require TLS"), backs off, and the `tls_downgrade` alert says why
  (certificate name mismatch or another CA, 8883 unreachable, TLS error,
  login refused). A verified pin is final. A CA an older image pinned without
  this check is re-verified as a candidate. New optional heartbeat key
  `ca_fp`: SHA-256 of the pinned CA PEM.
- The camera's setup portal no longer shows the node-personality select.
- Safety: `aux` max-on 60 s by default and per-channel `max_on_sec`; an explicit
  OFF wins over `pwm`/`level`; 10-min MQTT-loss safe mode; channels off at OTA
  start; OTA rollback on node and camera.
- The setup AP no longer opens on a WiFi hiccup (BOOT / GPIO 13 gesture
  instead); replay guard + topic binding on signed commands; portal node-id and
  password-keep rules; epoch `ts` + `"replay": true`; latched alerts; sensor
  staleness alerts; exact library pins (PubSubClient 2.8, ArduinoJson 7.4.3).

### Added
- `POST /api/hardware/nodes/{id}/peripherals`
  (`{"mhz19"|"hx711"|"reed"|"reed_inv": bool}`) sends a signed `cmd/config`;
  the node reboots ~1.5 s later if its driver set changed. `reed_inv` (a door
  contact wired on its NO terminal) applies live, so the endpoint takes every
  key the firmware does.
- Overdue-phase reminders: a daily 09:00 (container-local `TZ`) INFO "Phase
  check — <session>" for each grow past its phase's expected duration
  (`phase_reminders` task).
- Settings: `SPOREPRINT_VISION_AUTO_INTERVAL_MIN` (default 360),
  `SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS` (default false),
  `SPOREPRINT_PUBLIC_UI_URL`, `SPOREPRINT_CLAUDE_MODEL` (default
  `claude-sonnet-5`; every Claude feature), `TZ`, `FORWARDED_ALLOW_IPS`. Every
  `Settings` field is now forwarded by compose (enforced by a test).
- Vision: frame retention (30 days, then one frame per camera per day; flagged,
  labelled and referenced frames kept); `X-Camera-Sensor` stored as the node's
  `camera_sensor` and named in the Claude prompt; harvest-window INFO
  notification; contamination events recorded with `source='vision'`.
- Tasmota plugs also update from `stat/RESULT` and `tele/STATE` JSON
  (`POWER` / `POWER1`); Shelly and Tasmota plugs register on their first state
  report.
- `docs/auth.md`, the S3 pin map and troubleshooting rows in the build guide,
  and `server/tests/test_docs_consistency.py`, which pins the README, build
  guide, SVGs and AGENTS.md to the code, firmware and BOM.

### Changed
- **Signed node commands** carry two more signed members, `topic` and a random
  `nonce`: current firmware rejects redirected frames and no longer drops a
  legitimate identical command in the same second. Deployed firmware verifies
  them unchanged.
- **OFF is never published with `pwm`/`level`** (rules, manual node commands,
  cloud commands), and every published OFF — manual node, cloud, session-end
  safing, manual plug — clears that actuator's `safety_max_on_seconds`
  ceiling.
- Automation: the highest-priority rule whose condition holds owns an
  actuator; ceilings count from the first ON and a trip locks automation out
  for 15 min (WARNING page, CRITICAL if the OFF fails); life-safety rules
  (priority ≥ 20, absolute thresholds) run with no session; species-scoped
  rules match `lions-mane` and `lions_mane`; redundant OFFs to unpaired plugs
  are skipped, and a repeat OFF is re-sent only every 15 min unless something
  switched the actuator back ON — a manual, cloud or plug command, or a node
  reporting the channel ON, drops that suppression so the cutoff rule re-sends
  its OFF at the next evaluation; cron catch-up; scheduled FAE runs only when
  the phase's `fae_mode` is scheduled or continuous; new `profile_ref` `temp_mid_f`;
  `growth_form` antler/conk picks the CO₂ params; `bulk_bag` is sealed until
  fruiting; the rule `notification` flag now pages (WARNING < priority 20 ≤
  CRITICAL). Seeded templates are upgraded on boot unless edited (a WARNING
  names each edited copy). An edited Pre-cool or Heat Wave rule with no
  chamber-temperature condition now holds the cooler ON against Cooling
  Cutoff — add a `temp_f` condition. The Humidity Boost/Cut and Dry Weather
  rules carry 1800 s ceilings: a humidifier that needs more than 30 min to
  cross the band trips one (raise `safety_max_on_seconds` if yours is slow).
- Sessions: `POST /api/sessions` and `/phase` return 422 for an unknown phase
  or one the species can't enter; missing primordia/fruiting/rest setpoints
  borrow from each other; `next-phase` skips phases the species lacks; ending
  a grow safes the actuators it drove (per chamber when several grows run);
  phase history stores `params_snapshot`.
- Which grow a node belongs to is chamber-aware: a listed node belongs to its
  chamber's grow, an unlisted node to the newest chamberless grow. With grows
  in two chambers, list every node in its chamber.
- Node liveness: any telemetry frame from a registered node refreshes
  `last_seen`, so nodes on a 15 min–1 h publish interval no longer flap
  offline.
- Telemetry: `ts < 1e9` is treated as unsynced; replayed (`"replay": true`)
  and out-of-order frames (up to 120 s older than the node's newest live
  frame; a bigger step back is the node's clock being corrected and
  re-baselines) are stored but not evaluated or pushed live; readings are
  tagged with their grow; history charts fall through every rollup tier. The
  Pi's own clock
  never decides whether a frame is live: a Pi clock running minutes fast no
  longer silently stops automation and safety thresholds for every synced
  node. Pi-vs-node clock skew is measured per node, logged as a rate-limited
  WARNING past 120 s, and reported (with non-live frame counts) under
  `reliability` in `GET /api/health/detail/system`.
- Notifications: ntfy is published through its JSON API (titles with em dashes
  or °F now arrive); identical CRITICAL pages collapse for 15 min; temperature
  and humidity EMERGENCY pages dedupe per node, parameter and direction; node
  alerts reach ntfy by tier.
- Vision auto-analysis runs every 6 h per session (and on the first frame after
  a phase change) instead of every capture; the local CNN is still a stub.
  Contamination pages CRITICAL at confidence ≥ 0.6 and sends one "Possible
  contamination" WARNING at 0.3–0.6; stored frame names are unique and carry
  the real image type; a failed re-analysis never overwrites a stored one;
  `POST /api/contamination/identify` returns 415 for non-image uploads.
- Claude: every feature uses `SPOREPRINT_CLAUDE_MODEL`; output ceilings are
  16,000 tokens (32,000 streamed for the Builder). A refusal or truncated
  answer returns `{error}` (Builder: `truncated: true` plus the partial guide,
  not saved) instead of a 500 or a half-saved result.
- Weather: forecast alerts fire only once the weather→closet model is trained
  (~7 days), ignore past hours and dedupe per session, kind and day;
  `forecast_high_f` / `forecast_low_f` cover today's local day; the prediction
  model trains on 30 days; Open-Meteo times parse as UTC.
- Transcripts: per-phase telemetry summaries are filled from rollups for old
  phases; unknown session ids return 404; session analysis sends at most 150
  vision summaries.
- Sessions and species: chamber `PATCH` with `active_session_id: null`
  detaches; chambers with history can be deleted; iCal dates anchor at the
  first phase; the pink-oyster harvest page is CRITICAL; the substrate
  calculator and shopping list scale correctly; species setpoints match
  CLAUDE.md §4b (pink oyster, cordyceps, king trumpet CO₂);
  `POST /api/experiments/{id}/analyze` is the preferred route.
- Integrations: sending back a masked `••••last4` secret (or omitting it)
  keeps it, `""` clears it — but a kept secret stays bound to where it is
  sent: changing a driver's `secret_bound_fields` (`base_url` for Aranet,
  Agrowtek and BIOS) without re-entering the secret returns 422, so a config
  PUT can no longer redirect a stored key to another host. A lost or changed
  `.integration-key` shows "re-enter the credentials";
  vendor health transitions that happen while the cloud link is down are
  retried until delivered.
- `GET /api/provision/ca` is public in API-key mode, so Secure-MQTT nodes can
  fetch the CA; in that mode `GET`/`POST /api/cloud/pairing-code` now need the
  bearer, and a keyless `POST /api/vision/frame` is accepted only from a
  registered camera with a declared Content-Length ≤ 20 MB.
- Cloud pairing credentials persist to `cloud.env` beside the DB (0600) and
  survive rebuilds; `cloud_url` must be `https://`; `integrations_request`
  frames are replay-deduped and, after the first signed one, must be signed.
- `POST /api/automation/plugs/{id}/command` returns 409 for an unknown or
  unpaired plug and 503 when the broker is down; `POST
  /api/hardware/nodes/{id}/command` returns 503 when nothing was published.
- `POST /api/builder/guide` returns 503 (`not_configured`) or 502 (refusal,
  truncated, empty, upstream error) with the body fields unchanged; firmware
  ZIPs include `library.json`, `VERSION.txt`, every partition table and the
  version script, and never bundle a private-looking `extra_configs` file.
- Socket.IO rate limiting and client tracking use each client's real address
  (uvicorn `--proxy-headers` behind nginx).
- Nightly retention also prunes session-less `automation_firings` older than
  90 days and thins vision frames; new index
  `idx_rollup_node_sensor_time` speeds long-range charts.

### Security
- **DNS-rebinding guard.** The API and Socket.IO answer only for Host names an
  outside attacker cannot point at the Pi: private, loopback, link-local,
  CGNAT (Tailscale) and IPv6 unique-local IP literals; `localhost`, `*.local`,
  `*.lan`, `*.home`, `*.home.arpa`, `*.internal`, `*.localdomain`; dotless
  names; the host of `SPOREPRINT_PUBLIC_UI_URL`; and the new
  `SPOREPRINT_ALLOWED_HOSTS` (comma list of names, `*.suffix`, IPs or CIDRs;
  `*` turns the check off). Anything else gets **421** with the setting to
  change. `GET /api/health` and `GET /api/provision/ca` stay open. Reach the
  Pi by a public DNS name (Tailscale MagicDNS `*.ts.net`, a reverse-proxy
  domain)? Add it to `SPOREPRINT_ALLOWED_HOSTS`.
- **Stored integration secrets stay bound to their destination** (see
  Integrations above): a config `PUT` that changes `base_url` must re-enter
  the key.
- **Broker service accounts never become nodes.** Frames under
  `sporeprint/<id>/…` for `server`, `sp-3p`, `sp-cmd`, `sp-telemetry` or the
  Pi's own MQTT user are dropped (WARNING once) before registration or rule
  evaluation, `POST /api/hardware/claim` refuses those ids, and node rows an
  older server registered under them are deleted when MQTT starts. A leaked
  smart-plug credential can no longer register a node, claim a node type or
  feed the rules engine.
- **OTA connect-back peer check** (see Deploy): only the node being flashed
  can take the image.
- **Secure MQTT verifies before it pins** and reports `ca_fp` (see Firmware).
- A bearer token with non-ASCII bytes gets 401 instead of a 500 (the API-key
  check compares UTF-8 bytes, as the Grafana `/metrics` check already did).
- **`X-Forwarded-For` is trusted from one address only.** The ui and server
  containers share a fixed `edge` network (`SPOREPRINT_EDGE_SUBNET`, default
  `172.31.253.0/28`; ui `.2`, server `.3`), and `FORWARDED_ALLOW_IPS`
  defaults to the ui address instead of the whole `172.16.0.0/12` bridge
  range, whose gateway relays IPv6 and loopback clients of the published
  `:8000` that could forge the header. Move all four settings together if
  compose reports a pool overlap.
- `server/.dockerignore` keeps `data/`, SQLite files, `.integration-key` and
  `cloud.env` (the cloud device token) out of the image when the server was
  run from `server/`.

### Deploy
- `install.sh`: writes `TZ`, generates the command-signing key, issues the
  broker certificate with IP and DNS SANs for every host IPv4 (re-issued from
  the same CA when the IP changes), repairs Docker-created bind-mount
  directories, and prints the schedule time zone, signing status and
  smart-plug credential + Full Topic.
- `setup.sh` is a developer-workstation script (LAN-trust, no API key, IP
  SANs); `scripts/setup-pi.sh` wraps `install.sh`.
- `docker compose up` without `install.sh` fails loudly instead of creating
  root-owned directories; broker secrets are owned by the broker user; logs are
  capped at 10 MB × 3 per service.
- The broker ACL lets nodes publish log batches and coredump chunks and lets
  the server read `$SYS/broker/#`, so node logs, coredumps and
  `/api/health/detail/mqtt` fill in. The broker CA is mounted into the server
  container, so `/api/provision/ca` works under Docker.
- `provision-node.sh` writes the signing key to the repo-root `.env` (reusing
  an existing one); `add-node-mqtt-user.sh` mentions the key; broker password
  edits run inside the broker image and reload the `mqtt` service.
- Pi-pushed node OTA uses fixed TCP port 3233 (published in compose), runs one
  push at a time and retries invitations. The connect-back listener accepts
  only the node being flashed: another LAN host that connects first is logged
  and closed, and can no longer take the image and report a fake success.
  `generate-ota-keypair.py` creates the private key 0600 atomically.
- Images pinned: `eclipse-mosquitto:2.1.2-alpine`, `binwiederhier/ntfy:v2.28.0`,
  `nginx:1.30.5-alpine` and `python:3.12.14-slim` by digest. The server image
  installs exactly `server/uv.lock` (hash-checked).
- `rotate-mqtt-creds.sh` writes only the `server` password into `server/.env`;
  the other shared passwords stay in the repo-root `.env`.
- Pi OTA: the Docker install refuses cloud self-update; downgrades are refused;
  bundle extraction applies tarfile's `data` filter.
- The dashboard's nginx passes request bodies up to 21 MiB and gives `/api/`
  a 180 s timeout.

### Dependencies
- anthropic 0.94 → 1.8, fastapi 0.135 → 0.141, starlette 1.0 → 1.7 (Host-header
  bypass of the API-key gate fixed), cryptography 45 → 50.0.1, pillow 11.3 →
  12.3, uvicorn 0.54, python-multipart 0.0.32, python-socketio 5.17 /
  engineio 4.14, pydantic-settings 2.15. `server/uv.lock` regenerated (it was
  missing four runtime dependencies).
- GitHub Actions pinned to commit SHAs at current majors; PlatformIO 6.2.0 in
  CI and release; the release job alone gets write access.

### Fixed
- Transcript markdown (`GET /api/transcript/sessions/{id}/transcript?format=markdown`)
  no longer prints Python `None` for unset session fields. The header used
  `session.get(key, 'N/A')`, but a NULL column is present with value None, so
  it printed lines such as `**Substrate**: masters_mix (None)` and
  `**Inoculated**: None (None)`. A missing value now drops its line, and a
  missing detail drops its parentheses. The header fields are a list
  (`- **Species**: …`), so they render on separate lines in any markdown
  viewer.
- Plugs following the build guide never registered (missing Full Topic and
  credentials) — docs, Builder steps and the install summary now say both.
- Tapo local KLAP handshake (real devices authenticate), Kasa multi-segment
  replies, Wemo port probing (49153/49152/49154/49155/49151, `host:port`
  pins), Pulse session reuse, Grafana contamination counter.
- Upgrading a database created before v3.3.0 no longer crashes `init_db`.
- The server boots when `server/.env` holds keys that are not settings (a copy
  of the repo-root `.env` with `TZ` or `FORWARDED_ALLOW_IPS`) and when a
  non-string setting is present but blank (`SPOREPRINT_PORT=` means the
  default). A malformed non-blank value still fails loudly.
- The Tapo KLAP `set_power` integration test is no longer `xfail`.
- The CHANGELOG's earlier unreleased model entries (TAL220-only scale, saddle
  pump clamp, "Adafruit 1150 = Kamoer" wording) are superseded by the
  enclosure work above: Adafruit does not name the pump's OEM.

## [5.0.0] - 2026-07-16

Production-wiring release, in lockstep with the cloud repo (v5.0.0). The Pi
server grows the endpoints the cloud-web + mobile surfaces needed to stop
rendering fixtures, the automation engine gains remote pause/suspend plus a
bounded manual override, and self-hosting becomes a single command. Firmware
is a version-only bump — no functional change (see `firmware/CHANGELOG.md`).

### Added
- **Pre-grow automation coverage** — `GET /api/chambers/{id}/automation-coverage`
  returns, per grow phase, the actuator requirements and whether each is
  actually satisfied by a paired actuator (with a named fallback, e.g.
  vent-with-fans for a missing dehumidifier). Lets the UI warn before a grow
  starts that the hardware can't hold the species' targets.
- **Node discovery + claim** — `GET /api/hardware/discover` lists every LAN
  node the Pi has heard from (the heartbeat registry), tagged
  claimed/unclaimed; `POST /api/hardware/claim` adopts an unclaimed,
  heard-from node.
- **Dated grow-cycle proposal** — `propose_cycle` walks a species' real phases
  from an inoculation date into a contiguous dated calendar with per-phase
  setpoints and a projected harvest date; served as JSON at
  `GET /api/planner/propose` and as a calendar feed at
  `GET /api/planner/propose.ics`.
- **Remote automation control** — the engine gains `set_paused` (whole-engine
  pause, persisted to `user_settings`) and `suspend_rule` (expiring
  single-rule suspension), both drivable from the cloud relay via the
  `system` / `automation` command targets.
- **One-command self-host** — `install.sh` installs Docker + Compose,
  generates MQTT credentials + self-signed TLS, writes a LAN-trust `.env`
  (`SPOREPRINT_ALLOW_UNAUTHENTICATED=true` — the single-household posture:
  pi-ui calls `/api` same-origin with no bearer, while MQTT stays
  credentialed), and brings the stack up healthy. The Pi server also ships as
  a signed (Ed25519) OTA bundle, published by the cloud repo's
  `server-release.yml` to `updates.sporeprint.ai`.

### Changed
- **Vision auto-analysis on camera ingest** — a new frame at
  `POST /api/vision/frame` now schedules a throttled (15-min per session),
  BYOK-gated Claude pass that raises green-mold / Trichoderma contamination
  and harvest-ready alerts on its own, rather than only analyzing on explicit
  request. Gated on an active session and the operator's own Claude key.
- **Manual overrides are bounded and auto-resume** — every `ManualOverride`
  is clamped to a 24h TTL at construction (a null or over-long expiry can no
  longer pin an actuator forever), and expired overrides are swept back out
  automatically so the rules engine resumes control. The cloud actuator path
  routes through this via `target_kind="automation"`.
- **`docker-compose.yml` hardened** — healthchecks on server/mqtt/ntfy,
  `restart: unless-stopped`, a non-root server (`USER appuser`) with a
  one-shot `init-perms` volume `chown`, read-only bind mounts for config and
  certs, and a credentialed + ACL'd broker.

### Fixed
- **Species-id lookup drift** — `get_profile` now canonicalizes the `_` vs `-`
  separator, so a stored id resolves to its built-in profile regardless of
  spelling. A plain `WHERE id = ?` had missed 63 of 74 species and returned
  `None`.

## [4.2.0] - 2026-06-12

### Added
- **Firmware v2** — see `firmware/CHANGELOG.md` for the full entry: one
  unified node image + a camera image, portal-based provisioning,
  autodetecting sensors (incl. SHT4x family, SCD30, MH-Z19C, HX711, reed
  switch), opt-in TLS MQTT, a 69-case host-native test suite, and the v1
  defect class fixes (WDT-vs-portal boot brick, publish truncation,
  HMAC key corruption).
- Pi server consumes the firmware observability topics nothing ever read:
  node log batches land in a retained `node_logs` table (+
  `GET /api/hardware/nodes/{id}/logs`), coredump chunks reassemble to
  `data/coredumps/` with an alert on completion (+ list/download
  endpoints), and node OTA lifecycle events forward as `node_ota`.
- `GET /api/provision/ca` serves the broker CA for the firmware's
  trust-on-first-use TLS pinning; `setup.sh` generates the local CA +
  server certificate and mosquitto gains an 8883 TLS listener.
- Hardware guides + builder data updated to v2 reality: the SHT4x family,
  SCD30, and MH-Z19C flip from "needs firmware driver" to supported;
  Tier 3's load cell and reed switch are live features; the ESP32-S3
  DevKitC-1 gains a build target (bench verification pending); the reed
  wiring now documents the required EXTERNAL 10K pull-up (GPIO 34-39
  have no internal pulls — the old instructions were physically
  impossible).

### Changed
- Heartbeat ingestion refreshes `node_type` on every heartbeat and stores
  the v2 `roles` list; cloud command routing consults roles so a combined
  sensors+relay node receives climate-targeted commands. (The old upsert
  never updated the type — rows decayed to 'unknown' and type-routed
  commands quietly failed.)
- Firmware bundle downloads serve the v2 images (unified node + camera);
  v1 bundle slugs alias to the unified node so old links keep working.
- `docs/firmware-security.md` rewritten for the v2 model (command
  signing, TLS TOFU, provisioning, watchdog policy); the secure-boot /
  flash-encryption opt-in walkthrough is unchanged.

### Fixed
- docker-compose bound the MQTT broker to the host loopback — LAN nodes
  could never reach 1883 at all. The broker now listens on the LAN
  (credentials + ACL unchanged) alongside the new TLS listener.

## [4.1.6] - 2026-06-11

### Changed
- Hardware guides refreshed (June 2026 audit): the ESP32-WROOM-32 38-pin
  DevKit is the documented node board — it matches the firmware build targets
  (`esp32dev`) and the GPIO map in every wiring diagram. ESP32-S3 boards are
  explicitly marked unsupported until S3 build envs ship. The AI-Thinker
  ESP32-CAM is the documented camera board (matches the `esp32cam` build
  target and pin map).
- SCD41 sourcing notes updated — Adafruit 5190 is in stock again; the old
  "avoid Adafruit" advice removed. SHT31-D notes clarify that SHT4x-family
  sensors share the I²C address but not the command set, and are not
  drop-ins until a driver ships.
- Prices re-baselined across all tiers (including 2026 Raspberry Pi shortage
  pricing). Tier cost estimates recomputed: ~$180 / ~$350 / ~$540.
- Tier 3 load cell and reed switch rows now say "firmware support planned" —
  the relay firmware does not read them yet.
- Wiring diagrams: node labels corrected to ESP32-WROOM-32 / micro-USB
  (previously ESP32-S3 / USB-C); camera labels corrected to ESP32-CAM
  (OV2640). No pin assignments changed.
- `models/esp32_case.scad` defaults now fit the ESP32-WROOM-32 38-pin DevKit
  (28x52mm, micro-USB cable cutout); ESP32-S3 dimensions remain available via
  parameters. `cam_mount.scad` and `power_supply_mount.scad` notes updated
  (incl. Mean Well GST60A12 sizing parameters).
- `models/sensor_mount.scad` redesigned as a three-bay enclosure sized for
  the canonical Adafruit breakouts (SHT31-D, SCD41, BH1750) with wire
  pass-through notches for the I2C daisy chain and engraved bay labels —
  the previous two-bay version could not physically fit the SHT31-D or
  SCD41 boards it was documented for.
- Every printable model now carries an engraved SporePrint wordmark
  (previously only the relay mount was branded). All 8 models render
  clean — the earlier non-manifold warnings on cam_mount, fan_duct, and
  relay_board_mount are resolved.

### Fixed
- `sensor_mount.scad` lid ventilation holes were subtracted from a
  zero-size cube — a geometric no-op — so printed lids had no vents at
  all despite airflow over the sensors being critical for accurate CO2
  readings. The vents are now a real cut through the lid plate.
- Setup steps now instruct setting the Pi hostname to `sporeprint` (Raspberry
  Pi Imager advanced options) so ESP32 nodes can reach the MQTT broker at
  `sporeprint.local` out of the box.

## [4.1.5] - 2026-05-03

### Added
- Pi-side integration health sweeper + state-snapshot pusher (#38).
- Session events for vendor integration rule fires — the timeline now shows
  which vendor device was driven and how (#37).

## [4.1.4] - 2026-05-03

Pi side of the v4.1.4 release: automation engine fires vendor write actions, integrations RPC frames are HMAC-verified.

### Added
- `app/automation/models.py` — `RuleAction` gains `vendor_slug` / `vendor_action` / `vendor_params` (all optional, default None preserves v3.x behaviour).
- `app/automation/engine.py` — `_fire_rule` routes vendor-action rules through `app.integrations._actions.dispatch`; native MQTT path untouched. Failure handling matches the existing audit trail (`automation_firings` row updates to `status='failed'` with the error string).
- `app/cloud/integrations_proxy.py` — verifies HMAC-SHA256 signatures on inbound `integrations_request` frames using `app.cloud.signing.verify_frame` with the device's `cloud_token`. Bad signatures return `{success: false, status: 401}` with a precise reason field. Unsigned frames still accepted during the v4.1.4 rollout window.

### Changed
- Lockstep version bump with cloud parent v4.1.4.

### Notes
- **Vendor write actions inherit the existing safety surface.** Manual overrides (`manual_overrides` table) lock vendor targets the same way they lock MQTT targets — set `target = "vendor:<slug>"` to scope.

## [4.1.3] - 2026-05-02

Adds TP-Link Tapo as the third LAN smart-plug driver alongside Wemo and Kasa. Dual-transport (free local KLAP / premium tplinkcloud.com cloud), mirroring Pulse's hybrid shape. Lockstep with cloud parent v4.1.3.

### Added
- `app/integrations/tapo/` — driver, config, KLAP cipher implementation. `set_power` + `set_dim` write paths exposed via the unified vendor-actions dispatcher. SHA-1 in the user-hash is a TP-Link wire-protocol requirement (documented in `klap.py` and `.semgrepignore`).

### Changed
- `app/integrations/__init__.py` imports the `tapo` sub-package so it self-registers on boot.
- `app/integrations/_actions.py` advertises tapo's `set_power` + `set_dim` actions.
- `ui/dist/` rebuilt to ship the parent monorepo's Tapo schema + dual-transport UI.

### Notes
- **Live-device verification needed** — the KLAP handshake + cipher round-trip are unit-tested; on-wire behaviour against real Tapo firmware will be verified by operators with paired devices.

## [4.1.2] - 2026-05-02

Vendor write paths land across the integrations grid; two new free-tier smart-plug drivers ship end-to-end. Lockstep with cloud parent v4.1.2.

### Added
- **`app/integrations/_actions.py`** — single-map dispatcher for vendor write actions. Each driver advertises its writable actions in `VENDOR_ACTIONS`; the dispatcher filters payload kwargs to what the method accepts so stray fields don't blow up the call.
- **Write methods on every existing v4.1.1 driver**:
  - `set_dim(fixture_id, percent)` — Fluence, Fohse, BIOS.
  - `set_setpoint(target_c, mode?)` — Trane.
  - `set_setpoint(humidity_pct)` — Quest, Anden.
  - `set_output(output_id, value)` — Agrowtek.
- **Wemo driver** (`app/integrations/wemo/`) — UPnP/SOAP on TCP/49153. On/off control + Wemo Insight power-monitoring poll. SOAP envelopes inline; no new pip dep.
- **Kasa driver** (`app/integrations/kasa/`) — encrypted JSON on TCP/9999. XOR cipher (rolling key seeded at 0xAB) implemented inline; round-trip tested. On/off + dim (HS220) + emeter power-monitoring.
- **Cloud RPC handler** at `app/cloud/integrations_proxy.py` learns a new `vendor_action` action type that forwards inner-action + payload to the dispatcher, so cloud-web writes route through the same Socket.IO futures map as reads.
- **`docs/integrations/smart-plugs.md`** — operator-facing setup for Wemo + Kasa plus the full vendor-actions table.

### Changed
- `app/integrations/__init__.py` imports `wemo` + `kasa` so they self-register on boot.
- `ui/dist/` rebuilt to ship the parent monorepo's vendor-actions UI block + the Wemo/Kasa schemas.

### Notes
- **Write paths join the same "needs live-device verification" caveat as v4.1.1 reads.** Tolerant pydantic + dispatcher payload-filter mean unknown shapes degrade gracefully; refinements based on real hardware are additive.

## [4.1.1] - 2026-05-02

Adds seven new vendor drivers as defensible skeletons covering the Growlink-style lighting / HVAC / controller surface. Lockstep with cloud parent v4.1.1.

### Added
- **`server/app/integrations/_http_skeleton.py`** — shared `HttpVendorDriver` base. Subclasses override `poll_once()` and `test_connection()`; the base handles asyncio task lifecycle, idempotent start/stop, and `disabled → ok → degraded → error` health transitions.
- **Seven new vendor drivers** (each in its own `app/integrations/<slug>/` subpackage):
  - **Agrowtek GCX** (free, LAN HTTP) — controller bridge polling `/api/sensors`.
  - **Trane Nexia / BAS** (premium, cloud) — HVAC telemetry against `mynexia.com`.
  - **Fluence FluenceID** (premium, cloud) — fixture telemetry.
  - **Quest dehumidifier** (free, LAN HTTP) — temperature / humidity / setpoint.
  - **Anden dehumidifier** (free, LAN HTTP) — same shape as Quest plus power monitor.
  - **Fohse FohseConnect** (premium, cloud) — fixture telemetry.
  - **BIOS Lighting** (free, LAN HTTP) — fixture dim / power / temperature.
- **`docs/integrations/lighting-hvac-skeletons.md`** — operator-facing overview of the skeleton approach, per-vendor notes, what's NOT in v4.1.1, workflow for refining a parser when an operator hits live hardware.

### Changed
- `app/integrations/__init__.py` imports the new vendor sub-packages so they self-register on boot.
- `ui/dist/` rebuilt from the parent monorepo's `frontend/packages/pi-ui` so the compiled LAN UI's `/integrations` page renders the new vendor schemas.

### Notes
- **Live-device verification needed.** Vendor API shapes inferred from documentation only. Tolerant pydantic models accept payload-shape variance; `test_connection` surfaces transport errors verbatim. Operators with paired hardware should report unexpected payloads so the parser gets refined without shipping speculative code.
- **Read-only.** v4.1.1 ships the read side (poll → telemetry pipeline) of every new driver. Vendor write paths land in v4.1.x.

## [4.1.0] - 2026-05-02

First cut of the v4.1 third-party-integration grid on the Pi. Drivers run locally on each Pi; data stays on the LAN unless a vendor's API requires the cloud (premium-gated).

### Added
- **`server/app/integrations/`** — driver framework: `IntegrationDriver` ABC, encrypted-at-rest settings store (per-Pi Fernet key), registry-backed `/api/integrations/*` HTTP surface, lifespan boot with per-driver failure isolation.
- **Grafana / Prometheus exporter** (free) — `/metrics` endpoint in Prometheus text format with chamber/sensor/session/contamination/actuator metrics. Optional bearer-token gate.
- **Aranet PRO LAN poller** (free) — polls the PRO base station's local API and merges its sensors into the existing telemetry pipeline.
- **Pulse Grow dual-transport driver** (free local / premium cloud):
  - Cloud transport against `api.pulsegrow.com` with email + password (encrypted at rest, exchanged for session token on first poll).
  - Local transport with UDP discovery on the LAN broadcast (port 5683 CoAP convention) + per-device HTTP polling. Operators can skip discovery entirely with `local_device_urls`.
- **Cloud RPC handler** at `app/cloud/integrations_proxy.py` — listens for `integrations_request` events on the cloud connector socket, dispatches to local registry handlers, emits `integrations_response`. Powers the cloud-web mirror in the parent repo.
- **Per-vendor docs** in `docs/integrations/{grafana,aranet,pulse}/README.md` covering setup, troubleshooting, and operator-facing contracts.
- **Starter Grafana dashboard JSON** at `docs/integrations/grafana/sporeprint-chamber-dashboard.json`.

### Changed
- `ui/dist/` rebuilt from the parent monorepo's `frontend/packages/pi-ui` so the compiled LAN UI ships the new Integrations page + sidebar entry.

### Notes
- **Pulse local-mode discovery probe needs live-device verification.** Parser is tolerant of unknown payload shapes (degrades to empty rather than crashing). Refinements based on real hardware will be additive parser branches in v4.1.x.

## [4.0.7] - 2026-05-02

Lockstep version bump in step with the cloud parent (Stripe price-ID build-arg fix on the cloud side) — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.6] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.5] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.4] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.3] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.2] - 2026-05-01

Lockstep version bump only — no Pi-side, server, UI, or firmware changes. v4.0.2 fixes a cloud-web middleware short-circuit that was 5xx-ing Railway's healthcheck on the v4.0.1 deploy.

## [4.0.1] - 2026-05-01

Lockstep version bump only — no Pi-side code, server, UI, or firmware changes in this release. All v4.0.1 deltas are in the parent cloud monorepo (cloud-web landing page, Dockerfile + start.sh runtime aliasing, middleware allow-list expansion, GHA deploy-job disable, jsdom lockfile sync, placeholder cleanup). The submodule pointer moves with the parent so `release-guard.sh`'s lockstep invariant stays green.

## [4.0.0] - 2026-04-30

Major version bump in lockstep with the cloud parent repo's v4 migration (Vite SPA at `/app/*` → Next.js 15 App Router at `/`). Pi-side scope this release: OTA progress event fan-out (archaeology #7), Ed25519 OTA signing helpers, Pi UI v4 dist bundle, and a `/simplify` pass on the cloud connector + settings router. No GPIO / I2C / PWM pin changes; firmware-specific notes live in `firmware/CHANGELOG.md#400`.

### Added

- **OTA progress events (v4 archaeology #7).** `server/app/cloud/ota.py` now emits per-step progress via a new `_emit_step()` helper that calls `forward_event("ota_step", payload)` on the cloud relay. Cloud parent persists each step into the new `ota_progress_events` Supabase table so the mobile app + cloud-web shell can render a real progress bar instead of polling for terminal success/failure. `_promote_and_restart` was split into `_promote` and `_restart_unit` so each phase emits its own event.
- **OTA signing helpers in `scripts/`** — `generate-ota-keypair.py` (Ed25519 keypair generator) and `sign-ota-bundle.py` (signs an OTA tarball with the operator's private key). The cloud parent verifies the signature before promotion via `PUT /settings/ota-pubkey`. Operator workflow documented in `docs/firmware-security.md`.
- **Pi UI v4.0.0 dist bundle** in `ui/dist/`, compiled from the parent monorepo's `frontend/packages/pi-ui/`. Pi-served LAN UI now matches the cloud-web design system (warm substrate palette, JetBrains Mono numerics, shared SporePrintMark canvas).

### Changed

- **`server/app/cloud/ota.py` simplified** — removed the unused `_promote_and_restart` back-compat wrapper after callers were updated to the split `_promote` + `_restart_unit` pair. Stripped narrational comment overhead (-136 LOC).
- **`server/app/settings_router.py` simplified** — removed five redundant `try/except Exception → 500` patterns that just leaked exception text instead of letting FastAPI's default error handler do the right thing (-26 LOC).
- **`server/app/cloud/service.py`** — `forward_event()` extended to accept the new `ota_step` channel alongside the existing telemetry/alert channels.
- **Lockstep v4.0.0 version bump** with the cloud parent. No Pi-protocol break; v3.4.x Pis interoperate with a v4 cloud and vice-versa for telemetry, command signing, pairing, and HMAC. Web-app surface URL change (`/app/` → `/`) is parent-only.

### Fixed

- (none — `/simplify` cleanup + additive OTA-step plumbing only.)

## [3.4.10] - 2026-04-24

Lockstep version bump — no Pi or firmware changes. Cloud-side parent repo introduced a `KVCache` protocol for ephemeral in-pod state so a future Redis migration is drop-in. Firmware build unchanged.

## [3.4.9] - 2026-04-24

Fresh archaeology sweep of v3.4.8 (`analysis/02-security.md` in the parent repo). All Critical, High, Medium, Low + operator-feedback items closed in one pass. Firmware grew real defense-in-depth at the MQTT layer; the cloud relay gained tier/ownership re-checks + rate limiting + `cmd_id` correlation; the Pi server got structured logs + split MQTT ACL + synced dependency pins. Firmware-specific narrative in `firmware/CHANGELOG.md#349`.

### Added

- **HMAC verification of inbound MQTT commands on every ESP32 node** (`sporeprint_common/frame_verify.{h,cpp}`). Closes Sentinel **C-1** — the cloud-signed chain now extends past the broker to firmware. Shared canonical-JSON serialization is byte-identical to the Python `signing.py`. Uses mbedtls (part of ESP-IDF — no new dep).
- **NTP sync at WiFi connect** so the 30-second replay window on firmware command frames is meaningful (`wifi_manager.cpp`).
- **`scripts/provision-node.sh`** — generates an HMAC key, writes to `server/.env`, prints the `pio run` commands to bake the key into each node's NVS via `-DSPOREPRINT_PROVISION_HMAC`.
- **`esp_task_wdt` on climate / lighting / cam nodes** (M-6). Parity with relay_node; timeouts tuned per node (30 / 10 / 60 s).
- **`esp_reset_reason()` + wifi/mqtt reconnect counters** in every heartbeat (`heartbeat.cpp`).
- **OTA lifecycle MQTT events** on `sporeprint/<id>/ota` (start / success / error).
- **Minimum 12-char OTA password** (L-6).
- **Split Mosquitto users**: `sp-cmd` / `sp-telemetry` / `sp-3p`. Replaces the single `server readwrite #` account. `scripts/rotate-mqtt-creds.sh` rotates them.
- **`docs/firmware-security.md`** — operator guide for secure boot v2 + flash encryption + signed OTA.
- **Firmware `VERSION.txt`** + `SPOREPRINT_FW_VERSION` build flag — no more hardcoded `"0.1.0"`. `scripts/bump.sh` keeps it in lockstep.
- **`firmware/CHANGELOG.md`** — firmware changes now have their own narrative.
- **`.github/workflows/firmware-ci.yml`** — `pio run` on all four envs for every PR touching `firmware/**` (Risk 15).
- **Unity test-harness scaffold** at `firmware/test/` (Prescription 6.3.14 — opens the path).
- **`/api/vision/frame` whitelisted** in the Pi ApiKeyMiddleware (L-9).
- **Structured JSON logs on the Pi** with contextvar-based `request_id` threading (`logging_config.py` + `_request_id_mw.py`). Debt 5.
- **`_task_registry` wired** — every long-running supervisor registers + transitions status. Previously declared but never called (Debt 4).
- **`DesktopShell` component** (`app/src/components/web/DesktopShell.tsx`) — shared shell for the 18 desktop pages. Migration tracker in `app/src/pages/web/README.md`.

### Changed

- **Relay command handler refuses bare `{}` payloads** (M-5). Previously defaulted `state=on, pwm=255`.
- **Case-insensitive `state` parse** in relay_node.
- **`millis()` wrap-safe `offAt` compare** (L-1).
- **Cam `server_url` allow-list** (H-1). Allowed: paired Pi LAN, `sporeprint.local`, `sporeprint.ai`, RFC1918.
- **Climate alerts emit separately** (Debt 6) — simultaneous conditions no longer collapse.
- **MQTT inbound buffer 512 → 1024 bytes** (L-2). Oversize frames now explicitly dropped with a Serial log.
- **`OfflineBuffer::BUFFER_FILE` constant removed** (Debt 10).
- **`safety_cutoffs` + `captureFail` + `captureSuccess` + `avgLatencyMs` counters now increment** (Debt 3).
- **Pi `pyproject.toml` gains upper-bound caps** on every dep to match cloud policy (L-3).

### Fixed

- **`mqtt_publish()` signs every cmd/\* frame** with `settings.mqtt_hmac_key` before publishing. Paired with firmware verify, the Pi↔ESP32 hop is now HMAC-authenticated end-to-end.

## [3.4.8] - 2026-04-23

Firmware CI hygiene — all four node builds now compile clean against a pinned `platformio/espressif32@6.13.0` platform. Pre-existing build breaks from mixed Arduino-ESP32 API usage fixed without changing any GPIO / I2C / PWM pin assignment. No protocol or runtime behavior change.

### Changed

- **`firmware/platformio.ini`:** pinned `platform = espressif32@6.13.0` (official, Arduino-ESP32 core 2.x). Previously unpinned — fresh `pio install` pulled whatever latest happened to be, and the code's mix of core-2.x and core-3.x APIs compiled against neither.
- **`firmware/src/relay_node/main.cpp`:** replaced core-3.x `ledcAttach(pin, freq, resolution)` with the core-2.x `ledcSetup(channel, freq, resolution)` + `ledcAttachPin(pin, channel)` idiom. GPIO assignments (`CHANNEL_PINS[] = {25, 26, 27, 14}`) unchanged.
- **`firmware/src/lighting_node/main.cpp`:** same PWM API swap. GPIO assignments unchanged.
- **`firmware/src/climate_node/main.cpp`:** ClosedCube SHT31D 1.5 `readSerialNumber()` returns `uint32_t` directly, not an `SHT31D` struct. Reworked the sensor-present probe to check the serial number is non-zero instead of inspecting a `.error` field that doesn't exist on the 1.5 API. I2C address (`0x44`) unchanged.

### Fixed

- All four PlatformIO envs (`relay_node`, `climate_node`, `lighting_node`, `cam_node`) build cleanly from a fresh `pio install`. Post-install dev setup also needs `python3 -m pip install intelhex` for esptool's bootloader-assembly step on macOS with Homebrew Python 3.14.

## [3.4.7] - 2026-04-23

Independent code-archaeology sweep. 12 fixes across firmware safety, server concurrency, UI error visibility, and ops hardening. No breaking protocol changes; mobile + cloud clients unchanged.

### Added

- **Toast notification system** — `ui/src/stores/toastStore.ts` + `ui/src/components/ui/Toaster.tsx`. Replaces 26 silent `.catch(() => {})` / `catch { /* ignore */ }` swallows across 13 pages/components. Fetch failures now log with context to the console and surface a dismissable toast in the UI. `reportFetchError(context, err, userMessage)` is the single entry point.
- **`allow_unauthenticated` config flag (`server/app/config.py`)** — explicit opt-in for running the Pi without `SPOREPRINT_API_KEY`. Default is `False`; the server refuses to boot when both the key is empty and the flag is false. When opted in, a loud startup WARNING replaces the silent LAN-trust behavior. `docker-compose.yml` defaults the env var to `false` — fresh stacks must set it to `true` explicitly or provide an api_key.
- **`_SESSION_UPDATE_COLUMNS` whitelist (`server/app/sessions/service.py`)** — defense-in-depth for the (already Pydantic-typed) update column set.
- **Docker healthchecks** — `server` (urllib → `/health`), `mqtt` (`mosquitto_sub` on `$SYS/broker/version`), `ntfy` (`wget /v1/health`). `depends_on` upgraded to the long form with `condition: service_healthy` so `server` waits for the broker to actually accept subscriptions and `ui` waits for the API to respond.
- **AbortController for Vision analyze** — `ui/src/pages/Vision.tsx` now cancels in-flight `POST /vision/frames/{id}/analyze` when the user clicks a different frame. `api.post`/`get`/etc. accept an optional `{ signal }` option. Prevents stale responses clobbering the newer frame's state.

### Changed

- **`sessions.update_session` collapsed from N-per-column UPDATEs to a single `UPDATE ... COALESCE(?, col) ...`** statement. Partial failure mid-loop can no longer half-write a row; also 1 DB round-trip instead of up to 12.
- **`automation.engine` — `_state_lock: asyncio.Lock`** guards read-modify-write spans on `_overrides`, `_rule_cache`, `_last_fired`. `_load_overrides_from_db` fetches into a fresh dict and atomically swaps under the lock so concurrent evaluators never observe a cleared cache. `get_overrides` expiry sweep is lock-protected.
- **`cloud.service` — `_replay_lock: asyncio.Lock`** guards `_seen_command_ids` OrderedDict. Check-and-insert is atomic; two concurrent frames carrying the same command id can no longer both pass the dedup test. Socket emit is done outside the lock.

### Fixed

- **Firmware FW-1 (`relay_node/main.cpp`):** MQTT `duration_sec` is now clamped to `[1, 3600]` seconds before computing the off-at deadline. Previously, a huge or negative payload could wrap the `millis()` arithmetic and latch a relay ON indefinitely — the worst failure mode for a heater/humidifier.
- **Firmware FW-2 (`relay_node/main.cpp`):** ESP32 task watchdog armed at 10 s. `loop()` resets on each iteration; any deadlock in MQTT/OTA/WiFi now triggers a reboot. Safe state on reset is all-channels-OFF (setup() enforces).
- **Firmware FW-3 (`wifi_manager.cpp`):** Captive portal now has a 10-minute timeout. An abandoned provisioning session reboots the node rather than leaving it stranded in AP mode forever.
- **Firmware FW-4 (`climate_node/main.cpp`):** `read_interval_ms` and `publish_interval_ms` MQTT payloads are clamped to sensible ranges (1s–10min read, 5s–1h publish) with Serial warn on out-of-range. A `read_interval_ms=0` payload previously would busy-loop `readSensors()` and starve the MQTT/OTA tasks.
- **README:** removed broken `ui/public/mushroom-logo.svg` `<img>` reference. Renamed two `CLAUDE.md` references to `AGENTS.md` (the file that actually exists in this repo).
- **Tests:** `server/tests/conftest.py` sets `SPOREPRINT_ALLOW_UNAUTHENTICATED=true` at import so the test process can boot under the new secure-by-default behavior.

## [3.4.6] - 2026-04-23

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.6 release-tooling fix — the parent repo added `scripts/sync-after-merge.sh` and a bump preflight to prevent submodule-pointer drift after rebase/squash merges on GitHub. See the parent repo's `CHANGELOG.md` for the full context.

## [3.4.5] - 2026-04-22

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.5 `/simplify` pass over the v3.3.10 → v3.4.4 window (batched `metric_active_alerts` reads on every telemetry ingest, parallelized daily-summary fan-out, bounded caches, routed `alerts/escalation.py` through its persistence layer, extracted RevenueCat REST helper, narrative-ID comment sweep). See the parent repo's `CHANGELOG.md` for the full list.

## [3.4.4] - 2026-04-22

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.4 `/simplify` cleanup pass (code-reuse consolidation, event-loop offloading for DNS, parallelized tier reconcile, dead-import/dead-comment sweep). See the parent repo's `CHANGELOG.md` for the full list.

## [3.4.3] - 2026-04-22

No Pi protocol or code changes. Version bumped in lockstep with the cloud-side v3.4.3 (`@xmldom/xmldom` CVE override in the mobile app's dependency tree).

## [3.4.2] - 2026-04-22

No Pi protocol changes. Version bumped in lockstep with the cloud-side v3.4.2 release (catch-up bump covering the gap-close + no-deferrals work that landed between v3.4.1 and this version).

### Changed

- **L-4 `_configure_token` multi-slot dict.** Pre-v3.4.2 carried a single `dict | None` global — a second parallel `/pair` would overwrite the first's token and invalidate it before the first client could `/configure`. Now keyed by token in `_configure_tokens` with TTL sweeps and a 32-entry hard cap. Parallel `/pair` sessions coexist; pair-spam attackers can't blow memory.

## [3.4.1] - 2026-04-21

No Pi-side functional changes. Version bumped in lockstep with the cloud repo's fifth-archaeology close-out — see the cloud CHANGELOG for v3.4.1 for the commercial-side fixes (SSRF guard on `/devices/pair`, tier-cache invalidation on downgrade, `_device_sids` race fix, Pi-emit event pass-through handlers, CSP tightening, AI quota race lock, and 20 new regression tests).

All Pi protocols (HMAC signing, pair-verify, MQTT auth, bearer API-key gate) remain byte-compatible with v3.3.3+ / v3.4.x clouds.

## [3.4.0] - 2026-04-21

No Pi-side functional changes. Version bump to stay in lockstep with the commercial cloud release (tier-model clarification on the cloud side — see the cloud repo's CHANGELOG for details).

### Changed

- `scripts/bump.sh` now matches the cloud-side bump script: auto-inserts a CHANGELOG skeleton for the new version, updates the README's `**Version:**` banner if present, and prints a doc-drift warning for any lingering `v${CURRENT}` references in README / docs.

### Documentation

- README banner rewritten to explain the new commercial/OSS split: the Pi repo stays AGPL-3.0 free software; cloud-relay/mobile/web-app are paid. Pi-standalone users are unaffected.
- Added historical release callouts for v3.3.3 / v3.3.4 that were previously only in the cloud repo's CHANGELOG.

## [3.3.4] - 2026-04-20

Cloud-side fourth-archaeology close-out — the Pi changes in this release are support endpoints for the cloud's updated pairing + command-signing flows.

### Added

- **`GET /api/cloud/pair-verify?configure_token=<tok>`** (`server/app/cloud/router.py`). Closes S-M-11: the cloud now calls this endpoint from its own network during `POST /devices/pair` to confirm the configure_token really was issued by this Pi. Prevents a hostile LAN host from tricking the mobile app into writing an attacker-chosen device_token into Supabase.
- Signing-frame rejection categories (`server/app/cloud/service.py`). The Pi now tags rejection reasons as `clock_skew`, `signature_mismatch`, or `bad_frame` so the cloud + mobile UI can distinguish a drifting RTC-less Pi from a real signature mismatch (P2-10 / E-2).

### Unchanged

- HMAC signing protocol, nonce-cache shape, bearer-token scheme, MQTT auth, OTA password gate — all stable since v3.3.1.

## [3.3.3] - 2026-04-19

Pi-side hardening for command-signing freshness + replay protection.

### Added

- Persistent replay-nonce cache — survives Pi reboots so a Pi that restarts mid-attack can't accept a previously-seen command id within its 30s HMAC window.
- `scripts/setup-pi.sh` now installs and configures `chrony` so the Pi's clock stays within ±30 s of the cloud. Prior: a Pi whose clock drifted (common after long power outages on an RTC-less unit) would silently reject signed commands as stale.

### Fixed

- Clock-drift rejections now log with enough detail for operators to tell "bad signature" apart from "your clock is wrong."

## [3.3.2] - 2026-04-18

Cloud-parity release following the second-pass archaeology audit. Pi-side hardening in v3.3.0/v3.3.1 was airtight; this release extends the same discipline to the rest of the system and closes the remaining audit items.

### Security

- **Nonce cache is now a real FIFO (P6).** `server/app/cloud/service.py::_seen_command_ids` switched from `set` with arbitrary `pop()` to `OrderedDict` with `popitem(last=False)`. A burst of >1024 distinct ids no longer lets an earlier id be replayed inside the 30s HMAC window.

### Fixed

- **Pi-local alerters forward to cloud push (P2).** `engine._check_safety_thresholds`, `vision.analyze_frame_claude`, and `main._node_liveness_sweeper` now call `forward_event(...)` alongside their local ntfy notification. Premium mobile subscribers actually receive push alerts when thresholds breach or a node goes offline. Prior: local ntfy fired, cloud push never did.
- **Safety watchdog survives Pi restart (P10).** A new `safety_watchdogs` SQLite table records each armed `safety_max_on_seconds` auto-off. On boot, `rehydrate_safety_watchdogs` re-arms watchdogs whose `expires_at` is in the future and publishes OFF immediately for any whose expiry elapsed while the Pi was down. Prior: a reboot with a heater ON left the actuator stuck ON with no watchdog.
- **`push_log.read` vs `is_read` inconsistency resolved (Q10).** The cloud layer standardized on `is_read` (matches CLAUDE.md); migration renames the column if an older deployment had `read`.

### Changed

- **Pi router raw-SQL refactor (P12).** `automation/router.py`, `vision/router.py`, `hardware/router.py` now delegate all DB access to service-layer helpers. New `hardware/service.py`; expanded `automation/service.py` and `vision/service.py`. Router files drop to ~100 LOC each. Closes 3 of the PV1-PV3 layering violations.
- **`manual_overrides` + `safety_watchdogs` share a transaction on override set.** Prior version held two separate connections concurrently and deadlocked under SQLite's single-writer contract; the watchdog cancel + DB delete now happen inline so the override + watchdog records stay coherent.

### Added

- `server/app/automation/service.py` — new CRUD helpers (`list_rules_with_created_at`, `get_rule`, `create_rule`, `update_rule`, `delete_rule`, `toggle_rule`, `list_firings`) extracted from the router.
- `server/app/hardware/service.py` — new module with `list_nodes`, `get_node`, `send_command` + the regex validators.
- `server/app/vision/service.py` — `get_active_session_id`, `insert_frame`, `update_analysis_local`, `update_analysis_claude`, `get_frame_by_id`, `apply_user_label`.
- `safety_watchdogs` SQLite table for persistent watchdog state.
- `server/tests/fixtures/signing_vectors.json` — shared golden-file fixture with the cloud side. Drift trips tests on whichever runtime moved.
- `server/tests/test_signing_golden.py` — asserts the Pi's `_canonical` + `verify_frame` match the fixture byte-for-byte.

### Migration

- **Apply database changes by restarting the server** — `init_db` creates `safety_watchdogs` automatically.
- **No breaking protocol changes** — v3.3.1 and v3.3.2 Pis interoperate with a v3.3.1 cloud; the command contract is unchanged.

## [3.3.1] - 2026-04-17

Incremental security release — closes S3 (cloud command signing) end-to-end.

> ### ⚠️ BREAKING CHANGE — v3.3.1 Pi requires a v3.3.1 cloud relay
>
> **The Pi now refuses unsigned command frames.** Consequences:
>
> - **v3.3.1 Pi ←→ v3.3.0 cloud**: every mobile-app command is rejected with `Signature check failed: missing signature`. Remote control is fully broken until both sides are upgraded.
> - **v3.3.0 Pi ←→ v3.3.1 cloud**: commands still execute (old Pi ignores the new signature field) but nothing is protected — the cryptographic guarantee only holds when both ends verify.
>
> Deploy both sides together. The HMAC key is the already-provisioned `device_token` from pairing — no new operator secret.

### Security

- **Cloud command frames are now HMAC-SHA256 signed (S3 full closure).** Every `command` frame forwarded by the cloud relay carries a `signature` field covering the canonical JSON form of the frame and a `ts` (epoch seconds). `cloud/service.on_command` verifies signature + replay window (`±30s`) BEFORE checking tier, command id, target, or channel. A compromised cloud relay, a third party with socket access, or anyone who has re-authed their device socket cannot forge commands without the Pi's `cloud_token`. Replaces the v3.3.0 defense-in-depth pattern (tier string + id LRU + target allowlist) as primary — those remain as second-line guards.

  New file: `server/app/cloud/signing.py` mirrors the cloud-side signer byte-for-byte.

  Regression coverage: `server/tests/test_cloud_signing.py` — tamper, wrong key, missing/stale/future `ts`, empty key, key-order stability.

### Migration

- **Both sides must be upgraded together.** An old Pi paired to a new cloud will refuse all commands (old Pi doesn't verify; new cloud sends signed frames that old Pi doesn't know about — but the Pi side gate is new, so "old" means pre-v3.3.1). A new Pi paired to an old cloud will refuse all commands (no signature present). There is no opt-out flag — this is the contract.
- **No operator action required beyond pulling both repos.** The shared secret (`device_token` / `cloud_token`) is already in place from pairing; nothing new to provision.

## [3.3.0] - 2026-04-17

Security + stability release closing every critical finding from an external code audit. **Upgrading is strongly recommended for any Pi running unattended.**

### Security

- **MQTT broker is no-anonymous by default.** `config/mosquitto/mosquitto.conf` now sets `allow_anonymous false`, a `password_file`, and a per-role `acl.conf`. `setup.sh` provisions the `server` credential on first run (random 40-char). Firmware nodes read their credentials from NVS via `MqttManager._connect` (`mqtt_user` / `mqtt_pass`). The broker is bound to `127.0.0.1` in `docker-compose.yml`; never expose port 1883 to the internet. Prior to this release, any device on the LAN could publish `sporeprint/relay-01/cmd/heater {state:"on",pwm:255}` directly to the broker and the relay would obey.

- **`/api/cloud/configure` requires a short-lived `configure_token`.** `/pair` now validates the 6-digit code (with an 8-attempt / 10-minute lockout) and issues a `configure_token` in the response. `/configure` rejects any request without a matching token, rejects values containing `\n` / `\r` / `=` (newline-injection defense), resolves the `.env` path from the package root (not process CWD, which `/` under systemd), and writes atomically via `tempfile + os.replace` with `chmod 600`. Prior: unauthenticated LAN POST could rewrite `.env` and plant arbitrary env vars on next restart.

- **Backend bearer-token auth (opt-in).** New `app/auth.py` `ApiKeyMiddleware` gates every `/api/*` route plus the Socket.IO `connect` handshake when `SPOREPRINT_API_KEY` is set. Whitelist: `/api/health`, `/api/cloud/pair`, `/api/cloud/pairing-code`. `setup.sh` generates a key on first run so fresh installs are authed by default. Closes free-Claude-billing exhaustion, API-key exfil-by-substitution on the settings router, and ntfy-topic hijack.

- **Vision upload path traversal closed.** `POST /api/vision/frame` validates `X-Node-Id` against `^[a-zA-Z0-9_-]{1,32}$` and asserts the resolved write path stays inside `vision_storage`. Prior: a header value of `../../etc/passwd_image` would attempt to break out of the storage dir.

- **Hardware command topic lockdown.** `POST /api/hardware/nodes/{id}/command` drops any caller-supplied `topic` field and constructs the topic server-side from the URL path. Channel must match the safe-charset regex.

- **Cloud command channel HMAC-signed (S3 — full closure in v3.3.1).** v3.3.0 hardened this with defense-in-depth (id-replay LRU, target regex, registered-target check). v3.3.1 closes the remaining gap: every command frame forwarded by the cloud relay is now HMAC-SHA256 signed over a canonical JSON form of the payload using the Pi's `cloud_token` as the key. `cloud/service.on_command` verifies the signature and a `ts` timestamp (30-second replay window) BEFORE any other check — a compromised relay or a third party with socket access cannot forge commands without the shared secret. The signing helper (`server/app/cloud/signing.py`) mirrors the cloud-side implementation byte-for-byte.

- **OTA password enforcement.** `OTAManager::begin` refuses to call `ArduinoOTA.begin()` when `ota_pass` is unset or equals the legacy default `"sporeprint"`. Nodes log a warning until the operator sets a strong password via the captive portal.

- **python-multipart bumped to `>=0.0.18`** to close CVE-2024-24762 (permitted by the previous `>=0.0.6` floor).

### Fixed

- **`safety_max_on_seconds` is now actually enforced (R15 / P14).** Previously the field existed on `AutomationRule` and was used by built-in templates, but nothing in the codebase ever turned an actuator off based on it. Now `_fire_rule` schedules a cancellable `asyncio.Task` (`_safety_auto_off`) whenever it successfully publishes `state='on'` with a non-zero `safety_max_on_seconds`. The task publishes `state='off'` after the declared delay and writes an `automation_firings` row with `rule_name='safety_max_on_seconds:<original>'` so the timeout is visible in the audit log. Pending watchdogs are cancelled when a subsequent rule publishes `state='off'` for the same `target:channel`, or when an operator sets a manual override (operator owns timing while the override is in place). New regression suite `test_safety_max_on.py` covers all four behaviours. Fire-risk closure.

- **Dead `server/app/websocket/` package removed (P11 / V19 / D1).** `register_events` and `broadcast_telemetry` had no callers — Socket.IO handlers and emits are centralised in `main.py` and the various service modules. The module was a trap for new contributors looking for "where do sockets get wired up." Gone.

- **Firmware uptime timestamps no longer corrupt history (DATA-1).** `mqtt._handle_message` treats any `ts < 2020-01-01` as firmware uptime-seconds (the `millis()/1000` written by the offline-buffer drain) and replaces it with the server's receive time. A counter (`uptime_ts_clamps`) surfaces on `/api/health/detail/system` so operators can see when it triggers. Prior: every WiFi reconnect on any node inserted 1970-epoch rows into `telemetry_readings`.

- **Automation audit log no longer lies during MQTT outages (SAFETY-2).** `_fire_rule` now inserts `automation_firings` with `status='pending'`, attempts `mqtt_publish` (which returns a bool), and only then updates the row to `status='sent'` (publish succeeded) or `status='failed'` with the error captured. Prior ordering was publish-first, log-second: during the 5-second MQTT reconnect window, the publish silently dropped but the audit row still recorded a successful fire.

- **Manual overrides survive reboots (SAFETY-1).** `manual_overrides` DB table is now the source of truth for `engine._overrides`. `set_override` / `clear_override` / `get_overrides` read-through and write-through; `ensure_overrides_loaded` hydrates the in-memory cache on first use and prunes expired rows. Prior: operator safety locks were RAM-only and silently evaporated on every Pi reboot.

- **MQTT consumer no longer dies silently (RELIABILITY-1).** `_handle_message` is wrapped in `try/except Exception` with `log.exception`. `start_mqtt` body is wrapped in a `while True` supervisor with a 5-second backoff and a restart counter exposed in the reliability metrics. Prior: a single malformed payload killed the subscriber until manual restart with no operator signal.

- **Critical alerters actually fire (OBS-1).** `temperature_alert` and `co2_alert` are now called from `engine._check_safety_thresholds` when readings breach phase ceilings by a safety margin (`temp_max_f + 5°F` / `co2_max_ppm + 1000ppm`). `contamination_alert` fires from `vision.analyze_frame_claude` when Claude reports `contamination_detected`. A new 60-second `_node_liveness_sweeper` in the lifespan task flips stale `hardware_nodes.status` to `offline` and calls `node_offline` once per outage (900s `last_seen` threshold). Prior: all of these alerters were defined but never called from anywhere in the codebase.

- **Retention rollup can't lose raw rows (DATA-3).** `_rollup_telemetry_5min / hourly`, `_rollup_weather_hourly`, and `_cleanup_old_rollups` now use `INSERT ... ON CONFLICT DO UPDATE` with weighted-mean merging (`(old_avg * old_count + new_avg * new_count) / total_count`; `MIN` / `MAX` kept monotonic; counts summed). Each rollup runs inside an explicit `BEGIN` / `COMMIT` / `ROLLBACK` block. Prior `INSERT OR IGNORE` + `DELETE` would delete raw rows that never made it into the aggregate when a retried run hit a pre-existing rollup row.

- **Cloud queue actually drops the oldest message on overflow (DATA-2).** `forward_telemetry` now `get_nowait()`s the stalest item, `put_nowait`s the new one, and increments `_queue_drops`. Count exposed via `get_cloud_status()`. Prior `except QueueFull: pass` silently discarded the newest payload without logging.

### Changed

- **`AsyncAnthropic` everywhere.** `vision`, `transcript`, `builder`, `contamination`, and `experiments` services use `anthropic.AsyncAnthropic(...)` with `await client.messages.create(...)`. Inline `import anthropic` hoisted to module top per AGENTS.md. Prior sync SDK froze the event loop for 3-15 seconds per Claude call, halting MQTT, telemetry, and Socket.IO during the freeze.

- **SQLite tuned for production.** `init_db` applies `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`. `get_db` re-applies connection-scoped pragmas on every acquisition. Referential integrity is now actually enforced — REFERENCES clauses were previously decorative.

- **`automation_firings` schema migration.** Added `status TEXT NOT NULL DEFAULT 'sent'` + `error TEXT` via `_add_column_if_missing`. New index on `status`. Historical rows remain readable as `status='sent'`.

- **`Settings.mqtt_username` / `mqtt_password` / `api_key`** — three new config fields. `.env.example` and `docker-compose.yml` plumbed accordingly.

- **`mqtt_publish` returns `bool`.** True when the publish landed, False when `_client is None` or the underlying publish raised. Callers can now tell success from silent drop.

- **Socket.IO `cors_allowed_origins="*"` is now explicitly justified in a comment** — the connect-handler auth check (`app.auth.socketio_auth_ok`) is the confidentiality gate. With `SPOREPRINT_API_KEY` unset, LAN attackers can still read telemetry via WS. Set the key to close that surface.

### Added

- `server/app/auth.py` — `ApiKeyMiddleware` + `socketio_auth_ok` bearer-token gate.
- `config/mosquitto/acl.conf` — per-role broker ACL (server has full authority; nodes restricted to their own namespace + `cmd/` read).
- `config/mosquitto/passwd.example` — placeholder with regen instructions.
- Reliability counters on `/api/health/detail/system.reliability`: `uptime_ts_clamps`, `mqtt_supervisor_restarts`.
- `server/tests/test_mqtt.py` — regression for the uptime-ts clamp.
- `server/tests/test_automation_fire.py` — regression for the rule-fire ordering (verifies `status='failed'` when the broker is down during publish).
- `test_override_persists_across_reload` — verifies overrides survive a simulated process restart.
- `_node_liveness_sweeper()` lifespan task (60s interval, 900s staleness threshold).

### Migration notes

- **Run `./setup.sh` after pulling.** It generates `SPOREPRINT_API_KEY` and the Mosquitto `server` credential in `.env` if they're blank. Nothing is overwritten.
- **Add MQTT creds to every firmware node before flashing v3.3.0.** Set `mqtt_user` / `mqtt_pass` in NVS (captive portal on first boot of a wiped device, or push via `ConfigStore`). Nodes without creds will fail to connect to the newly-authed broker.
- **Set a real OTA password on every node before it starts enforcing in v3.3.0 firmware.** Nodes running default `"sporeprint"` will refuse to call `ArduinoOTA.begin()` — they stay functional but cannot receive OTA updates until the operator sets a strong password.
- **Existing `manual_overrides` rows are now honored.** If you had rows in the table from a prior debug session, they will be loaded on next start. Clear any stale ones before upgrading if you don't want them applied.
