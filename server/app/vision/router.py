import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from ..config import settings
from ..db import get_db
from .service import analyze_frame_local, analyze_frame_claude, get_frames

router = APIRouter()

# Node IDs drive on-disk filenames — constrain the charset to what
# firmware actually uses and reject traversal payloads like `../etc/passwd`.
_NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


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
    if len(content) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(413, "File too large (max 20MB)")
    file_path.write_bytes(content)

    # Get active session
    session_id = None
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row:
            session_id = row["id"]

        # Store frame record
        cursor = await db.execute(
            """INSERT INTO vision_frames (session_id, node_id, timestamp, file_path, resolution, flash_used)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, x_node_id, ts, str(file_path), x_resolution, int(x_flash_used)),
        )
        frame_id = cursor.lastrowid
        await db.commit()

    # Run local CNN analysis (async, non-blocking)
    local_result = await analyze_frame_local(file_path)
    if local_result:
        async with get_db() as db:
            await db.execute(
                "UPDATE vision_frames SET analysis_local = ? WHERE id = ?",
                (json.dumps(local_result), frame_id),
            )
            await db.commit()

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
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM vision_frames WHERE id = ?", (frame_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Frame not found")
        return dict(row)


@router.post("/frames/{frame_id}/analyze")
async def trigger_claude_analysis(frame_id: int):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM vision_frames WHERE id = ?", (frame_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Frame not found")
        frame = dict(row)

    result = await analyze_frame_claude(frame)
    if result:
        async with get_db() as db:
            await db.execute(
                "UPDATE vision_frames SET analysis_claude = ? WHERE id = ?",
                (json.dumps(result), frame_id),
            )
            await db.commit()

    return result


@router.post("/frames/{frame_id}/label")
async def label_frame(frame_id: int, data: dict):
    """Active learning: confirm or correct local CNN prediction."""
    label = data.get("label")
    correct = data.get("correct", True)
    async with get_db() as db:
        cursor = await db.execute("SELECT analysis_local FROM vision_frames WHERE id = ?", (frame_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Frame not found")

        local = json.loads(row["analysis_local"]) if row["analysis_local"] else {}
        local["user_label"] = label
        local["user_confirmed"] = correct
        await db.execute(
            "UPDATE vision_frames SET analysis_local = ? WHERE id = ?",
            (json.dumps(local), frame_id),
        )
        await db.commit()
    return {"status": "labeled"}
