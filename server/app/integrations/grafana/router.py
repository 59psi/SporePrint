"""`/metrics` route handler.

Mounted *outside* the `/api/*` namespace so the API-key middleware does
not gate it (Prometheus convention is unauthenticated on the LAN). An
optional bearer-token check inside the handler covers the Tailscale →
Grafana-Cloud case where the operator wants a soft auth gate without
exposing the same key as the rest of the Pi API.

The route returns 404 when the driver is disabled, so `/metrics`
appearing only when the operator opts in matches the principle of least
surface.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Response

from ...auth import _extract_bearer, token_matches
from ...cloud.version import server_version
from .exporter import collect_samples


logger = logging.getLogger(__name__)
router = APIRouter()


# Prometheus expects exactly this content-type. `prometheus_client`
# exports `CONTENT_TYPE_LATEST` for it; we hard-code the string so a
# major version bump in the library can't silently break the contract.
PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _import_driver():
    # Lazy to avoid a registry-time circular when the package's __init__
    # registers the driver.
    from .. import _registry

    drv = _registry.registered_drivers().get("grafana")
    if drv is None:
        # Defensive — should never happen because the package __init__
        # registers on import.
        raise HTTPException(503, "grafana driver not registered")
    return drv


@router.get("/metrics")
async def metrics(authorization: str | None = Header(default=None)) -> Response:
    drv = _import_driver()
    if not drv.enabled:
        # 404 instead of 503 so the operator can verify the route shape
        # exists but the driver is off — Prometheus treats both as
        # "scrape failed" but the operator-facing message is clearer.
        raise HTTPException(404, "grafana exporter disabled")

    cfg = drv.config
    # The API bearer gate's own parsing and constant-time comparison
    # (app.auth): a missing, wrong or odd token is a 401, never a 500.
    if cfg.bearer_token and not token_matches(
        _extract_bearer(authorization), cfg.bearer_token
    ):
        raise HTTPException(401, "invalid bearer token")

    try:
        # The running server's version (cached; the image installs only the
        # dependencies, so package metadata alone reads "unknown").
        payload = await collect_samples(cfg, version=server_version())
    except Exception as exc:  # noqa: BLE001
        drv.record_scrape(False, str(exc))
        logger.exception("grafana exporter: scrape failed")
        raise HTTPException(500, f"exporter error: {exc}")

    drv.record_scrape(True)
    return Response(content=payload, media_type=PROM_CONTENT_TYPE)
