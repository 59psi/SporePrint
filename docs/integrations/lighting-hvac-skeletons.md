# Lighting / HVAC vendor skeletons

Seven vendor drivers ship as **defensible skeletons** rather than
hardware-verified integrations. They arrived in v4.1.1 as read-only drivers;
v4.1.2 added their write actions. All of them run free on the Pi (it has no
paygate); the cloud ones talk to the vendor's cloud directly with your own
account, whose credentials stay on the Pi:

| Vendor | Tier | Transport | Doc reference |
|---|---|---|---|
| Agrowtek GCX | free | LAN HTTP | `app/integrations/agrowtek/` |
| Trane Nexia / BAS | free | Cloud (mynexia.com) | `app/integrations/trane/` |
| Fluence (FluenceID) | free | Cloud (fluencebioengineering.com) | `app/integrations/fluence/` |
| Quest dehumidifier | free | LAN HTTP | `app/integrations/quest/` |
| Anden dehumidifier | free | LAN HTTP | `app/integrations/anden/` |
| Fohse (FohseConnect) | free | Cloud (fohse.com) | `app/integrations/fohse/` |
| BIOS Lighting | free | LAN HTTP | `app/integrations/bios/` |

## What "skeleton" means here

Each driver:

1. **Auto-registers** with the integrations framework on import — they
   show up in the Pi LAN UI's `/integrations` page and the cloud-web
   mirror immediately.
2. **Has a complete config schema** with the obvious fields (URL or
   credentials, poll interval, mappings) and standard validators.
3. **Implements the full IntegrationDriver lifecycle** —
   `configure / start / stop / test_connection / health` are wired and
   tested at the contract level.
4. **Polls a documented vendor endpoint** with **tolerant pydantic
   models** — unknown payload shapes degrade to empty rather than
   crashing the poll task.
5. **Advertises its write actions** through the vendor-actions
   dispatcher (`app/integrations/_actions.py`): `set_dim` for Fluence,
   Fohse and BIOS, `set_setpoint` for Trane, Quest and Anden, `set_output`
   for Agrowtek (`POST /api/integrations/{slug}/actions/{action}`; see
   [smart-plugs.md](smart-plugs.md#write-actions-across-the-rest-of-the-grid)).
6. **Is NOT verified against real vendor hardware.** The vendor API
   shapes were inferred from documentation; refinements based on
   actual response payloads are expected and will be additive (new
   parser branches, not structural rewrites).

## Operator workflow when you have a vendor device

1. Open the Pi LAN UI at `/integrations`, find the vendor row.
2. Configure the credentials/URL.
3. Hit *Test connection*. If you get a clean `ok`, great.
4. If `test` fails with a parser error, file an issue with the raw
   response payload — that's how we refine the parser without
   shipping speculative code.
5. **Do not enable the driver until `test_connection` returns `ok`.**
   The poll loop logs failures but doesn't block your other drivers.

## Sensor name mapping

The new drivers introduce no new SporePrint sensor names beyond what
v4.1.0 already established (`vpd_kpa`, `dew_point_c`,
`setpoint_humidity`, `power_w`, `dimming_percent`, `light_temp_c`).
Temperature/humidity readings these drivers store (where vendor APIs
return those fields) land in telemetry history and the Grafana
exporter. They do **not** drive automation rules or safety alerts:
those run only on MQTT telemetry from SporePrint nodes.

Each driver stores its readings under node ids `<vendor>:<device id>`
(below), in no chamber. The chamber and mapping fields in their configs
(`chamber_id`, `fixture_mappings`, `device_mappings`, `sensor_mappings`)
are accepted but not used yet. To show a vendor device's readings with a
chamber (in Grafana's `chamber_id` label, for one), add its node id to
that chamber's `node_ids` (`PATCH /api/chambers/{id}`).

## Per-vendor notes

### Agrowtek GCX (free)

GCX firmware ≥ 4.0 exposes a documented LAN REST API at
`/api/sensors`. Mints API keys in the GCX admin UI. The driver pulls
sensor readings on the configured interval and stores them in telemetry
history under node ids `agrowtek:<sensor id>`, not tied to a chamber or a
grow. `sensor_mappings` is accepted in the config but not used yet.

### Trane Nexia / BAS (free, vendor cloud)

Trane's residential Nexia API and commercial BAS API differ in path
structure. The driver targets the Nexia shape today; commercial-tier
operators may need to set `house_id` (one id, no slashes) to scope reads.
Authentication is email + password; we hold the session token in process
memory and, on a 401, log in again and repeat the request once. Readings
are stored under `trane:<thermostat id>`. `device_mappings` is accepted in
the config but not used yet.

### Fluence (free, vendor cloud)

FluenceID cloud API. Authentication is email + password from your
fluencebioengineering.com account. Readings are stored under
`fluence:<fixture id>`. `fixture_mappings` is accepted in the config but
not used yet.

### Quest / Anden dehumidifiers (free)

Both vendors ship networked grow-room dehumidifiers with a LAN status
endpoint. Configure the LAN URL; no auth required. Driver normalises
`temp_c`, `humidity`, `setpoint_humidity` (and `power_w` for Anden's
power-monitored models), stored under `quest:<host>` / `anden:<host>`.
`chamber_id` is accepted in the config but not used yet.

### Fohse FohseConnect (free, vendor cloud)

FohseConnect cloud — fixture telemetry (intensity %, power
watts, fixture temperature). Same shape as Fluence: readings are stored
under `fohse:<fixture id>`, and `fixture_mappings` is accepted in the
config but not used yet.

### BIOS Lighting (free)

LAN HTTP REST. Optional bearer token for newer firmware revisions
that ship with API auth. Reports per-fixture dim level, watts, and
fixture temperature, stored under `bios:<fixture id>`.
`fixture_mappings` is accepted in the config but not used yet.

### Sign-in for the cloud drivers (Trane, Fluence, Fohse)

A login the vendor refuses (wrong password, locked account) is not
resent on every poll, since repeated failures can lock the account:
polls and write actions fail at once with the vendor's answer until you
save the settings again (re-saving the same credentials, after unlocking
the account, counts) or run *Test connection*, which always logs in.

## What these drivers don't do yet

- **Hardware verification.** Both the read paths and the write actions
  are written against vendor documentation, not tested on vendor hardware.
  Test a write action by hand before an automation relies on it.
- **Unattended control you can trust.** An automation rule can call a
  vendor write action (its action sets `vendor_slug`, `vendor_action` and
  `vendor_params`, and its `target` names the override key
  `vendor:{slug}:{ip-or-id}`), but until the write path is verified on
  your hardware, watch the first firings.
- **Event-driven push** (e.g. "lights came on, log it"). Polling is the
  only integration paradigm.

Every vendor here has its own settings form on the Integrations page (the
`INTEGRATION_SCHEMAS` map in the parent monorepo's
`frontend/packages/design/src/components/IntegrationsPanel.tsx`).
