"""Bearer-token auth gate for /api/* and Socket.IO.

Enabled when `SPOREPRINT_API_KEY` is set. When unset (dev mode) all requests
pass through — the LAN-scoped CORS middleware remains the only gate.

Requests that pass without the bearer:
- `/api/health` (any method) — the UI's existence probe must work before auth is set up
- `POST /api/cloud/pair`      — pairing handshake (code + lockout is the gate here)
- `POST /api/vision/frame`    — ESP32-CAM uploads (the camera has no slot for the
  key), ONLY for an X-Node-Id registered in `hardware_nodes` and with a declared
  Content-Length within the 20 MB cap (checked before the body is read)

`/api/cloud/pairing-code` (GET and POST) is NOT public: unauthenticated minting
replaced the operator's code and reset the pairing lockout at will, and the GET
leaked the live code. Everything else requires
`Authorization: Bearer <SPOREPRINT_API_KEY>`.

## LAN-trust model (v3.3.3 documentation)

The Pi lives on the user's LAN behind a home router. There is deliberately
no per-client identity: every machine on the LAN that presents the correct
`SPOREPRINT_API_KEY` can reach the API. This is a conscious tradeoff —
per-client JWT infrastructure on a Pi was judged to be more operational
burden than the blast-radius of "a LAN-side attacker already inside the
grower's network can hit the API". Compensating controls:

  * CORS regex narrows browser origins to localhost, mDNS, RFC1918, and
    the official Capacitor shells + sporeprint.ai (see main.py).
  * Every connect is logged with `sid`, remote IP, and whether auth is
    present — a spike of connects from one IP is visible in journalctl.
  * Rate-limit on Socket.IO connect (bounded-retry via `_connect_rate_ok`)
    prevents a compromised LAN device from burning through a shared key
    via rapid-fire connection attempts.
  * The HMAC command path signs with the *per-device* cloud_token, not the
    shared API key — a stolen LAN bearer cannot forge cloud commands.

If you need per-client identity (multi-tenant Pi, commercial deployment
with untrusted LAN segments), swap `socketio_auth_ok` for a JWT validator
and require the caller to sign in with the cloud's Supabase issuer. Leaving
the current shared-bearer in place for the single-household default.
"""

from __future__ import annotations

import collections
import hmac
import logging
import re
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .db import get_db

log = logging.getLogger(__name__)

# Socket.IO connect rate-limiter — capped at 20 connections per IP per 60 s.
# A household has at most a few devices; 20/min is generous for legitimate
# reconnects and tight enough to trip on a scripted probe.
_CONNECT_RATE_CAP = 20
_CONNECT_RATE_WINDOW = 60.0
_connect_attempts: dict[str, collections.deque] = {}


def _connect_rate_ok(remote_addr: str | None) -> bool:
    if not remote_addr:
        return True
    now = time.time()
    q = _connect_attempts.setdefault(remote_addr, collections.deque())
    # Drop timestamps older than the window.
    while q and (now - q[0]) > _CONNECT_RATE_WINDOW:
        q.popleft()
    if len(q) >= _CONNECT_RATE_CAP:
        return False
    q.append(now)
    return True

# Public for every method.
_PUBLIC_PATHS = frozenset({
    "/api/health",
})

# Public only for the listed method (method-aware: the old path-only
# whitelist also exposed e.g. POST /api/cloud/pairing-code).
_PUBLIC_ROUTES = frozenset({
    ("POST", "/api/cloud/pair"),
})

# v3.4.9 L-9 — the camera node posts JPEGs here but has no slot for
# SPOREPRINT_API_KEY (no captive-portal UI to enter it, no secure
# distribution channel from the Pi to each ESP32). A keyless upload is
# accepted only when (enforced in _camera_frame_rejection):
#   * X-Node-Id matches [a-zA-Z0-9_-]{1,32}
#   * that node_id exists in hardware_nodes (registered device only — the
#     camera registers itself over MQTT with its heartbeat)
#   * Content-Length is declared and within the 20 MB cap, checked BEFORE
#     the body is read into RAM
# The route itself keeps its resolve()+is_relative_to storage guard. A
# stronger per-node auth (HMAC over the JPEG with the node's hmac_key) is
# still future work.
_CAMERA_FRAME_ROUTE = ("POST", "/api/vision/frame")
_MAX_FRAME_UPLOAD_BYTES = 20 * 1024 * 1024
_NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


async def _node_is_registered(node_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM hardware_nodes WHERE node_id = ? LIMIT 1", (node_id,)
        )
        return (await cursor.fetchone()) is not None


async def _camera_frame_rejection(request: Request) -> JSONResponse | None:
    """Gate a keyless camera frame upload; None means let it through."""
    node_id = request.headers.get("x-node-id") or ""
    if not _NODE_ID_RE.match(node_id):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    length = request.headers.get("content-length")
    if length is None:
        return JSONResponse({"error": "Content-Length required"}, status_code=411)
    if not length.isdigit():
        return JSONResponse({"error": "Invalid Content-Length"}, status_code=400)
    if int(length) > _MAX_FRAME_UPLOAD_BYTES:
        return JSONResponse({"error": "File too large (max 20MB)"}, status_code=413)
    if not await _node_is_registered(node_id):
        log.warning("Rejected frame upload from unregistered node %r", node_id)
        return JSONResponse({"error": "Unknown camera node"}, status_code=403)
    return None


def _extract_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def _valid_token(presented: str | None) -> bool:
    if not settings.api_key:
        return True
    if not presented:
        return False
    return hmac.compare_digest(presented, settings.api_key)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.api_key:
            return await call_next(request)

        # The ASGI scope path is what the router dispatches on. request.url
        # is rebuilt from the Host header, which older Starlette let a
        # crafted `Host: x/api/health?` rewrite into a public path.
        path = request.scope.get("path") or request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # CORS preflight never carries auth — let it through so the browser
        # can see the allowed headers.
        if request.method == "OPTIONS":
            return await call_next(request)

        if path in _PUBLIC_PATHS or (request.method, path) in _PUBLIC_ROUTES:
            return await call_next(request)

        presented = _extract_bearer(request.headers.get("authorization"))
        if _valid_token(presented):
            return await call_next(request)

        if (request.method, path) == _CAMERA_FRAME_ROUTE:
            rejection = await _camera_frame_rejection(request)
            if rejection is not None:
                return rejection
            return await call_next(request)

        return JSONResponse({"error": "Unauthorized"}, status_code=401)


def socketio_auth_ok(auth: dict | None, remote_addr: str | None = None) -> bool:
    """Callback used by the Socket.IO connect handler.

    When ``remote_addr`` is provided, the caller is rate-limited to
    ``_CONNECT_RATE_CAP`` connections per ``_CONNECT_RATE_WINDOW`` seconds.
    A LAN-side attacker cannot burn through the shared bearer by reconnecting
    thousands of times per second — they have to work through the cap.
    """
    if remote_addr and not _connect_rate_ok(remote_addr):
        log.warning("Socket.IO connect rate-limited for %s", remote_addr)
        return False
    if not settings.api_key:
        return True
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    return _valid_token(token)
