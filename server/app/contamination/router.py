import base64
import logging

import anthropic
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import settings
from ..vision.service import (
    CLAUDE_MAX_TOKENS,
    claude_response_text,
    claude_stop_reason,
    parse_claude_json,
    sniff_image_media_type,
)
from . import service
from .library import CONTAMINANTS, IDENTIFICATION_SYSTEM_PROMPT
from .models import ContaminationEventCreate, RootCauseUpdate

log = logging.getLogger(__name__)

router = APIRouter()

_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


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


@router.post("/identify")
async def identify_contamination(
    file: UploadFile = File(...),
    session_id: int | None = Form(None),
    chamber_id: int | None = Form(None),
):
    """Upload an image for Claude Vision contamination identification.

    On a positive detection the result is also persisted as a
    `source='identify'` contamination event (linked to session_id/chamber_id
    when supplied). The response contract is unchanged.
    """
    if not settings.claude_api_key:
        raise HTTPException(503, "Claude API key not configured")

    content = await file.read()

    if len(content) > _MAX_IMAGE_SIZE:
        raise HTTPException(
            413, f"Image too large ({len(content)} bytes). Maximum size is 10 MB."
        )

    # The bytes decide the type: the Messages API accepts only JPEG/PNG/GIF/WebP
    # and rejects a declared media_type that doesn't match the image. A HEIC
    # phone photo or unknown blob gets a clear 415 instead of an opaque 502.
    media_type = sniff_image_media_type(content)
    if media_type is None:
        raise HTTPException(
            415, "Unsupported image type. Upload a JPEG, PNG, WebP or GIF image."
        )
    image_data = base64.standard_b64encode(content).decode("utf-8")

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)
        message = await client.messages.create(
            model=settings.claude_model,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=IDENTIFICATION_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyze this mushroom cultivation image for contamination. Respond with JSON only.",
                        },
                    ],
                }
            ],
        )

        stop_reason = claude_stop_reason(message)
        if stop_reason == "refusal":
            raise HTTPException(
                502, "Contamination identification failed: Claude declined to analyze this image"
            )
        truncated = stop_reason == "max_tokens"
        if truncated:
            log.warning("Contamination identify response truncated at max_tokens")
        raw_text = claude_response_text(message)
        result = parse_claude_json(raw_text)

        if "raw_response" in result:
            parse_error = {"parse_error": True, "raw_response": result["raw_response"]}
            if truncated:
                parse_error["truncated"] = True
            return parse_error

        # Persist positive detections. A DB hiccup must not turn a successful
        # identification into a 500 — the identify response contract is unchanged.
        detection = service.detection_from_identify(result)
        if detection is not None:
            try:
                await service.record_event(
                    source="identify",
                    session_id=session_id,
                    chamber_id=chamber_id,
                    contamination_type=detection["contamination_type"],
                    confidence=detection["confidence"],
                )
            except Exception as e:
                log.warning("Failed to persist contamination event: %s", e)

        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error("Contamination identification failed: %s", e)
        status = 502 if "API" in type(e).__name__ else 500
        raise HTTPException(status, f"Contamination identification failed: {e}")


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
    return await service.create_manual_event(data)


@router.post("/events/{event_id}/root-cause")
async def record_root_cause(event_id: int, data: RootCauseUpdate):
    """Stamp a root-cause analysis onto an event (the RCA form)."""
    updated = await service.set_root_cause(event_id, data.root_cause)
    if not updated:
        raise HTTPException(404, "Contamination event not found")
    return updated
