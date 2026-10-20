"""Claude photo identification behind POST /api/contamination/identify.

Its own module, imported only by the router: vision.service imports
contamination.service at its top (it records vision detections), so the
service cannot import vision's Claude helpers back without a cycle. The router
keeps the HTTP side (the upload limits, the status codes).
"""

import asyncio
import base64
import logging

import anthropic

from ..config import settings
from ..vision.service import (
    CLAUDE_MAX_TOKENS,
    _ai_timing_span,
    claude_response_text,
    claude_stop_reason,
    parse_claude_json,
)
from . import service
from .library import IDENTIFICATION_SYSTEM_PROMPT

log = logging.getLogger(__name__)

_USER_PROMPT = "Analyze this mushroom cultivation image for contamination. Respond with JSON only."


class IdentifyUpstreamError(Exception):
    """Claude could not answer: an API error (rate limit, bad key, overload,
    a retired model) or a refusal to analyze the image."""


def _b64(content: bytes) -> str:
    return base64.standard_b64encode(content).decode("ascii")


async def identify_image(
    content: bytes,
    media_type: str,
    *,
    session_id: int | None = None,
    chamber_id: int | None = None,
) -> dict:
    """Claude's contamination read of an image, as the route returns it.

    A reply with no JSON object in it comes back as {"parse_error": True,
    "raw_response": ...}, with "truncated" when it was cut off at max_tokens.
    A positive detection (contamination.service.detection_from_identify) is
    also recorded as a source='identify' event linked to session_id /
    chamber_id; failing to record it is logged, never raised, so it cannot
    cost the paid identification. Raises IdentifyUpstreamError when Claude
    errs or declines.
    """
    # Up to the 10 MB cap: encoded off the event loop, as vision does.
    image_data = await asyncio.to_thread(_b64, content)
    client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)
    try:
        with _ai_timing_span(
            "pi.contamination.identify",
            media_type=media_type,
            image_b64_bytes=len(image_data),
        ):
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
                            {"type": "text", "text": _USER_PROMPT},
                        ],
                    }
                ],
            )
    except anthropic.APIError as e:
        raise IdentifyUpstreamError(f"{type(e).__name__}: {e}") from e

    stop_reason = claude_stop_reason(message)
    if stop_reason == "refusal":
        raise IdentifyUpstreamError("Claude declined to analyze this image")
    truncated = stop_reason == "max_tokens"
    if truncated:
        log.warning("Contamination identify response truncated at max_tokens")
    result = parse_claude_json(claude_response_text(message))
    if "raw_response" in result:
        parse_error = {"parse_error": True, "raw_response": result["raw_response"]}
        if truncated:
            parse_error["truncated"] = True
        return parse_error

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
