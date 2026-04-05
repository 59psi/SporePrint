import json
import logging
from pathlib import Path

from ..config import settings
from ..db import get_db

log = logging.getLogger(__name__)


def parse_claude_json(text: str) -> dict:
    """Parse JSON from a Claude response, handling markdown code blocks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        elif "```" in text:
            json_str = text.split("```")[1].split("```")[0].strip()
            return json.loads(json_str)
        return {"raw_response": text}


async def analyze_frame_local(file_path: Path) -> dict | None:
    """Run local CNN inference on a frame.

    Returns classification result or None if model not available.
    In production this loads a TFLite/ONNX model. For now, returns a stub.
    """
    try:
        # Stub — real implementation loads TFLite model:
        # interpreter = tflite.Interpreter(model_path="models/weights/contam_detector.tflite")
        # interpreter.allocate_tensors()
        # ... preprocess image, run inference ...

        return {
            "model": "stub",
            "prediction": "healthy",
            "confidence": 0.0,
            "classes": {
                "healthy": 0.0,
                "trich_early": 0.0,
                "trich_green": 0.0,
                "cobweb": 0.0,
                "bacterial": 0.0,
                "other_contam": 0.0,
                "no_change": 0.0,
            },
            "note": "Local CNN model not loaded — install vision extras and provide model weights",
        }
    except Exception as e:
        log.error("Local vision analysis failed: %s", e)
        return None


async def analyze_frame_claude(frame: dict) -> dict | None:
    """Send frame to Claude Vision API for deep analysis."""
    if not settings.claude_api_key:
        return {"error": "Claude API key not configured"}

    file_path = Path(frame["file_path"])

    try:
        import anthropic
        import base64

        client = anthropic.Anthropic(api_key=settings.claude_api_key)

        image_data = base64.standard_b64encode(file_path.read_bytes()).decode("utf-8")

        # Get session context
        session_context = ""
        if frame.get("session_id"):
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT s.*, sp.data as profile_data FROM sessions s LEFT JOIN species_profiles sp ON s.species_profile_id = sp.id WHERE s.id = ?",
                    (frame["session_id"],),
                )
                row = await cursor.fetchone()
                if row:
                    session = dict(row)
                    profile = json.loads(session.get("profile_data", "{}")) if session.get("profile_data") else {}
                    session_context = f"""
Session: {session.get('name', 'Unknown')}
Species: {profile.get('common_name', session.get('species_profile_id', 'Unknown'))}
Current Phase: {session.get('current_phase', 'Unknown')}
Colonization Visual: {profile.get('colonization_visual_description', 'N/A')}
Contamination Notes: {profile.get('contamination_risk_notes', 'N/A')}
"""

        system_prompt = f"""You are an expert mycologist analyzing a mushroom cultivation image.
Provide a structured analysis in JSON format with these fields:
- health_assessment: "healthy" | "concern" | "contaminated" | "unknown"
- confidence: 0.0-1.0
- contamination_detected: null or {{ type, confidence, description }}
- growth_stage: description of current growth stage
- morphology_notes: observations about mycelium/fruit body morphology
- harvest_readiness: "not_ready" | "approaching" | "ready" | "overdue" | "n/a"
- recommendations: list of actionable recommendations
- summary: 2-3 sentence natural language summary

{session_context}"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyze this mushroom cultivation image. Respond with JSON only.",
                        },
                    ],
                }
            ],
            system=system_prompt,
        )

        return parse_claude_json(message.content[0].text)

    except Exception as e:
        log.error("Claude vision analysis failed: %s", e)
        return {"error": str(e)}


async def get_frames(
    session_id: int | None = None,
    node_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    query = "SELECT * FROM vision_frames WHERE 1=1"
    params: list = []
    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    if node_id:
        query += " AND node_id = ?"
        params.append(node_id)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    async with get_db() as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_deserialize_frame(row) for row in rows]


def _deserialize_frame(row) -> dict:
    """Deserialize JSON analysis fields from a vision_frames row."""
    frame = dict(row)
    for field in ("analysis_local", "analysis_claude"):
        if frame.get(field):
            frame[field] = json.loads(frame[field])
    return frame
