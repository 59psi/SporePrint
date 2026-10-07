# Mosquitto broker config

The `mqtt` service in `docker-compose.yml` (Eclipse Mosquitto 2.1) reads
this directory: [`mosquitto.conf`](mosquitto.conf) (listeners, auth) and
[`acl.conf`](acl.conf) (who may publish or subscribe where). `install.sh`
generates the rest on the Pi; none of it is committed:

- `passwd`: the password file (owned by the broker's uid 1883, mode 0600).
  [`passwd.example`](passwd.example) explains it.
- `certs/`: the broker's CA (`ca.crt`) and server certificate
  (`server.crt` / `server.key`), with every Pi IPv4 as an IP and DNS SAN.
  Re-running `install.sh` re-issues the server certificate from the same CA.

## Listeners

| Port | Transport | Who |
|---|---|---|
| 1883 | plaintext | nodes without Secure MQTT, smart plugs, the server |
| 8883 | TLS (`certs/`) | nodes with Secure MQTT ticked; they pin `ca.crt`, fetched from `GET /api/provision/ca` |

Both are published on the LAN. Anonymous clients are refused
(`allow_anonymous false`). Never port-forward either port.

## Accounts

| User | Created by | Grants (`acl.conf`) |
|---|---|---|
| `server` | `install.sh` (`SPOREPRINT_MQTT_USERNAME` / `_PASSWORD`) | read `sporeprint/#`, `shellies/#`, `tasmota/#`, `$SYS/broker/#`; write `sporeprint/+/cmd[/#]`, `shellies/+/relay/0/command`, `shellies/+/rpc`, `tasmota/+/cmnd/POWER` |
| `sp-3p` | `install.sh` (`SPOREPRINT_MQTT_3P_PASSWORD`) | readwrite `shellies/#` and `tasmota/#`: the login you type into every smart plug |
| `sp-cmd` | `scripts/rotate-mqtt-creds.sh` (`SPOREPRINT_MQTT_CMD_PASSWORD`) | external tooling: read node telemetry / status / health / alert / ota, write `cmd/*` |
| `sp-telemetry` | `scripts/rotate-mqtt-creds.sh` (`SPOREPRINT_MQTT_TELEMETRY_PASSWORD`) | read-only `sporeprint/#` (dashboards, `mosquitto_sub`) |
| `<node_id>` | `scripts/add-node-mqtt-user.sh <node_id>` | its own `sporeprint/<node_id>/…` only: write telemetry, status, health, alert, ota, logs and coredump chunks; read its `cmd/#` |

A node's MQTT username must equal its node id, because the per-node grants
are `pattern` lines on `%u`. The server drops frames on
`sporeprint/<name>/…` whose `<name>` is a service account (`server`, `sp-3p`,
`sp-cmd`, `sp-telemetry`), so a leaked plug login cannot pose as a node.
Edit `passwd` only with the two scripts above (they run `mosquitto_passwd`
inside the broker image).

## Smart plugs

The ACL covers each plug family only in the topic layout the server uses:

- **Tasmota**: Full Topic `tasmota/%topic%/%prefix%/` (Tasmota's default
  `%prefix%/%topic%/` is outside the grant).
- **Shelly Gen1**: default topics `shellies/<device_id>/relay/0[...]`.
- **Shelly Gen2+** (Plus, Pro, Mini, Gen3, Gen4): MQTT prefix
  `shellies/<role>`, exactly one level under `shellies/`. The factory prefix
  is the device id, a top-level tree per device; no grant could cover those
  trees without also covering every two-level topic on the broker, so the
  prefix is changed instead.

Setup steps: [docs/integrations/smart-plugs.md](../../docs/integrations/smart-plugs.md).

## Adding a topic

Mosquitto denies silently: a publish or subscription outside the ACL just
never arrives. A new node topic needs a `pattern write sporeprint/%u/<topic>`
line here **and** a handler branch in `server/app/mqtt.py`; prefer adding a
key to the telemetry JSON instead. `server/tests/test_mqtt_acl_contract.py`
parses `acl.conf` and fails if a topic the server subscribes to or publishes,
or a topic the firmware builds, is not granted.
