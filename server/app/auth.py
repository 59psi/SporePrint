"""Bearer-token auth gate for /api/* and Socket.IO.

Enabled when `SPOREPRINT_API_KEY` is set. When unset (dev mode) all requests
pass through — the LAN-scoped CORS middleware remains the only gate.

Whitelist of always-public paths:
- `/api/health`        — the UI's existence probe must work before auth is set up
- `/api/cloud/pairing-code` (GET) — displayed in the web UI for an operator who is about to pair
- `/api/cloud/pair`    — pairing handshake (code + lockout is the gate here)

Everything else requires `Authorization: Bearer <SPOREPRINT_API_KEY>`.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

log = logging.getLogger(__name__)

_PUBLIC_PATHS = frozenset({
    "/api/health",
    "/api/cloud/pair",
    "/api/cloud/pairing-code",
})


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

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # CORS preflight never carries auth — let it through so the browser
        # can see the allowed headers.
        if request.method == "OPTIONS":
            return await call_next(request)

        if path in _PUBLIC_PATHS:
            return await call_next(request)

        presented = _extract_bearer(request.headers.get("authorization"))
        if not _valid_token(presented):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)


def socketio_auth_ok(auth: dict | None) -> bool:
    """Callback used by the Socket.IO connect handler."""
    if not settings.api_key:
        return True
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    return _valid_token(token)
