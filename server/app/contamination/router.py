import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import FormData, UploadFile

from ..config import settings
from ..db import UnknownReferenceError
from ..vision.service import sniff_image_media_type
from . import service
from .identify import IdentifyUpstreamError, identify_image
from .library import CONTAMINANTS
from .models import ContaminationEventCreate, RootCauseUpdate

log = logging.getLogger(__name__)

router = APIRouter()

_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
# Room for the multipart boundary, the part headers and the two id fields
# around a max-size image.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
_TOO_LARGE = "Image too large. Maximum size is 10 MB."

# The multipart body the route parses itself (see _read_identify_upload), as
# FastAPI documented it for the File/Form parameters it used to declare.
_IDENTIFY_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "session_id": {"type": "integer"},
                        "chamber_id": {"type": "integer"},
                    },
                }
            }
        },
    }
}


def _form_id(form: FormData, field: str) -> int | None:
    value = form.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise HTTPException(422, f"{field} must be an integer")
    try:
        return int(value)
    except ValueError:
        raise HTTPException(422, f"{field} must be an integer")


async def _read_identify_upload(request: Request) -> tuple[bytes, int | None, int | None]:
    """(image bytes, session_id, chamber_id) of the multipart upload, never
    reading past the 10 MB cap.

    A declared Content-Length over the cap is refused before the form is
    parsed: Starlette spools a file part to disk whatever its size, and the
    whole upload used to be read into memory before the size check (the
    server's port is reachable past nginx's body limit). A chunked body
    declares no length, so one is required. The image part is then read only
    up to the cap.
    """
    media_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if media_type != "multipart/form-data":
        raise HTTPException(422, "Upload the image as multipart/form-data with a 'file' part")
    declared = request.headers.get("content-length")
    if declared is None:
        raise HTTPException(411, "Content-Length required for the image upload")
    if not declared.strip().isdigit():
        raise HTTPException(400, "Invalid Content-Length")
    if int(declared) > _MAX_IMAGE_SIZE + _MULTIPART_OVERHEAD_BYTES:
        raise HTTPException(413, _TOO_LARGE)

    form = await request.form(max_files=1, max_fields=8)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "The upload has no 'file' part")
        content = await upload.read(_MAX_IMAGE_SIZE + 1)
        session_id = _form_id(form, "session_id")
        chamber_id = _form_id(form, "chamber_id")
    finally:
        await form.close()
    if len(content) > _MAX_IMAGE_SIZE:
        raise HTTPException(413, _TOO_LARGE)
    return content, session_id, chamber_id


@router.get("/library")
async def list_contaminants():
    """Return the full contamination reference library."""
    return CONTAMINANTS


@router.get("/library/{contaminant_id}")
async def get_contaminant(contaminant_id: str):
    """Return a single contaminant profile by ID."""
    for c in CONTAMINANTS:
        if c["id"] == contaminant_id:
            return c
    raise HTTPException(404, f"Contaminant '{contaminant_id}' not found")


@router.post("/identify", openapi_extra=_IDENTIFY_BODY)
async def identify_contamination(request: Request):
    """Upload an image (multipart `file`, optional `session_id` /
    `chamber_id` fields) for Claude Vision contamination identification.

    On a positive detection the result is also persisted as a
    `source='identify'` contamination event (linked to session_id/chamber_id
    when supplied). The response contract is unchanged.
    """
    if not settings.claude_api_key:
        raise HTTPException(503, "Claude API key not configured")

    content, session_id, chamber_id = await _read_identify_upload(request)

    # The bytes decide the type: the Messages API accepts only JPEG/PNG/GIF/WebP
    # and rejects a declared media_type that doesn't match the image. A HEIC
    # phone photo or unknown blob gets a clear 415 instead of an opaque 502.
    media_type = sniff_image_media_type(content)
    if media_type is None:
        raise HTTPException(
            415, "Unsupported image type. Upload a JPEG, PNG, WebP or GIF image."
        )
    # Before the paid call: an unknown session or chamber could not be linked.
    try:
        await service.check_event_references(session_id=session_id, chamber_id=chamber_id)
    except UnknownReferenceError as e:
        raise HTTPException(422, str(e))

    try:
        return await identify_image(
            content, media_type, session_id=session_id, chamber_id=chamber_id,
        )
    except IdentifyUpstreamError as e:
        log.error("Contamination identification failed: %s", e)
        raise HTTPException(502, f"Contamination identification failed: {e}")
    except Exception as e:
        log.error("Contamination identification failed: %s", e)
        raise HTTPException(500, f"Contamination identification failed: {e}")


@router.get("/events")
async def list_contamination_events(
    session_id: int | None = None, chamber_id: int | None = None, limit: int = 200
):
    """Newest-first contamination event log (backs the page's gallery)."""
    return await service.list_events(
        session_id=session_id, chamber_id=chamber_id, limit=limit
    )


@router.post("/events")
async def create_contamination_event(data: ContaminationEventCreate):
    """Manually log a contamination event (the page's manual-mark flow)."""
    try:
        return await service.create_manual_event(data)
    except UnknownReferenceError as e:
        raise HTTPException(422, str(e))


@router.post("/events/{event_id}/root-cause")
async def record_root_cause(event_id: int, data: RootCauseUpdate):
    """Stamp a root-cause analysis onto an event (the RCA form)."""
    updated = await service.set_root_cause(event_id, data.root_cause)
    if not updated:
        raise HTTPException(404, "Contamination event not found")
    return updated
