"""Pi-side structured logging — v3.4.9 Debt 5.

Matches the cloud's JSON log shape so an operator debugging at 3am can
grep both sides on the same `request_id`. Before this, the Pi wrote
bare stdlib lines without request correlation; cross-system diagnosis
required timestamp reconciliation across two clock sources.

Design:
 * A `ContextVar[str]` holds the per-request id (or an empty string on
   startup paths / scheduled tasks). Middleware reads the inbound
   `X-Request-ID` header; absent → generate a uuid4 hex.
 * A custom `logging.Filter` pulls the contextvar into every record so
   the JSON formatter can emit it.
 * `python-json-logger` if installed, otherwise a plain format string
   that still includes request_id. We don't hard-require the dep
   because some self-host Pi installs skip extras.
"""

from __future__ import annotations

import contextvars
import logging
import sys

# Process-wide context variable. Every coroutine scheduled from a
# request-carrying task inherits the value automatically via asyncio's
# PEP-567 support.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sporeprint_request_id", default=""
)


class _RequestIdFilter(logging.Filter):
    """Attach the current request_id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("") or "-"
        return True


def configure(level: str = "INFO") -> None:
    """Idempotent logging setup; safe to call once from the lifespan.

    Prefers python-json-logger when importable; falls back to a plain
    format including request_id. Either way, every record has an
    addressable request_id field for cross-system joins.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any handlers installed by uvicorn's default logger so we
    # don't double-emit.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())

    try:
        from pythonjsonlogger import jsonlogger  # type: ignore

        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        )
    except ImportError:  # pragma: no cover — optional dep
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s req=%(request_id)s %(message)s"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet the chattier libraries unless DEBUG explicitly requested.
    if level.upper() != "DEBUG":
        logging.getLogger("aiomqtt").setLevel(logging.WARNING)
        logging.getLogger("aiosqlite").setLevel(logging.WARNING)
        logging.getLogger("engineio").setLevel(logging.WARNING)
        logging.getLogger("socketio").setLevel(logging.WARNING)
