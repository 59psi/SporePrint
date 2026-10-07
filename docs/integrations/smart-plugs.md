# Smart plugs

SporePrint drives two kinds of smart plug:

- **MQTT plugs (Tasmota, Shelly Gen1, Shelly Gen2+)** — the BOM's Athom
  Tasmota plugs, and Shelly plugs of either API generation. They talk to the
  Pi's own broker, need no integration setup, and are what the built-in
  humidifier / dehumidifier / heater / cooler rules switch.
- **LAN vendor drivers (Wemo, Kasa, Tapo)** — configured on the Integrations
  page; they are reached through the vendor-actions dispatcher.

## MQTT plugs: Tasmota and Shelly

Both authenticate to the Pi's broker as the smart-plug user **`sp-3p`**. Its
password is `SPOREPRINT_MQTT_3P_PASSWORD` in the `.env` in the Pi's SporePrint
folder (`install.sh` generates it; `scripts/rotate-mqtt-creds.sh` rotates it).
The broker ACL lets `sp-3p` use `tasmota/#` and `shellies/#` only; the
server may publish only `tasmota/+/cmnd/POWER`, `shellies/+/relay/0/command`
and `shellies/+/rpc` there (`config/mosquitto/acl.conf`).

### Tasmota (Athom plugs)

In the Tasmota web UI, **Configuration → MQTT**:

| Field | Value |
|---|---|
| Host | the Pi's IP |
| Port | 1883 |
| User | `sp-3p` |
| Password | `SPOREPRINT_MQTT_3P_PASSWORD` from `.env` |
| Topic | the plug's role: `humidifier`, `dehumidifier`, `heater` or `cooler` (must be unique) |
| Full Topic | **`tasmota/%topic%/%prefix%/`** |

Or in the Tasmota console:

```
Backlog MqttHost <pi-ip>; MqttPort 1883; MqttUser sp-3p; MqttPassword <password>; Topic humidifier; FullTopic tasmota/%topic%/%prefix%/
```

**The Full Topic is required.** Tasmota's default `%prefix%/%topic%/` publishes
`stat/<topic>/POWER` and listens on `cmnd/<topic>/POWER`. Both are outside the
`sp-3p` ACL and outside the Pi's subscriptions, so the broker silently drops
them: the plug looks connected in Tasmota and never appears in SporePrint.
Without the User/Password the broker refuses the plug outright, just as
silently.

With the Full Topic set, the plug uses:

| Topic | Direction | Payload |
|---|---|---|
| `tasmota/<topic>/stat/POWER` | plug → Pi | `ON` / `OFF` |
| `tasmota/<topic>/stat/RESULT` | plug → Pi | `{"POWER": "ON"}` (command replies; `POWER1` on multi-relay firmware) |
| `tasmota/<topic>/tele/STATE` | plug → Pi | periodic status, including `POWER` |
| `tasmota/<topic>/tele/SENSOR` | plug → Pi | energy readings (`ENERGY.Power` watts) |
| `tasmota/<topic>/cmnd/POWER` | Pi → plug | `ON` / `OFF` |

A plug registers itself the first time it reports its relay state (toggle it
once). Its id is `plug-<topic>`, so a plug with Topic `humidifier` is
`plug-humidifier` — exactly the target the built-in rules drive. A plug with
any other Topic can be given its role (`device_role`) in the app. Empty
payloads, such as a retained message being cleared, are ignored.

### Shelly (Gen1)

Shelly Gen1 plugs work with their default topics: they publish
`shellies/<device_id>/relay/0` (`on` / `off`) and `…/relay/0/power`, and take
`shellies/<device_id>/relay/0/command`. Enter the `sp-3p` login in the Shelly's
MQTT settings. The plug id is `plug-<device_id>`; assign its role in the app.

### Shelly Gen2+ (Plus, Pro, Mini, Gen3, Gen4)

Every Shelly on the JSON-RPC "Gen2 API" (Plus, Pro and Mini devices, the Gen3
and Gen4 lines: plugs, 1 / 1PM, 2PM, 4PM, Power Strip) is plug type
`shelly_gen2`. These devices publish everything under one configurable
**MQTT prefix**. Its factory value is the device id (`shellyplusplugs-<mac>`),
a top-level topic tree the broker drops, so the prefix must be changed. In
the Shelly web UI, **Settings → Connectivity → MQTT**:

| Field | Value |
|---|---|
| Enable | on |
| Server | the Pi's IP and port: `<pi-ip>:1883` |
| Username | `sp-3p` |
| Password | `SPOREPRINT_MQTT_3P_PASSWORD` from `.env` |
| MQTT prefix | **`shellies/<role>`**: `shellies/humidifier`, `shellies/dehumidifier`, `shellies/heater` or `shellies/cooler` (one level under `shellies/`, unique per plug) |
| RPC status notifications over MQTT | on |
| Generic status update over MQTT | on |

Saving reboots the plug. When it comes back online the Pi asks it for its
status (`Shelly.GetStatus`), so it registers without being toggled. The role
becomes the plug id (`shellies/humidifier` → `plug-humidifier`), as Tasmota's
Topic does. A prefix with more than one level under `shellies/` is refused:
the broker would drop the commands, so the Pi does not send them.

Topics under the prefix:

| Topic | Direction | Payload |
|---|---|---|
| `<prefix>/rpc` | Pi → plug | `{"id": n, "src": "<prefix>/sporeprint", "method": "Switch.Set", "params": {"id": 0, "on": true}}` |
| `<prefix>/sporeprint/rpc` | plug → Pi | JSON-RPC replies (incl. `Shelly.GetStatus`) |
| `<prefix>/events/rpc` | plug → Pi | `NotifyStatus` / `NotifyFullStatus`, e.g. `{"params": {"switch:0": {"output": true, "apower": 52.1}}}` |
| `<prefix>/status/switch:<n>` | plug → Pi | the full switch status ("Generic status update") |
| `<prefix>/online` | plug → Pi | `true` / `false` (retained) |

Only `output`, `apower` and `errors` are read. `NotifyStatus` is a delta: a
missing key means unchanged, never off. An overpower or overtemp entry in
`errors` is logged. On a multi-channel device, `switch:0` is
`plug-<role>` and `switch:<n>` is `plug-<role>-<n>`.

### Online / offline

`<prefix>/online` (Shelly, both generations) and `tasmota/<topic>/tele/LWT`
(`Online` / `Offline`) set every plug under that prefix online or offline,
pushed to Socket.IO clients as `plug_online`. Any state report also marks its
plug online. A report arriving on a plug's topics also corrects its stored
plug type and prefix, so a Gen1 Shelly replaced by a Gen2 one under the same
name needs no re-registration.

### Commands and safety

`POST /api/automation/plugs/{plug_id}/command` switches a plug by hand. It
returns 409 for an unknown or unpaired plug and 503 when the broker is down or
the publish failed. A manual OFF also clears a running `safety_max_on_seconds`
ceiling for that plug.

Keep plugs outside the humid chamber. The Athom plugs are not UL/ETL listed:
keep a space heater ≤ 1500 W (≤ 1200 W preferred) on one plug.

## LAN vendor drivers

Three free-tier drivers control LAN smart plugs and switches without a
vendor-cloud round-trip (write paths since v4.1.2):

- **Wemo** (Belkin) — UPnP/SOAP over TCP.
- **Kasa** (TP-Link) — encrypted JSON on TCP/9999.
- **Tapo** (TP-Link) — the local KLAP (v2) handshake (below).

Each has full read + write paths. No extra pip dependencies — the SOAP
envelopes, the Kasa XOR cipher and the KLAP handshake are inline. An
automation rule can switch them too: its action sets `vendor_slug`,
`vendor_action` (`set_power`, `set_dim`) and `vendor_params`, and its
`target` names the override key `vendor:{slug}:{ip-or-id}`; a
`safety_max_on_seconds` ceiling switches them off through the same
dispatcher.

### Wemo

| Field | Notes |
|---|---|
| `devices[].ip` | Per-device LAN address — a host, or `host:port` to pin the port. |
| `devices[].chamber_id` | Optional chamber tagging for telemetry. |
| `devices[].is_insight` | True for the Wemo Insight (enables power-monitoring poll). |

Wemo firmware moves its control port around. Without a pinned port the driver
tries 49153, 49152, 49154, 49155 and 49151 when a connection is refused, and
caches the one that answers.

Belkin sunset their cloud in late 2024; the local SOAP endpoint stays
functional on existing hardware. Discovery is not yet automated — list
the device IPs explicitly.

#### Wemo write actions

| Action | Body | Effect |
|---|---|---|
| `set_power` | `{"ip": "...", "on": true}` | On/off via `SetBinaryState`. |

### Kasa

| Field | Notes |
|---|---|
| `devices[].ip` | Per-device LAN address — a host or `host:port`. |
| `devices[].is_dimmer` | True for HS220 (enables brightness poll + `set_dim`). |
| `devices[].has_emeter` | True for Insight-style models (enables emeter poll). |

The Kasa XOR cipher is implemented inline (`_encrypt` / `_decrypt` in
`kasa/driver.py`). Round-trip-tested. Replies that span several TCP segments
(HS300 / KP303 strips) are read completely.

#### Kasa write actions

| Action | Body | Effect |
|---|---|---|
| `set_power` | `{"ip": "...", "on": true}` | `system.set_relay_state`. |
| `set_dim` | `{"ip": "...", "percent": 75}` | `smartlife.iot.dimmer.set_brightness`. HS220 only. |

### Tapo

Tapo uses the local KLAP (v2) handshake. `transport=cloud` does not collect
telemetry yet (health reports it; switch to `transport=local`), and writes
(`set_power` / `set_dim`) always need the device's LAN IP.

### Input rules (every vendor action)

- Boolean params accept `true`/`false`, `on`/`off`, `yes`/`no`, `1`/`0` (also as
  strings); anything else is 400.
- Device IPs must be a host or `host:port`; vendor ids must match
  `[A-Za-z0-9_.:~-]{1,128}`. Invalid values get 400.

## Reaching write actions from cloud-web

The relay's RPC tunnel forwards `vendor_action` requests to the Pi.
Pattern:

```http
POST /api/integrations/{device_id}/{slug}/actions/{action}
Content-Type: application/json
Authorization: Bearer <jwt>

{ "ip": "10.0.0.20", "on": true }
```

Premium-gated + ownership-checked at the cloud edge. On the Pi, the same
actions are `POST /api/integrations/{slug}/actions/{action}`.

## Write actions across the rest of the grid

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
| Tapo | `set_power`, `set_dim` |

`GET /api/integrations/{slug}/actions` lists each driver's writable
actions for the cloud-web UI to render the right control buttons.
