"""Host-header allow-list — DNS-rebinding protection for the LAN API.

In LAN-trust mode (the default install) the network boundary is the only
gate in front of /api/* and Socket.IO. A web page from anywhere can get past
it by DNS rebinding: its own hostname re-resolves to the Pi's LAN address,
and the browser then treats the Pi as same-origin with that page (actuators,
node OTA, integration configs). What the page cannot change is the Host
header: it stays the attacker's name. So the server answers only for names
an outside attacker cannot get a public DNS record for:

* IP literals in loopback, RFC 1918, link-local, CGNAT (100.64.0.0/10,
  e.g. Tailscale) and IPv6 unique-local ranges
* localhost and *.localhost, and the private-use suffixes *.local (mDNS),
  *.lan, *.home, *.home.arpa, *.internal and *.localdomain
* dotless names (router DNS such as "raspberrypi", compose's "server")
* the host of SPOREPRINT_PUBLIC_UI_URL
* SPOREPRINT_ALLOWED_HOSTS: a comma list of names, "*.suffix" wildcards,
  IP literals or CIDRs; "*" disables the check

Anything else gets 421 Misdirected Request naming the setting to change.
A request without a Host header passes (no browser sends one). Exempt for
every host, because they serve nothing sensitive: GET/HEAD /api/health
(container and uptime probes) and GET /api/provision/ca (the broker's public
CA, fetched by Secure-MQTT nodes that may know the Pi by any name).

This is a pure ASGI middleware wrapped around main.socket_app, so it covers
the Socket.IO endpoint as well as every FastAPI route; a refused websocket
handshake gets the same 421 (or a policy close where the server cannot send
an HTTP denial).

A camera that uploads under a refused name loses its frames, and with them
the vision checks, while MQTT keeps it looking online. Each such upload is
logged with its node id (at most hourly per node and name), and a camera
registered in hardware_nodes pages the operator once a day (WARNING).

Cross-site requests (CrossSiteRequestGuard, inside the Host check): a page on
another site the operator visits can still *send* requests to the Pi's real
LAN name. Browsers mark every POST, PUT, PATCH and DELETE with its Origin, so
those are refused (403) unless the Origin is the request's own host or a name
this allow-list admits (origin_is_allowed); Socket.IO applies the same check
to its handshake. A request without an Origin (curl, scripts, the camera, the
cloud's pairing callbacks) is not a page and passes. The deprecated GET form
of experiment analysis spends Claude credit on every call, so a cross-site
load of it (an <img>, which carries no Origin) is refused by its
Sec-Fetch-Site header instead.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import time
from functools import lru_cache
from typing import NamedTuple
from urllib.parse import urlsplit

from .config import settings
from .db import get_db
from .node_ids import NODE_ID_RE
from .notifications.service import notify_warning

log = logging.getLogger(__name__)

_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128",                         # loopback
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",  # RFC 1918
    "169.254.0.0/16", "fe80::/10",                    # link-local
    "100.64.0.0/10",                                  # CGNAT (Tailscale)
    "fc00::/7",                                       # IPv6 unique-local
))
# Suffixes no outside party can register a public DNS name under.
_PRIVATE_SUFFIXES = (
    ".localhost", ".local", ".lan", ".home", ".home.arpa", ".internal",
    ".localdomain",
)
_EXEMPT_ROUTES = frozenset({
    ("GET", "/api/health"),
    ("HEAD", "/api/health"),
    ("GET", "/api/provision/ca"),
})

# host[:port] or [ipv6][:port]; lowercased before matching.
_HOST_RE = re.compile(
    r"^(?:\[(?P<v6>[0-9a-f:.]+(?:%[0-9a-z._-]+)?)\]|(?P<name>[a-z0-9_.-]+))"
    r"(?::\d{1,5})?$"
)

_LOG_ONCE_CAP = 64
_logged_hosts: set[str] = set()

# Refused camera uploads: (node id, host) -> when it was last logged. Logged
# at most hourly per pair; a registered camera pages once a day per node.
_FRAME_UPLOAD_ROUTE = ("POST", "/api/vision/frame")
_FRAME_REFUSAL_LOG_SECONDS = 3600
_FRAME_REFUSAL_PAGE_SECONDS = 86400
_FRAME_REFUSAL_CAP = 64
_frame_refusals: dict[tuple[str, str], float] = {}
# Pages are sent off the request path; strong refs until each one finishes.
_background_pages: set[asyncio.Task] = set()

# Cross-site guard (CrossSiteRequestGuard).
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# GET routes that do more than read, kept for clients that still call them.
_STATEFUL_GET_PATHS = (re.compile(r"^/api/experiments/[^/]+/analyze$"),)
_logged_origins: set[str] = set()


class _AllowConfig(NamedTuple):
    allow_all: bool
    names: frozenset[str]
    suffixes: tuple[str, ...]
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]


def _as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _public_ui_host(public_ui_url: str) -> str | None:
    try:
        return urlsplit(public_ui_url or "").hostname
    except ValueError:  # e.g. an unbalanced "[" — never fail every request
        log.warning("SPOREPRINT_PUBLIC_UI_URL %r is not a URL; its host is not "
                    "added to the allowed Host names", public_ui_url)
        return None


@lru_cache(maxsize=8)
def _allow_config(allowed_hosts: str, public_ui_url: str) -> _AllowConfig:
    allow_all = False
    names: set[str] = set()
    suffixes: list[str] = []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

    entries = [e.strip().lower() for e in (allowed_hosts or "").split(",")]
    ui_host = _public_ui_host(public_ui_url)
    if ui_host:
        entries.append(ui_host.lower())

    for entry in entries:
        if not entry:
            continue
        if entry == "*":
            allow_all = True
            continue
        if entry.startswith(("*.", ".")):
            suffix = entry.lstrip("*.").rstrip(".")
            if suffix:
                suffixes.append("." + suffix)
            continue
        try:  # an IP literal or a CIDR
            networks.append(ipaddress.ip_network(entry.strip("[]"), strict=False))
            continue
        except ValueError:
            pass
        host = _hostname(entry)  # a name, possibly with a :port
        ip = _as_ip(host) if host else None
        if ip is not None:
            networks.append(ipaddress.ip_network(ip))
        elif host:
            names.add(host)
        else:
            log.warning("SPOREPRINT_ALLOWED_HOSTS entry %r is not a host name, "
                        "IP or CIDR; ignored", entry)
    return _AllowConfig(allow_all, frozenset(names), tuple(suffixes), tuple(networks))


def _config() -> _AllowConfig:
    return _allow_config(settings.allowed_hosts, settings.public_ui_url)


def _hostname(host_header: str) -> str | None:
    """The bare, lowercased host of a Host header; None when malformed."""
    m = _HOST_RE.match(host_header.strip().lower())
    if m is None:
        return None
    if m.group("v6") is not None:
        return m.group("v6") if _as_ip(m.group("v6")) is not None else None
    name = m.group("name").rstrip(".")
    return name or None


def _name_is_listed(host: str, cfg: _AllowConfig) -> bool:
    """A bare host the allow-list admits (its "*" switch aside)."""
    ip = _as_ip(host)
    if ip is not None:
        return any(ip in net for net in (*_PRIVATE_NETWORKS, *cfg.networks)
                   if net.version == ip.version)
    if "." not in host or host == "localhost" or host in cfg.names:
        return True
    return host.endswith(_PRIVATE_SUFFIXES + cfg.suffixes)


def host_is_allowed(host_header: str | None) -> bool:
    """Whether a request carrying this Host header may be served."""
    if host_header is None:
        return True
    cfg = _config()
    if cfg.allow_all:
        return True
    host = _hostname(host_header)
    if host is None:
        return False
    return _name_is_listed(host, cfg)


def _origin_host(origin: str) -> str | None:
    """The bare host of a browser Origin; None for "null" or a malformed one."""
    try:
        netloc = urlsplit(origin.strip()).netloc
    except ValueError:
        return None
    return _hostname(netloc) if netloc else None


def origin_is_allowed(origin: str | None, host_header: str | None = None) -> bool:
    """Whether a page from this browser Origin may drive the Pi.

    No Origin passes: curl, scripts, the camera and the cloud's callbacks send
    none, and browsers send one with every request that changes state. An
    Origin passes when its host is the request's own Host (the dashboard on
    whatever name it is reached by; nginx forwards Host without the port) or
    a name this allow-list admits. SPOREPRINT_ALLOWED_HOSTS's "*" switches
    the Host check off, not this one. An opaque Origin ("null": a sandboxed
    frame or a file:// page) never passes.
    """
    if origin is None:
        return True
    host = _origin_host(origin)
    if host is None:
        return False
    if host_header is not None and host == _hostname(host_header):
        return True
    return _name_is_listed(host, _config())


def socketio_origin_allowed(origin: str | None, environ: dict | None = None) -> bool:
    """python-engineio's cors_allowed_origins callable (main.sio): the same
    Origin rule for the Socket.IO handshake, so a page on another site can
    neither open the live stream nor read it."""
    return origin_is_allowed(origin, (environ or {}).get("HTTP_HOST"))


def _header_values(scope, name: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in scope.get("headers") or () if k == name]


def _host_header(scope) -> tuple[bool, str | None]:
    """(well-formed, value): two Host headers are ambiguous, so malformed."""
    values = _header_values(scope, b"host")
    if len(values) > 1:
        return False, None
    if not values:
        return True, None
    return True, values[0]


def _log_refusal(host: str | None) -> None:
    key = host if host is not None else "<duplicate Host headers>"
    if key in _logged_hosts:
        return
    if len(_logged_hosts) < _LOG_ONCE_CAP:
        _logged_hosts.add(key)
    log.warning(
        "Refused a request for Host %r (DNS-rebinding guard). If this is how "
        "you reach the Pi, add it to SPOREPRINT_ALLOWED_HOSTS.", key,
    )


async def _page_refused_camera(node_id: str, host: str) -> None:
    """Page once a day per camera, for a node id the Pi has registered (a
    LAN script inventing ids cannot page)."""
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT 1 FROM hardware_nodes WHERE node_id = ? LIMIT 1", (node_id,)
            )
            if await cursor.fetchone() is None:
                return
        await notify_warning(
            f"Camera {node_id}: frames refused",
            f"Camera {node_id} uploads its frames to the Pi as {host!r}, a name "
            "the Pi does not answer to (DNS-rebinding protection), so none are "
            "stored or analysed. Add that name to SPOREPRINT_ALLOWED_HOSTS in "
            ".env and run `docker compose up -d server`, or set the camera's "
            "Pi host to the Pi's IP address or sporeprint.local.",
            dedup_key=f"frame-host:{node_id}",
            dedup_seconds=_FRAME_REFUSAL_PAGE_SECONDS,
        )
    except Exception as e:
        log.warning("paging the refused uploads of camera %s failed: %s", node_id, e)


def _note_refused_frame_upload(scope, host: str | None) -> None:
    """A camera whose uploads are refused looks online (MQTT is not behind
    the Host check) while its frames, and the vision checks, stop."""
    node_ids = _header_values(scope, b"x-node-id")
    node_id = node_ids[0] if len(node_ids) == 1 else ""
    if host is None or not NODE_ID_RE.match(node_id):
        return
    now = time.monotonic()
    key = (node_id, host)
    last = _frame_refusals.get(key)
    if last is not None and now - last < _FRAME_REFUSAL_LOG_SECONDS:
        return
    if last is None and len(_frame_refusals) >= _FRAME_REFUSAL_CAP:
        for old in [k for k, t in _frame_refusals.items()
                    if now - t >= _FRAME_REFUSAL_LOG_SECONDS]:
            del _frame_refusals[old]
        if len(_frame_refusals) >= _FRAME_REFUSAL_CAP:
            return
    _frame_refusals[key] = now
    log.warning(
        "Refused a frame upload from camera %s for Host %r (DNS-rebinding "
        "guard): its frames are not stored. Add the name to "
        "SPOREPRINT_ALLOWED_HOSTS, or set the camera's Pi host to the Pi's IP "
        "address.", node_id, host,
    )
    task = asyncio.create_task(_page_refused_camera(node_id, host))
    _background_pages.add(task)
    task.add_done_callback(_background_pages.discard)


def _refusal_body(host: str | None) -> bytes:
    shown = "(several Host headers)" if host is None else repr(host)
    return json.dumps({
        "error": "Misdirected Request",
        "detail": (
            f"Host {shown} is not a name this SporePrint server answers to "
            "(DNS-rebinding protection). If you reach the Pi by this name, add "
            "it to SPOREPRINT_ALLOWED_HOSTS in .env and run "
            "`docker compose up -d server`."
        ),
    }).encode()


class HostAllowMiddleware:
    """Pure ASGI: refuse HTTP and websocket requests for unlisted Hosts."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and (
            scope.get("method"), scope.get("path")
        ) in _EXEMPT_ROUTES:
            return await self.app(scope, receive, send)

        well_formed, host = _host_header(scope)
        if well_formed and host_is_allowed(host):
            return await self.app(scope, receive, send)

        _log_refusal(host)
        if scope["type"] == "http" and (
            scope.get("method"), scope.get("path")
        ) == _FRAME_UPLOAD_ROUTE:
            _note_refused_frame_upload(scope, host)
        body = _refusal_body(host)
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 421, "headers": headers})
            await send({"type": "http.response.body", "body": body})
        elif "websocket.http.response" in (scope.get("extensions") or {}):
            await send({"type": "websocket.http.response.start", "status": 421,
                        "headers": headers})
            await send({"type": "websocket.http.response.body", "body": body})
        else:
            # Before accept, a close makes the server answer the handshake 403.
            await send({"type": "websocket.close", "code": 1008})


def _cross_site_refusal(scope) -> str | None:
    """Why this HTTP request is a cross-site write to refuse; None to serve it."""
    method = scope.get("method")
    origins = _header_values(scope, b"origin")
    if len(origins) > 1:
        return "it carries several Origin headers"
    origin = origins[0] if origins else None
    _, host = _host_header(scope)
    stateful_get = method in ("GET", "HEAD") and any(
        p.match(scope.get("path") or "") for p in _STATEFUL_GET_PATHS
    )
    if method not in _UNSAFE_METHODS and not stateful_get:
        return None
    if not origin_is_allowed(origin, host):
        return (f"its Origin {origin!r} is not a name this SporePrint server "
                "answers to")
    if stateful_get and origin is None:
        # An <img> or link load from another site carries no Origin.
        sites = _header_values(scope, b"sec-fetch-site")
        if sites and sites[0].strip().lower() == "cross-site":
            return "a page on another site sent it (Sec-Fetch-Site: cross-site)"
    return None


def _log_cross_site_refusal(reason: str) -> None:
    if reason in _logged_origins:
        return
    if len(_logged_origins) < _LOG_ONCE_CAP:
        _logged_origins.add(reason)
    log.warning("Refused a cross-site request: %s.", reason)


class CrossSiteRequestGuard:
    """Pure ASGI: refuse state-changing requests sent by a page on another site.

    Wrapped inside HostAllowMiddleware around Socket.IO and the FastAPI app.
    See the module docstring for the rule.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        reason = _cross_site_refusal(scope)
        if reason is None:
            return await self.app(scope, receive, send)
        _log_cross_site_refusal(reason)
        body = json.dumps({
            "error": "Forbidden",
            "detail": (
                f"Cross-site request refused: {reason}. A page that should "
                "drive the Pi from another name needs that name in "
                "SPOREPRINT_ALLOWED_HOSTS (.env, then `docker compose up -d "
                "server`)."
            ),
        }).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})
