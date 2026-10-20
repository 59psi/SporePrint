import math
import time

from fastapi import APIRouter, HTTPException, Query

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
    if not isinstance(node_id, str) or not node_id:
        raise HTTPException(422, "node_id must be a non-empty string")
    ts = data.pop("ts", None)
    if ts is None:
        ts = time.time()
    # A string or NaN ts was stored as is: TEXT sorts above every REAL, so
    # that row read as the node's newest reading for good.
    elif not _finite_number(ts):
        raise HTTPException(422, "ts must be a finite number (Unix seconds)")
    await store_bulk_readings(node_id, data, float(ts))
    return {"status": "ok"}


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an integer too large for a float
        return False
