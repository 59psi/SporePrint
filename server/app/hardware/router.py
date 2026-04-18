import re

from fastapi import APIRouter, HTTPException

from ..db import get_db
from ..mqtt import mqtt_publish

router = APIRouter()

# Path segments must stay inside the per-node namespace. A caller that set
# `topic: "sporeprint/OTHER_NODE/cmd/heater"` previously bypassed it entirely.
_NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_CHANNEL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


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
    if not _NODE_ID_RE.match(node_id):
        raise HTTPException(400, "Invalid node_id")
    # Drop any caller-supplied `topic` — it is an old attack surface.
    command.pop("topic", None)
    channel = command.pop("channel", None) or "config"
    if not _CHANNEL_RE.match(str(channel)):
        raise HTTPException(400, "Invalid channel")
    topic = f"sporeprint/{node_id}/cmd/{channel}"
    await mqtt_publish(topic, command)
    return {"status": "sent", "topic": topic}
