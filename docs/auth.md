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
requests. A page on another site can also send requests to the Pi's real
name, as a form post or an image load does; the
[cross-site guard](#cross-site-requests) refuses the ones that change
anything, and CORS keeps the answers to the rest from the page. What neither
stops, in LAN-trust mode, is any compromised device or guest on the LAN.

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
`Authorization: Bearer <SPOREPRINT_API_KEY>`. Use it to gate external
clients (scripts, other tools). **The bundled browser dashboard sends no key, so it
stops working in this mode.**

Public paths in API-key mode:

| Path | Why |
|---|---|
| `/api/health` (any method) | Liveness checks |
| `POST /api/cloud/pair` | The cloud pairing handshake: a LAN client trades the code for a configure token (code-gated, rate-limited) |
| `GET /api/cloud/pair-verify` | The cloud's check, while pairing or rotating the device token, that the Pi issued the configure token. The cloud never holds your API key; anything but a live configure token gets 401 |
| `POST /api/cloud/configure` | The cloud's delivery of the device credentials, with the same configure token: single-use, valid 10 minutes, issued only by `POST /api/cloud/pair` |
| `GET /api/provision/ca` | The broker's public CA, fetched keyless by Secure-MQTT nodes. It never serves a file containing a private key |

`GET`/`POST /api/cloud/pairing-code` need the bearer in this mode, so the
pairing code, and with it every configure token, needs the key.

**Pairing with sporeprint.ai** needs the Pi on a public HTTPS address for a
few minutes (the cloud calls `pair-verify` and `configure` back). Use API-key
mode for that window: in LAN-trust mode that address would serve the whole
API to anyone who finds the name (a new HTTPS name often shows up in public
certificate logs within minutes). The dashboard sends no key, so mint the
pairing code with curl; the
steps are in the README ([Pairing a Pi](../README.md#pairing-a-pi)).

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

The connect handshake uses the same bearer rule. A browser's handshake must
also come from an allowed Origin (see [Cross-site requests](#cross-site-requests)),
so a page on another site can neither open nor read the live stream; native
clients send no Origin. Connect attempts are
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

The same applies to a camera node whose portal "Pi host" is such a name,
including a router's own LAN domain outside the list above (for example
`sporeprint.fritz.box`): its frame uploads are refused until the name is
listed, while MQTT keeps the camera looking online. The server logs each such
camera with its node id (at most hourly), and a camera registered with the Pi
pages once a day (WARNING) until the name is listed or the camera's Pi host
is changed. `GET /api/health` and `GET /api/provision/ca` (the public broker
CA) answer for any name.

## Cross-site requests

Browsers mark every `POST`, `PUT`, `PATCH` and `DELETE` with the `Origin` of
the page that sent it. In both modes the server refuses those (**403**) unless
that Origin is the request's own host (the dashboard, by whatever name you
reach it) or a name the Host allow-list above admits, so a page on another
site cannot abort a session or mint a pairing code through your browser. A
request without an `Origin` (curl, scripts, the camera, the cloud's pairing
calls) is not a page and passes. `SPOREPRINT_ALLOWED_HOSTS=*` turns off the
Host check, not this one. The deprecated `GET` form of
`/api/experiments/{id}/analyze` (it spends Claude credit) is refused when the
browser marks it `Sec-Fetch-Site: cross-site`, since an image load carries no
`Origin`. The Socket.IO handshake applies the same Origin rule.

## CORS

`allow_origin_regex` admits localhost, `*.local`, the RFC 1918 ranges and
`capacitor://localhost` only, for every method the API uses (`PUT` included)
and the `X-Request-ID` header, which responses expose. CORS decides which
pages may *read* responses; sending is the [cross-site guard](#cross-site-requests)'s
job.

## Recovering a Pi set up with the old `setup.sh`

Older `setup.sh` runs generated an API key, which makes the dashboard return
401 on every call. In `.env`, blank `SPOREPRINT_API_KEY`, set
`SPOREPRINT_ALLOW_UNAUTHENTICATED=true`, then run `docker compose up -d server`.
`setup.sh` is now a developer-workstation script; install Pis with
`./install.sh`.
