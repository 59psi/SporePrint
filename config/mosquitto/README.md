# Mosquitto broker config

The `mqtt` service in `docker-compose.yml` (Eclipse Mosquitto 2.1) reads
this directory: [`mosquitto.conf`](mosquitto.conf) (listeners, auth) and
[`acl.conf`](acl.conf) (who may publish or subscribe where). `install.sh`
generates the rest on the Pi; none of it is committed:

- `passwd`: the password file (owned by the broker's uid 1883, mode 0600).
  [`passwd.example`](passwd.example) explains it.
- `certs/`: the broker's CA (`ca.crt`) and server certificate
  (`server.crt` / `server.key`), with every Pi IPv4 as an IP and DNS SAN.
  Re-running `install.sh` keeps the CA, which nodes pin, and re-issues the
  server certificate from it when the certificate is missing, expires within
  30 days or does not name the Pi's current IP. Deleting `certs/` is the only
  way to a new CA; every Secure-MQTT node then needs a factory reset.

## Listeners

| Port | Transport | Who |
|---|---|---|
| 1883 | plaintext | nodes without Secure MQTT, smart plugs, the server |
| 8883 | TLS (`certs/`) | nodes with Secure MQTT ticked; they pin `ca.crt`, fetched from `GET /api/provision/ca` |

Both are published on the LAN, on IPv4 only (`docker-compose.yml` binds
`0.0.0.0`, so a Pi's global IPv6 address does not expose them). Anonymous
clients are refused (`allow_anonymous false`). Never port-forward either
port.

## Accounts

| User | Created by | Grants (`acl.conf`) |
|---|---|---|
| `server` | `install.sh` (`SPOREPRINT_MQTT_USERNAME` / `_PASSWORD`) | read `sporeprint/#`, `shellies/#`, `tasmota/#`, `$SYS/broker/#`; write `sporeprint/+/cmd[/#]`, `shellies/+/relay/0/command`, `shellies/+/rpc`, `tasmota/+/cmnd/POWER` |
| `sp-3p` | `install.sh` (`SPOREPRINT_MQTT_3P_PASSWORD`) | readwrite `shellies/#` and `tasmota/#`: one login shared by every smart plug set up with it |
| `<plug name>` | `scripts/add-plug-mqtt-user.sh <name>` (listed in `SPOREPRINT_MQTT_PLUG_USERS`) | its own `tasmota/<name>/…` and `shellies/<name>/…` only: the plug's Tasmota Topic, Shelly role or Gen1 device id. The safer login for a plug |
| `sp-cmd` | `scripts/rotate-mqtt-creds.sh` (`SPOREPRINT_MQTT_CMD_PASSWORD`) | external tooling: read node telemetry / status / health / alert / ota, write `cmd/*` |
| `sp-telemetry` | `scripts/rotate-mqtt-creds.sh` (`SPOREPRINT_MQTT_TELEMETRY_PASSWORD`) | read-only `sporeprint/#` (dashboards, `mosquitto_sub`) |
| `<node_id>` | `scripts/add-node-mqtt-user.sh <node_id>` | its own `sporeprint/<node_id>/…` only: write telemetry, status, health, alert, ota, logs and coredump chunks; read its `cmd/#` |

A node's MQTT username must equal its node id, and a plug's its topic level,
because the per-node and per-plug grants are `pattern` lines on `%u`. Those
lines apply to every login, so the server drops frames on
`sporeprint/<name>/…` whose `<name>` is a service account (`server`, `sp-3p`,
`sp-cmd`, `sp-telemetry`) or a listed plug login, and plug frames under a
service account's name: a leaked plug password cannot pose as a node. A
plug's password is readable from its web page; with `sp-3p` that one
password switches and fakes every plug, with a per-plug login only its own.
Edit `passwd` only with the scripts above (they run `mosquitto_passwd`
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
