"""Aranet-specific routes that complement the unified
/api/integrations/aranet/{config,test,enable,disable} endpoints from the
registry.

Adds:
  - GET /api/integrations/aranet/discover
      Live PRO base-station scan. Returns the sensor list with raw
      measurements so the settings UI can populate the
      sensor-id → chamber-id mapping table without committing config.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import _registry
from .client import AranetClient, AranetError


router = APIRouter()


def _driver():
    drv = _registry.registered_drivers().get("aranet")
    if drv is None:
        raise HTTPException(503, "aranet driver not registered")
    return drv


@router.get("/discover")
async def discover():
    """Probe the configured PRO base station and list sensors.

    Uses the *staged* config (whatever the operator most recently saved)
    so the UI can surface a live preview without enabling the driver
    full-time. If config is incomplete, returns 400 with a clear error
    instead of an opaque transport failure.
    """
    drv = _driver()
    cfg = drv.config
    if not cfg.base_url or not cfg.api_key:
        raise HTTPException(400, "configure base_url and api_key first")
    client = AranetClient(
        cfg.base_url, cfg.api_key, timeout_s=cfg.request_timeout_seconds
    )
    try:
        response = await client.fetch_latest()
    except AranetError as exc:
        raise HTTPException(502, str(exc))
    return {
        "sensors": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "measurement_types": [m.type for m in s.measurements],
                "mapped_to_chamber": cfg.sensor_mappings.get(s.id),
            }
            for s in response.sensors
        ],
    }
