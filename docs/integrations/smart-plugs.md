# Smart-plug integrations (v4.1.2)

Two new free-tier drivers control LAN smart plugs and switches without
a vendor-cloud round-trip:

- **Wemo** (Belkin) — UPnP/SOAP on TCP/49153.
- **Kasa** (TP-Link) — encrypted JSON on TCP/9999.

Both ship with full read + write paths. No new pip dependencies — the
SOAP envelopes and the Kasa XOR cipher are inline.

## Wemo

| Field | Notes |
|---|---|
| `devices[].ip` | Per-device LAN address. |
| `devices[].chamber_id` | Optional chamber tagging for telemetry. |
| `devices[].is_insight` | True for the Wemo Insight (enables power-monitoring poll). |

Belkin sunset their cloud in late 2024; the local SOAP endpoint stays
functional on existing hardware. Discovery is not yet automated — list
the device IPs explicitly.

### Wemo write actions

| Action | Body | Effect |
|---|---|---|
| `set_power` | `{"ip": "...", "on": true}` | On/off via `SetBinaryState`. |

## Kasa

| Field | Notes |
|---|---|
| `devices[].ip` | Per-device LAN address. |
| `devices[].is_dimmer` | True for HS220 (enables brightness poll + `set_dim`). |
| `devices[].has_emeter` | True for Insight-style models (enables emeter poll). |

The Kasa XOR cipher is implemented inline (`_encrypt` / `_decrypt` in
`kasa/driver.py`). Round-trip-tested.

### Kasa write actions

| Action | Body | Effect |
|---|---|---|
| `set_power` | `{"ip": "...", "on": true}` | `system.set_relay_state`. |
| `set_dim` | `{"ip": "...", "percent": 75}` | `smartlife.iot.dimmer.set_brightness`. HS220 only. |

## Reaching write actions from cloud-web

The relay's RPC tunnel forwards `vendor_action` requests to the Pi.
Pattern:

```http
POST /api/integrations/{device_id}/{slug}/actions/{action}
Content-Type: application/json
Authorization: Bearer <jwt>

{ "ip": "10.0.0.20", "on": true }
```

Premium-gated + ownership-checked at the cloud edge.

## v4.1.2 write actions across the rest of the grid

The vendor-actions dispatcher in `app/integrations/_actions.py` advertises:

| Vendor | Actions |
|---|---|
| Fluence | `set_dim` |
| Fohse | `set_dim` |
| BIOS | `set_dim` |
| Trane | `set_setpoint` |
| Agrowtek | `set_output` |
| Quest | `set_setpoint` |
| Anden | `set_setpoint` |
| Wemo | `set_power` |
| Kasa | `set_power`, `set_dim` |

`GET /api/integrations/{slug}/actions` lists each driver's writable
actions for the cloud-web UI to render the right control buttons.
