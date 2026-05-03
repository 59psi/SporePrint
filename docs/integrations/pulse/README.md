# Pulse Grow integration

The SporePrint Pi can poll your Pulse Grow devices (Pulse One / Pro /
Zero) in two transports:

- **Local mode** (free) — UDP discovery on the LAN + per-device HTTP
  polling. Traffic stays on your LAN.
- **Cloud mode** (premium) — authenticate to `api.pulsegrow.com` with
  your Pulse account credentials, poll each device's `recent-data`
  endpoint. Cloud mode is gated premium because we hold your Pulse
  credentials on the Pi (encrypted at rest) and refresh tokens against
  Pulse's API on your behalf.

Both transports publish into the same SporePrint telemetry pipeline
under node IDs like `pulse:<device_id>`, so chamber UI, automation,
and the Grafana exporter all work identically regardless of which
mode you pick.

## Local mode (free)

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
     ["http://10.0.0.5", "http://10.0.0.6"]
     ```
   - `local_broadcast_addr`: `255.255.255.255` is the default. If
     your router blocks limited broadcast, set this to your subnet
     broadcast (e.g. `10.0.0.255`).
   - `local_discovery_port`: `5683` (CoAP convention) is the default.
   - `local_http_port`: `80` is the default per-device HTTP port.
3. Save, then *Test connection*. You should see "ok · transport: local
   · devices_seen: N".
4. Map `device_mappings` to chamber IDs (same shape as Aranet):

   ```json
   { "PULSE-ABC-123": "1" }
   ```
5. Save again, then *Enable*.

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

## Cloud mode (premium)

### Quick start (cloud)

1. In the Pi LAN UI at `/integrations`:
   - `transport`: `cloud`
   - `email`: your Pulse account email
   - `password`: your Pulse account password — stored encrypted at
     rest via the integrations Fernet key, exchanged for a session
     token on first poll.
2. Save, then *Test connection*. You should see "ok · transport:
   cloud · devices_seen: N".
3. Map `device_mappings` to chambers, same as local mode.
4. Save again, then *Enable*.

### Cloud-mode caveats

- **Rate limits.** Pulse's cloud API rate limit is approximately 1
  req/s per token across all devices on your account. The driver's
  `poll_seconds` floor is 60 s. If you have many Pulse devices on one
  account, raise `poll_seconds` to keep the per-poll burst under the
  limit.
- **Token expiry.** The driver re-logs in transparently on a 401
  response (token expired). Persistent 401s after one re-login surface
  as a clear error — usually means the password changed and the
  integration needs an update.
- **Why premium?** Because *our* infrastructure holds your Pulse
  credentials and pays for the Sentry/log noise of a third-party
  cloud dependency. Per `feedback_tier_model`, that's the line.
  Local mode is free and recommended whenever your Pulse devices are
  reachable on your LAN.

## Sensor type mapping

| Pulse `type` | SporePrint sensor name |
|---|---|
| `temperature` | `temp_c` |
| `humidity` | `humidity` |
| `vpd` | `vpd_kpa` |
| `dew_point` | `dew_point_c` |
| `light` | `lux` |

`vpd_kpa` and `dew_point_c` are SporePrint sensor names introduced by
this driver. Existing automation rules that match on `temp_c` /
`humidity` continue to work; rules that want VPD can match on the
new name.
