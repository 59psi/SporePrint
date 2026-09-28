import re
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile

from ..config import settings
from .service import (
    analyze_frame_claude,
    analyze_frame_local,
    apply_user_label,
    frame_storage_name,
    get_active_session_id,
    get_frame_by_id,
    get_frames,
    insert_frame,
    maybe_schedule_auto_analysis,
    maybe_schedule_vision_prune,
    resolve_frame_timestamp,
    sniff_image_media_type,
    update_analysis_claude,
    update_analysis_local,
)

router = APIRouter()

# Node IDs drive on-disk filenames — constrain the charset to what
# firmware actually uses and reject traversal payloads like `../etc/passwd`.
_NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_ACCEPTED_MEDIA = ("image/jpeg", "image/png", "image/webp")


@router.post("/frame")
async def ingest_frame(
    request: Request,
    # Optional, NOT required. The ESP32-CAM firmware POSTs the JPEG as a raw
    # `image/jpeg` body (esp_http_client has no multipart encoder), so a
    # required File(...) made FastAPI reject every camera frame with a 422
    # before this function ever ran — the vision pipeline had never ingested a
    # single firmware frame. Multipart stays supported for the web UI + tests.
    file: UploadFile | None = File(None),
    x_node_id: str = Header("cam-01"),
    x_timestamp: str = Header(default=""),
    x_resolution: str = Header(default=""),
    x_flash_used: str = Header(default="1"),
):
    if not _NODE_ID_RE.match(x_node_id):
        raise HTTPException(400, "Invalid X-Node-Id (alphanumeric, _, -, max 32 chars)")

    if file is not None:
        media_type = (file.content_type or "").split(";")[0].strip().lower()
        content = await file.read()
    else:
        media_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        content = await request.body()

    if media_type not in _ACCEPTED_MEDIA:
        raise HTTPException(415, "Only JPEG, PNG, and WebP images are accepted")
    if not content:
        raise HTTPException(400, "Empty frame body")

    # Unsynced cams (missing / uptime-based X-Timestamp) get arrival time.
    try:
        ts = resolve_frame_timestamp(x_timestamp)
    except ValueError:
        raise HTTPException(400, "Invalid X-Timestamp")

    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 20MB)")

    storage = Path(settings.vision_storage).resolve()
    storage.mkdir(parents=True, exist_ok=True)

    # Keep the real image type (bytes win over the header) so the extension —
    # and the media_type later declared to Claude — match the content.
    stored_type = sniff_image_media_type(content) or media_type
    for _ in range(3):
        file_path = (storage / frame_storage_name(x_node_id, ts, stored_type)).resolve()
        if not file_path.is_relative_to(storage):
            raise HTTPException(400, "Invalid frame path")
        try:
            with file_path.open("xb") as fh:  # exclusive: never overwrite a frame
                fh.write(content)
            break
        except FileExistsError:
            continue
    else:
        raise HTTPException(500, "Could not allocate a unique frame filename")

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

    # H4-1: the local CNN above is a permanent stub, so kick the real Claude
    # detector on ingest to actually catch contamination / harvest windows.
    # Cost-gated (BYOK key present + active session + per-session throttle) and
    # non-blocking — it runs in the background and routes any detection through
    # the existing alert + cloud-forward plumbing, so the response returns now.
    await maybe_schedule_auto_analysis(
        frame_id=frame_id,
        session_id=session_id,
        node_id=x_node_id,
        file_path=str(file_path),
    )
    # Thin frames past the retention window (throttled, background).
    await maybe_schedule_vision_prune()

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
    # Persist only a real analysis: analyze_frame_claude returns a truthy
    # {"error": ...} on failure (no key, rate limit), which used to overwrite
    # the frame's previous good analysis. The error is still returned so the
    # UI can show it.
    if isinstance(result, dict) and result and "error" not in result:
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
