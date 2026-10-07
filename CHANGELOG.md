# Changelog

All notable changes to the public SporePrint Pi-side repo.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.2.0] - 2026-10-07

### Added

- **Grow sessions and contamination events reach the cloud.**
  `app/cloud/session_sync.py` sends each session's snapshot after every
  change: create, edit, phase advance, harvest, complete or abort. Every
  recorded contamination event (vision, identify, manual) is sent as it is
  recorded. Anything unsent is resent on reconnect, and every connect
  backfills the last year, so the cloud's sessions, analytics, planner,
  chamber tiles and contamination history fill from real grows. See
  [`docs/cloud-relay-flow.md`](docs/cloud-relay-flow.md).

### Fixed

- **The cloud connector could not connect.** python-socketio's asyncio
  client needs aiohttp, which nothing installed, so every connect failed.
  The Pi now depends on `python-socketio[asyncio_client]`.
- **Pis seeded by an older release never got newer built-in rules.** CO2
  Hard Ceiling and CO2 Floor — Restrict FAE were missing on those Pis. Each
  built-in is now offered once, and a built-in the operator deleted stays
  deleted.

## [5.1.2] - 2026-10-06

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [5.1.1] - 2026-10-06

### Changed

- Lockstep version bump in step with the cloud parent — no Pi-side server,
  UI, or firmware code changes in this release.

## [Unreleased]

## [5.1.0] - 2026-10-06

Two passes since 5.0.0. The **2026-09 hardware + software audit**: a live
re-check of the whole bill of materials, every enclosure re-fit to sourced
part drawings and joined with heat-set inserts, and ~180 verified software
findings fixed test-first across the server, firmware, broker/install scripts
and dependencies. The **2026-10 follow-ups**: Arduino-ESP32 core 3.3.12,
drivers for every sensor the BOM ever listed, the ESP32-S3 camera boards,
Shelly Gen2+ plugs, the shiitake browning phase, coredump acknowledgements,
and signed OTA manifests for the Pi and (optionally) for nodes. The wire
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
  from 5.0.0 or earlier pins the CA at its next reboot without that check:**
  if the certificate does not cover the node's Pi address (an IP the old
  certificate lacks), that node loses MQTT, drops to safe mode after 10 min,
  and needs physical access (portal gesture or factory reset). Point nodes at
  `sporeprint.local`, or update their firmware first.
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
- **Node firmware moves to core 3.x over the air.** Push the new image from
  the dashboard's Firmware page as before: nodes on a core 2.x image (every
  release up to 5.0.0) take the first 3.x image with no USB cable. Update one
  node per board type and check its heartbeat before the rest
  ([`firmware/README.md`](firmware/README.md#updating-nodes-from-a-core-2x-image)).
  Building firmware now needs PlatformIO Core ≥ 6.2.0 and `git`.
- **Bare-metal Pi self-update checks a signed release manifest** (see *Cloud
  and Pi self-update*). A bare-metal Pi that takes beta or dev builds must set
  `SPOREPRINT_OTA_CHANNEL`. The legacy bundle `.sig` is still published, so
  older Pis keep updating; a current Pi accepts a release that has only the
  legacy `.sig` (published before manifests) only with
  `SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE=true`.

### Hardware and the Builder BOM (`GET /api/builder/tiers`)
- **Tier totals are now ~$290 / ~$745 / ~$960** (were ~$180 / ~$390 / ~$555),
  re-checked live on 2026-09-27, and now include the cabling, consumables,
  heat-set inserts and screws. A second chamber adds ~$62 / ~$316 / ~$527
  (the Pi side once, kits and spools in whole packs). They exclude the
  tri-spectrum strip's shipping and duty (~$10+) and tools. README and the
  build guide use the same numbers.
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
- **The ESP32-S3 camera boards of earlier BOMs are supported again:** the
  camera's BOM note and the Builder's Assistant context no longer call them
  unsupported (the BOM still recommends the AI-Thinker ESP32-CAM; firmware
  below).
- **Whole packs, counted per chamber.** Every pack line has one shape:
  - New optional API fields `Component.pack_price` and `Component.pack_size`.
    `quantity` counts the units a tier needs per chamber, `price_approx` is
    the per-unit price inside the pinned pack, `pack_price` that pack's price
    and `pack_size` its units; N chambers buy `ceil(quantity x N / pack_size)`
    packs (`Component.line_cost(chambers)`, `HardwareTier.parts_cost(chambers)`),
    and `shared` lines never multiply. The camera 2-pack, USB charger 2-packs,
    1 ft USB-C 3-pack, micro-USB 2-pack, NA-SEC3 3-pack, DC pigtail 2-pack,
    KF301 30-pack and door-contact 2-set used to count packs (so ×4 chambers
    bought 8 cameras for 4), and the ESP32 / IRLZ44N / resistor / diode packs
    were bought once per chamber (×4 bought four 100-packs of resistors).
    All the Things now lists 4 ESP32 boards (the 6-pack leaves 2 spares)
    instead of 6. The inline fuse holders are two per chamber from a 10-pack
    instead of a shared line.
  - **Kits and spools the chambers use up are per-chamber pack lines** (new
    optional API field `Component.shared_units`). They used to be `shared` —
    bought once whatever the chamber count — so a multi-chamber shopping list
    under-bought from ~3–4 chambers up: the WAGO 221 assortment (3 × 221-413 +
    3 × 221-415, one of each per chamber) stayed one kit at ×4 and ×12, and 12
    All the Things chambers got one ruthex assortment (100 M3 inserts) for
    436. Now `quantity` counts what one chamber takes — inserts and screws
    from the `models/README.md` shopping list (a mixed kit counts the size the
    chambers use up first: M4 inserts on Recommended, M3 on All the Things;
    M2.5 × 6; M5 × 16; the M4 × 30/35/40 fan-duct screws), WAGO 221-413 +
    221-415 pairs (3 per assortment), fuse sets (15 per box), M-F Dupont
    jumpers (40 per kit), VELCRO 12" straps (12 per roll), 18 AWG pair by the
    foot (~20 / ~35 ft a chamber), the 22/4 cable (~12 ft), 22 AWG hookup
    (~2 ft of black) and solder by the gram (~5 / ~7 g) — and `shared_units`
    is the Pi case's share of the same pack (4 M2.5 inserts, 4 M3 inserts,
    4 M2.5 × 6), bought once: N chambers buy
    `ceil((quantity × N + shared_units) / pack_size)` packs. The bulk
    consumables are per-chamber pack lines too — zip ties, heat-shrink, large
    grommets and 18" duct ties (one per fan, of 100) — since one pack covering
    the 12-chamber preset still under-bought from 17 of the Builder's up to
    99 chambers. Only the Pi side and the bench breadboard stay shared (and
    Bare Bones' screw kit, which only the Pi lid draws on). The docs'
    "reusable kits" share (every shared line except the Pi side) is replaced
    by what a second chamber adds: ~$62 / ~$316 / ~$527.
  - **Mixed consumable kits are counted per size**, from the pinned listings
    (re-read 2026-10-05). **Heat-shrink**: the 400-piece kit holds only
    12 × ½" and 12 × ¾" pieces, and each 12 V chamber uses one of each over
    its two strip joints, so the line counts ¾" pieces (one kit covers 12
    chambers, not 16-26). **Zip ties**: 100 each of 4" / 6" / 8" / 12"; each
    tier counts its scarcest size from the printed parts' tie slots and its
    cable runs (one pack covers 33 / 11 / 7 chambers, not 16). **Grommets**:
    the kit has 10 open 7/8" / 1" grommets (the other 8 large ones are closed
    plugs), so one kit covers 10 chambers, not 20. **M4 kit**: its 75 flat
    washers now cover hx711_scale's 4 DIN 125 washers (the last uncounted
    fastener). Every size is checked at 1-99 chambers.
  - One-chamber totals are unchanged throughout. At ×4 / ×12 chambers the
    tiers come to $484.60 / $1,060.80, $1,733.38 / $4,644.18 and
    $2,613.78 / $7,180.87 (the ×12 totals include a second grommet kit, $13,
    and on Recommended / All the Things a second zip-tie pack, $13).
- **Setup steps**:
  - All tiers: `install.sh`; `./scripts/add-node-mqtt-user.sh <node_id>`
    before the portal, Node ID left blank; Tasmota User / Password / Topic /
    Full Topic (the step names the topic the default Full Topic publishes,
    `stat/<topic>/POWER`); ESP32-CAM-MB flashing (hold IO0, tap RST if the
    upload won't start); print presets per part; heat-set insert and screw
    counts per tier; PSU load budgets; the S3 pin map wherever
    `node_esp32s3` is named.
  - The smart-plug step also covers a Shelly Gen2+ plug (Plus, Gen3, Gen4):
    MQTT on, server = the Pi on port 1883, user `sp-3p`, MQTT prefix
    `shellies/<role>`, and both "RPC status notifications over MQTT" and
    "Generic status update over MQTT" on.
  - The PlatformIO step says `pip install -U platformio`, PlatformIO Core
    6.2.0+ and git, core 3.3.12 and the ~1 GB first build (every tier said
    only `pip install platformio`).
  - The steps name the Builder's current tabs (Firmware, Models) and the
    dashboard's Hardware page, and check a smart plug with
    `GET /api/automation/plugs` — the dashboard has no plug panel.
  - Every shell command, file path, JSON payload, MQTT topic, env name and
    config key is wrapped in backticks (`` `like this` ``), so the Builder can
    show them as copyable code; component notes and wiring rows stay plain.
    `tests/test_hardware_guides.py` checks that each marked span exists in
    the repo: scripts (and that they are executable), pio envs, compose
    services and published ports, `/api` routes, the keys the node reads
    from `cmd/config`, OpenSCAD parameters and their values, the install
    URLs, and the broker ACL for the Tasmota topics; it rejects name
    fragments. The weather step spells out `SPOREPRINT_WEATHER_LON` (it said
    `_LON`), and so does the weather API's "unavailable" message.
- Capability bullets that described unimplemented features were removed (kWh,
  PID, timelapse, quiet hours, EXIF, sensor fallback/divergence, correlation
  reports, local CNN).
- `POST /api/builder/guide` returns 503 (`not_configured`) or 502 (refusal,
  truncated, empty, upstream error) with the body fields unchanged. Firmware
  ZIPs include `library.json`, `VERSION.txt`, every partition table and the
  version script, and never bundle a private-looking `extra_configs` file.

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
- This work supersedes the earlier unreleased model entries (TAL220-only
  scale, saddle pump clamp, "Adafruit 1150 = Kamoer" wording): Adafruit does
  not name the pump's OEM.

### Firmware (details in `firmware/CHANGELOG.md`)
- **Arduino-ESP32 core 3.3.12 / ESP-IDF 5.5.5** (pioarduino platform
  55.03.312-1, pinned by release URL) replaces the end-of-life core 2.0.17 /
  ESP-IDF 4.4. Same images, pins, partition tables, MQTT payloads and signing
  vectors; still 25 kHz / 10-bit PWM. Field nodes update **over the air from
  2.x** — they keep their 2.x bootloader, which boots the 3.x image and still
  rolls back a 3.x image that fails its 60 s MQTT probation; NVS settings
  carry over. The Pi's OTA push keeps working: the node speaks the same espota
  handshake (core 3.3's `ArduinoOTA` would have demanded a PBKDF2 answer the Pi
  does not send). Building needs PlatformIO Core ≥ 6.2.0 and `git`; a
  post-build guard (`firmware/scripts/image_guard.py`) fails any image that
  leaves < 64 KiB of its OTA slot or drifts from the fleet partition layout.
  Library pins are exact (PubSubClient 2.8, ArduinoJson 7.4.3).
- **Drivers for every sensor the BOM ever recommended**
  ([`firmware/docs/drivers.md`](firmware/docs/drivers.md) is the inventory):
  - **AHT20** (I²C 0x38), autodetected. It was a listed SHT31-D alternate with
    no driver. Its init follows Aosong's v1.1 datasheet (register re-init of
    0x1B / 0x1C / 0x1E when the status asks for it, the v1.0 `0xBE` init as
    the fallback), at boot and, non-blocking, after a part resets.
  - **BME280 / BMP280** (I²C 0x76 / 0x77), autodetected. It adds the
    telemetry key **`pressure_hpa`**, which the Pi now stores.
  - **MH-Z19B** frames pinned to the manual. The MH-Z19C driver serves it.
  - **SCD30 on core 3.x:** the SCD30 gets its own I²C path at 50 kHz with
    the clock-stretch timeout at the chip's hardware ceiling. Core 3.x's Wire
    allows only 2 ms, which would have made it go stale. The SCD30 on a
    WROOM-32 node is listed as partial until bench-tested: the classic ESP32
    can wait only 13.1 ms for its clock stretch.

  These changes are additive and change no node pins.
- **ESP32-S3 camera boards** from the 2026-04 to 2026-06 BOMs now run the
  cam image: envs `cam_esp32s3` (Freenove ESP32-S3-WROOM CAM),
  `cam_xiao_esp32s3` (Seeed XIAO ESP32S3 Sense) and `cam_waveshare_s3`
  (Waveshare ESP32-S3-CAM-OV5640 / -OV3660). They have no flash LED and use
  BOOT (GPIO 0) as the reset button; build guide §8b has their pin maps.
  Firmware CI and the release workflow build all three.
- New env **`node_esp32s3_n32r16v`** for the ESP32-S3-DevKitC-1-N32R16V (same
  pin map as `node_esp32s3`), built by CI and shipped as
  `node_esp32s3_n32r16v.zip` in every release (`node_esp32s3.zip` does not
  boot on that board).
- Camera detects **OV2640 / OV3660 / OV5640** and tunes per sensor; flash stays
  on through the exposure; uploads default to the portal's Pi address; HTTPS
  uploads require the pinned Pi CA. The camera's setup portal no longer shows
  the node-personality select.
- **Reed invert** (portal checkbox / `cmd/config {"peripherals":
  {"reed_inv": true}}`) for door contacts wired on NO.
- Heartbeat on its own clock (min(publish interval, 5 min)), with `tls` and
  `board` keys. Secure MQTT never downgrades silently (`tls_downgrade` alert,
  CA-fetch retries, optional "Require TLS").
- **Secure MQTT verifies before it pins.** A fetched CA is only a candidate:
  the node tries TLS on 8883 with it from RAM and writes it to NVS only after
  the broker's CONNACK. A failed trial goes back to plaintext (or stays off
  MQTT with "Require TLS"), backs off, and the `tls_downgrade` alert says why
  (certificate name mismatch or another CA, 8883 unreachable, TLS error,
  login refused). A verified pin is final. A CA an older image pinned without
  this check is re-verified as a candidate. New optional heartbeat key
  `ca_fp`: SHA-256 of the pinned CA PEM.
- Safety: `aux` max-on 60 s by default and per-channel `max_on_sec`; an explicit
  OFF wins over `pwm`/`level`; 10-min MQTT-loss safe mode; channels off at OTA
  start; OTA rollback on node and camera.
- The setup AP no longer opens on a WiFi hiccup (BOOT / GPIO 13 gesture
  instead); replay guard + topic binding on signed commands; portal node-id and
  password-keep rules; epoch `ts` + `"replay": true`; latched alerts; sensor
  staleness alerts.

### Nodes: commands, OTA and coredumps (Pi side)
- `POST /api/hardware/nodes/{id}/peripherals`
  (`{"mhz19"|"hx711"|"reed"|"reed_inv": bool}`) sends a signed `cmd/config`;
  the node reboots ~1.5 s later if its driver set changed. `reed_inv` (a door
  contact wired on its NO terminal) applies live, so the endpoint takes every
  key the firmware does.
- **Signed node commands** carry two more signed members, `topic` and a random
  `nonce`: current firmware rejects redirected frames and no longer drops a
  legitimate identical command in the same second. Deployed firmware verifies
  them unchanged.
- **OFF is never published with `pwm`/`level`** (rules, manual node commands,
  cloud commands), and every published OFF — manual node, cloud, session-end
  safing, manual plug — clears that actuator's `safety_max_on_seconds`
  ceiling. `POST /api/hardware/nodes/{id}/command` returns 503 when nothing
  was published.
- Node liveness: any telemetry frame from a registered node refreshes
  `last_seen`, so nodes on a 15 min–1 h publish interval no longer flap
  offline.
- **Coredumps survive until the Pi has them.** Nodes used to erase a panic
  dump as soon as its last chunk left, so a Pi restart or a lost chunk lost
  the crash. Chunks now carry `coredump_id` (the dump's SHA-256); the Pi
  checks the reassembled bytes against it, writes the file durably (temp
  file, fsync, rename) and only then sends the signed `cmd/coredump_ack`.
  The node erases only on that ack, retries with backoff otherwise (3 uploads
  per boot, 6 per dump), then keeps the dump. A re-upload is acknowledged
  again without a second file or alert. Older nodes (no id) are stored as
  before and never acked; a Pi without ack support gets at most 6 copies
  from a new node, which keeps its dump.
- **Signed node OTA manifests (optional).** `POST
  /api/hardware/nodes/{id}/ota` takes optional `manifest` + `manifest_sig`
  files (the release manifest format the Pi's own OTA uses, with `artifact`
  = the PlatformIO env). The Pi verifies them against its pinned
  `SPOREPRINT_OTA_PUBKEY_B64`, the uploaded `.bin` and the node's firmware
  version, sends them on `cmd/ota_manifest`, and waits for the node's
  answer: a node image built with the key then flashes only that exact
  image; a node rejection stops the push; a node without manifest support
  gets a Pi-verified push. `GET .../ota` reports `manifest`
  (`node_verified` | `pi_verified` | null) and the node's refusal text.
  This repo's firmware releases, from `firmware-v5.1.0` on, are built with
  the key and sign one manifest per env (see *Dependencies and CI* and
  `docs/firmware-security.md`).
- Pi-pushed node OTA uses fixed TCP port 3233 (published in compose), runs one
  push at a time and retries invitations. The connect-back listener accepts
  only the node being flashed: another LAN host that connects first is logged
  and closed, and can no longer take the image and report a fake success.

### Automation
- The highest-priority rule whose condition holds owns an actuator; ceilings
  count from the first ON and a trip locks automation out for 15 min (WARNING
  page, CRITICAL if the OFF fails); life-safety rules (priority ≥ 20,
  absolute thresholds) run with no session; species-scoped rules match
  `lions-mane` and `lions_mane`; redundant OFFs to unpaired plugs are skipped,
  and a repeat OFF is re-sent only every 15 min unless something switched the
  actuator back ON — a manual, cloud or plug command, or a node reporting the
  channel ON, drops that suppression so the cutoff rule re-sends its OFF at
  the next evaluation; cron catch-up; scheduled FAE runs only when the
  phase's `fae_mode` is scheduled or continuous; new `profile_ref`
  `temp_mid_f`; `growth_form` antler/conk picks the CO₂ params; `bulk_bag` is
  sealed until fruiting; the rule `notification` flag now pages (WARNING <
  priority 20 ≤ CRITICAL).
- Seeded templates are upgraded on boot unless edited (a WARNING names each
  edited copy). An edited Pre-cool or Heat Wave rule with no
  chamber-temperature condition now holds the cooler ON against Cooling
  Cutoff — add a `temp_f` condition. The Humidity Boost/Cut and Dry Weather
  rules carry 1800 s ceilings: a humidifier that needs more than 30 min to
  cross the band trips one (raise `safety_max_on_seconds` if yours is slow).

### Sessions, species and transcripts
- **Shiitake browning phase** (`browning`, between `substrate_colonization`
  and `primordia_induction`): the unbagged block holds 60-70 °F, 70-80 % RH,
  CO2 under 2000 ppm, 12/12 light and passive FAE for 7-14 days. `GET
  /api/sessions/{id}/next-phase` suggests colonization → browning →
  primordia induction for shiitake (other species unchanged) and returns the
  new `exit_reminder`, the cold-water soak (35-50 °F, 12-24 h). Stepping on
  out of browning logs a `phase_exit_reminder` session event (also in the
  transcript), and the daily phase check offers the soak from day 7. A
  profile without browning setpoints refuses the phase (422); custom profiles
  can add it with the new optional `PhaseParams.exit_reminder`. The humidity,
  dehumidify, misting, CO2 and photoperiod built-in rules now also run in
  browning, a grow bag counts as open from browning on, and unedited stored
  copies of those rules upgrade at start-up. Vision tells Claude the brown,
  popcorned skin is normal for shiitake, reads a `browning_percent`, and
  sends an INFO "Browning complete" with the soak at 90 %; a colonized
  shiitake block is reported ready to brown, not to fruit.
- Overdue-phase reminders: a daily 09:00 (container-local `TZ`) INFO "Phase
  check — <session>" for each grow past its phase's expected duration
  (`phase_reminders` task).
- `POST /api/sessions` and `/phase` return 422 for an unknown phase or one the
  species can't enter; missing primordia/fruiting/rest setpoints borrow from
  each other; `next-phase` skips phases the species lacks; ending a grow safes
  the actuators it drove (per chamber when several grows run); phase history
  stores `params_snapshot`.
- Session events: the `phase_change` event reads "Phase advanced to primordia
  induction" (it printed the raw enum, which the timeline, chamber feed and
  transcript then showed); `data.phase` keeps the raw value. Leaving a phase
  that owes a manual step logs the `phase_exit_reminder` event before the
  `phase_change` (same second, so the event id is the order): the session
  timeline and the transcript's Key Events — the text Claude analyses —
  listed shiitake's cold-water soak after "Phase advanced to primordia
  induction". `get_events` and the transcript sort same-second events by id.
- Chamber `PATCH` with `active_session_id: null` detaches; chambers with
  history can be deleted; iCal dates anchor at the first phase; the
  pink-oyster harvest page is CRITICAL; the substrate calculator and shopping
  list scale correctly; species setpoints match the spec's §4b, now
  `docs/species-reference.md` (pink oyster, cordyceps, king trumpet CO₂);
  `POST /api/experiments/{id}/analyze` is the preferred route.
- A species' grow-supplies list (`GET /api/species/{id}/shopping-list`) lists
  the vessel its first recipe uses: a filter-patch grow bag for a
  pressure-sterilized block (supplemented sawdust, masters mix), jars for
  grain / brown-rice / agar cultures, nothing for an outdoor bed or log, and
  the monotub + liner only for pasteurized bulk (CVG, manure, straw) — it gave
  every species a monotub + trash-bag liner.
- Transcripts: per-phase telemetry summaries are filled from rollups for old
  phases; unknown session ids return 404; session analysis sends at most 150
  vision summaries. The markdown transcript
  (`GET /api/transcript/sessions/{id}/transcript?format=markdown`) no longer
  prints Python `None` for unset session fields: the header used
  `session.get(key, 'N/A')`, but a NULL column is present with value None, so
  it printed lines such as `**Substrate**: masters_mix (None)` and
  `**Inoculated**: None (None)`. A missing value now drops its line, and a
  missing detail drops its parentheses. The header fields are a list
  (`- **Species**: …`), so they render on separate lines in any markdown
  viewer.
- Species summaries agree with their own cards: the Shiitake summary names
  the cold-water soak (35-50°F, 12-24 h) its pinning trigger and reminder
  use and 3-6 flushes, and the king trumpet, yellow oyster, chestnut,
  pioppino and nameko summaries give their yield notes' flush range
  (`tests/test_species.py` checks every profile).
- `POST /api/sessions` with a `chamber_id` the Pi has no chamber for answers
  422 `chamber N not found` instead of a bare 500 from the foreign-key
  failure; a cloud `session_start` reports the same reason.

### Telemetry, vision, weather and notifications
- Telemetry: `ts < 1e9` is treated as unsynced; replayed (`"replay": true`)
  and out-of-order frames (up to 120 s older than the node's newest live
  frame; a bigger step back is the node's clock being corrected and
  re-baselines) are stored but not evaluated or pushed live; history charts
  fall through every rollup tier. The Pi's own clock never decides whether a
  frame is live: a Pi clock running minutes fast no longer silently stops
  automation and safety thresholds for every synced node. Pi-vs-node clock
  skew is measured per node, logged as a rate-limited WARNING past 120 s, and
  reported (with non-live frame counts) under `reliability` in
  `GET /api/health/detail/system`.
- Readings are tagged with their grow, chamber-aware: a listed node belongs
  to its chamber's grow, an unlisted node to the newest chamberless grow.
  With grows in two chambers, list every node in its chamber.
- Vision auto-analysis runs every 6 h per session
  (`SPOREPRINT_VISION_AUTO_INTERVAL_MIN`, default 360) and on the first frame
  after a phase change, instead of every capture; the local CNN is still a
  stub. Contamination pages CRITICAL at confidence ≥ 0.6 and sends one
  "Possible contamination" WARNING at 0.3–0.6; contamination events are
  recorded with `source='vision'`. Frame retention: 30 days, then one frame
  per camera per day (flagged, labelled and referenced frames kept).
  `X-Camera-Sensor` is stored as the node's `camera_sensor` and named in the
  Claude prompt; a harvest-window INFO notification; stored frame names are
  unique and carry the real image type; a failed re-analysis never
  overwrites a stored one; `POST /api/contamination/identify` returns 415 for
  non-image uploads.
- Claude: every feature uses `SPOREPRINT_CLAUDE_MODEL` (default
  `claude-sonnet-5`); output ceilings are 16,000 tokens (32,000 streamed for
  the Builder). A refusal or truncated answer returns `{error}` (Builder:
  `truncated: true` plus the partial guide, not saved) instead of a 500 or a
  half-saved result.
- Weather: forecast alerts fire only once the weather→closet model is trained
  (~7 days), ignore past hours and dedupe per session, kind and day;
  `forecast_high_f` / `forecast_low_f` cover today's local day; the prediction
  model trains on 30 days; Open-Meteo times parse as UTC.
- Notifications: ntfy is published through its JSON API (titles with em dashes
  or °F now arrive); identical CRITICAL pages collapse for 15 min; temperature
  and humidity EMERGENCY pages dedupe per node, parameter and direction; node
  alerts reach ntfy by tier.
- Nightly retention also prunes session-less `automation_firings` older than
  90 days and thins vision frames; new index `idx_rollup_node_sensor_time`
  speeds long-range charts.
- INFO and WARNING notifications sent without a dedup key now dedupe by
  title (1 h and 5 min, as documented), and the drying-complete INFO keys on
  the harvest: it repeated on every drying-log entry past the target.

### Smart plugs and integrations
- **Shelly Gen2+ smart plugs** (Plus / Pro / Mini, Gen3, Gen4 — plug_type
  `shelly_gen2`) alongside Gen1 and Tasmota. Set the device's MQTT prefix to
  `shellies/<role>` (e.g. `shellies/humidifier` → `plug-humidifier`) and log in
  as `sp-3p`; the factory prefix (the device id) is outside the ACL and is
  dropped. Commands are JSON-RPC `Switch.Set {id, on}` on `<prefix>/rpc`
  (the `server` account gains `write shellies/+/rpc`; `sp-3p` is unchanged);
  state and `apower` come from `NotifyStatus` / `NotifyFullStatus` on
  `<prefix>/events/rpc`, `<prefix>/status/switch:<n>` and the reply to a
  `Shelly.GetStatus` the Pi sends whenever `<prefix>/online` turns true (so a
  plug registers and refreshes without a toggle). Multi-channel devices
  register `plug-<role>-<n>` per extra switch. Safety ceilings, manual OFFs
  and the cutoff re-assert work as for the other plugs; a Gen2 `errors` trip
  (overpower, overtemp) is logged. Every plug type now keeps `status`
  online/offline from its online flag or Tasmota `tele/LWT` (Socket.IO
  `plug_online`), and a plug report re-types a row whose `plug_type` no longer
  matches the device (a role assigned with the default `plug_type: "shelly"`
  keeps a detected Gen2).
- Tasmota plugs also update from `stat/RESULT` and `tele/STATE` JSON
  (`POWER` / `POWER1`); Shelly and Tasmota plugs register on their first state
  report.
- Plugs following the build guide never registered (missing Full Topic and
  credentials) — docs, Builder steps and the install summary now say both.
- `POST /api/automation/plugs/{id}/command` returns 409 for an unknown or
  unpaired plug and 503 when the broker is down.
- Integrations: sending back a masked `••••last4` secret (or omitting it)
  keeps it, `""` clears it — but a kept secret stays bound to where it is
  sent: changing a driver's `secret_bound_fields` (`base_url` for Aranet,
  Agrowtek and BIOS) without re-entering the secret returns 422, so a config
  PUT can no longer redirect a stored key to another host. A lost or changed
  `.integration-key` shows "re-enter the credentials"; vendor health
  transitions that happen while the cloud link is down are retried until
  delivered.
- Vendor drivers: the Tapo local KLAP handshake (real devices authenticate;
  its `set_power` integration test is no longer `xfail`), Kasa multi-segment
  replies, Wemo port probing (49153/49152/49154/49155/49151, `host:port`
  pins), Pulse session reuse, the Grafana contamination counter.

### Cloud and Pi self-update
- Cloud pairing credentials persist to `cloud.env` beside the DB (0600) and
  survive rebuilds; `cloud_url` must be `https://`; `integrations_request`
  frames are replay-deduped and, after the first signed one, must be signed.
- **Pi self-update verifies a signed release manifest.** Releases now
  publish `{version}.manifest.json` + `.manifest.json.sig`: canonical JSON
  `{schema, artifact, version, channel, sha256, size, published_at}` signed
  with the existing OTA key (`server/app/cloud/ota_manifest.py`, test vectors
  in `server/tests/fixtures/ota_manifest_vectors.json`). Before downloading
  the bundle, the Pi checks the signature over the exact bytes and the
  canonical form. The version must be the one requested, the channel must
  be the Pi's new `SPOREPRINT_OTA_CHANNEL` (default `stable`), and the
  version must not be older than the installed one or the floor recorded by
  the last OTA. The bundle is then capped at the signed size and its sha256
  checked. A downgrade needs `SPOREPRINT_OTA_ALLOW_DOWNGRADE=true` on the Pi;
  the OTA command cannot allow one. A key sent in the command (`ota_pubkey`)
  is ignored. A manifest that is present but broken never falls back to the
  legacy `.sig` (upgrade notes above). `scripts/sign-ota-bundle.py
  --manifest-out` writes the manifest. The version check uses `fullmatch` (a
  trailing newline used to pass).
- Pi OTA: bare-metal Pis only — the Docker install refuses cloud self-update
  and the refusal says `git pull && ./install.sh`; downgrades are refused;
  bundle extraction applies tarfile's `data` filter.

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
- **Broker service accounts never become nodes.** Frames under
  `sporeprint/<id>/…` for `server`, `sp-3p`, `sp-cmd`, `sp-telemetry` or the
  Pi's own MQTT user are dropped (WARNING once) before registration or rule
  evaluation, `POST /api/hardware/claim` refuses those ids, and node rows an
  older server registered under them are deleted when MQTT starts. A leaked
  smart-plug credential can no longer register a node, claim a node type or
  feed the rules engine.
- `GET /api/provision/ca` is public in API-key mode, so Secure-MQTT nodes can
  fetch the CA; in that mode `GET`/`POST /api/cloud/pairing-code` now need the
  bearer, and a keyless `POST /api/vision/frame` is accepted only from a
  registered camera with a declared Content-Length ≤ 20 MB.
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
- **The Pi's node OTA push also answers the PBKDF2 login.** arduino-esp32
  3.3.1+'s stock `ArduinoOTA` challenges with a 64-hex nonce and accepts only
  `sha256(pbkdf2_hmac_sha256(sha256(password), nonce:cnonce, 10000):nonce:cnonce)`
  with a 64-hex cnonce; `server/app/hardware/ota_push.py` now picks the answer
  by nonce length as espota.py does (32 hex: the MD5 digest every SporePrint
  image still offers; 64 hex: PBKDF2, computed off the event loop) and refuses
  any other length. Nothing changes on the wire for current nodes. It is the
  first half of the coordinated move to the stock library: a firmware that
  drops `ota_service.cpp`'s MD5 login must wait until every Pi that pushes to
  it runs a release newer than 5.0.0.
- Also security-relevant, described above: stored integration secrets stay
  bound to their destination (*Smart plugs and integrations*), the OTA
  connect-back peer check (*Nodes*), Secure MQTT verify-before-pin and `ca_fp`
  (*Firmware*), and the signed Pi release manifest (*Cloud and Pi
  self-update*).

### Install and deploy
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
  `generate-ota-keypair.py` creates the private key 0600 atomically.
- `rotate-mqtt-creds.sh` writes only the `server` password into `server/.env`;
  the other shared passwords stay in the repo-root `.env`.
- New settings: `SPOREPRINT_VISION_AUTO_INTERVAL_MIN` (default 360),
  `SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS` (default false),
  `SPOREPRINT_PUBLIC_UI_URL`, `SPOREPRINT_CLAUDE_MODEL` (default
  `claude-sonnet-5`; every Claude feature), `SPOREPRINT_ALLOWED_HOSTS`,
  `SPOREPRINT_OTA_CHANNEL` / `_ALLOW_DOWNGRADE` / `_ALLOW_LEGACY_SIGNATURE`,
  `TZ`, `FORWARDED_ALLOW_IPS` and the `edge` network's
  `SPOREPRINT_EDGE_SUBNET` / `_UI_IP` / `_SERVER_IP`. Every `Settings` field
  is now forwarded by compose (enforced by a test).
- The server boots when `server/.env` holds keys that are not settings (a copy
  of the repo-root `.env` with `TZ` or `FORWARDED_ALLOW_IPS`) and when a
  non-string setting is present but blank (`SPOREPRINT_PORT=` means the
  default). A malformed non-blank value still fails loudly.
- Upgrading a database created before v3.3.0 no longer crashes `init_db`.
- Images pinned: `eclipse-mosquitto:2.1.2-alpine`, `binwiederhier/ntfy:v2.28.0`,
  `busybox:1.36.1` (BusyBox's latest stable release; 1.37 and 1.38 are
  unstable upstream), and `nginx:1.30.5-alpine` and `python:3.12.15-slim` by
  digest. The server image installs exactly `server/uv.lock` (hash-checked,
  exported with uv 0.12.23).
- The dashboard's nginx passes request bodies up to 21 MiB and gives `/api/`
  a 180 s timeout. Socket.IO rate limiting and client tracking use each
  client's real address (uvicorn `--proxy-headers` behind nginx).

### Dashboard (`ui/dist`)
- **Rebuilt from the monorepo's pi-ui** after five browser audits and again for
  the 2026-10 follow-ups. The first
  rebuild also brought in the other pi-ui and design-package changes made in
  the monorepo since the previous `ui/dist`, from the v5.0.0
  release work and the fixes after it. The main bundle is 1,166 kB (338 kB
  gzipped, built with Vite 8); it was 1,258 kB (340 kB) before the wiring
  SVGs moved to their own 173 kB chunk, fetched only when the Wiring tab
  opens (1,112 kB / 323 kB right after the split).
  `tests/test_ui_builder_sync.py` follows references from `index.html`
  through the bundle, so that chunk counts as a shipped asset. `ui/dist`
  no longer ships source maps (the same test fails on any `*.map` file or
  `sourceMappingURL` comment in `ui/dist`).
- **Licence notices ship with the dashboard.** The minified bundle carries no
  legal comments, so `ui/dist/THIRD-PARTY-LICENSES.md` lists every library
  the bundle and its stylesheet include (React, React Router, lucide-react,
  Tailwind CSS and the rest) with its licence text, and
  `ui/dist/FONT-LICENSES.txt` carries the SIL Open Font License and
  copyright of each bundled font family. `tests/test_ui_builder_sync.py`
  checks both are there.
- **Fonts ship with the dashboard.** Space Grotesk, Cormorant Garamond and
  JetBrains Mono (latin subset, woff2, SIL Open Font License) are bundled in
  `ui/dist/assets` instead of loaded from Google Fonts, so opening the LAN
  dashboard contacts no font service and the fonts work offline.
- **Species wizard** cards are keyed by species ID: two strains of one
  species share a binomial, and changing an answer used to leave a stale
  card behind (four cards, one ranked twice) while the
  education-and-research notice went away. **Shopping List** shows that
  notice when a controlled-category species is picked under Add a species
  or is among the grows. The Builder's **Firmware** tab links the signed
  `firmware-vX.Y.Z` release images and says a build from its ZIPs has no
  verify key; the **OTA verify key** row and note in Settings say to pin the
  key each firmware release's notes print (the keypair script only for
  signing your own builds: a freshly generated key makes the Pi refuse every
  official signed update). The **New session** and **New culture** pickers
  open on the first species outside the controlled category instead of the
  first library entry.
- **Built with Vite 8** (React 19.3, Tailwind v4). The bundle's build target
  is pinned to Chrome/Edge 111, Firefox 114 and Safari/iOS 16.4 (Vite 6
  targeted Safari 14 / Chrome 87); no browser the dashboard ran on is
  dropped, since its Tailwind v4 CSS already needed Safari 16.4, Chrome 111
  and Firefox 128. Vite 8's minifier writes string literals in backticks,
  so `tests/test_ui_builder_sync.py` and `tests/test_hardware_guides.py` now
  accept any JS quote in the bundle, as `scripts/sync_ui_builder_data.py`
  already did.
- **The Builder page reads this Pi live.** It loads the BOM
  (`/api/builder/tiers` and `/tiers/{id}`), the models, the wiring diagrams
  and the firmware ZIPs from the Pi. If a request fails, that resource falls
  back to a copy generated from this repo at build time, and a pill at the
  top of the page says which data is on screen. This replaces the stale
  static copy, which had a pre-audit BOM with no cabling, "browse repo" and
  wiring links to `hardware/3d` and `hardware/wiring` (both 404), raw GitHub
  `.scad` downloads that cannot render without `models/lib/`, and a false
  "slicer-ready STL exports" claim. The built-in BOM counts the mixed kits
  per size (×12: $1,061 / $4,644 / $7,181).
  - **Shopping tab and totals:** `shared` parts are bought once per
    installation and every other line's units scale with the chamber count;
    pack-sold lines buy whole packs (`shared_units` included), so totals
    equal `parts_cost(N)` at any chamber count from 1 to 99 (Bare Bones ×10
    buys two packs of M3 inserts for 104). Lines show their units and the
    packs that buy them, worded one way on the Shopping tab, the Shopping
    List and its CSV ("4 · 2 packs of 2 · 1 spare", "$5.49 / pack of 100 ·
    ~$0.05 ea"), and "(shared)" shows at every chamber count. Lines counted
    in something other than pieces say so (new optional API field
    `Component.unit`): "420 ft · 5 packs of 100 ft · 80 ft spare", "$26 /
    pack of 100 ft", "~$0.26 / ft"; the WAGO assortment reads "12 chamber
    sets · 4 packs of 3 chamber sets"; solder in grams, VELCRO in straps, the
    insert and screw kits in the size they are counted in. The total shows
    the shared and chambered parts separately and says what whole packs
    save; smart plugs, wiring and hardware have their own sections. Cost
    captions use whole dollars (the stale "Pi's estimate" clause is
    removed).
  - **Overview and tier cards:** the Overview counts packs and parts to buy
    (and BOM lines and units separately) instead of adding feet, grams and
    pieces, uses the Shopping tab's "shared, bought once" caption, and its
    cost caption reads like the BOM totals at ×1. Tier cards price the chosen
    count ("47 lines · ~$1,733 for 4 chambers"); a count outside the presets
    shows as its own "×7" pill next to a − / + count box; the chamber caption
    names what is bought once: the Pi side, the bench breadboard and bulk
    packs that cover 12+ chambers. The tier and chamber count stay in the
    URL.
  - **Setup tab:** the backticked commands, paths and topics show as code
    with a copy button (on a plain-http Pi it falls back to
    `execCommand("copy")`). Copying or selecting text no longer ticks the
    step. Ticks are stored per step id instead of per position, so adding a
    step no longer moves them; ticks saved by the released dashboard carry
    over to the matching new steps. The setup step covers Shelly Gen2+
    plugs.
  - **Wiring tab:** the tier's SVG as the Pi serves it, scaled to its box's
    width, with an "open full size" link and a link to its GitHub source;
    the cards show a thumbnail with a readable "full-size svg →" label. If
    the Pi's SVG does not load, the page shows the same generated diagram
    from the bundle instead of the old hand-drawn sketch, which clipped
    labels, put pin labels under wires and cut off the legend. The
    connection table uses the live wiring rows.
  - **Models tab:** each card shows the title and description from the
    model's `.scad` header (a cut description ends on a whole word, and
    "more" reads the full header from the Pi's download first, then GitHub)
    and downloads the Pi's self-contained file (`lib/` inlined); a "download
    all (.zip)" link; "browse repo" opens `models/`. Single-column model cards
    no longer leave blank bands.
  - **Firmware tab:** one card per image (unified node, camera), downloaded
    as the Pi's self-contained ZIP. An image is listed for a tier when one of
    its PlatformIO envs is a tier target, which covers
    `node_esp32s3_n32r16v`. Each card lists the `pio run -t upload -e <env>`
    command for each board, with copy buttons; the camera card lists `cam`,
    `cam_esp32s3`, `cam_xiao_esp32s3` and `cam_waveshare_s3`, each with its
    board. File names are their download links, so the table fits a phone.
    Offline, the tab lists the files (the new firmware files included, and
    `cam_policy.h` as well as `main.cpp` on the camera card) from a listing
    generated from this repo (raw GitHub links and sizes) instead of a
    hand-copied list.
  - **Resources:** the repo is labelled AGPL-3.0 (it said MIT). The dead forum
    link is removed, and the dead Discord invite is replaced by a plain-text
    "coming soon" placeholder with no link. "User docs" opens the
    sporeprint.ai user guide; "Quick start" is the README's.
  - **Layout:** checked in Chrome on every tier and tab from 320 to 1600 px
    wide: nothing sticks out of its box and the page never scrolls sideways.
    Below 900 px the BOM and wiring-connection tables stack as cards instead
    of scrolling (the Buy link and wiring notes were cut off between 1024
    and 1340 px); the firmware-file table scrolls inside its own box.
- **Shopping List** shows your build. "Send BOM to /shopping" is a real link
  (`/shopping?bom=…&chambers=…`) that hands over the tier and chamber count,
  and "Open in builder →" keeps them. The page no longer shows demo rows or a
  restock banner: it lists the sent BOM (live from
  `/api/builder/tiers/{id}`, totals equal to the Builder's), grow supplies
  for each species with an active session
  (`/api/species/{id}/shopping-list`), and your custom items.
  - Grow supplies are merged across species, one row per item (spawn,
    cultures and inoculants stay one row per species); a merged supply counts
    as bought only when every species it serves is ticked ("partly bought —
    for …" until then). A species with a session (`lions-mane`) and the same
    species picked by hand (`lions_mane`) is one grow target, not two.
  - A hand-set grow count shows as an override with a reset; a count change
    refetches only that species; one message when the sessions can't be
    read; the two 404s are told apart. An out-of-range `?chambers=` opens on
    99 instead of 1, the URL says what the page shows, and an unknown
    `?bom=` warns (on a full page load too).
  - Ticks and notes follow a part across builds; notes grow with their text;
    custom items validate their name and link inline. Two open Shopping List
    tabs stay in step: a tick, note, custom item, grow count or build sent in
    one shows in the other, and every change is written into what is stored,
    so one tab no longer undoes the other's.
  - The hardware tables line up; below 900 px of table each row becomes a
    card on screen. A printed list is a table again: the card layout is
    screen-only, so a Letter or A4 sheet no longer prints one tall card per
    row (a 4-chamber list ran to 20 pages). A print stylesheet hides the
    navigation and prints dark on white; the Buy column and the "notes &
    substitutes" disclosure stay off paper, notes print in full, cells are
    tighter and the columns size to their content; the note column is a
    fifth of the table.
  - The CSV writes "×N" and "(shared)" as the table does, one supplier URL
    per cell and "lb" for every pound, and defuses every formula-like cell
    (`-1+2`, a leading tab).
- **Sessions:** a new session shows as day 0 (it showed "20710d") and counts
  toward the 30-day yield, and the Day column and 30-day yield no longer read
  every session as day 0. The phase pill names the grow's phase ("primordia
  induction", not the "fruiting" bucket) and its chamber by name; rows show
  the session name; timeline tags name the event (NEW, PHASE, …) instead of
  truncating it ("SESSI"). "advance → <next phase>" shows the phase's exit
  reminder (the cold-water soak when leaving shiitake browning) before the
  confirm; browning segments read tan on the phase bar, and the browning
  events are tagged STEP and VISION.
- **Species:** cards show common names, size to their content and expand in
  place when opened, so Tab order matches the screen. The four categories
  have their own colours (green, amber, blue-violet, orchid; checked for
  colour-blind contrast), and the 8 novelty species get a filter chip, so
  the category KPI adds up to the 74 shown; KPI labels fit one line. Tags
  collapse to the 12 most used behind an "all 129 tags" toggle, and the tag
  counter is always announced. On a phone the filters and "recently viewed"
  fold behind one "filters" button, so the first card is on the first
  screen. Phases read "Substrate colonization" / "Primordia induction" and
  flush counts "~4 flushes"; inactive filter chips are legible (WCAG AA).
- **Other pages:** tables on Sessions, Transcripts, Inventory, Cultures and
  Contamination scroll inside their own column (from 1180 to about 1600 px
  they ran under the right-hand panel), and Sessions and Transcripts pin
  their row action instead of scrolling the page. The transcript preview
  renders bold, italic and code. Contamination pills follow one severity
  ladder (critical red, high amber) and list every entry; its upload buttons
  wrap at 390 px; a contamination check without a Claude key says so in
  words and links to Settings, and the log stacks on a phone. Long
  automation conditions wrap. Chamber tiles carry the chamber's name; the
  Quick overrides strip fits five tiles down to ~600 px of card; the CLOUD
  KPI no longer breaks mid-word; the Planner's cycle table fits its card at
  1440. Firmware: a push can carry the release's signed manifest and `.sig`
  ("signed release manifest (optional)" under update firmware; both or
  neither), and the status says whether the node or only this Pi checked it.
- **Navigation:** below 768 px the rail becomes a drawer behind a menu
  button on every page; the drawer is a modal dialog (focus kept inside, the
  page behind it inert, focus restored on close). The sidebar footer
  (version, uptime) is no longer clipped.
- **`scripts/sync_ui_builder_data.py` now verifies the bundle instead of
  patching a static copy.** `--check` confirms that the bundle requests
  `/api/builder/*` live and has none of the old static Builder's dead links or
  claims. It also confirms that the built-in copy matches this server: the
  tiers exactly as in `hardware_guides.py`, plus the models, diagrams and
  firmware envs. Without `--check`, the script rewrites only stale built-in
  data, in place. `tests/test_ui_builder_sync.py` enforces all of this and
  also checks the built-in copy against the API's actual responses.
- **+ new session works again on a Pi with chambers.** The Chamber select
  picked the first chamber as the list loaded, but the trigger went blank and
  an untouched form posted `chamber_id: 0`, which failed with a 500. The
  select keeps the picked chamber (the shared Select ignores the empty value
  Radix's hidden form `<select>` reports when value and items change in one
  render), and the form sends a missing or blank chamber as unassigned.
- Smaller dashboard fixes: the Settings quiet-hours row says the Pi sends
  every alert to ntfy (filter by priority in the ntfy app) instead of
  pointing at the cloud app; the Sessions stage chips' hints read "phases:
  …" ("rest (between flushes)" under harvest); an idle, unnamed chamber's
  header names it once; chamber names stay on one line in the inventory and
  Planner tables (the Planner's node count moved under the name); small text
  that read under 4.5:1 (Shopping List pack, price and note lines, the
  Planner's weekday header, the sidebar uptime, "not yet supported on this
  Pi", chamber tile badges, Automation rule stats, contaminant growth speed,
  "not edible", the selected Sessions row and Builder tier card) is brighter.
- **Education-and-research notice on the species pages.** The dashboard's
  species library and species wizard show one short note: "For education
  and research purposes only. Some species may be controlled where you live;
  you are responsible for following local law." The species library shows it
  above the list (its category chips can always pick the category) and in an
  active profile's details; the species wizard shows it when a
  recommendation is in that category; the species pickers on the new
  session, new culture and plan-a-grow forms show it while a species in that
  category is chosen. It names no species.
- **Active species are opt-in in the wizard and listed last in the library**,
  as on the cloud. `GET /api/species/recommend` leaves the `active`
  category out of the ranking unless `include_active=true`; the species
  wizard's "candidate pool" switch (off on every visit) sends it and shows
  the notice while it is on. The species library lists the other categories
  first, A to Z by common name, then the active category; before, it kept
  the profile file's order, which starts with that category.

### Docs and diagrams
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
  common ground; a *Tools you need* list; the S3 pin map (§8a) and the three
  S3 camera boards of earlier BOMs (§8b); a 12 V pre-power check in the
  bring-up list; new troubleshooting rows (dead board, swapped fan wires).
  New `docs/auth.md` (LAN-trust vs API-key mode, public paths).
- `models/README.md`: per-tier insert and screw totals; the BOM's insert and
  screw kits, the 18" (457 mm) duct tie and the VELCRO straps.
- **Docs brought in line with the code (2026-10).** `README.md`: React 19
  dashboard that loads over REST (no Socket.IO client, no PWA, no unit
  switch; the Builder's Claude guide generator is API-only), the real
  Socket.IO event names (`rule_fired`, not `rule_firing`; plus
  `actuator_state`, `node_status`, `node_log`, `node_ota`, `plug_online`),
  the node `ota` / `coredump/chunk` / `cmd/coredump_ack` /
  `cmd/ota_manifest` topics and the Shelly Gen2+ topics and setup,
  PlatformIO Core ≥ 6.2.0 + git for the core-3 platform, the OTA listener
  (`ota_service.cpp`, not `ArduinoOTA`) and signed node manifests, the
  extra drivers and the ESP32-S3 camera boards, and an upgrade note for
  nodes still on core-2.x images; the pairing code lives in Setup → § III
  Cloud link; unknown `server/.env` keys are ignored and `TZ` must be
  exported; no side-by-side experiment telemetry, chamber comparison view,
  label-printer presets, container labels or per-category ntfy topics; the
  Server Modules table lists all 20 packages and labels the two single-file
  routers; the cloud pairing steps; the Sessions page row names what the
  page has (a finished session's `report.md`; the drying log and
  `report.csv` are API-only — no drying tracker or report downloads);
  `labels/` makes QR code PNGs (no thermal-printer support); the wizard asks
  five questions (the API scores six inputs). `AGENTS.md`: the platform pin,
  the core-3 pitfalls, the espota handshake rule, Shelly Gen2 prefixes,
  coredump store-then-ack, OTA manifests, the `browning` phase and the
  current frontend stack; frame liveness is replay / out-of-order, not frame
  age; `labels/` is router-only. New `firmware/README.md` sections
  (platform, build, OTA, updating nodes from a core-2.x image, coredumps) and
  `config/mosquitto/README.md` (listeners, accounts, plug topic layouts,
  adding a topic). `docs/integrations/smart-plugs.md` gains a Shelly Gen2+
  section; the build guide the Gen2 setup, a troubleshooting row and node
  firmware updates; `docs/firmware-security.md`, `docs/data-flow.md` and
  `docs/dual-repo-architecture.md` (React 19 bundle, 74 species, no
  Capacitor shell) are corrected; the spec (Cordyceps / active-category rest FAE,
  the MQTT watchdog, the vision correction mark).
- **Release docs pass (2026-10).** `docs/architecture-overview.svg` matches
  the stack: a React 19 / Vite 8 / Tailwind v4 dashboard on REST (it showed
  React 18, a PWA, Zustand and a Socket.IO client), the Compose services,
  every server module, the autodetected sensor set, OV5640 and the S3 camera
  boards, Shelly Gen1 and Gen2+, 25 kHz 10-bit PWM.
  `docs/wiring-overall-system.svg` names OV5640, ntfy, the Shelly Gen2+
  prefix and the browser's REST link. The Recommended and All the Things
  diagrams point S3 camera boards to build guide §8b, which gains a pin table
  for the AI-Thinker and the three S3 camera boards; the build guide also
  covers the portal's NTP server field and the Firmware page's signed-manifest
  upload. `docs/data-flow.md` describes the current flows (adding node
  maintenance: OTA push and coredump store-then-ack) instead of per-release
  change lists; `docs/cloud-relay-flow.md` has the real command shape
  (`target_kind`), the Pi's checks in order and the real `ota_step` names;
  the Mermaid block in `docs/dual-repo-architecture.md` is valid again (its
  services subgraph did not parse). README gains a `**Version:**` line that
  `scripts/bump.sh` keeps current, the cloud command checks (`target_kind`,
  a 64-character channel), the Shelly `status/switch:<n>` topic, the NTP
  portal field and `SPOREPRINT_INTEGRATION_KEY_PATH`. The integrations docs
  list Tapo with the LAN drivers, the vendor write actions (since v4.1.2)
  and rule-driven vendor actions, and the Grafana weight and door metrics.
- `tests/test_docs_consistency.py` pins the README, build guide, SVGs,
  AGENTS.md, the spec's tracked reference pages (`docs/species-reference.md`,
  `docs/feature-status.md`, `docs/automation-rules.md`) and (when present)
  the git-ignored `CLAUDE.md` to the code,
  firmware and BOM: tier prices and what a second chamber adds, fuse ratings,
  WAGO parts and wire gauges, the common ground in every guide and diagram,
  the strip sizes, the per-tier insert sourcing, the table and species
  counts and categories, the `GrowPhase` list, the platform pin, the PWM
  spec, the Socket.IO event names, the Shelly Gen2 prefix and each 2026-10
  audit claim; since the release docs pass also the camera pin tables (build
  guide and `firmware/docs/drivers.md`) against `firmware/boards/`, the
  architecture diagram's stack and module boxes, the README `**Version:**`
  line against `server/pyproject.toml`, the cloud command gate
  (`target_kind`, channel pattern, `ota_step` names), the retention tiers in
  `docs/data-flow.md`, the Grafana metric list, the vendor write actions, and
  a parse check for every Mermaid flowchart.
- **Docs fix round (2026-10).** The Aranet, Pulse and vendor-skeleton docs
  say vendor readings are stored and exported but never drive automation
  rules or safety alerts (only MQTT node telemetry does). No doc shows a
  shipping mobile app any more: README, `docs/dual-repo-architecture.md`,
  `docs/cloud-relay-flow.md` and `docs/auth.md` drop the iOS/Android app,
  `guardWriteAction` and FCM push, and `wiring-overall-system.svg`'s
  bottom-right box is now *Remote Access (Browser)*. The cloud docs put
  FastAPI on internal `127.0.0.1:9001` and the relay's ownership recheck at
  60 s. README: remote control is premium only (no read-only free path), QR
  labels open the Sessions or Cultures page, `SPOREPRINT_OTA_PUBKEY_B64`
  also verifies signed node manifests on Docker, `SPOREPRINT_CLOUD_URL`
  takes `https://` (plain `http://` only to a LAN dev relay), and the
  Development and Contributing commands match `AGENTS.md`. The submodule SHA
  is pinned by its gitlink, not `.gitmodules`. `AGENTS.md`: no CI runs on
  push or PR, parallel PlatformIO and `uv sync` pitfalls, REST and relay
  payloads are additive-only too, the LAN-only CORS rule, the version
  strings `bump.sh` rewrites, every trigger for stale Builder data, and the
  general import-cycle rule; its frontend brief points at the monorepo.
- README: the Chambers page loads chamber readings and events when it opens
  (only the Pi system panel polls); Chamber inventory shows the maintenance
  log, lifetime stats and photos, and chambers are created and given nodes
  through `POST`/`PATCH /api/chambers` only; a chamber follows its active
  grow's targets; the dashboard rebuild runs `port_builder.py` in the
  server's environment. The Agrowtek notes say where its readings go
  (`agrowtek:<sensor id>`; `sensor_mappings` is not used yet). The partition
  tables' comments name the envs that build with them and no longer call core
  2.0.17 the pinned core. `AGENTS.md` lists the lint and vendored-Monocypher
  guard suites and says never to edit the vendored copy. A
  `.worktreeinclude` copies the operator's git-ignored `CLAUDE.md` into each
  Claude Code worktree.
- **The active category is described, never named, in public docs.** The
  README's Species Library lists it as "species that are controlled or
  restricted in many jurisdictions" (it named the genus) and carries the
  dashboard's education-and-research notice; `docs/species-reference.md` and
  `docs/feature-status.md` say the same. `tests/test_active_species_public_docs.py`
  builds every active profile's common, strain, scientific, genus and
  epithet names from `profiles.py` and fails if any tracked Markdown file or
  anything under `docs/` uses one (word-bounded, case-blind), and checks the
  notice is where the category is described.
- `docs/cloud-relay-flow.md` and `docs/dual-repo-architecture.md` list
  browser notifications from `sporeprint.ai` (Web Push) beside the Pi's ntfy
  for premium accounts (they said browser push was not live yet). README,
  `docs/architecture-overview.svg` and `docs/dual-repo-architecture.md` name
  Vite 8, which now builds the dashboard. `docs/dual-repo-architecture.md`
  also names Next.js 16 for the cloud web app and calls the paid side "the
  commercial layer" without a repository name.

### Dependencies and CI
- anthropic 0.94 → 1.11, fastapi 0.135 → 0.142, starlette 1.0 → 1.7
  (Host-header bypass of the API-key gate fixed), cryptography 45 → 50.0.2
  (wheels bundle OpenSSL 4.0.3; now the floor), pillow 11.3 → 12.3, icalendar
  6.3 → 7.3 (no code change: the calendar feeds use none of 7.0's moved or
  removed APIs), uvicorn 0.54, python-multipart 0.0.32, python-socketio 5.17 /
  engineio 4.14, pydantic-settings 2.15, ruff 0.16. `server/uv.lock`
  regenerated (it was missing four runtime dependencies).
- GitHub Actions pinned to commit SHAs at current majors; PlatformIO 6.2.0 in
  CI and release; the release job alone gets write access.
- **Firmware releases are signed.** A `firmware-vX.Y.Z` tag
  (`.github/workflows/firmware-release.yml`) now publishes, per image env, a
  zip with `firmware.bin`, `bootloader.bin`, `partitions.bin` and the signed
  release manifest `<env>.manifest.json` + `.sig`, every image built with the
  release verify key compiled in (the release notes print it). The signing
  key (secret `OTA_SIGNING_KEY`) reaches only one step in each of two jobs
  that run no build tooling, no third-party action and no write token: one
  derives the public key, the other signs. The PlatformIO builds get the
  public key only, and the job that creates the release holds a write token
  but never the key. The two key jobs run in a `firmware-release`
  environment, so the key can be scoped to release tags there
  (`docs/firmware-security.md`). The workflow fails closed without the
  secret, accepts only exact `firmware-vX.Y.Z` tags, refuses a tag whose
  `firmware/VERSION.txt` differs, and restores no build cache. Its key, sign
  and release jobs install only the hash-pinned `cryptography` wheels
  `server/uv.lock` records; the build installs PlatformIO 6.2.0 and its
  dependencies from the new hash-pinned `firmware/requirements-pio.txt`,
  creates the platform's own Python virtualenv from the new hash-pinned
  `firmware/requirements-penv.txt` and builds with uv offline (so the
  platform's open version floors fetch nothing from PyPI), then fetches the
  pioarduino platform zip and the framework and tool packages it builds
  with, and refuses any whose SHA-256 differs from the new
  `firmware/toolchain.lock.json` (`scripts/pin_firmware_toolchain.py`,
  which also refuses a platform whose virtualenv wants an unpinned package
  and fails the build if anything was installed from an unchecked URL or the
  virtualenv holds an unpinned package). The toolchain binaries come
  through Espressif's `idf_tools.py`, which checks them against the SHA-256
  in those packages. The first job records the tagged commit, and every later job
  stops unless the tag still names it, so a tag moved during a run releases
  nothing. The new
  `scripts/verify_firmware_release.py` checks every zip as the Pi and the
  node will (signature, canonical manifest, env, version, channel, SHA-256,
  size, cross-checked with the Pi's own verifier) and that each image is for
  its env's chip with the verify key, env and version compiled in; the
  workflow runs it after signing and again just before publishing, and
  anyone can run it on a downloaded zip. The release notes' USB flash
  commands erase the flash first, since the zips carry no OTA boot
  selection. Tests: the script against the committed manifest vectors and
  tampered zips; the workflow's triggers, permissions, key scoping,
  environment, SHA pins, tag guard and env list; and its sign, zip and
  verify scripts run under bash (`tests/test_verify_firmware_release.py`,
  `tests/test_firmware_release_workflow.py`); the toolchain lock and its
  checks (`tests/test_pin_firmware_toolchain.py`).
- `ruff check app/` passes again (unused imports and placeholder-less
  f-strings removed; E402 is ignored by design for `app/main.py` and the
  vendor `__init__.py` files) and `tests/test_lint.py` keeps it green.
- Every dependency checked against its latest stable release on 2026-10-06:
  the Python packages, base and service images, PlatformIO libraries
  (PubSubClient 2.8, ArduinoJson 7.4.3, Monocypher 4.0.3: already current)
  and workflow actions (already current). The Python base image stays on the
  3.12 line.
- The lint gate's rule set is pinned in `server/pyproject.toml`
  (`select = ["E4", "E7", "E9", "F"]`, the rules it has always checked): ruff
  0.16 widened its implicit default from 59 rules to 413, and a ruff upgrade
  must not change the gate by itself.
- The unused `vision` extra is gone from `server/pyproject.toml`: nothing
  imported its runtimes (the local CNN pass is still a stub), and its
  `tflite-runtime` has had no release since 2023 and no wheel for Python 3.12.
  The runtime the CNN loads comes back with the change that builds it. The
  stub result's `note` no longer tells you to install the extra.
- FastAPI 0.142 brings `opentelemetry-api`. It stays a no-op: the image
  installs no OpenTelemetry SDK or exporter, and compose forwards no `OTEL_*`
  variable, so no traces, metrics or logs leave the Pi.
- **Dependabot** (`.github/dependabot.yml`): weekly version updates for the
  server's uv lock, the server and ui base images, the compose service images
  and the workflow actions, with a release-age cooldown. uv and Actions
  minor/patch updates are grouped; image updates come one PR each. No CI
  runs on its pull requests (Actions are release-gated), so each one is
  verified locally before merging; PlatformIO pins and the firmware
  release's hash-pinned Python requirements stay manual.

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

Lockstep version bump — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.6] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.5] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.4] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.3] - 2026-05-02

Lockstep version bump in step with the cloud parent — no Pi-side server, UI, or firmware code changes in this release.

## [4.0.2] - 2026-05-01

Lockstep version bump only — no Pi-side, server, UI, or firmware changes.

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

Lockstep version bump — no Pi or firmware changes. Firmware build unchanged.

## [3.4.9] - 2026-04-24

Fresh archaeology sweep of v3.4.8. All Critical, High, Medium, Low + operator-feedback items closed in one pass. Firmware grew real defense-in-depth at the MQTT layer; the cloud relay gained tier/ownership re-checks + rate limiting + `cmd_id` correlation; the Pi server got structured logs + split MQTT ACL + synced dependency pins. Firmware-specific narrative in `firmware/CHANGELOG.md#349`.

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

No Pi protocol or code changes. Lockstep version bump.

## [3.4.5] - 2026-04-22

No Pi protocol or code changes. Lockstep version bump.

## [3.4.4] - 2026-04-22

No Pi protocol or code changes. Lockstep version bump.

## [3.4.3] - 2026-04-22

No Pi protocol or code changes. Lockstep version bump.

## [3.4.2] - 2026-04-22

No Pi protocol changes. Lockstep version bump.

### Changed

- **L-4 `_configure_token` multi-slot dict.** Pre-v3.4.2 carried a single `dict | None` global — a second parallel `/pair` would overwrite the first's token and invalidate it before the first client could `/configure`. Now keyed by token in `_configure_tokens` with TTL sweeps and a 32-entry hard cap. Parallel `/pair` sessions coexist; pair-spam attackers can't blow memory.

## [3.4.1] - 2026-04-21

No Pi-side functional changes. Lockstep version bump.

All Pi protocols (HMAC signing, pair-verify, MQTT auth, bearer API-key gate) remain byte-compatible with v3.3.3+ / v3.4.x clouds.

## [3.4.0] - 2026-04-21

No Pi-side functional changes. Lockstep version bump.

### Changed

- `scripts/bump.sh` now matches the cloud-side bump script: auto-inserts a CHANGELOG skeleton for the new version, updates the README's `**Version:**` banner if present, and prints a doc-drift warning for any lingering `v${CURRENT}` references in README / docs.

### Documentation

- README banner rewritten to explain the new commercial/OSS split: the Pi repo stays AGPL-3.0 free software; cloud-relay/mobile/web-app are paid. Pi-standalone users are unaffected.
- Added historical release callouts for v3.3.3 / v3.3.4.

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
