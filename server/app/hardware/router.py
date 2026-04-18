from fastapi import APIRouter, HTTPException

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
