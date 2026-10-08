<h1 align="center">SporePrint</h1>

<p align="center">
  <strong>Automate a mushroom grow room from a Raspberry Pi you run</strong><br>
  Raspberry Pi server, ESP32 firmware and printable enclosures: 74 species profiles,<br>
  rules-based climate control, weather-aware alerts and optional Claude camera analysis.<br>
  The server, firmware and models are open source (AGPL-3.0); the Pi dashboard ships here as a pre-built bundle.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="#open-source">Open Source</a> &bull;
  <a href="#species-library">Species Library</a> &bull;
  <a href="#hardware">Hardware</a> &bull;
  <a href="#api-reference">API Reference</a> &bull;
  <a href="#contributing">Contributing</a> &bull;
  <a href="#getting-help">Getting Help</a>
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" />
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue.svg" />
  <img alt="FastAPI" src="https://img.shields.io/badge/fastapi-0.110%2B-009688.svg" />
  <img alt="Platform" src="https://img.shields.io/badge/platform-Raspberry%20Pi%205-c51a4a.svg" />
</p>

---

## Release notes

**Version:** 5.2.2

The full history is in [CHANGELOG.md](CHANGELOG.md) (Pi server, install,
enclosures) and [firmware/CHANGELOG.md](firmware/CHANGELOG.md) (ESP32 images).

- **5.2.0:** a paired Pi now sends its grow sessions and contamination events
  to the sporeprint.ai web app, the cloud connector connects again (it was
  missing a dependency), and a Pi set up by an older release gets the
  built-in rules added since (CO2 Hard Ceiling, CO2 Floor — Restrict FAE).
  No firmware code changed.
- **5.1.0:** the large release after 5.0.0. A September 2026 review of the
  parts list, firmware, safety, enclosures and install, and the October
  follow-ups: Arduino-ESP32 core 3.x, a driver for every sensor the parts
  list ever named, ESP32-S3 camera boards, Shelly Gen2+ plugs, the shiitake
  browning phase, coredump acknowledgements and signed firmware manifests.

### Upgrading an existing Pi

- **The Pi:** `cd ~/SporePrint && git pull && ./install.sh` (see
  [Update](#update)).
- **Coming from 5.0.x or earlier,** these changes need your attention:
  - Automation schedules (photoperiod, time windows, cron) follow the Pi's
    time zone: `install.sh` writes the host zone into `.env` as `TZ` and prints
    a warning. Rule times you typed in UTC to compensate must be changed back,
    or set `TZ=UTC` in `.env` to keep the old behaviour.
  - Command signing is on by default: `install.sh` generates
    `SPOREPRINT_MQTT_HMAC_KEY` (or reuses the one an older
    `provision-node.sh` left in `server/.env`). A cloud-paired Pi without a key
    refuses every node command, so run `./install.sh` (or
    `./scripts/provision-node.sh`) and `docker compose up -d server` before
    pairing.
  - The database moves to incremental auto-vacuum with one full `VACUUM`. A
    database up to 32 MB converts at the end of the first boot, once MQTT,
    automation and the safety watchdogs are running; a bigger one is left to
    the nightly retention window. It needs free disk of at least 2 × the
    database size + 64 MB; otherwise it is skipped with a WARNING and retried.
  - Nodes with **Secure MQTT** ticked that ran on the plaintext fallback now
    get the Pi's CA. Run `./install.sh` first (it re-issues the broker
    certificate with every Pi IPv4). Firmware from 5.0.0 or earlier pins
    the CA at its next reboot without checking that TLS works, so a node whose
    Pi address the certificate doesn't cover loses MQTT until you reach it
    physically; point nodes at `sporeprint.local` or update their firmware
    first. Current firmware pins only after a working TLS connection.
  - The API answers only for LAN host names (DNS-rebinding guard). Reach the
    Pi by a public DNS name, such as a Tailscale `*.ts.net` name? Add it to
    `SPOREPRINT_ALLOWED_HOSTS` in `.env`, then `docker compose up -d server`.
- **Node firmware:** push the new image to each node from the dashboard's
  Firmware page, as before. From `firmware-v5.1.0` on, each
  `firmware-vX.Y.Z` GitHub Release has a signed zip per board:
  `firmware.bin` plus its signed manifest. The push form takes the manifest
  too, once the Pi pins the release key printed in the release notes
  (Settings → OTA verify key); see
  [firmware/README.md](firmware/README.md#releases). Nodes on a core 2.x
  image (any release before 5.1.0) take the first core 3.x image over the
  air, with no USB cable. Before you update every node, update one per board
  type and check its heartbeat
  ([firmware/README.md](firmware/README.md#updating-nodes-from-a-core-2x-image)).
- **Pis older than v3.3.0:** the broker has refused anonymous clients since
  v3.3.0, so every node needs its own broker login
  (`./scripts/add-node-mqtt-user.sh <node_id>`) and an OTA password of at
  least 12 characters, entered in its setup portal. Cloud relays must be at
  v3.3.1 or later (the relay signs every command).

---

## What is SporePrint?

SporePrint automates a mushroom grow room from a Raspberry Pi you run. ESP32
nodes report temperature, humidity, CO2 and light over MQTT, plus scale
weight and door state if you fit them. Rules built from each species profile
switch your fans, lights, pump and smart-plug humidifier, dehumidifier,
heater and cooler to hold the targets of the grow's current phase. The Pi
sends you an ntfy notification when temperature, humidity or CO2 moves
outside the phase's range by more than a set margin, when a node goes
offline, and, once you give it your location, when the weather forecast puts
a target at risk in the next 72 hours.

It also records each grow from inoculation to harvest: phases, yield and
biological efficiency, drying, cultures and lineage, A/B experiments and QR
labels. With your own Anthropic API key, Claude checks each grow's camera
photos every 6 hours, flags likely contamination, and analyzes sessions and
experiments.

### Free and Premium

**Free.** This repo runs on your own Raspberry Pi and ESP32 nodes, with no
account needed: monitoring, automation rules, weather-aware alerts, grow
tracking, the species library, and Claude camera analysis with your own
Anthropic API key. The Pi dashboard is on your network at
`http://<pi-ip>:3001` and asks for no login, so keep the Pi behind your
router; to reach it away from home, use your own VPN, such as Tailscale.
Monitoring and automation keep running without internet. Weather, Claude,
installs and updates need a connection.

**Premium (optional).** $4.99/month or $39.99/year (USD) at
[sporeprint.ai](https://sporeprint.ai/pricing). One plan covers every Pi you
pair, and each paired Pi shows in the web app as one chamber. It adds the
sporeprint.ai web app on top of your Pi: remote control, browser
notifications and email escalation, a daily summary, grows synced from your
Pi, analytics on up to 90 days of telemetry, exports, Claude photo checks,
Grow Advisor and session analysis.

- Premium annual starts with a 14-day free trial if you haven't subscribed on
  the web before. Monthly has no trial.
- On SporePrint's Anthropic key you get 10 Claude requests a month, shared
  across those features and reset on the 1st (00:00 UTC). With your own
  Anthropic API key, added in the web app, there's no monthly cap (rate
  limits apply).
- Pairing needs your Pi at a public HTTPS address for a few minutes; after
  that the Pi connects out. See [Cloud Connector](#cloud-connector).
- If Premium lapses, your Pi keeps running locally. The web app stops
  receiving data, and cloud grow data is deleted 90 days later unless you
  resubscribe.

There's no SporePrint mobile app yet. On iPhone or iPad (iOS 16.4+), add
sporeprint.ai to your Home Screen to get browser notifications.

### Key Highlights

- **74 built-in species profiles**, each with per-phase environmental targets, TEK guides, substrate recipes and photo references ([Species Library](#species-library) lists the categories)
- **20 server modules** with 150 API operations (REST + a Prometheus `/metrics` exporter)
- **Pre-built Pi dashboard** -- chambers overview, sessions, species library, vision, automation, hardware builder, grow planner, contamination guide, cultures, experiments, integrations and settings. It ships here as a bundle; its source is not in this repo (see [Open Source](#open-source))
- **33 SQLite tables** with tiered data retention (~120 MB/year)
- **Claude camera analysis** -- every camera frame is stored; with your own Anthropic API key, Claude checks them every 6 h per grow, on each phase change and on demand. The local CNN layer is still a stub.
- **Weather failover** -- Open-Meteo first (free, no key), then the US National Weather Service, then OpenWeatherMap if you add its API key
- **Weather-predictive alerts** up to 72 hours in advance
- **10 OpenSCAD 3D-printable enclosure models** -- parametric, fit-checked against sourced part drawings, joined with brass heat-set inserts
- **5 SVG diagrams** -- a colour-coded wiring diagram per hardware tier (inside vs outside the chamber, power strip, fused 12 V distribution, wire gauges, the common ground), a whole-system overview and an architecture overview

---

## Open Source

The Pi server, the ESP32 firmware, the enclosure models and the docs in this
repo are open source under the [GNU AGPL-3.0](LICENSE). The Pi dashboard
ships here as a free pre-built bundle in `ui/dist`; its source, and the
sporeprint.ai web app and cloud, are proprietary and not published. That
means dashboard changes can't come through a pull request here; report
dashboard bugs as issues instead (see [Contributing](#contributing)).

---

## Quick Start

### What you need

- A **Raspberry Pi 5 (4 GB)** with the official 27 W USB-C power supply and
  the Active Cooler, running 64-bit Raspberry Pi OS, Ubuntu Server or
  Debian 12+. A Pi 4 isn't recommended: its ports differ and it doesn't fit
  the printed case.
- **ESP32 nodes** for the sensors and for switching fans, lights and the
  pump, and optionally a camera node and Tasmota or Shelly smart plugs.
  [Hardware](#hardware) lists the supported boards and sensors. The three
  reference builds come to about $290, $745 and $960 in parts (prices checked
  27 Sep 2026), and the [build guide](docs/hardware-build-guide.md) walks
  through each one.

### Install on the Pi

1. Image the SD card with Raspberry Pi Imager. In its advanced options, set
   the hostname to `sporeprint`, turn on SSH and enter your WiFi details.
   ESP32 nodes look for the broker at `sporeprint.local`; with another
   hostname, give each node the Pi's IP address instead (and reserve that
   address in your router).
2. SSH into the Pi and run:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/59psi/SporePrint/main/install.sh | bash
   ```

The script installs Docker if it's missing, so this is the only command you
need. `install.sh` is safe to run again. It:

1. Detects the OS and installs Docker Engine + the Compose plugin (via
   `get.docker.com`), plus `chrony` (NTP) and `openssl`, if they are missing.
2. Clones the repo into `~/SporePrint` (or pulls it if it is already there;
   run from inside a checkout, it uses that checkout as is).
3. Writes a LAN-trust `.env` with the secrets the stack needs — the MQTT broker
   credentials (`server`, plus `sp-3p` for smart plugs), the command-signing
   key `SPOREPRINT_MQTT_HMAC_KEY` and the host's time zone as `TZ` — and
   creates the broker's TLS certificates (IP and DNS SANs for every host IPv4).
   Values you already set are kept; no secret is committed.
4. Builds and starts everything with `docker compose up -d --build`, then waits
   for the API to report healthy.
5. Prints the dashboard URL, the schedule time zone, the command-signing status,
   the smart-plug credential and the common ops commands.

When it finishes, open the Pi dashboard at **http://<pi-ip>:3001**, or
`http://sporeprint.local:3001` if you named the Pi `sporeprint` and mDNS works
on your network. On a new Pi it opens the Setup wizard.

The wizard's **Setup → § III Cloud link** step pairs the Pi with a Premium
sporeprint.ai account ([Cloud Connector](#cloud-connector) has the steps).
Skip it to run the Pi on its own.

### Update

```bash
cd ~/SporePrint && git pull && ./install.sh
```

Run `./install.sh` after every pull: it writes any keys a new release needs
into `.env` and rebuilds the stack, which a plain
`git pull && docker compose up -d --build` skips. There is no downloadable Pi
update, and the cloud doesn't update the Pi: the Docker install refuses update
commands sent from the cloud. ESP32 nodes are updated from the dashboard's
Firmware page (see [Upgrading an existing Pi](#upgrading-an-existing-pi)).

### Running the Pi

**Manage the stack** (from `~/SporePrint`):

```bash
docker compose logs -f server    # live server logs
docker compose ps                # service status
docker compose up -d server      # apply .env changes ('restart' does NOT re-read .env)
docker compose down              # stop (data is kept in named volumes)
```

**Time zone.** Photoperiod, time-window and cron rules, the daily 09:00
phase reminder, transcript timestamps and the weather "today" window follow
`TZ` in `~/SporePrint/.env` (compose passes `TZ=${TZ:-UTC}`). Use a canonical
Region/City name such as `America/Los_Angeles`: the server image has no legacy
aliases, and an unknown zone silently runs on UTC.

**Security — LAN-trust by default.** The Pi's own dashboard calls the API
same-origin with no token, so the stack ships with HTTP auth off
(`SPOREPRINT_ALLOW_UNAUTHENTICATED=true`). That is safe on a home LAN behind a
router/NAT — keep the Pi there and never port-forward it. To reach the
dashboard away from home, use your own VPN, such as Tailscale. The MQTT broker is
still credentialed, and the API answers only for LAN host names, so a web
page cannot reach it by DNS rebinding (`SPOREPRINT_ALLOWED_HOSTS` adds
others). To require an API key for external clients (scripts, other
tools), set `SPOREPRINT_API_KEY` in `~/SporePrint/.env` and run
`docker compose up -d server` — the bundled browser dashboard sends no key, so
it stops working in that mode. See [docs/auth.md](docs/auth.md).

**Backups.** There is no backup script yet. Back up the whole `sporeprint_db`
Docker volume: `sporeprint.db` (copy it with `sqlite3 … ".backup …"`, not
`cp`), `.integration-key` (losing it means re-entering every vendor
credential) and `cloud.env` (the cloud pairing, mode 0600). Vision frames live
in the `sporeprint_vision` volume.

### Manual Docker Compose

The one-command installer above is the supported path because the stack needs a
broker password file and TLS certificates generated on first run. A bare
`docker compose up` without them fails with "bind source path does not exist".
If you prefer to drive Compose yourself, let `install.sh` do that one-time
preparation, then start the stack:

```bash
git clone https://github.com/59psi/SporePrint.git
cd SporePrint
SPOREPRINT_SKIP_START=1 ./install.sh   # writes .env + broker creds + TLS certs, then stops
docker compose up -d --build
```

Services:
- **UI**: http://localhost:3001  (nginx — serves the dashboard, proxies `/api` + `/socket.io`)
- **API**: http://localhost:8000  (also serves `/metrics` when the Grafana integration is on)
- **MQTT**: port 1883, TLS on 8883 — published on the LAN, credentialed and ACL-scoped; ESP32 nodes connect here
- **ntfy**: http://localhost:8080 (notifications on your network)
- **OTA push callback**: TCP 3233 (nodes fetch Pi-pushed firmware from it)

### Manual Development Setup

```bash
./setup.sh                              # DEVELOPER workstation only: .venv, .env, broker creds + certs
source .venv/bin/activate
docker compose up -d mqtt               # the credentialed broker, on localhost:1883
cd server && uvicorn app.main:socket_app --reload    # API on :8000
```

Run from `server/`, the API reads `server/.env`, not the repo-root `.env`.
Copy the `SPOREPRINT_*` settings you need there (for example
`SPOREPRINT_MQTT_USERNAME=server` and its password from the root `.env`).
Keys it does not know, such as `TZ` or `SPOREPRINT_MQTT_3P_PASSWORD`, are
ignored, so a copied root `.env` works. But the schedule time zone is read from
the process environment, not from `.env`: export `TZ` in the shell that runs
uvicorn.

The dashboard source is not in this repo (see [Open Source](#open-source)):
this repo ships the pre-built bundle in `ui/dist`, which the `ui` container
serves. Its Builder page reads this server live: the BOM from `/api/builder/tiers`, the 3D models from
`/api/builder/models`, the wiring diagrams from `/api/builder/diagrams` and
the firmware ZIPs from `/api/builder/firmware`. If one of those requests
fails, that resource falls back to a copy built into the bundle, and a pill
at the top of the page says whether you are seeing live or built-in data.
The built-in copy is generated from this repo when the dashboard is built.
`server/tests/test_ui_builder_sync.py` fails when the bundle stops reading
the API live, or when its built-in copy no longer matches this server.
[Development](#development) shows how the bundle is rebuilt (maintainer
only) and how anyone can refresh its built-in copy.

### ESP32 Firmware

Once the Pi is running, open the Builder page (`http://<pi-ip>:3001/builder`)
and scroll to **ESP32 Firmware**. Two images cover everything: the
**unified node** (climate / relay / lighting — pick the personality in the
node's setup portal) and the **camera**. The ZIP buttons download
self-contained PlatformIO projects. Unzip, then flash with:

```bash
cd firmware
pio run -t upload -e node_esp32             # ESP32-WROOM-32 DevKit (every wiring diagram)
pio run -t upload -e node_esp32s3           # ESP32-S3-DevKitC-1 N8 / N8R8 / N16R8 — different pin map
pio run -t upload -e node_esp32s3_n32r16v   # ESP32-S3-DevKitC-1-N32R16V (node_esp32s3 does not boot on it)
pio run -t upload -e cam                    # AI-Thinker ESP32-CAM (OV2640 / OV3660 / OV5640), on its ESP32-CAM-MB
pio run -t upload -e cam_esp32s3            # earlier BOMs' S3 cameras: Freenove ESP32-S3-WROOM CAM,
pio run -t upload -e cam_xiao_esp32s3       #   Seeed XIAO ESP32S3 Sense,
pio run -t upload -e cam_waveshare_s3       #   Waveshare ESP32-S3-CAM-OV5640 (no flash LED; build guide §8b)
```

Prebuilt, signed images for every board are on each `firmware-vX.Y.Z`
GitHub Release from `firmware-v5.1.0` on, with esptool commands for a USB
flash; see [firmware/README.md](firmware/README.md#releases). (The older
`firmware-v4.2.0` release holds unsigned images for three boards only.)

Before provisioning a node, create its broker login on the Pi:
`./scripts/add-node-mqtt-user.sh <node_id>` (the MQTT username is the node
id). On first boot each node opens the `SporePrint-Setup` WiFi portal
(WiFi, Pi address, MQTT login, personality, optional peripherals, OTA password,
command-signing key, Secure MQTT, NTP server; the camera's portal has no
personality or peripherals). Or clone the repo and flash from `firmware/` directly — the ZIP
bundle is equivalent to `firmware/src/<image>/ + firmware/lib/ +
firmware/boards/ + firmware/platformio.ini`, plus `VERSION.txt`, every
`partitions*.csv` and the files `platformio.ini` references (the
`scripts/fw_version.ini` extra config, its version script and the
`image_guard.py` post-build check). The first build downloads the pinned
platform (Arduino-ESP32 core 3.3.12, about 1 GB) and needs PlatformIO Core
6.2.0 or newer plus git. The S3 builds use their own GPIOs: see the
[build guide](docs/hardware-build-guide.md).

### Prerequisites

Only needed for manual dev — `install.sh` handles everything on a Pi
(`scripts/setup-pi.sh` is now just a wrapper around it).

- Python 3.11+
- openssl
- Docker and Docker Compose (for the broker, and for production deployment)
- PlatformIO Core 6.2.0 or newer, plus git (for ESP32 firmware — `pip install -U platformio`; the pinned pioarduino platform downloads about 1 GB on the first build)

---

## Features

### Environmental Monitoring and Automation

- **Telemetry** -- temperature, humidity, CO2, light, scale weight and door state from ESP32 nodes via MQTT
- **Declarative rules engine** -- threshold, schedule, and compound conditions with species-aware targets and per-chamber scoping; the highest-priority rule whose condition holds owns an actuator
- **Safety ceilings** -- `safety_max_on_seconds` counts from the first ON; a tripped held-ON ceiling switches the device off and locks automation out of it for 15 min
- **Weather-aware virtual sensors** -- the system learns the correlation between outdoor weather and indoor conditions over time
- **Multi-provider weather failover** -- the Pi gets weather from Open-Meteo (free, no key), falls back to the US National Weather Service (US only), and then to OpenWeatherMap if you add its API key. Set the Pi's location through `/api/settings` or `.env`; the order is fixed
- **Predictive alerts** -- warns up to 72 hours ahead when species targets will be violated based on weather forecasts
- **Smart plug integration** -- Tasmota, Shelly Gen1 and Shelly Gen2+ (Plus, Pro, Mini, Gen3, Gen4) control via MQTT (Tasmota needs Full Topic `tasmota/%topic%/%prefix%/`; a Gen2+ Shelly needs MQTT prefix `shellies/<role>`)
- **Third-party integrations** -- Aranet, Pulse, Kasa, Tapo, Wemo, Grafana/Prometheus and more under [docs/integrations/](docs/integrations/), all free on the Pi. Kasa, Tapo and Wemo plugs are switched through integration actions, not the built-in climate rules. The Agrowtek, Quest, Anden, BIOS, Trane, Fluence and Fohse drivers, and Pulse Grow's local mode, are written from vendor docs and not yet tested on hardware ([details](docs/integrations/lighting-hvac-skeletons.md), [Pulse](docs/integrations/pulse/README.md))
- **Tiered data retention** -- raw (7 days), 5-min averages (30 days), hourly (1 year), daily (forever); ~120 MB/year on Pi

### Grow Session Management

- **Full lifecycle tracking** -- inoculation through harvest with validated phase transitions and location tracking (tub, shelf, side). Colonized jars and agar park in cold storage; shiitake gets its own browning phase, with the cold-water soak reminder before pinning
- **Yield statistics** -- per-session biological efficiency and yield-per-gram calculations
- **Drying tracker** -- per-harvest drying log with weight tracking over time and cracker-dry notification
- **Session reports** -- Markdown (`report.md`) and CSV (`report.csv`) downloads per session
- **iCal calendar feed** -- subscribe in Google Calendar or Apple Calendar for session milestones and phase reminders
- **Session transcripts** -- structured JSON and narrative markdown exports with Claude analysis scoring
- **Actuator safing** -- ending a grow switches the actuators it drove off (per chamber when several grows run)

### Species Library (74 profiles)

- **Per-phase environmental targets** -- temperature, humidity, CO2, light, and FAE for every grow phase
- **TEK guides** -- step-by-step cultivation instructions from agar to harvest
- **Substrate recipes** -- species-specific formulations with ingredient ratios
- **Photo references** -- visual guides for identifying healthy growth stages
- **Contamination risk data** -- species-specific susceptibilities and prevention strategies
- **Regional growing notes** -- climate-specific tips
- **Species Selector Wizard** -- guided five-question questionnaire on the dashboard (the API scores six inputs) with weighted scoring to recommend species for your setup and experience level. Species in the active category are left out unless you opt in (`include_active=true`, the wizard's "include active species" switch); that category is for education and research purposes only (notice below)
- **Substrate Calculator** -- volume-based recipe scaling for custom container dimensions
- **Shopping List Generator** -- itemized supply lists with quantities and supplier links

> **Educational and research use** ([Terms of Service §7](https://sporeprint.ai/legal/terms#educational-use)): Some cultivation profiles in SporePrint cover species that are controlled or restricted in many jurisdictions. That information is provided for education and research purposes only. Any use of SporePrint with those species is for education and research purposes only, and only where it is lawful. It is not encouragement to cultivate, possess, or use any controlled organism. You are solely responsible for knowing and complying with the laws where you live.

### Seasonal Grow Planner

- **Weather-based species recommendations** -- scores species against local climate history to find what grows best in your area right now
- **Grow calendar** -- monthly view of species compatibility per season
- **Dated cycle proposal** -- from a species + inoculation date, generates the full phase-by-phase grow calendar with per-phase setpoints and a projected harvest date (`/api/planner/propose`, or `.ics` for any calendar app)
- **Session warnings** -- alerts for active sessions when unfavorable conditions are forecast
- **iCal export** -- add your grow calendar to any calendar app

### Contamination Library

- **7 contaminant profiles** -- trichoderma, cobweb mold, black mold, bacterial blotch, lipstick mold, penicillium and wet spot
- **Symptoms and treatment protocols** -- identification guides with recommended responses
- **Claude identification** -- upload a photo of suspected contamination and Claude assesses it (needs your own Anthropic API key)

### Culture and Genetics Tracking

- **Lineage tree visualization** -- trace genetics from spore print through agar, liquid culture, grain, and bulk
- **Generation counting** -- automatic generation tracking with parent/child relationships
- **Transfer logs** -- record every transfer with date, source, destination, and notes
- **Contamination rate per lineage** -- identify clean vs. problematic genetics
- **Spore print and clone tracking** -- log spore prints, tissue clones, and liquid culture with source metadata

### Multi-Chamber Management

- **Named chambers** -- each chamber runs to the targets of its active grow's species profile (a chamber stores no targets of its own)
- **Node assignment** -- assign ESP32 nodes to specific chambers through the API (`POST /api/chambers`, `PATCH /api/chambers/{id}` with `node_ids`; neither dashboard edits chambers yet). With grows in more than one chamber, list every node (climate, relay, light, camera) in its chamber: an unlisted node then belongs to neither grow
- **Per-chamber automation** -- rules scoped to individual chambers
- **Chamber comparison API** -- `GET /api/chambers/compare?ids=…` returns side-by-side chamber metrics (API only; the dashboard has no comparison view)

### A/B Experiment Mode

- **Controlled experiments** -- compare conditions, substrates, or species across paired sessions
- **Per-metric comparison** -- control vs. variant value, percent difference and winner for each dependent variable (`GET /api/experiments/{id}/comparison`)
- **Optional Claude analysis** -- Claude interprets the experiment's results (needs your own Anthropic API key)

### QR Code Labels

- **Session labels** -- QR codes that open the Pi dashboard's Sessions page (culture labels: the Cultures page), for jars, bags, and tubs. The page does not jump to the item, so keep the id printed on the label
- **Culture labels** -- track genetics containers with scannable codes
- **PNG QR codes** -- `GET /api/labels/qr?type=session|culture&id=…&size=50–500` (pixels); print them from your label printer's own app

### Vision Pipeline

- **Camera node** -- AI-Thinker ESP32-CAM (OV2640 or OV3660, OV5640 also supported, auto-detected) takes a flash-lit UXGA still every 15 minutes (and on demand) and POSTs it to the Pi. The same image builds for the ESP32-S3 camera boards earlier BOMs listed (no flash LED). There is no live MJPEG stream
- **Claude camera analysis** -- morphology analysis with species-specific context: every 6 h per session (`SPOREPRINT_VISION_AUTO_INTERVAL_MIN`), on the first frame after a phase change, and on demand. It uses your own Anthropic API key (`SPOREPRINT_CLAUDE_API_KEY` or Settings), and frames go from the Pi straight to Anthropic
- **Contamination alerts** -- a confident contamination read (≥ 0.6) pages CRITICAL and is recorded as a contamination event; 0.3–0.6 sends one "Possible contamination" WARNING
- **Local CNN** -- the fast first-pass layer is a stub today, so Claude auto-analysis is the only automatic contamination detector (worst-case latency = the auto-analysis interval)
- **Frame retention** -- frames are kept 30 days, then thinned to one per camera per day (flagged, labelled and referenced frames are always kept)

### Hardware Builder

- **3 hardware tiers** -- Bare Bones (~$290), Recommended (~$745), All the Things (~$960); a second chamber adds ~$62 / ~$316 / ~$527, because the Pi side is bought once and the kits and spools (wire, connectors, fuses, inserts, screws, solder) come in whole packs that cover more than one chamber
- **Shopping lists** -- complete parts lists with purchase links, re-checked live 2026-09-27, including the cabling and consumables (surge strip, pigtail, WAGO connectors, inline fuses, 18 / 22 AWG wire, fan extensions, heat-shrink, grommets, inserts, screws)
- **Wiring diagrams** -- color-coded SVG diagrams for each tier, served by the Pi at `/api/builder/diagrams/<file>.svg`
- **Step-by-step assembly** -- guides for building sensor and actuator nodes
- **Claude guide generator** -- `POST /api/builder/guide` writes a parts / wiring / firmware / MQTT / OpenSCAD / safety / test guide for new hardware, with your registered nodes and the reserved GPIOs as context, and saves it (`/api/builder/guides`). Needs your own Anthropic API key. API only: the dashboard has no chat for it

### Notifications

- **3-tier ntfy alerts** -- critical (immediate; identical pages collapse for 15 min), warning (5-min dedup), info (the same message at most once an hour)
- **Delivery** -- the bundled ntfy server runs on the Pi (port 8080). In the ntfy app, subscribe to the topic (`sporeprint` by default) on `http://<pi-ip>:8080`. The phone has to reach the Pi, on your network or over your own VPN. On an iPhone, alerts can arrive late while the ntfy app is in the background, because the Pi's ntfy server doesn't forward to Apple's push service
- **Weather-predictive notifications** -- alerts up to 72 hours before conditions deteriorate
- **Phase reminders** -- a daily 09:00 (local `TZ`) INFO notice for every grow past its phase's expected duration, and the shiitake cold-water soak once browning has run its minimum time
- **Configurable topic** -- one ntfy topic (`SPOREPRINT_NTFY_TOPIC`, or Settings → Notifications) for every tier; the tiers map to ntfy priorities

### System Health

- **Pi system metrics** -- CPU, memory, disk, temperature via psutil
- **MQTT broker stats** -- connection counts, message rates
- **Socket.IO client tracking** -- active WebSocket connections by real client address
- **Background task registry** -- status of MQTT, weather polling, retention, phase reminders, cloud connector

### Unit Preferences

SporePrint shows temperature in °F and weight in grams. There's no °C or
ounce setting (the dashboard's Settings lists it as unsupported), and the
server stores no unit preference. Every species profile's targets are in °F.

---

## Build one

- **[Hardware Build Guide](docs/hardware-build-guide.md)** — step-by-step, parts to first telemetry. Start here.
- Wiring diagrams: [Bare Bones](docs/wiring-tier1-bare-bones.svg) · [Recommended](docs/wiring-tier2-recommended.svg) · [All the Things](docs/wiring-tier3-all-the-things.svg) · [Whole system](docs/wiring-overall-system.svg)
- Printable enclosures: [`models/`](models/) — see [models/README.md](models/README.md) for presets, heat-set inserts and screws
- Firmware security model: [docs/firmware-security.md](docs/firmware-security.md)

## Architecture

- [Architecture Overview](docs/architecture-overview.svg) — three-layer Pi system (dashboard → server → ESP32)
- [Data Flow](docs/data-flow.md) — telemetry, weather intelligence, user actions, and the closed-loop control path (Mermaid)
- [Cloud Relay Flow](docs/cloud-relay-flow.md) — browser → cloud → HMAC-signed command → Pi (Mermaid sequence diagram)
- [Dual Repo Architecture](docs/dual-repo-architecture.md) — how this public repo relates to the proprietary sporeprint.ai cloud (Mermaid)
- [Auth](docs/auth.md) — LAN-trust vs API-key mode, and the public paths
- [Species reference](docs/species-reference.md) — the species profile data model and the setpoints of the species whose automation is special
- [Feature status](docs/feature-status.md) — what the original design spec asked for that is not built yet, or only in part

```
ESP32 nodes ──MQTT──> Pi server <──────────REST──────────> Pi dashboard
  (sensors,            (FastAPI, SQLite,                    (pre-built in ui/dist,
   relays,              20 modules, 150 endpoints,           served by nginx)
   lighting,            33 tables, automation engine,
   camera)              weather failover,
                        ntfy notifications)
```

**Hardware layer**: ESP32 sensor/actuator nodes (climate, relay (MOSFET), lighting, camera) plus Shelly/Tasmota smart plugs, all communicating via MQTT. A 3-tier hardware builder provides shopping lists and wiring diagrams.

**Backend**: FastAPI on Raspberry Pi 5. SQLite with tiered retention. Mosquitto MQTT broker. Declarative automation rules engine with weather-aware virtual sensors. Claude camera analysis with your own Anthropic API key (the local CNN layer is a stub). Predictive model learns weather-to-closet correlation. ntfy notifications, including predictive alerts.

**Frontend**: React 19 + TypeScript + Vite 8 + Tailwind CSS v4, built from source that is not in this repo and shipped here as `ui/dist`. Pages load their data over REST; the Chambers page polls the Pi's system metrics every 15 s. The bundled dashboard does not use the Socket.IO server (other clients can), and it is not a PWA. Dark theme with species category accent colors. The weather forecast, grow-impact and planner-recommendation endpoints have no page yet.

### Project Structure

```
SporePrint/
├── firmware/                  # ESP32 PlatformIO monorepo (v2; Arduino-ESP32 core 3.3.12 via pioarduino)
│   ├── lib/sp_core/           # Native-safe core: HMAC canonicalizer + replay guard, channel state machine, buffers, boot/TLS policy, espota handshake, OTA manifest + gate, coredump drain
│   ├── lib/sp_drivers/        # Native-safe sensor drivers over injected HAL (SHT3x/4x, AHT20, BME280/BMP280, SCD4x/30, BH1750, MH-Z19, HX711, reed; inventory: firmware/docs/drivers.md)
│   ├── lib/sp_device/         # Arduino layer: provisioning portal, MQTT link, OTA service + rollback, TLS, bounded DNS, NVS
│   ├── boards/                # Pin profiles: esp32dev, esp32-s3-devkitc-1 (also N32R16V), esp32cam, ESP32-S3 camera boards
│   ├── scripts/               # Version define + image guard (partition layout, slot headroom), run by every build
│   ├── docs/drivers.md        # Driver inventory: every sensor, actuator and board the BOM ever listed
│   └── src/
│       ├── node/              # Unified node image (personality: climate / relay / lighting)
│       └── cam/               # ESP32-CAM image (OV2640 / OV3660 / OV5640 captures → frame POST)
├── server/                    # Python FastAPI backend (20 modules)
│   ├── tests/                 # pytest + pytest-asyncio
│   └── app/
│       ├── main.py            # App entrypoint + Socket.IO + background tasks
│       ├── config.py          # Pydantic settings (env vars)
│       ├── db.py              # SQLite schema (33 tables) + connection manager
│       ├── mqtt.py            # MQTT subscriber, command signing, weather enrichment
│       ├── auth.py            # Optional API-key gate + public paths
│       ├── provision.py       # Broker CA download for Secure-MQTT nodes
│       ├── telemetry/         # Sensor data ingest + rollup-aware history
│       ├── sessions/          # Grow session lifecycle, yield stats, drying tracker, reports, iCal feed
│       ├── automation/        # Rules engine, smart plugs, overrides, per-chamber scoping, coverage
│       ├── species/           # 74 species profiles, wizard, substrate calc, shopping list
│       ├── vision/            # Frame ingest + retention, Claude camera analysis (local CNN stub)
│       ├── weather/           # Multi-provider weather, prediction, forecasts, history aggregation
│       ├── retention/         # Tiered data compression (raw > 5min > hourly > daily)
│       ├── notifications/     # ntfy push notifications (3-tier + predictive)
│       ├── transcript/        # JSON/markdown export, Claude analysis
│       ├── builder/           # 3-tier hardware guide, firmware + model downloads, Claude guide generator
│       ├── cloud/             # Cloud connector (opt-in link to the sporeprint.ai relay), Pi OTA + signed release manifest
│       ├── health/            # System metrics (CPU, memory, disk, MQTT, clients)
│       ├── hardware/          # Node registry, commands, peripherals, OTA push (+ signed manifest), logs, coredumps (store-then-ack)
│       ├── integrations/      # Third-party drivers (Aranet, Pulse, Kasa, Tapo, Wemo, Grafana, …)
│       ├── planner/           # Seasonal grow planner (recommend, calendar, warnings)
│       ├── contamination/     # Contaminant library + Claude photo ID
│       ├── cultures/          # Genetics pipeline with lineage trees
│       ├── chambers/          # Multi-chamber management + comparison
│       ├── experiments/       # A/B experiment mode
│       ├── labels/            # QR code PNGs for sessions and cultures
│       ├── settings_router.py # User settings API (weather, Claude key, ntfy topic, OTA verify key, setup status)
│       └── settings_service.py # Settings persistence service
├── models/                    # OpenSCAD 3D-printable enclosure models (10 files + lib/, see models/README.md)
├── ui/                        # Pre-built Pi dashboard (dist/; source not in this repo) + nginx config + Dockerfile
├── config/                    # Mosquitto config (ACL, passwd, certs)
├── scripts/                   # Broker users, command-signing key, credential rotation, OTA signing
├── docs/                      # Build guide, wiring + architecture diagrams, security, species reference, feature status, integrations
├── install.sh                 # One-command Pi installer
├── setup.sh                   # Developer workstation setup
├── docker-compose.yml
└── AGENTS.md                  # Agent / contributor context
```

### UI Pages

| Page | Description |
|------|-------------|
| Chambers (dashboard, `/`) | Per-chamber readings against the grow's targets and the recent event feed (loaded when the page opens; reload to refresh), Pi system + broker health (polled every 15 s), cloud status, quick overrides |
| Chamber detail + history | One chamber's conditions, nodes, overrides and long-range charts |
| Chamber inventory (`/inventory`) | Chamber list with maintenance log, lifetime stats and photos (creating chambers and assigning nodes are API-only: `POST`/`PATCH /api/chambers`) |
| Sessions | Grow session list with detail view, phase timeline, next-phase action (with the exit reminder), yield stats, a finished session's report.md (the drying log and report.csv are API-only) |
| Species | Species library with TEK guides, substrate recipes, photo references |
| Species Wizard | Guided species selector questionnaire with compatibility scoring |
| Shopping List | Supply list generator with quantities and supplier links, and the Builder BOM hand-off |
| Automation | Rule list with enable toggles, manual overrides, firing log (rules are created and edited through the API) |
| Vision | Camera frames per node, on-demand Claude analysis |
| Planner | Grow calendar (planned events) and dated cycle proposals |
| Contamination | Contaminant library with symptoms and treatments, contamination events and root cause, Claude photo identification |
| Cultures | Genetics lineage tree, spore print/clone tracking, generation counts |
| Experiments | A/B experiments, side-by-side comparison, on-demand Claude analysis |
| Transcripts | Session transcripts (JSON / markdown) and Claude analysis |
| Builder | Hardware tiers with a chamber count, BOM, wiring diagrams, 3D models, firmware flash commands, setup progress |
| Firmware | Node firmware status and OTA push |
| Hardware | Node registry and health |
| Integrations | Third-party integration settings (Grafana, Aranet, Pulse, plugs, lighting, HVAC) |
| Settings | Claude key, OTA verify key, ntfy topic, system info, cloud link (weather settings are API-only: `PUT /api/settings/{key}`) |
| Setup | First-run wizard: node discovery and claim, cloud pairing code |

### Server Modules

The 20 packages under `server/app/`. Endpoints counts the API operations under
each module's `/api/<module>` prefix.

| Module | Endpoints | Description |
|--------|-----------|-------------|
| `telemetry` | 3 | Sensor data ingest and rollup-aware history queries |
| `sessions` | 19 | Grow session CRUD, validated phase management, yield stats, drying tracker, reports, iCal feed |
| `species` | 8 | Species profiles, wizard scoring, substrate calculator, shopping list generator |
| `automation` | 13 | Declarative rules engine, smart plug control, overrides (24h TTL, auto-resume), firing history |
| `weather` | 5 | Multi-provider weather API with failover (Open-Meteo, then NWS, then OpenWeatherMap with a key), 7-day forecast, prediction model, history aggregation |
| `vision` | 5 | Camera frame ingest, Claude camera analysis, active-learning labels |
| `builder` | 13 | 3-tier hardware guide, wiring diagrams, firmware bundles, 3D models, Claude guide generator |
| `hardware` | 11 | Node registry, command dispatch, peripherals, OTA push, logs, coredumps, LAN discovery + claim |
| `cloud` | 7 | Opt-in WebSocket link to the sporeprint.ai relay for Premium remote control, pairing |
| `health` | 6 | System metrics (CPU, memory, disk, MQTT, clients, tasks, clock) |
| `integrations` | 10 + `/metrics` | Third-party drivers, vendor actions, Prometheus `/metrics` |
| `planner` | 9 | Seasonal species recommendations, grow calendar, session weather warnings, dated cycle proposal (`.ics`) |
| `contamination` | 6 | Contaminant library (7 profiles), contamination events, Claude photo identification |
| `cultures` | 6 | Genetics pipeline, lineage trees, transfer logs, generation tracking |
| `chambers` | 12 | Multi-chamber CRUD, node assignment, maintenance, comparison, automation-coverage verdict |
| `experiments` | 7 | A/B experiments, session pairing, comparison reports |
| `labels` | 1 | QR code generation (PNG) for sessions and cultures |
| `transcript` | 2 | Session transcript export and Claude analysis |
| `notifications` | 0 | ntfy push in three tiers (critical / warning / info) with dedup, called by the other modules |
| `retention` | 0 | Nightly tiered telemetry compression, old firing cleanup and vision-frame thinning (a background task) |

Two more routers are single files, not packages:

| Router | Endpoints | Description |
|--------|-----------|-------------|
| `settings_router.py` (`/api/settings`) | 5 | User settings persistence (weather location and key, Claude key, ntfy topic, OTA verify key, setup status) |
| `provision.py` (`/api/provision`) | 1 | Broker CA for Secure-MQTT nodes |

### Database Schema (33 SQLite tables)

Telemetry (`telemetry_readings`, `telemetry_rollups`, `actuator_events`),
sessions (`sessions`, `phase_history`, `session_notes`, `session_events`,
`harvests`, `drying_log`), species (`species_profiles`), automation
(`automation_rules`, `automation_firings`, `safety_watchdogs`,
`manual_overrides`, `smart_plugs`), vision (`vision_frames`,
`contamination_events`), hardware (`hardware_nodes`, `node_logs`), weather
(`weather_readings`, `weather_forecasts`, `weather_rollups`, `weather_history`,
`prediction_models`), cloud (`cloud_command_replay`), builder
(`builder_guides`), and the v3+ modules (`cultures`, `chambers`,
`chamber_maintenance`, `experiments`, `planned_events`, `user_settings`,
`integration_settings`). New databases use incremental auto-vacuum.

---

## Species Library

SporePrint ships with **74 built-in species profiles** across four categories:

- **Gourmet** (30) -- oyster varieties, shiitake, lion's mane, king trumpet, maitake, nameko, pioppino, enoki, and more
- **Medicinal** (11) -- reishi, turkey tail, chaga, cordyceps, and more
- **Novelty** (8) -- bioluminescent and ornamental species
- **Active** (25) -- species that are controlled or restricted in many jurisdictions. This category is for education and research purposes only (notice below)

> **Educational and research use** ([Terms of Service §7](https://sporeprint.ai/legal/terms#educational-use)): Some cultivation profiles in SporePrint cover species that are controlled or restricted in many jurisdictions. That information is provided for education and research purposes only. Any use of SporePrint with those species is for education and research purposes only, and only where it is lawful. It is not encouragement to cultivate, possess, or use any controlled organism. You are solely responsible for knowing and complying with the laws where you live.

The Pi dashboard shows a short form of this notice ("For education and research purposes only. Some species may be controlled where you live; you are responsible for following local law.") in its species library, which lists the other categories first; in the species wizard, which leaves the active category out unless you opt in; and in the new-session, new-culture and plan-a-grow species pickers while one of those species is chosen.

Each profile includes:

- Per-phase environmental targets (temperature, humidity, CO2, light, FAE) for the grow phases the species uses
- TEK guide with step-by-step cultivation instructions
- Substrate recipes with ingredient ratios
- Photo references for identifying healthy growth
- Contamination risk assessment and prevention strategies
- Regional growing notes for climate-specific tips

Species can also be imported as custom JSON profiles for varieties not in the built-in library. Built-ins are read-only: clone one (`POST /api/species` with a new id) to customize it.

> **Note for public materials:** screenshots, docs and examples use gourmet species only (Blue Oyster, Lion's Mane, Shiitake and the like), never an active one.

---

## Hardware

### Supported Hardware

| Component | Description |
|-----------|-------------|
| **Raspberry Pi 5 (4GB)** | Runs the server, MQTT broker and Pi dashboard (official 27W PSU + Active Cooler). A Pi 4 isn't recommended: its ports differ and it doesn't fit `pi_case.scad` |
| **ESP32-WROOM-32 DevKit (38-pin, USB-C)** | Sensor/actuator nodes (climate, relay, lighting) — the pin map in every wiring diagram |
| **ESP32-S3-DevKitC-1** | Alternative node board (`node_esp32s3`, or `node_esp32s3_n32r16v` for the N32R16V) with its own pin map; bench verification pending |
| **ESP32-CAM (AI-Thinker)** | Camera node, OV2640 or OV3660 (OV5640 also supported), flashed and powered through an ESP32-CAM-MB |
| **ESP32-S3 camera boards** | Freenove ESP32-S3-WROOM CAM, Seeed XIAO ESP32S3 Sense, Waveshare ESP32-S3-CAM (earlier BOMs' cameras; still supported, not recommended for new builds; no flash LED; bench verification pending) |
| **SHT31-D / SHT4x** | Temperature + humidity sensor (STEMMA QT) |
| **SCD41 / SCD40 / SCD30 / MH-Z19C** | CO2 sensor (the SCD4x also reports temp/humidity; the SCD30 on a WROOM-32 is partial, bench-pending) |
| **AHT20 / BME280 / BMP280 / MH-Z19B** | Also driven, for parts earlier BOMs and combo boards listed: AHT20 temp/RH (used when no SHT is fitted), BME280/BMP280 barometric pressure (`pressure_hpa`), MH-Z19B CO2. See [firmware/docs/drivers.md](firmware/docs/drivers.md) |
| **BH1750** | Light level sensor (lux) |
| **HX711 + 5 kg load cell** | Harvest scale (All the Things) |
| **Wired door contact (reed)** | Door-open telemetry (All the Things) |
| **IRLZ44N MOSFET** | Low-side switch for 12 V fans, pump and LED strips (4 channels per node, 25 kHz 10-bit PWM; no SSRs) |
| **Tasmota / Shelly plugs** | WiFi smart plugs for humidifier, dehumidifier, heater and cooler: Tasmota (the BOM's Athom plugs), Shelly Gen1, Shelly Gen2+ (Plus, Pro, Mini, Gen3, Gen4) |
| **Power + cabling** | UL-listed surge strip outside the chamber; 12 V PSU → 14 AWG pigtail → WAGO 221 → inline fuse per branch (relay 3 A, lighting 5 A / 7.5 A) → switch boards on 18 AWG; each ESP32's GND tied to its board's GND bus; USB 5 V per board (6 ft cables into the chamber) |

No driver exists for the DHT22, DS18B20, AHT10, BME680, BMP180, capacitive soil-moisture probes, or VOC and particulate sensors ([firmware/docs/drivers.md](firmware/docs/drivers.md#checked-and-never-recommended)). Cameras take still photos only; there is no live stream.

### Hardware Tiers

| Tier | Cost | What You Get |
|------|------|--------------|
| **Bare Bones** | ~$290 | Pi 5 + 1 climate node (SHT31-D + BH1750 on a STEMMA QT chain) + 1 Tasmota plug (humidifier), 6-outlet surge strip, 6 ft USB run through a grommet |
| **Recommended** | ~$745 | + SCD41 CO₂, relay node (3 fans + aux), lighting node (white + 450 nm blue), 1 camera, 2 plugs, 12 V 5 A PSU with fused WAGO distribution (3 A relay / 5 A lighting), 12-outlet strip |
| **All the Things** | ~$960 | + 2nd climate node, all 4 light channels (660 nm red, 730 nm far-red), HX711 scale, door contact, peristaltic pump, 4 plugs, 2nd camera, 12 V 10 A PSU (3 A / 7.5 A fuses), 12-outlet + 2 USB-A strip |

Costs are the sum of the Builder's parts list (`server/app/builder/hardware_guides.py`), re-checked 2026-09-27, and include the cabling, consumables, heat-set inserts and screws. A second chamber adds ~$62 / ~$316 / ~$527: the Pi side is bought once, and the kits and spools (wire, WAGO connectors, fuses, inserts, screws, solder, jumpers, VELCRO, zip ties, heat-shrink, grommets) count what one chamber uses in whole packs that cover more than one chamber — the Builder page's chamber count buys another pack only when the chambers use one up, and leaves only the bench breadboard at one. They leave out the tri-spectrum strip's shipping from China and import duty (~$10+) and your tools (listed in the build guide).

The built-in Hardware Builder provides complete shopping lists with purchase links, color-coded SVG wiring diagrams (one per tier + a system overview), step-by-step assembly instructions for each tier, and 10 parametric OpenSCAD 3D-printable enclosure models (Pi case, ESP32 case, sensor mount + bracket, camera mount, HX711 load-cell scale, peristaltic pump bracket, relay/lighting switch board, power supply mount, fan duct).

### Firmware

ESP32 firmware is a PlatformIO monorepo under `firmware/` (v2) on **Arduino-ESP32 core 3.3.12 / ESP-IDF 5.5.5**, pinned as the pioarduino release `55.03.312-1` (PlatformIO Core 6.2.0+ and git required). The host-testable libraries `lib/sp_core` (HMAC command verification with topic binding and a replay guard, channel safety state machine, byte-capped offline buffer, boot and TLS policy, the espota OTA handshake, signed OTA manifests, the coredump drain) and `lib/sp_drivers` (autodetecting sensor drivers) sit under the Arduino layer `lib/sp_device` (provisioning portal, MQTT link, OTA with rollback, opt-in TLS). One unified node image covers climate/relay/lighting via a provisioning-time personality; the camera is its own image. Every relay and lighting channel is 25 kHz, 10-bit LEDC PWM. Panic coredumps stay in flash until the Pi acknowledges it has stored them. `pio test -e native` runs the full host suite, including byte-for-byte signing parity with the server. See [firmware/README.md](firmware/README.md) (builds, OTA from core 2.x images), [firmware/docs/drivers.md](firmware/docs/drivers.md) (driver inventory) and [firmware/test/README.md](firmware/test/README.md).

---

## API Reference

The server exposes a REST API, plus a Socket.IO endpoint that pushes live events to other local clients (the bundled dashboard uses REST only).

**REST API base**: `http://<pi-address>:8000/api` (or through the dashboard's nginx at `http://<pi-address>:3001/api`)

### Key Endpoint Groups

| Group | Base Path | Description |
|-------|-----------|-------------|
| Telemetry | `/api/telemetry` | Sensor data ingest and history queries |
| Sessions | `/api/sessions` | Grow session CRUD, phase management (422 on an unknown or undefined phase), yield stats, calendar feed |
| Species | `/api/species` | Species profiles, wizard, substrate calculator, shopping list |
| Automation | `/api/automation` | Rules CRUD, smart plug control, overrides (24h TTL, auto-resume) |
| Weather | `/api/weather` | Forecast, prediction, provider status |
| Vision | `/api/vision` | Frame upload, Claude analysis, labels |
| Transcript | `/api/transcript` | Session transcript export + Claude analysis |
| Builder | `/api/builder` | Hardware tiers, BOM, wiring diagrams, firmware bundles, 3D models, guide assistant |
| Hardware | `/api/hardware` | Node registry, commands, peripherals, OTA push, logs, coredumps, LAN discovery + claim |
| Cloud | `/api/cloud` | Cloud connector status, pairing |
| Health | `/api/health` | Liveness; `/api/health/detail/*` for system metrics, task status, clients, MQTT, clock |
| Planner | `/api/planner` | Species recommendations, grow calendar, session warnings, dated cycle proposal (`/propose`, `.ics`) |
| Contamination | `/api/contamination` | Contaminant library, contamination events, Claude photo identification |
| Cultures | `/api/cultures` | Lineage CRUD, transfer logs, generation tree |
| Chambers | `/api/chambers` | Chamber CRUD, node assignment, comparison, automation-coverage verdict |
| Experiments | `/api/experiments` | Experiment CRUD, comparison reports, analysis |
| Labels | `/api/labels` | QR code generation (PNG) |
| Settings | `/api/settings` | User settings (weather, Claude key, ntfy topic, OTA verify key, setup status) |
| Integrations | `/api/integrations` | Third-party driver config, vendor actions |
| Provision | `/api/provision` | Broker CA download (`GET /api/provision/ca`) |

### WebSocket Events (Socket.IO)

The server runs a Socket.IO endpoint (`/socket.io`, behind the same bearer gate
as `/api` when `SPOREPRINT_API_KEY` is set). The bundled dashboard does not
connect to it; it is there for other local clients.

| Event | Direction | Description |
|-------|-----------|-------------|
| `telemetry` | Server -> Client | Live sensor readings (replayed and out-of-order frames are not pushed) |
| `actuator_state` | Server -> Client | A node channel's switch / level report |
| `node_status` | Server -> Client | Node online / offline |
| `component_health` | Server -> Client | ESP32 node health updates |
| `alert` | Server -> Client | Node-side alerts and "coredump saved" |
| `node_log` | Server -> Client | Forwarded firmware log batches |
| `node_ota` | Server -> Client | Node OTA lifecycle (start, success, error, manifest armed / rejected) |
| `rule_fired` | Server -> Client | Automation rule execution (rule, target, channel, action, publish status) |
| `plug_state` | Server -> Client | Smart plug state changes |
| `plug_online` | Server -> Client | Smart plug online / offline (Shelly `online`, Tasmota `LWT`) |
| `weather` | Server -> Client | Current weather after each poll |

### MQTT Topics

```
sporeprint/{node_id}/telemetry           # Sensor readings (JSON, ts = epoch once NTP-synced)
sporeprint/{node_id}/telemetry/{channel} # Actuator switch/level reports
sporeprint/{node_id}/status              # online/offline (retained, LWT)
sporeprint/{node_id}/status/heartbeat    # Heartbeat every min(publish interval, 5 min)
sporeprint/{node_id}/health              # Per-sensor driver health
sporeprint/{node_id}/alert               # Node-side alerts (sensor_failure, tls_downgrade, …)
sporeprint/{node_id}/logs                # Forwarded firmware log batches
sporeprint/{node_id}/ota                 # Node OTA lifecycle events
sporeprint/{node_id}/coredump/chunk      # Panic-dump upload; each chunk carries coredump_id (SHA-256 of the dump)
sporeprint/{node_id}/cmd/{channel}       # Actuator commands (HMAC-signed; channel | scene | config)
sporeprint/{node_id}/cmd/coredump_ack    # {coredump_id} once the Pi has stored the dump — only then does the node erase it
sporeprint/{node_id}/cmd/ota_manifest    # Signed release manifest sent before an OTA push (nodes built with the key)
shellies/{device_id}/relay/0             # Shelly Gen1 plug state (…/relay/0/command to switch)
shellies/{role}/rpc                      # Shelly Gen2+ JSON-RPC command (Switch.Set); replies on shellies/{role}/sporeprint/rpc
shellies/{role}/events/rpc               # Shelly Gen2+ NotifyStatus (switch output, power)
shellies/{role}/status/switch:{n}        # Shelly Gen2+ full switch status ("Generic status update")
shellies/{role}/online                   # Shelly online flag (retained; Gen1 and Gen2+)
tasmota/{topic}/stat/POWER               # Tasmota plug state (requires FullTopic tasmota/%topic%/%prefix%/)
tasmota/{topic}/cmnd/POWER               # Tasmota plug command
```

Tasmota's default Full Topic `%prefix%/%topic%/` publishes `stat/<topic>/POWER`,
which the broker ACL silently drops: set **Full Topic**
`tasmota/%topic%/%prefix%/`, a unique **Topic** (the plug's role, e.g.
`humidifier`), and the broker login **User** `sp-3p` / **Password**
`SPOREPRINT_MQTT_3P_PASSWORD` from `.env`.

A Shelly Gen2+ plug (Plus, Pro, Mini, Gen3, Gen4) speaks JSON-RPC under a
configurable MQTT prefix whose factory value is its device id, a topic tree
the broker drops. In its web UI, **Settings → Connectivity → MQTT**: enable
MQTT, server `<pi-ip>:1883`, user `sp-3p` with the same password, **MQTT
prefix** `shellies/<role>` (e.g. `shellies/humidifier` → plug id
`plug-humidifier`), and turn on "RPC status notifications over MQTT" and
"Generic status update over MQTT". Saving reboots the plug. Details:
[docs/integrations/smart-plugs.md](docs/integrations/smart-plugs.md).

---

## Configuration

All settings via environment variables (prefix `SPOREPRINT_`). Under Docker, put
them in the repo-root `.env` (`install.sh` writes it) — a setting reaches the
server only if `docker-compose.yml` forwards it, and changes apply with
`docker compose up -d server`. See [.env.example](.env.example) for every key.

| Variable | Default | Description |
|---|---|---|
| `TZ` | `UTC` (install.sh writes the host zone) | Time zone for schedules, reminders and transcripts. Canonical Region/City names only. Docker only; bare metal sets it in the service environment |
| `SPOREPRINT_DATABASE_PATH` | `data/db/sporeprint.db` | SQLite database path (Docker: `/data/db/sporeprint.db`) |
| `SPOREPRINT_MQTT_HOST` | `localhost` | MQTT broker host (Docker: `mqtt`) |
| `SPOREPRINT_MQTT_PORT` | `1883` | MQTT broker port |
| `SPOREPRINT_MQTT_USERNAME` | *(empty)* | MQTT broker username (`server`, generated by `install.sh`; the broker refuses anonymous clients) |
| `SPOREPRINT_MQTT_PASSWORD` | *(empty)* | MQTT broker password (generated by `install.sh`; rotate with `scripts/rotate-mqtt-creds.sh`) |
| `SPOREPRINT_MQTT_3P_PASSWORD` | *(generated)* | The `sp-3p` smart-plug broker password. Documentation only — enter it in each plug; the server doesn't read it |
| `SPOREPRINT_MQTT_HMAC_KEY` | *(generated)* | Signs every `cmd/*` frame. `install.sh` creates it; `./scripts/provision-node.sh` prints it, `--rotate` replaces it |
| `SPOREPRINT_MQTT_REQUIRE_SIGNING` | `auto` | `auto` (refuse unsigned commands once cloud-paired) / `always` / `never`. Must not be empty |
| `SPOREPRINT_API_KEY` | *(empty)* | Bearer-token gate for `/api/*` and Socket.IO. Empty = LAN-trust (needs `SPOREPRINT_ALLOW_UNAUTHENTICATED=true`). See [docs/auth.md](docs/auth.md) |
| `SPOREPRINT_ALLOW_UNAUTHENTICATED` | `false` | Explicit opt-in to run with no API key (`install.sh` sets `true`) |
| `SPOREPRINT_NTFY_URL` | `http://localhost:8080` | ntfy base URL (Docker: `http://ntfy:80`) |
| `SPOREPRINT_NTFY_TOPIC` | `sporeprint` | ntfy notification topic |
| `SPOREPRINT_VISION_STORAGE` | `data/vision` | Vision frame storage path |
| `SPOREPRINT_INTEGRATION_KEY_PATH` | `data/db/.integration-key` | Key that encrypts stored vendor credentials (Docker: `/data/db/.integration-key`). Losing it means re-entering every vendor credential |
| `SPOREPRINT_VISION_AUTO_INTERVAL_MIN` | `360` | Minutes between automatic Claude analyses per session (≤ 0 falls back to 6 h) |
| `SPOREPRINT_CLAUDE_API_KEY` | *(empty)* | Anthropic API key (vision, contamination ID, transcripts, experiments, builder assistant) |
| `SPOREPRINT_CLAUDE_MODEL` | `claude-sonnet-5` | Model for every Claude feature; blank = default |
| `SPOREPRINT_WEATHER_PROVIDER` | `openmeteo` | Stored, but nothing reads it yet: the Pi always tries Open-Meteo, then NWS (US only), then OpenWeatherMap when `SPOREPRINT_WEATHER_API_KEY` is set |
| `SPOREPRINT_WEATHER_API_KEY` | *(empty)* | OpenWeatherMap API key; setting it adds OpenWeatherMap as the last fallback |
| `SPOREPRINT_WEATHER_LAT` | *(empty)* | Latitude for weather data |
| `SPOREPRINT_WEATHER_LON` | *(empty)* | Longitude for weather data |
| `SPOREPRINT_WEATHER_POLL_MINUTES` | `10` | Weather polling interval |
| `SPOREPRINT_CLOUD_URL` | *(empty)* | Cloud relay URL (opt-in; `https://`, plain `http://` only to a LAN/loopback dev relay). Pairing writes `cloud.env` beside the DB, which overrides these |
| `SPOREPRINT_CLOUD_TOKEN` | *(empty)* | Device auth token for cloud pairing |
| `SPOREPRINT_CLOUD_DEVICE_ID` | *(empty)* | Unique device identifier |
| `SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS` | `false` | Reject every unsigned cloud `integrations_request` from the start |
| `SPOREPRINT_PUBLIC_UI_URL` | `http://sporeprint.local:3001` | Where browsers reach the dashboard (set `http://<pi-ip>:3001` without mDNS). Its host is also an allowed Host name |
| `SPOREPRINT_ALLOWED_HOSTS` | *(empty)* | DNS-rebinding guard: extra Host names the API answers to (comma list of names, `*.suffix`, IPs or CIDRs; `*` = off). Private IPs, `localhost`, `*.local` / `*.lan` / `*.home.arpa` / `*.internal` and dotless names are always allowed; any other Host gets 421 |
| `SPOREPRINT_OTA_PUBKEY_B64` | *(empty)* | Pinned Ed25519 release key: verifies signed node-firmware manifests (any install) and Pi self-update (bare-metal only). Also Settings → OTA verify key |
| `SPOREPRINT_OTA_CHANNEL` | `stable` | Pi self-update (bare-metal only): the release channel this Pi follows (`stable` / `beta` / `dev`). The signed release manifest must name it; an OTA for another channel is refused |
| `SPOREPRINT_OTA_ALLOW_DOWNGRADE` | `false` | Pi self-update (bare-metal only): accept a signed release older than the installed one (anti-rollback off). Set only on the Pi; the OTA command cannot |
| `SPOREPRINT_OTA_ALLOW_LEGACY_SIGNATURE` | `false` | Pi self-update (bare-metal only), transitional: accept a release that has only the bundle `.sig` and no signed manifest (version and channel unsigned) |
| `FORWARDED_ALLOW_IPS` | `172.31.253.2` | Docker: the one address uvicorn trusts `X-Forwarded-For` from — the ui container's fixed address on the `edge` network. Keep it equal to `SPOREPRINT_EDGE_UI_IP` |
| `SPOREPRINT_EDGE_SUBNET` / `_EDGE_UI_IP` / `_EDGE_SERVER_IP` | `172.31.253.0/28` / `.2` / `.3` | Docker: the ui → server `edge` network. Compose reads them, not the server. Move all three (and `FORWARDED_ALLOW_IPS`) together if `docker compose up` reports "Pool overlaps" |

Pi self-update applies only to a bare-metal install, which this repo doesn't
support. The Docker install refuses update commands sent from the cloud, and
no Pi update bundle is published: update with `git pull && ./install.sh`
([Update](#update)).

---

## Development

```bash
# Backend environment (3.12 = the Docker image; never a bare `uv sync`: it drops the dev extra and may pick a newer Python)
cd server && uv sync --python 3.12 --extra dev

# Backend checks + tests
cd server && uv run ruff check app/ && uv run pytest

# Firmware host tests + builds
cd firmware && pio test -e native
cd firmware && pio run -e node_esp32 -e node_esp32s3 -e node_esp32s3_n32r16v -e cam -e cam_esp32s3 -e cam_xiao_esp32s3 -e cam_waveshare_s3

# Validate Docker Compose
docker compose config --quiet
```

**The Pi dashboard bundle.** The dashboard is built from source that is not
in this repo and committed here as `ui/dist`, which nginx serves as is
(`index.html` plus the hashed files in `assets/`). Its Builder page's
built-in fallback is generated from this repo's BOM, model headers and wiring
SVGs by `scripts/port_builder.py` in the dashboard's source repo. That
generator imports this repo's server code, so it runs in the server's
environment. Maintainers rebuild the bundle with:

```bash
cd <SporePrint checkout>/server && uv run --no-sync python <monorepo>/scripts/port_builder.py --public-repo <SporePrint checkout>
cd <monorepo> && pnpm -C frontend --filter @sporeprint/pi-ui build
rsync -a --delete --checksum frontend/packages/pi-ui/dist/ <SporePrint checkout>/ui/dist/
```

A change here to the BOM, a model header, a wiring SVG or a PlatformIO env
makes the built-in copy stale, and anyone can refresh it inside the bundle:
`cd server && uv run python ../scripts/sync_ui_builder_data.py`. Add
`--check` to verify without writing. The script only rewrites that data. If
the bundle has stopped reading `/api/builder/*` live, or still has the old
static Builder's dead `hardware/3d` / `hardware/wiring` links, it exits 1 and
asks for a rebuild, which only a maintainer can do.

### Dependencies

**Backend (Python)**:
- FastAPI, uvicorn, aiosqlite (raw SQL, no ORM)
- aiomqtt, python-socketio
- Pydantic v2, pydantic-settings
- anthropic (Claude API), httpx (weather, vendor integrations, OTA downloads)
- cryptography (integration secrets, OTA signatures)
- qrcode + pillow (QR labels)
- icalendar (iCal feeds)
- prometheus-client (`/metrics`)
- psutil (system metrics)

Exact versions are pinned in `server/uv.lock`; the Docker image installs exactly
those (hash-checked). After changing `pyproject.toml`, run `cd server && uv lock`.

**Pi dashboard bundle** (built outside this repo; listed so you know what
`ui/dist` contains):
- React 19, TypeScript, Vite 8
- Tailwind CSS v4
- React Router v7
- Lucide React (icons)
- Radix UI, Recharts, TanStack Table

---

## Cloud Connector

The cloud connector links a Pi to a Premium account on
[sporeprint.ai](https://sporeprint.ai). It is opt-in and stays dormant until
the Pi is paired; the Pi works the same without it, and its dashboard keeps
working when the internet or the cloud is down. Once configured
(`SPOREPRINT_CLOUD_URL` and `SPOREPRINT_CLOUD_TOKEN`), the Pi opens an
outbound Socket.IO connection to the cloud relay, sends telemetry, alerts,
grow sessions, contamination events and Claude's analysis results up, and
receives remote commands. Camera frames and your weather location never
reach sporeprint.ai: frames go from the Pi straight to Anthropic only if you
give the Pi your own key, and the location goes only to the weather
services. Remote control is premium only: the relay refuses free accounts,
and the Pi rejects every command not marked premium.

### Pairing a Pi

1. Give the Pi a public HTTPS address for the next few minutes, for example a
   Tailscale Funnel or a Cloudflare Tunnel to port 3001. The cloud refuses
   private and LAN addresses because it calls the Pi back to finish pairing.
   Add that host name to `SPOREPRINT_ALLOWED_HOSTS` in `~/SporePrint/.env`,
   then run `docker compose up -d server`.
2. On the Pi dashboard, open **Setup → § III Cloud link** and click
   **generate pairing code →**. The 6-digit code is valid for 10 minutes and
   works once; after 8 wrong tries pairing locks for 10 minutes.
3. On your network, trade the code for a configure token:

   ```bash
   curl -s -X POST http://<pi-ip>:3001/api/cloud/pair \
     -H 'Content-Type: application/json' -d '{"code":"123456"}'
   ```

   The reply carries `configure_token` (valid 10 minutes, one use) and the
   Pi's `cloud_device_id`.
4. In the web app, open **Devices → Pair new device** and enter the Pi's
   public address (`https://…`, no path), the configure token, the cloud
   device id and a name.
5. Restart the server so it connects:
   `docker compose up -d --force-recreate server`. The Pi then shows as
   online in the web app, and its connection to
   sporeprint.ai is outbound, so close the public address: stop the tunnel,
   remove the name from `SPOREPRINT_ALLOWED_HOSTS` and run
   `docker compose up -d server`.

Behind step 4, the cloud checks the session with the Pi
(`GET /api/cloud/pair-verify`), mints a device token and calls
`POST /api/cloud/configure` with the `configure_token` and the cloud
credentials. Values containing `\n`, `\r` or `=` are rejected (newline-injection
defense). The credentials are written atomically to `cloud.env` beside the
database (Docker: `/data/db/cloud.env`, mode 0600) and survive container
rebuilds. Delete that file to unpair.

### Commands from the cloud

Inbound commands from the cloud are rejected unless they carry a valid HMAC-SHA256 signature over a `ts` within ±30 s of the Pi's clock, a unique `id` (no replay; accepted ids survive a server restart), `tier == "premium"`, a `target_kind` of `climate`, `relay`, `lighting` or `camera` that resolves to a registered node (or the Pi-internal `system` / `automation` targets), and a channel matching `^[a-zA-Z0-9_-]{1,64}$`. See [docs/cloud-relay-flow.md](docs/cloud-relay-flow.md).

The sporeprint.ai cloud and web app are proprietary and not in this repo.
The cloud can't update the Pi: update it on the Pi ([Update](#update)).

---

## Security

SporePrint is designed for a single operator on a trusted home LAN. Defense-in-depth covers the cross-trust surfaces that break that premise:

- **MQTT broker**: anonymous clients are **refused**. The broker reads a `password_file` and a per-role `acl.conf`; `install.sh` provisions the `server` and `sp-3p` (smart plug) logins, and `scripts/add-node-mqtt-user.sh <node_id>` gives each ESP32 its own login, scoped by the ACL to `sporeprint/<node_id>/…`. Frames under a service account's name (`server`, `sp-3p`, `sp-cmd`, `sp-telemetry`) are dropped, so a leaked smart-plug credential cannot pose as a node. Ports **1883** and **8883 (TLS)** are published on the LAN by `docker-compose.yml` — never port-forward them to the internet.
- **Command signing**: every `sporeprint/<node>/cmd/*` frame the Pi publishes is HMAC-SHA256 signed and carries the topic it was sent on plus a random nonce. Nodes holding the key reject unsigned, forged, replayed or redirected frames. See [docs/firmware-security.md](docs/firmware-security.md).
- **DNS rebinding**: the API and Socket.IO answer only for Host names an outside web page cannot point at the Pi — private and loopback IP literals, `localhost`, `*.local` and other private-use suffixes, dotless names, the host of `SPOREPRINT_PUBLIC_UI_URL` and anything listed in `SPOREPRINT_ALLOWED_HOSTS`. Any other Host gets 421 (`GET /api/health` and `GET /api/provision/ca` excepted), so a rebinding page cannot drive the API in LAN-trust mode.
- **Backend API**: set `SPOREPRINT_API_KEY` to require `Authorization: Bearer <key>` on all `/api/*` routes plus the Socket.IO `connect` handshake. Public in that mode: `/api/health`, `POST /api/cloud/pair` and `GET /api/provision/ca` (the broker's public CA). `POST /api/vision/frame` is accepted without a bearer only from a camera registered in `hardware_nodes`, with a declared Content-Length of at most 20 MB. `/metrics` sits outside `/api` and has its own optional bearer (Grafana integration). See [docs/auth.md](docs/auth.md).
- **OTA**: a node's OTA listener (port 3232, `firmware/lib/sp_device/ota_service.cpp`, the espota handshake the Pi's push speaks) stays disabled until a password of at least 12 characters is set in the node's setup portal. A new image is on probation and rolls back if it never holds an MQTT connection for 60 s. A Pi-pushed image goes only to the node being flashed: the connect-back listener on TCP 3233 serves that node's address and closes any other peer. Optionally, a push can carry a signed release manifest (`POST /api/hardware/nodes/{id}/ota` with `manifest` + `manifest_sig`): the Pi checks it against its pinned key and the uploaded `.bin`, and a node image built with that key flashes only the exact image the manifest names. A push without a manifest still flashes, unless the image was built with `SPOREPRINT_OTA_REQUIRE_MANIFEST=1`. This repo's firmware releases from `firmware-v5.1.0` on are built with the key and ship each image's `<env>.manifest.json` + `.sig`; local builds and Builder ZIPs carry no key, so their images ignore manifests. How the signing key is kept out of the build, and how to verify a download: [docs/firmware-security.md](docs/firmware-security.md#signed-firmware-releases).
- **Secure MQTT**: a node pins the Pi's CA only after a TLS connection with it succeeds, and reports the pinned CA's SHA-256 as `ca_fp` in its heartbeat. See [docs/firmware-security.md](docs/firmware-security.md#secure-mqtt-tls).

CORS on the backend is LAN-scoped via `allow_origin_regex` (localhost, `*.local`, RFC1918 ranges, `capacitor://localhost`). Settings-mutation routes (`PUT /api/settings/*`) sit behind the same bearer-token gate as every other write path. Vision uploads validate `X-Node-Id` against `^[a-zA-Z0-9_-]{1,32}$` and assert the resolved write path stays inside `vision_storage`.

Hardware command routing (`POST /api/hardware/nodes/{id}/command`) strips any caller-supplied `topic` field and reconstructs the topic from the URL path, so nothing on the LAN can address a sibling node through your Pi.

---

## Contributing

Contributions to the Pi server, the ESP32 firmware, the enclosure models and
the docs are welcome:

1. Fork the repository and create a feature branch (`git checkout -b feature/my-feature`).
2. Follow the code conventions below and in `AGENTS.md`.
3. Add tests for new backend behavior, and host tests under `firmware/test/` for firmware.
4. Run the checks in `AGENTS.md` → Commands before you submit:
   `cd server && uv run ruff check app/ && uv run pytest`, plus
   `cd firmware && pio test -e native` for firmware changes.
5. Open a pull request that says what changed and why.

The Pi dashboard's source isn't in this repo, so pull requests can't change
the dashboard (`ui/dist` is a build output). Report dashboard bugs and
requests as [issues](https://github.com/59psi/SporePrint/issues) instead.

### Code Conventions

- **Backend**: FastAPI routers are thin wrappers; business logic lives in service modules. DB access via `async with get_db() as db:` with batch writes and single commit. Pydantic v2 models. Config via `SPOREPRINT_` env prefix; every new setting must also be forwarded in `docker-compose.yml`.
- **MQTT**: Topic convention is `sporeprint/{node_id}/telemetry|status|health|alert|logs|ota|coredump/chunk|cmd/{channel}` (see [MQTT Topics](#mqtt-topics)).
- **Firmware**: Non-blocking (use `yield()` not `delay()`). ArduinoJson v7. 25 kHz, 10-bit LEDC PWM on every channel. New payload keys are optional; the signing vectors never change.
- **Species**: docs, screenshots and examples use gourmet species only (see the note under [Species Library](#species-library)).

---

## Getting Help

- **Bugs and feature requests** for the Pi server, firmware, models or
  dashboard: [GitHub Issues](https://github.com/59psi/SporePrint/issues).
- **Security issues**: don't open a public issue. Email
  support@sporeprint.ai with "Security" in the subject.
- **Premium, billing and your sporeprint.ai account**: email
  support@sporeprint.ai, or read the
  [user guide](https://sporeprint.ai/docs/user-guide.md). Service status is
  at [sporeprint.ai/status](https://sporeprint.ai/status).

---

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
The Pi dashboard's source is not in this repo; it and the sporeprint.ai cloud
and web app are proprietary (see [Open Source](#open-source)).
