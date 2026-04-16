import base64
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import settings
from ..vision.service import parse_claude_json
from .library import CONTAMINANTS, IDENTIFICATION_SYSTEM_PROMPT

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
async def identify_contamination(file: UploadFile = File(...)):
    """Upload an image for Claude Vision contamination identification."""
    if not settings.claude_api_key:
        raise HTTPException(503, "Claude API key not configured")

    content = await file.read()

    if len(content) > _MAX_IMAGE_SIZE:
        raise HTTPException(
            413, f"Image too large ({len(content)} bytes). Maximum size is 10 MB."
        )

    media_type = file.content_type or "image/jpeg"
    image_data = base64.standard_b64encode(content).decode("utf-8")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.claude_api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
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

        raw_text = message.content[0].text
        result = parse_claude_json(raw_text)

        if "raw_response" in result:
            return {"parse_error": True, "raw_response": result["raw_response"]}

        return result

    except Exception as e:
        log.error("Contamination identification failed: %s", e)
        status = 502 if "API" in type(e).__name__ else 500
        raise HTTPException(status, f"Contamination identification failed: {e}")
