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
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from functools import lru_cache
from typing import NamedTuple
from urllib.parse import urlsplit

from .config import settings

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
    ip = _as_ip(host)
    if ip is not None:
        return any(ip in net for net in (*_PRIVATE_NETWORKS, *cfg.networks)
                   if net.version == ip.version)
    if "." not in host or host == "localhost" or host in cfg.names:
        return True
    return host.endswith(_PRIVATE_SUFFIXES + cfg.suffixes)


def _host_header(scope) -> tuple[bool, str | None]:
    """(well-formed, value): two Host headers are ambiguous, so malformed."""
    values = [v for k, v in scope.get("headers") or () if k == b"host"]
    if len(values) > 1:
        return False, None
    if not values:
        return True, None
    return True, values[0].decode("latin-1")


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
