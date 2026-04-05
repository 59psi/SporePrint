import time

from fastapi import APIRouter, Query

from .service import get_latest, get_history, store_bulk_readings

router = APIRouter()


@router.get("/latest")
async def latest_readings(node_id: str | None = None):
    return await get_latest(node_id)


@router.get("/history")
async def reading_history(
    node_id: str = Query(...),
    sensor: str = Query(...),
    from_ts: float | None = None,
    to_ts: float | None = None,
    resolution: str | None = None,
):
    return await get_history(node_id, sensor, from_ts, to_ts, resolution)


@router.post("/ingest")
async def manual_ingest(data: dict):
    node_id = data.pop("node_id", "manual")
    ts = data.pop("ts", None) or time.time()
    await store_bulk_readings(node_id, data, ts)
    return {"status": "ok"}
