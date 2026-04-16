"""API router for user-configurable settings."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import settings_service

router = APIRouter()


class SettingUpdate(BaseModel):
    value: str


@router.get("")
async def get_settings():
    """Return all configurable settings with current values and source."""
    try:
        return await settings_service.get_all_settings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {e}")


@router.put("/{key}")
async def update_setting(key: str, body: SettingUpdate):
    """Update a single setting. Returns all settings after update."""
    try:
        return await settings_service.set_setting(key, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save setting: {e}")


@router.delete("/{key}")
async def delete_setting(key: str):
    """Remove a user override, reverting to env/default."""
    try:
        return await settings_service.delete_setting(key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete setting: {e}")
