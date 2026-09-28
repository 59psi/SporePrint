# HTTP auth — LAN-trust vs API-key mode

The Pi's API (`/api/*` on port 8000, and through the dashboard's nginx on
port 3001) has two modes. `server/app/auth.py` is the source of truth.

## LAN-trust (the default install)

`install.sh` leaves `SPOREPRINT_API_KEY` empty and writes
`SPOREPRINT_ALLOW_UNAUTHENTICATED=true` into `.env`. Every `/api/*` request
and Socket.IO connect is accepted without a token. This is what the bundled
dashboard needs: it calls `/api` same-origin and sends no bearer.

LAN-trust means exactly that: **every device on your LAN can use the whole
API** (actuators, node OTA, integration settings) without a key. Use it only
on a home network whose devices you trust, behind a router/NAT, and never
port-forward 3001, 8000, 1883 or 8883. The MQTT broker is credentialed in
both modes.

A web page you open is not on your LAN, but a malicious one could try to act
as if it were by *DNS rebinding* (its own hostname re-resolves to the Pi's LAN
address, so the browser treats the Pi as the same site). The
[Host allow-list](#host-allow-list-dns-rebinding) below refuses those
requests. What it does not stop, in LAN-trust mode:

- any compromised device or guest on the LAN;
- a page in your browser *sending* a request to the Pi's IP (a cross-site
  form post or image load). It cannot read the answer (CORS), and JSON
  endpoints refuse non-JSON bodies, but requests that need no body can still
  be triggered that way.

On a network you do not fully trust, use API-key mode.

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
only from `FORWARDED_ALLOW_IPS`. Under Docker that is the ui container's fixed
address on the compose `edge` network (default `172.31.253.2`), never a
range: a bridge gateway is where Docker relays some clients of the published
port 8000 from (IPv6 and loopback ones), and those could otherwise forge the
header. A raw `X-Forwarded-For` header sent straight to port 8000 is ignored.

If `docker compose up` fails with "Pool overlaps with other one on this
address space", move the network in `.env`: `SPOREPRINT_EDGE_SUBNET`,
`SPOREPRINT_EDGE_UI_IP`, `SPOREPRINT_EDGE_SERVER_IP` and `FORWARDED_ALLOW_IPS`
(set to the ui address) together.

## Host allow-list (DNS rebinding)

In both modes the server answers `/api/*`, `/metrics` and Socket.IO only when
the request's `Host` names the Pi in a way no outside web page can fake
(`server/app/host_allow.py`):

- an IP address in the loopback, private (RFC 1918), link-local, CGNAT
  (`100.64.0.0/10`, e.g. Tailscale) or IPv6 unique-local ranges;
- `localhost`, `*.localhost`, `*.local` (mDNS, e.g. `sporeprint.local`),
  `*.lan`, `*.home`, `*.home.arpa`, `*.internal`, `*.localdomain`;
- a name without a dot (router DNS such as `raspberrypi`);
- the host of `SPOREPRINT_PUBLIC_UI_URL`;
- anything in `SPOREPRINT_ALLOWED_HOSTS`.

Other names get **421 Misdirected Request** with a message naming the
setting, and the server logs the refused name once. If you reach the Pi by
another name (a Tailscale MagicDNS name, your own domain, a split-DNS record),
add it to `SPOREPRINT_ALLOWED_HOSTS` in `.env` and run
`docker compose up -d server`:

```bash
SPOREPRINT_ALLOWED_HOSTS=pi.example.net,*.ts.net   # names, *.suffix, IPs, CIDRs
SPOREPRINT_ALLOWED_HOSTS=*                          # turn the check off
```

The same applies to a camera node whose portal "Pi host" is such a name: its
frame uploads are refused until the name is listed. `GET /api/health` and
`GET /api/provision/ca` (the public broker CA) answer for any name.

## CORS

`allow_origin_regex` admits localhost, `*.local`, the RFC 1918 ranges and
`capacitor://localhost` only. CORS decides which pages may *read* responses;
it does not stop a request from being sent (see LAN-trust above).

## Recovering a Pi set up with the old `setup.sh`

Older `setup.sh` runs generated an API key, which makes the dashboard return
401 on every call. In `.env`, blank `SPOREPRINT_API_KEY`, set
`SPOREPRINT_ALLOW_UNAUTHENTICATED=true`, then run `docker compose up -d server`.
`setup.sh` is now a developer-workstation script; install Pis with
`./install.sh`.
