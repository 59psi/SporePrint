import json

from fastapi import APIRouter, HTTPException

from ..db import get_db
from ..mqtt import mqtt_publish

router = APIRouter()


@router.get("/nodes")
async def list_nodes():
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes ORDER BY last_seen DESC")
        return [dict(r) for r in await cursor.fetchall()]


@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes WHERE node_id = ?", (node_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Node not found")
        return dict(row)


@router.post("/nodes/{node_id}/command")
async def send_command(node_id: str, command: dict):
    topic = command.pop("topic", f"sporeprint/{node_id}/cmd/config")
    await mqtt_publish(topic, command)
    return {"status": "sent", "topic": topic}
