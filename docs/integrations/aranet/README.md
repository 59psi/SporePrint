# Aranet PRO integration

The SporePrint Pi can poll an Aranet PRO base station's local API and
store its sensors' readings in the Pi's telemetry history, where the
telemetry API and the Grafana exporter see them. They do **not** drive
automation rules or safety alerts: those run only on MQTT telemetry
from SporePrint nodes, so keep a SporePrint climate node in any chamber
the rules control. Free-tier — traffic stays on the LAN.

## Hardware requirements

- **Aranet PRO base station** (≈$500). The base station bridges
  Aranet4 / Aranet RADIATION / Aranet Soil sensors over 868/915 MHz
  radio to a LAN HTTP server.
- **Firmware ≥ 2.0.** Older firmware is Aranet-Cloud-only with no
  local API; the driver returns a clear "firmware ≥ 2.0" error if it
  hits a 404 on the documented endpoint.

## Quick start

1. In the Aranet PRO web UI: *Admin → API* → mint a new API key. Note
   the value somewhere safe — the driver stores it encrypted at rest.
2. Find the PRO's LAN IP. The web UI shows it under *Settings →
   Network*; or check your router's DHCP table.
3. In the Pi LAN UI at `/integrations`, find the Aranet row and click
   *Configure*:
   - `base_url`: e.g. `http://10.0.0.42` (mDNS hostnames OK).
   - `api_key`: paste the value from step 1. Settings show a saved key as
     `••••` plus a short fingerprint, never any of its characters. A later
     save keeps the stored key when `api_key` is omitted or sent back as
     that preview (`""` clears it) — except when the save changes
     `base_url`: the key is only ever sent to the address it was entered
     for, so a new `base_url` needs the key re-entered (422 otherwise).
   - `poll_seconds`: 60 s is plenty — Aranet sensors only radio every
     ~10 minutes anyway.
   - Save (don't enable yet).
4. Hit *Test connection*. You should see "ok · sensors_seen: N" with N
   matching the number of sensors paired to your PRO. A test only reads
   the PRO; it stores nothing.
5. Call `GET /api/integrations/aranet/discover`. The response lists every
   Aranet sensor with its `id` and current measurement types.
6. *Enable*. Within one poll interval the readings land in telemetry
   history under node IDs like `aranet:abc-123-uuid`, in no chamber.
   `sensor_mappings` (sensor id → chamber id) is accepted in the config
   but not used yet: to show a sensor with a chamber (in Grafana's
   `chamber_id` label and the chamber's readings), add its node id to
   that chamber's `node_ids` (`PATCH /api/chambers/{id}`).

## Sensor type mapping

| Aranet measurement type | SporePrint sensor name |
|---|---|
| `temperature` | `temp_c` (a reading the PRO reports in °F is converted) |
| `humidity` | `humidity` |
| `co2` | `co2_ppm` |

Other types (`atmospheric_pressure`, `radiation_dose_rate`, `soil_*`)
are returned by `/discover` but not yet driven into the telemetry
pipeline. Adding them is a one-line entry in `_TYPE_MAP` once the
chamber UI grows widgets for those names — file an issue if you have a
use case.

## Sensor freshness

Aranet sensors radio about every 10 minutes, so the values you see are
guaranteed to lag by up to that interval. The driver polls the PRO
every 60 s by default — that's fine because the PRO caches the latest
reading per sensor. Lowering `poll_seconds` further does not get you
fresher data; it just hits the PRO's rate limit faster.

Because the PRO keeps serving a sensor's latest reading until the next
one arrives, each reading is stored once, at the time the sensor took it
(when the PRO reports that time), not again on every poll. A sensor whose
reading stops changing for 30 minutes (or three polls, when that is
longer) — a flat battery, out of radio range — is not stored as fresh:
the integration's health turns `degraded` and names it (`error` when
every sensor has gone quiet).

## Troubleshooting

- **Test returns "401 unauthorized — check the X-API-Key value"** —
  the API key in your config doesn't match what the PRO expects. Mint
  a fresh one in *Admin → API* and update the integration settings.
- **Test returns "404 from /api/v1/measurements/last — confirm Aranet
  PRO firmware ≥ 2.0"** — the PRO's local API was added in firmware
  2.0. Older firmware has no local endpoint. Update the PRO firmware
  via Aranet's app, or accept that the integration won't work until
  you do.
- **Sensors discovered but readings empty** — measurement types not in
  the `_TYPE_MAP` are silently skipped. If you have only soil/radiation
  sensors and no temperature/humidity/CO2, the driver succeeds but
  writes zero rows. Check the discover endpoint output.
