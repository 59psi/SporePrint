import secrets
import time

from fastapi import APIRouter, HTTPException

from .service import get_cloud_status

router = APIRouter()

# In-memory pairing code (single Pi, single code at a time)
_pairing_code: dict | None = None


@router.get("/status")
async def cloud_status():
    return get_cloud_status()


@router.post("/reconnect")
async def cloud_reconnect():
    status = get_cloud_status()
    if not status["configured"]:
        return {"status": "not_configured", "message": "Set SPOREPRINT_CLOUD_URL and _TOKEN to enable"}
    return {"status": "reconnecting", "current": status}


@router.post("/pairing-code")
async def generate_pairing_code():
    """Generate a 6-digit pairing code valid for 10 minutes."""
    global _pairing_code
    code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
    _pairing_code = {
        "code": code,
        "created_at": time.time(),
        "expires_at": time.time() + 600,  # 10 minutes
    }
    return {"code": code, "expires_in": 600}


@router.get("/pairing-code")
async def get_pairing_code():
    """Get the current pairing code (for the Pi's web UI settings page)."""
    if not _pairing_code:
        return {"code": None, "expired": True}
    if time.time() > _pairing_code["expires_at"]:
        return {"code": None, "expired": True}
    remaining = int(_pairing_code["expires_at"] - time.time())
    return {"code": _pairing_code["code"], "expires_in": remaining}


@router.post("/pair")
async def pair_device(data: dict):
    """Validate pairing code from mobile app. Returns device info if valid."""
    global _pairing_code
    code = data.get("code", "")

    if not _pairing_code:
        raise HTTPException(400, "No pairing code active. Generate one from the Pi's settings page.")
    if time.time() > _pairing_code["expires_at"]:
        _pairing_code = None
        raise HTTPException(400, "Pairing code expired. Generate a new one.")
    if code != _pairing_code["code"]:
        raise HTTPException(400, "Invalid pairing code.")

    # Code is valid — return device info for the mobile app to store
    from ..config import settings
    _pairing_code = None  # one-time use

    return {
        "success": True,
        "device": {
            "cloud_device_id": settings.cloud_device_id or secrets.token_hex(16),
            "name": "SporePrint Pi",
            "firmware_version": "0.3.0",
        },
    }


@router.post("/configure")
async def configure_cloud(data: dict):
    """Receive cloud credentials from mobile app after pairing.
    Writes them to .env so they persist across restarts."""
    import os
    from pathlib import Path

    device_id = data.get("cloud_device_id", "")
    token = data.get("device_token", "")
    cloud_url = data.get("cloud_url", "")

    if not device_id or not token:
        raise HTTPException(400, "Missing cloud_device_id or device_token")

    # Write to .env file
    env_path = Path(".env")
    env_content = env_path.read_text() if env_path.exists() else ""

    updates = {
        "SPOREPRINT_CLOUD_DEVICE_ID": device_id,
        "SPOREPRINT_CLOUD_TOKEN": token,
    }
    if cloud_url:
        updates["SPOREPRINT_CLOUD_URL"] = cloud_url

    for key, value in updates.items():
        if f"{key}=" in env_content:
            lines = env_content.split("\n")
            env_content = "\n".join(
                f"{key}={value}" if line.startswith(f"{key}=") else line
                for line in lines
            )
        else:
            env_content += f"\n{key}={value}"

    env_path.write_text(env_content)

    return {"status": "configured", "message": "Cloud credentials saved. Restart to connect."}
