"""API router for user-configurable settings."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import settings_service

router = APIRouter()


class SettingUpdate(BaseModel):
    value: str


class SetupStatusUpdate(BaseModel):
    setup_complete: bool


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
