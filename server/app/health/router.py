from fastapi import APIRouter

from .service import (
    get_client_list,
    get_clock_status,
    get_mqtt_stats,
    get_system_metrics,
    get_task_statuses,
)

router = APIRouter()


@router.get("/system")
async def system_health():
    return await get_system_metrics()


@router.get("/mqtt")
async def mqtt_health():
    # Lazy import avoids a cycle (mqtt imports health.service).
    from ..mqtt import command_signing_status

    return {**get_mqtt_stats(), "command_signing": command_signing_status()}


@router.get("/clients")
async def connected_clients():
    return get_client_list()


@router.get("/tasks")
async def background_tasks():
    return get_task_statuses()


@router.get("/clock")
async def clock_drift():
    """v3.3.3 — the Pi's wall clock and chrony tracking state
    (health.service.get_clock_status)."""
    return await get_clock_status()
