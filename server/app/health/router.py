from fastapi import APIRouter

from .service import get_system_metrics, get_mqtt_stats, get_client_list, get_task_statuses

router = APIRouter()


@router.get("/system")
async def system_health():
    return await get_system_metrics()


@router.get("/mqtt")
async def mqtt_health():
    return get_mqtt_stats()


@router.get("/clients")
async def connected_clients():
    return get_client_list()


@router.get("/tasks")
async def background_tasks():
    return get_task_statuses()
