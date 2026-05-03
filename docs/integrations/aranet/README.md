# Aranet PRO integration

The SporePrint Pi can poll an Aranet PRO base station's local API and
merge its sensors into your chambers as if they were native sensors.
Existing automation rules, alerts, and the Grafana exporter all see
Aranet readings unchanged. Free-tier — traffic stays on the LAN.

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
   - `api_key`: paste the value from step 1.
   - `poll_seconds`: 60 s is plenty — Aranet sensors only radio every
     ~10 minutes anyway.
   - Leave `sensor_mappings` empty for now; we'll fill it in next.
   - Save (don't enable yet).
4. Hit *Test connection*. You should see "ok · sensors_seen: N" with N
   matching the number of sensors paired to your PRO.
5. Click *Discover* (or call `GET /api/integrations/aranet/discover`).
   The response lists every Aranet sensor with its `id` and current
   measurement types. Use the IDs to populate `sensor_mappings`:

   ```json
   {
     "abc-123-uuid": "1",
     "def-456-uuid": "2"
   }
   ```

   The keys are Aranet sensor IDs; the values are SporePrint chamber
   IDs as strings.
6. Save again, then *Enable*. Within one poll interval you should see
   readings flow through to the chamber UI under node IDs like
   `aranet:abc-123-uuid`.

## Sensor type mapping

| Aranet measurement type | SporePrint sensor name |
|---|---|
| `temperature` | `temp_c` |
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
