from fastapi import APIRouter

from .service import get_cloud_status

router = APIRouter()


@router.get("/status")
async def cloud_status():
    return get_cloud_status()


@router.post("/reconnect")
async def cloud_reconnect():
    # The connector auto-reconnects; this just reports current status
    status = get_cloud_status()
    if not status["configured"]:
        return {"status": "not_configured", "message": "Set SPOREPRINT_CLOUD_URL and _TOKEN to enable"}
    return {"status": "reconnecting", "current": status}
