from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..db import get_db
from . import ota_push
from .coredumps import dump_path, list_dumps
from .discovery import ReservedNodeIdError, claim_node, list_discovered_nodes
from .node_manifest import (
    MAX_NODE_MANIFEST_BYTES,
    NodeManifestError,
    check_node_manifest,
)
from .service import (
    NODE_ID_RE,
    get_node as service_get_node,
    list_nodes as service_list_nodes,
    peripherals_command,
    publish_node_command,
    send_command,
)

router = APIRouter()

_NOT_PUBLISHED = (
    "Command not published — MQTT broker unavailable, or command "
    "signing is enforced and SPOREPRINT_MQTT_HMAC_KEY is unset "
    "(see GET /api/health/detail/mqtt)"
)


# ─── LAN discovery + claim (H2-1) ───────────────────────────────

@router.get("/discover")
async def discover_nodes():
    """Nodes the Pi has heard from on the LAN, each tagged claimed/unclaimed.

    Backed by the heartbeat-populated `hardware_nodes` registry — that
    heartbeat is the firmware's LAN-presence signal (see discovery.py).
    """
    return {"nodes": await list_discovered_nodes()}


@router.post("/claim")
async def claim_node_route(body: dict):
    """Adopt an unclaimed, heartbeat-known node. Body: {"node_id": "..."}."""
    node_id = (body or {}).get("node_id")
    if not node_id or not NODE_ID_RE.match(str(node_id)):
        raise HTTPException(400, "Invalid or missing node_id")
    try:
        claimed = await claim_node(str(node_id))
    except ReservedNodeIdError as e:
        raise HTTPException(400, str(e))
    if not claimed:
        raise HTTPException(404, "Node not found — only heartbeat-known nodes can be claimed")
    return {"status": "claimed", "node_id": node_id}


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
        topic, published = await send_command(node_id, command)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not published:
        raise HTTPException(503, _NOT_PUBLISHED)
    return {"status": "sent", "topic": topic}


@router.post("/nodes/{node_id}/peripherals")
async def set_node_peripherals(node_id: str, peripherals: dict):
    """Enable/disable a node's optional peripherals without a factory reset.

    Body: any of {"mhz19": bool, "hx711": bool, "reed": bool,
    "reed_inv": bool}. Sent as the signed cmd/config {"peripherals": {...}}.
    A node whose driver set (mhz19/hx711/reed) changes saves it and reboots
    about 1.5 s later; reed_inv (door contact wired on its NO lead) is saved
    and applied live, without a reboot.
    """
    if not NODE_ID_RE.match(node_id):
        raise HTTPException(400, "Invalid node_id")
    try:
        command = peripherals_command(peripherals)
    except ValueError as e:
        raise HTTPException(422, str(e))
    topic, published = await send_command(node_id, {"channel": "config", **command})
    if not published:
        raise HTTPException(503, _NOT_PUBLISHED)
    return {"status": "sent", "topic": topic, **command}


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


@router.post("/nodes/{node_id}/ota", status_code=202)
async def push_node_firmware(
    node_id: str,
    file: UploadFile = File(...),
    password: str = Form(...),
    port: int = Form(ota_push.DEFAULT_OTA_PORT),
    manifest: UploadFile | None = File(None),
    manifest_sig: UploadFile | None = File(None),
):
    """Push a firmware .bin to an ESP32 node via the espota protocol (v4.2).

    The node's ArduinoOTA password is supplied per request and never
    stored or logged. The transfer runs in the background — poll
    GET .../ota for the Pi-side outcome; the node's own lifecycle arrives
    as node_ota MQTT events.

    Optional ``manifest`` + ``manifest_sig``: the release's signed manifest
    for this image (``{env}.manifest.json`` + ``.sig``). Verified here
    against the pinned OTA key and the uploaded bytes, then handed to the
    node so it flashes only this exact image (hardware/node_manifest.py).
    """
    if not NODE_ID_RE.match(node_id):
        raise HTTPException(400, "Invalid node_id")
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Invalid port")
    if not (file.filename or "").lower().endswith(".bin"):
        raise HTTPException(400, "Firmware image must be a .bin file")
    node = await service_get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if not node.get("ip_address"):
        raise HTTPException(400, "Node has no known IP address")
    image = await file.read(ota_push.MAX_UPLOAD_BYTES + 1)
    if len(image) > ota_push.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Firmware image exceeds the 16 MB cap")
    if not image:
        raise HTTPException(400, "Firmware image is empty")
    signed = None
    if manifest is not None or manifest_sig is not None:
        if manifest is None or manifest_sig is None:
            raise HTTPException(400, "manifest and manifest_sig go together")
        try:
            signed = check_node_manifest(
                await manifest.read(MAX_NODE_MANIFEST_BYTES + 1),
                await manifest_sig.read(128),
                image, node.get("firmware_version"))
        except NodeManifestError as e:
            raise HTTPException(400, f"Signed manifest refused: {e}") from None
    # No await between this check and start_push — the check-and-set is
    # atomic on the event loop, so concurrent POSTs cannot both start.
    if ota_push.is_running(node_id):
        raise HTTPException(409, "An OTA push to this node is already running")
    ota_push.start_push(node_id, node["ip_address"], port, password, image,
                        manifest=signed,
                        send_command=publish_node_command if signed else None)
    return {"status": "started", "node_id": node_id}


@router.get("/nodes/{node_id}/ota")
async def get_node_ota_status(node_id: str):
    """Pi-side status of the most recent espota push to this node.

    Covers the failures that never reach MQTT (wrong password, node
    unreachable, stalled transfer): state idle|running|ok|error + message
    + timestamps + byte progress.
    """
    if not NODE_ID_RE.match(node_id):
        raise HTTPException(400, "Invalid node_id")
    if not await service_get_node(node_id):
        raise HTTPException(404, "Node not found")
    return ota_push.get_status(node_id)


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
