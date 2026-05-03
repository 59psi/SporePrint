# Lighting / HVAC vendor skeletons (v4.1.1)

This release ships seven new vendor drivers as **defensible skeletons**
rather than hardware-verified integrations:

| Vendor | Tier | Transport | Doc reference |
|---|---|---|---|
| Agrowtek GCX | free | LAN HTTP | `app/integrations/agrowtek/` |
| Trane Nexia / BAS | premium | Cloud (mynexia.com) | `app/integrations/trane/` |
| Fluence (FluenceID) | premium | Cloud (fluencebioengineering.com) | `app/integrations/fluence/` |
| Quest dehumidifier | free | LAN HTTP | `app/integrations/quest/` |
| Anden dehumidifier | free | LAN HTTP | `app/integrations/anden/` |
| Fohse (FohseConnect) | premium | Cloud (fohse.com) | `app/integrations/fohse/` |
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
5. **Is NOT verified against real vendor hardware.** The vendor API
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
Existing automation rules that match on `temp_c` / `humidity` continue
to work for the temperature/humidity readings emitted by these drivers
where vendor APIs return those fields.

## Per-vendor notes

### Agrowtek GCX (free)

GCX firmware ≥ 4.0 exposes a documented LAN REST API at
`/api/sensors`. Mints API keys in the GCX admin UI. The driver pulls
sensor readings on the configured interval and merges them into your
chambers via `sensor_mappings`.

### Trane Nexia / BAS (premium)

Trane's residential Nexia API and commercial BAS API differ in path
structure. The driver targets the Nexia shape today; commercial-tier
operators may need to set `house_id` to scope reads. Authentication is
email + password; we hold the session token in process memory and
refresh on 401.

### Fluence (premium)

FluenceID cloud API. Authentication is email + password from your
fluencebioengineering.com account.

### Quest / Anden dehumidifiers (free)

Both vendors ship networked grow-room dehumidifiers with a LAN status
endpoint. Configure the LAN URL; no auth required. Driver normalises
`temp_c`, `humidity`, `setpoint_humidity` (and `power_w` for Anden's
power-monitored models).

### Fohse FohseConnect (premium)

FohseConnect cloud — premium fixture telemetry (intensity %, power
watts, fixture temperature). Same shape as Fluence.

### BIOS Lighting (free)

LAN HTTP REST. Optional bearer token for newer firmware revisions
that ship with API auth. Reports per-fixture dim level, watts, and
fixture temperature.

## What's NOT in v4.1.1

- Verified write paths (set dim level, set HVAC setpoint, etc.).
  v4.1.1 ships **read-only** drivers; control flows happen via the
  existing actuator pipeline once the read path is verified.
- Per-vendor settings UI fields beyond the generic JSON renderer in
  `IntegrationsPanel`. Hand-curated per-vendor schemas land
  vendor-by-vendor in `frontend/packages/design/src/components/IntegrationsPanel.tsx`'s
  `INTEGRATION_SCHEMAS` map.
- Vendor-specific event-driven push (e.g. "lights came on, log it").
  Polling is the single integration paradigm in v4.1.x.
