from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_db
from .coredumps import dump_path, list_dumps
from .service import (
    NODE_ID_RE,
    get_node as service_get_node,
    list_nodes as service_list_nodes,
    send_command,
)

router = APIRouter()


@router.get("/nodes")
async def list_nodes():
    return await service_list_nodes()


@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    node = await service_get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node


@router.post("/nodes/{node_id}/command")
async def post_command(node_id: str, command: dict):
    if not NODE_ID_RE.match(node_id):
        raise HTTPException(400, "Invalid node_id")
    try:
        topic = await send_command(node_id, command)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "sent", "topic": topic}


@router.get("/nodes/{node_id}/logs")
async def get_node_logs(node_id: str, limit: int = 200):
    """Recent firmware log entries forwarded over MQTT (v4.2)."""
    if not NODE_ID_RE.match(node_id):
        raise HTTPException(400, "Invalid node_id")
    limit = max(1, min(limit, 1000))
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT ts_ms, level, msg, received_at FROM node_logs "
            "WHERE node_id = ? ORDER BY id DESC LIMIT ?",
            (node_id, limit),
        )
        rows = await cursor.fetchall()
    return {"node_id": node_id,
            "entries": [dict(r) for r in rows]}


@router.get("/coredumps")
async def get_coredumps():
    """Reassembled firmware panic dumps (v4.2). Decode offline with
    espcoredump.py + the matching firmware ELF."""
    return {"dumps": list_dumps()}


@router.get("/coredumps/{filename}")
async def download_coredump(filename: str):
    p = dump_path(filename)
    if p is None:
        raise HTTPException(404, "Dump not found")
    return FileResponse(p, media_type="application/octet-stream",
                        filename=p.name)
