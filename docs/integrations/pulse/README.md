# Pulse Grow integration

The SporePrint Pi can poll your Pulse Grow devices (Pulse One / Pro /
Zero) in two transports, both free (the Pi has no paygate):

- **Local mode** — UDP discovery on the LAN + per-device HTTP
  polling. Traffic stays on your LAN.
- **Cloud mode** — authenticate to `api.pulsegrow.com` with your Pulse
  account credentials, poll each device's `recent-data` endpoint. The
  Pi talks to Pulse directly; your credentials stay on the Pi
  (encrypted at rest), never on sporeprint.ai.

Both transports store readings in the same SporePrint telemetry
history under node IDs like `pulse:<device_id>`, in no chamber, so the
telemetry API and the Grafana exporter see them the same way whichever
mode you pick. They do **not** drive automation rules or safety alerts:
those run only on MQTT telemetry from SporePrint nodes.
`device_mappings` (device id → chamber id) is accepted in the config but
not used yet: to show a device with a chamber, add its node id to that
chamber's `node_ids` (`PATCH /api/chambers/{id}`).

`recent-data` returns a device's latest reading whether or not it is
new, so each reading is stored once, at the time the device took it
(when Pulse reports that time). A device whose reading stops changing
for 10 minutes (or three polls, when that is longer), or whose fetch
fails, turns the integration's health `degraded` and is named there
(`error` when every device is affected).

## Local mode

> ⚠ **Live-device verification needed.** Local mode was developed
> against Pulse's documented LAN behaviour but has not been
> exercised against a paired device by us. The discovery probe and
> the HTTP path may need tweaking for your specific firmware
> revision; please file an issue with the discovery response and the
> exact endpoint your device exposes if it differs from what's coded
> here.

### Quick start (local)

1. Open the Pi LAN UI at `/integrations` and find the Pulse row.
2. Click *Configure* and set:
   - `transport`: `local`
   - **Either** leave `local_device_urls` empty for UDP discovery,
     **or** set it to a list of explicit device URLs if you know your
     Pulse devices' LAN IPs:
     ```json
     ["http://10.0.0.5", "http://10.0.0.6:8080"]
     ```
     Each entry is a device's root URL (no path), checked when you save;
     one that names a port keeps it, the others use `local_http_port`.
   - `local_broadcast_addr`: `255.255.255.255` is the default. If
     your router blocks limited broadcast, set this to your subnet
     broadcast (e.g. `10.0.0.255`).
   - `local_discovery_port`: `5683` (CoAP convention) is the default.
   - `local_http_port`: `80` is the default per-device HTTP port.
3. Save, then *Test connection*. You should see "ok · transport: local
   · devices_seen: N".
4. *Enable*.

### Local-mode caveats

- **Subnet-broadcast vs limited-broadcast.** Some home routers drop
  packets sent to `255.255.255.255` because they're considered
  "outside the routable LAN." If discovery returns no devices and you
  know the Pulse devices are on, switch to your subnet broadcast
  (e.g. `10.0.0.255`).
- **No discovery → use `local_device_urls`.** If discovery is
  unreliable in your environment, just give the driver explicit URLs
  for each Pulse device and skip the scan entirely.
- **Polling cadence.** Default 120 s, floor 30 s. Pulse devices
  refresh internally about every minute; polling faster than that
  doesn't give you fresher data.

## Cloud mode

### Quick start (cloud)

1. In the Pi LAN UI at `/integrations`:
   - `transport`: `cloud`
   - `email`: your Pulse account email
   - `password`: your Pulse account password — stored encrypted at
     rest via the integrations Fernet key, exchanged for a session
     token on first poll.
2. Save, then *Test connection*. You should see "ok · transport:
   cloud · devices_seen: N".
3. *Enable*.

### Cloud-mode caveats

- **Rate limits.** Pulse's cloud API rate limit is approximately 1
  req/s per token across all devices on your account. The driver's
  `poll_seconds` floor is 60 s. If you have many Pulse devices on one
  account, raise `poll_seconds` to keep the per-poll burst under the
  limit.
- **Token expiry.** The driver re-logs in transparently on a 401
  response (token expired). Persistent 401s after one re-login surface
  as a clear error — usually means the password changed and the
  integration needs an update. A login Pulse refuses is not resent on
  every poll (repeated failures can lock the account): polls fail at
  once until you save the settings again, even unchanged.
- **Local first.** Local mode is recommended whenever your Pulse
  devices are reachable on your LAN: no account sign-in, no third-party
  cloud between the device and the Pi.

## Sensor type mapping

| Pulse `type` | SporePrint sensor name |
|---|---|
| `temperature` | `temp_c` (a reading Pulse reports in °F is converted) |
| `humidity` | `humidity` |
| `vpd` | `vpd_kpa` |
| `dew_point` | `dew_point_f` (converted from °C unless Pulse reports °F) |
| `light` | `lux` |

`vpd_kpa` is the one SporePrint sensor name this driver introduces;
dew point uses the canonical firmware name `dew_point_f`. Every reading
is stored (the Grafana exporter picks up `temp_c` and `humidity`), but
no automation rule evaluates it: rules run only on MQTT node telemetry,
and the built-in temperature rules match `temp_f`, not `temp_c`.
