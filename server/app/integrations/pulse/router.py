"""Pulse-specific routes that complement the unified
/api/integrations/pulse/{config,test,enable,disable} endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import _registry
from .client import PulseCloudClient, PulseError


router = APIRouter()


def _driver():
    drv = _registry.registered_drivers().get("pulse")
    if drv is None:
        raise HTTPException(503, "pulse driver not registered")
    return drv


@router.get("/devices")
async def list_devices_for_mapping():
    """Live device-list scan for the settings UI's mapping table.

    Uses the *staged* config so the operator can preview their account's
    devices before flipping the driver enabled. Returns 400 if creds
    are not yet saved, 502 on Pulse-side errors.
    """
    drv = _driver()
    cfg = drv.config
    if not cfg.email or not cfg.password:
        raise HTTPException(400, "configure email and password first")
    client = PulseCloudClient(
        cfg.email,
        cfg.password,
        timeout_s=cfg.request_timeout_seconds,
    )
    try:
        await client.login()
        devices = await client.list_devices()
    except PulseError as exc:
        raise HTTPException(502, str(exc))
    return {
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "type": d.type,
                "mapped_to_chamber": cfg.device_mappings.get(d.id),
            }
            for d in devices.devices
        ],
    }
