"""FastAPI middleware that populates logging_config.request_id_var.

Reads X-Request-ID inbound; generates a uuid4 hex if missing. Echoes
the id back on the response so clients can cross-reference with the
cloud's logs. Mirrors cloud/app/_request_context.py's contract — the
two systems use the same header name and the same log field name so a
grep on one side finds correlated records on the other.
"""

from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging_config import request_id_var

_RID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or ""
        if not rid or not _RID_RE.match(rid):
            rid = uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(token)
