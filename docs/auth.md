# HTTP auth — LAN-trust vs API-key mode

The Pi's API (`/api/*` on port 8000, and through the dashboard's nginx on
port 3001) has two modes. `server/app/auth.py` is the source of truth.

## LAN-trust (the default install)

`install.sh` leaves `SPOREPRINT_API_KEY` empty and writes
`SPOREPRINT_ALLOW_UNAUTHENTICATED=true` into `.env`. Every `/api/*` request
and Socket.IO connect is accepted without a token. This is what the bundled
dashboard needs: it calls `/api` same-origin and sends no bearer.

It is safe on a home LAN behind a router/NAT. Keep the Pi there and never
port-forward 3001, 8000, 1883 or 8883. The MQTT broker is credentialed in
both modes.

With both settings unset (an empty key and
`SPOREPRINT_ALLOW_UNAUTHENTICATED=false`) the server refuses to boot and points
at `./install.sh`.

## API-key mode

Set a long random `SPOREPRINT_API_KEY` in the repo-root `.env`, then apply it:

```bash
docker compose up -d server     # 'docker compose restart' does not re-read .env
```

From then on every `/api/*` request and every Socket.IO connect must send
`Authorization: Bearer <SPOREPRINT_API_KEY>`. Use it to gate the mobile app
and other external clients. **The bundled browser dashboard sends no key, so it
stops working in this mode.**

Public paths in API-key mode:

| Path | Why |
|---|---|
| `/api/health` (any method) | Liveness checks |
| `POST /api/cloud/pair` | The mobile app's pairing handshake (code-gated, rate-limited) |
| `GET /api/provision/ca` | The broker's public CA, fetched keyless by Secure-MQTT nodes. It never serves a file containing a private key |

`GET`/`POST /api/cloud/pairing-code` need the bearer in this mode.

**Camera uploads.** The ESP32-CAM has no slot for the API key, so
`POST /api/vision/frame` without a bearer is accepted only when:

- `X-Node-Id` matches `[A-Za-z0-9_-]{1,32}` (otherwise 401),
- the request declares a `Content-Length` (411) of at most 20 MB (413),
- that node id is registered in `hardware_nodes` (403 otherwise). Cameras
  register themselves over MQTT with their heartbeat.

**`/metrics`** (Grafana/Prometheus) sits outside `/api` and is not covered by
the API key. It returns 404 until the Grafana integration is enabled, and can
carry its own bearer token (see
[integrations/grafana/README.md](integrations/grafana/README.md)).

## Socket.IO

The connect handshake uses the same bearer rule. Connect attempts are
rate-limited per client address, and the address is the real client: behind
the dashboard's nginx it comes from `X-Forwarded-For`, which uvicorn trusts
only from `FORWARDED_ALLOW_IPS` (default `172.16.0.0/12`, Docker's bridge
range). A raw `X-Forwarded-For` header sent straight to port 8000 is ignored.

## CORS

`allow_origin_regex` admits localhost, `*.local`, the RFC 1918 ranges and
`capacitor://localhost` only.

## Recovering a Pi set up with the old `setup.sh`

Older `setup.sh` runs generated an API key, which makes the dashboard return
401 on every call. In `.env`, blank `SPOREPRINT_API_KEY`, set
`SPOREPRINT_ALLOW_UNAUTHENTICATED=true`, then run `docker compose up -d server`.
`setup.sh` is now a developer-workstation script; install Pis with
`./install.sh`.
