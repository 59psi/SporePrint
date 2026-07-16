"""API router for user-configurable settings."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import settings_service, system_actions

router = APIRouter()


class SettingUpdate(BaseModel):
    value: str


class SetupStatusUpdate(BaseModel):
    setup_complete: bool


class HostnameUpdate(BaseModel):
    hostname: str


@router.get("")
async def get_settings():
    return await settings_service.get_all_settings()


@router.get("/setup-status")
async def get_setup_status():
    """Pi UI calls this at boot; redirects to /setup when false so the
    operator never sees a half-configured fleet view."""
    value = await settings_service.get_setting("setup_complete")
    return {"setup_complete": value == "1"}


@router.post("/setup-status")
async def set_setup_status(body: SetupStatusUpdate):
    new_value = "1" if body.setup_complete else "0"
    await settings_service.set_setting("setup_complete", new_value)
    return {"setup_complete": body.setup_complete}


# ── System actions (LAN-only, same trust model as every other route) ──
# NOTE: these fixed paths MUST be registered before the /{key} catch-alls
# below, or PUT /hostname would be swallowed by update_setting.


@router.post("/system/reboot")
async def system_reboot():
    """Reboot the Pi after a short grace so this response flushes first."""
    return system_actions.schedule_reboot()


@router.post("/system/restart-broker")
async def system_restart_broker():
    """Restart the mosquitto broker (immediate — doesn't kill the API)."""
    try:
        system_actions.restart_broker()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok"}


@router.get("/system/hostname")
async def get_hostname():
    return {"hostname": system_actions.get_hostname()}


@router.put("/hostname")
async def set_hostname(body: HostnameUpdate):
    try:
        return system_actions.set_hostname(body.hostname)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{key}")
async def update_setting(key: str, body: SettingUpdate):
    try:
        return await settings_service.set_setting(key, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{key}")
async def delete_setting(key: str):
    try:
        return await settings_service.delete_setting(key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
