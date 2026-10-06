# Grafana / Prometheus integration

The SporePrint Pi exposes a `/metrics` endpoint in Prometheus text format
for users who run their own Grafana + Prometheus stack (self-hosted or
Grafana Cloud's hosted Prometheus). Free-tier — data stays on your LAN
unless you yourself point an external scraper at the Pi.

## Quick start

`/metrics` is served by the API on **port 8000** only. The dashboard's
nginx on port 3001 proxies just `/api` and `/socket.io`, so
`http://<pi>:3001/metrics` returns the dashboard's HTML, not metrics.
Use `sporeprint.local` below, or the Pi's IP if mDNS doesn't resolve on
your network.

1. **Enable on the Pi** — open the Pi LAN UI at
   `http://sporeprint.local:3001/integrations`, find the Grafana row, set
   `enabled` to true, and Save. The `/metrics` route appears the moment
   you save (returns 404 while disabled).
2. **Verify locally** — from any LAN host:
   ```sh
   curl http://sporeprint.local:8000/metrics | head
   ```
   You should see lines like `sporeprint_node_temperature_celsius{...} 23.5`.
3. **Add a Prometheus scrape job** — in your `prometheus.yml`:

   ```yaml
   scrape_configs:
     - job_name: sporeprint
       scrape_interval: 30s
       static_configs:
         - targets: ['sporeprint.local:8000']
   ```
4. **Import the dashboard** — in Grafana, go to *Dashboards → New →
   Import* and paste `sporeprint-chamber-dashboard.json` from this
   directory (Grafana 10+ recommended).

## Authentication (optional)

By default `/metrics` is unauthenticated, matching Prometheus
convention — network scoping (your home router) is the gate. It sits
outside `/api`, so `SPOREPRINT_API_KEY` does not cover it. If you want a
soft auth check, set `bearer_token` in the integration settings; scrapes
then need an `Authorization: Bearer <token>` header (a missing, wrong or
non-ASCII token gets 401). Useful for Tailscale → Grafana-Cloud setups.

## Metric reference

All metrics are prefixed with `sporeprint_` for easy filtering.

| Metric | Type | Labels | Notes |
|---|---|---|---|
| `sporeprint_node_temperature_celsius` | gauge | node_id, chamber_id | Last reading per sensor |
| `sporeprint_node_humidity_percent` | gauge | node_id, chamber_id | |
| `sporeprint_node_co2_ppm` | gauge | node_id, chamber_id | |
| `sporeprint_node_lux` | gauge | node_id, chamber_id | |
| `sporeprint_node_dewpoint_celsius` | gauge | node_id, chamber_id | Converted from F at scrape time |
| `sporeprint_node_weight_grams` | gauge | node_id, chamber_id | Calibrated HX711 scale reading |
| `sporeprint_node_door_open` | gauge | node_id, chamber_id | Door reed: 1 = open, 0 = shut |
| `sporeprint_chamber_session_active` | gauge | chamber_id, species_profile_id, phase | 1 if active session |
| `sporeprint_actuator_event_count` | counter | node_id, channel, action | Lifetime events |
| `sporeprint_contamination_events_total` | counter | chamber_id | Lifetime contamination events (vision detections + manual marks), plus older sessions marked contaminated that have no event row |
| `sporeprint_build_info` | info | version | Pi build metadata |

`chamber_id` is `""` when a sensor is not yet mapped to a chamber.

## Cardinality tuning

The default surface is conservative. If you have a large fleet and
Prometheus cardinality is a concern:

- `include_actuator_state=false` — drops the actuator counter.
- `include_contamination_metrics=false` — drops the contamination counter.

Both flags live in the same Pi LAN UI page.

## Troubleshooting

- **`/metrics` returns 404** — driver is disabled. Enable it in the Pi
  LAN UI's Integrations page.
- **`/metrics` returns HTML / Prometheus reports a parse error** — the
  scrape hit the dashboard on port 3001 (or 80, where nothing listens).
  Scrape port 8000.
- **`/metrics` returns 401** — you've set `bearer_token` and the
  scraper is missing the header. Either remove the token or add it to
  Prometheus' `authorization` block.
- **Grafana shows no data but `curl` works** — Prometheus scrape
  interval may be too long. Try 15 s while debugging.
