"""Validation for caller-supplied vendor addresses and IDs.

Vendor write actions (``/api/integrations/{slug}/actions/*``, the cloud
``vendor_action`` RPC, automation vendor rules) take device IPs and IDs from
the request body and interpolate them into URLs. Without validation a value
like ``10.0.0.5:80/latest#`` or ``../../admin/users?x=`` rewrites the request
target — the latter with the operator's vendor bearer token attached (httpx
normalises dot segments).

These helpers accept exactly one host (optionally ``:port``) or one path
segment, and raise ``ValueError`` otherwise; the action dispatcher maps that
to HTTP 400.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import quote


# RFC 1123-ish hostname, leniently allowing "_" (seen on some LAN DNS).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
    r"(?:\.[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?)*\.?$"
)

# One URL path segment. Covers numeric, UUID, slug and MAC-style vendor IDs.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.:~-]{1,128}$")


def split_host_port(value: object, *, field: str = "ip") -> tuple[str, int | None]:
    """Validate ``host`` or ``host:port`` and return ``(host, port|None)``.

    ``host`` is an IPv4/IPv6 literal or a DNS hostname. Anything carrying a
    path, query, fragment, userinfo or whitespace is rejected.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    value = value.strip()
    host, port = value, None
    # Bare IPv6 literals contain several colons; exactly one colon is host:port.
    if value.count(":") == 1:
        host, _, port_s = value.partition(":")
        if not port_s.isdigit() or not 1 <= int(port_s) <= 65535:
            raise ValueError(f"{field}: invalid port in {value!r}")
        port = int(port_s)
    elif value.startswith("[") and "]" in value:
        inner, _, rest = value[1:].partition("]")
        host = inner
        if rest:
            if not rest.startswith(":") or not rest[1:].isdigit() or not 1 <= int(rest[1:]) <= 65535:
                raise ValueError(f"{field}: invalid port in {value!r}")
            port = int(rest[1:])
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME_RE.match(host):
            raise ValueError(f"{field}: {value!r} is not a host or IP address") from None
    return host, port


def url_host(host: str) -> str:
    """Host as it must appear in a URL authority (IPv6 literals bracketed)."""
    try:
        if ipaddress.ip_address(host).version == 6:
            return f"[{host}]"
    except ValueError:
        pass
    return host


def path_segment(value: object, *, field: str) -> str:
    """Validate a vendor ID used as one URL path segment; return it encoded.

    Numeric IDs (e.g. Nexia thermostat ids arriving as JSON numbers) are
    accepted and stringified; booleans are not IDs.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field} must be a string or integer id")
    text = str(value).strip()
    if not _SEGMENT_RE.match(text) or text in (".", ".."):
        raise ValueError(f"{field}: {text!r} is not a valid id")
    return quote(text, safe=":~")
