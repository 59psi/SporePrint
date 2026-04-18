import re
import time
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from ..config import settings
from .service import (
    analyze_frame_claude,
    analyze_frame_local,
    apply_user_label,
    get_active_session_id,
    get_frame_by_id,
    get_frames,
    insert_frame,
    update_analysis_claude,
    update_analysis_local,
)

router = APIRouter()

# Node IDs drive on-disk filenames — constrain the charset to what
# firmware actually uses and reject traversal payloads like `../etc/passwd`.
_NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/frame")
async def ingest_frame(
    file: UploadFile = File(...),
    x_node_id: str = Header("cam-01"),
    x_timestamp: str = Header(default=""),
    x_resolution: str = Header(default=""),
    x_flash_used: str = Header(default="1"),
):
    if not _NODE_ID_RE.match(x_node_id):
        raise HTTPException(400, "Invalid X-Node-Id (alphanumeric, _, -, max 32 chars)")

    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "Only JPEG, PNG, and WebP images are accepted")

    try:
        ts = float(x_timestamp) if x_timestamp else time.time()
    except ValueError:
        raise HTTPException(400, "Invalid X-Timestamp")

    storage = Path(settings.vision_storage).resolve()
    storage.mkdir(parents=True, exist_ok=True)

    filename = f"{x_node_id}_{int(ts)}.jpg"
    file_path = (storage / filename).resolve()
    if not file_path.is_relative_to(storage):
        raise HTTPException(400, "Invalid frame path")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 20MB)")
    file_path.write_bytes(content)

    session_id = await get_active_session_id()
    frame_id = await insert_frame(
        session_id=session_id,
        node_id=x_node_id,
        timestamp=ts,
        file_path=str(file_path),
        resolution=x_resolution,
        flash_used=int(x_flash_used),
    )

    # Run local CNN analysis (async, non-blocking).
    local_result = await analyze_frame_local(file_path)
    if local_result:
        await update_analysis_local(frame_id, local_result)

    return {
        "frame_id": frame_id,
        "file_path": str(file_path),
        "local_analysis": local_result,
    }


@router.get("/frames")
async def list_frames(
    session_id: int | None = None,
    node_id: str | None = None,
    limit: int = 50,
):
    return await get_frames(session_id=session_id, node_id=node_id, limit=limit)


@router.get("/frames/{frame_id}")
async def get_frame(frame_id: int):
    frame = await get_frame_by_id(frame_id)
    if not frame:
        raise HTTPException(404, "Frame not found")
    return frame


@router.post("/frames/{frame_id}/analyze")
async def trigger_claude_analysis(frame_id: int):
    frame = await get_frame_by_id(frame_id)
    if not frame:
        raise HTTPException(404, "Frame not found")

    result = await analyze_frame_claude(frame)
    if result:
        await update_analysis_claude(frame_id, result)

    return result


@router.post("/frames/{frame_id}/label")
async def label_frame(frame_id: int, data: dict):
    """Active learning: confirm or correct local CNN prediction."""
    label = data.get("label")
    correct = data.get("correct", True)
    if not await apply_user_label(frame_id, label, correct):
        raise HTTPException(404, "Frame not found")
    return {"status": "labeled"}
