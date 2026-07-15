import base64
import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path

import anthropic

from ..config import settings
from ..db import get_db
from ..notifications.service import contamination_alert, harvest_ready

log = logging.getLogger(__name__)


@contextmanager
def _ai_timing_span(op: str, **tags):
    """v3.3.5 — Pi-side lightweight tracer for AI paths.

    The Pi is deliberately Sentry-free (documented non-goal). Instead of
    adding the SDK, we emit structured INFO lines with ``op`` + duration
    + outcome so an operator can ``journalctl -u sporeprint | grep ai_span``
    and get the same latency distribution a real tracer would. Matches
    the shape the cloud Sentry spans use so a future integration can
    harvest this stream without a format rewrite.
    """
    t0 = time.monotonic()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        dur_ms = int((time.monotonic() - t0) * 1000)
        extras = " ".join(f"{k}={v}" for k, v in tags.items() if v is not None)
        log.info("ai_span op=%s status=%s duration_ms=%d %s", op, status, dur_ms, extras)


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
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

        image_data = base64.standard_b64encode(file_path.read_bytes()).decode("utf-8")

        session_context = ""
        species_name = "Unknown"
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
                    species_name = profile.get("common_name", session.get("species_profile_id", "Unknown"))
                    session_context = f"""
Session: {session.get('name', 'Unknown')}
Species: {species_name}
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

        # v3.3.5 — wrap in the Pi-side AI tracer so an operator can see
        # latency + success rate in journalctl without adding Sentry.
        image_bytes_len = len(image_data)
        with _ai_timing_span(
            "pi.vision.claude",
            species=species_name,
            image_b64_bytes=image_bytes_len,
        ):
            message = await client.messages.create(
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

        result = parse_claude_json(message.content[0].text)

        contam = result.get("contamination_detected") if isinstance(result, dict) else None
        if isinstance(contam, dict):
            contam_type = str(contam.get("type", "unknown"))
            confidence = float(contam.get("confidence") or 0.0)
            try:
                await contamination_alert(
                    species=species_name,
                    contam_type=contam_type,
                    confidence=confidence,
                )
            except Exception as e:
                log.warning("contamination_alert failed: %s", e)
            # Also forward to cloud so premium mobile subscribers get the push.
            try:
                from ..cloud.service import forward_event
                await forward_event("contamination_alert", {
                    "node_id": frame.get("node_id"),
                    "session_id": frame.get("session_id"),
                    "species": species_name,
                    "contamination_type": contam_type,
                    "confidence": confidence,
                    "frame_id": frame.get("id"),
                })
            except Exception as e:
                log.warning("forward_event(contamination_alert) failed: %s", e)

        return result

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


# ─── CRUD helpers for the vision router (P12 layering cleanup) ──────────
# Router now imports these instead of running inline SQL. Shared helpers also
# used by vision/router.py ingest path.

async def get_active_session_id() -> int | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM sessions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row["id"] if row else None


async def insert_frame(session_id: int | None, node_id: str, timestamp: float,
                       file_path: str, resolution: str, flash_used: int) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO vision_frames (session_id, node_id, timestamp, file_path, resolution, flash_used)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, node_id, timestamp, file_path, resolution, flash_used),
        )
        await db.commit()
        return cursor.lastrowid


async def update_analysis_local(frame_id: int, analysis: dict) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE vision_frames SET analysis_local = ? WHERE id = ?",
            (json.dumps(analysis), frame_id),
        )
        await db.commit()


async def update_analysis_claude(frame_id: int, analysis: dict) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE vision_frames SET analysis_claude = ? WHERE id = ?",
            (json.dumps(analysis), frame_id),
        )
        await db.commit()


async def get_frame_by_id(frame_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM vision_frames WHERE id = ?", (frame_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def apply_user_label(frame_id: int, label: str | None, correct: bool) -> bool:
    """Active-learning update on vision_frames.analysis_local JSON blob.

    Returns True if the row existed, False otherwise.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT analysis_local FROM vision_frames WHERE id = ?", (frame_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return False
        local = json.loads(row["analysis_local"]) if row["analysis_local"] else {}
        local["user_label"] = label
        local["user_confirmed"] = correct
        await db.execute(
            "UPDATE vision_frames SET analysis_local = ? WHERE id = ?",
            (json.dumps(local), frame_id),
        )
        await db.commit()
        return True


# ─── Fruiting growth-rate tracking → "time to harvest" alert ────────────
# Contamination detection is per-frame. Ripeness, though, is a RATE: a fruit
# body grows fast, then plateaus, and the plateau is the harvest signal (veil
# about to break / spore drop imminent). The local CNN is a stub and cannot
# measure growth across time; the reliable path is Claude comparing the earliest
# and latest frames in a window and reporting the delta. We are explicit about
# that — this is a Claude-vision feature, not a local-CNN one.

# Phases where a growth-slowing signal is meaningful (fruit bodies are forming).
_FRUITING_PHASES = frozenset({"primordia_induction", "fruiting"})

# "slow"/"stalled" growth after visible fruiting = ripe. See _GROWTH_PROMPT.
_HARVEST_GROWTH_RATES = frozenset({"slow", "stalled", "plateaued"})

_GROWTH_PROMPT = """You are a mycologist comparing two timestamped photos of the SAME mushroom grow, an earlier one and a later one, to judge how fast the fruit bodies are still growing. Fruit bodies grow fast then plateau; the plateau is the harvest signal. Respond with JSON only:
- growth_observed: boolean (are there fruit bodies that changed at all?)
- growth_rate: "rapid" | "moderate" | "slow" | "stalled"
- size_change_pct: approximate % size increase of the largest cluster, earlier→later
- recommend_harvest: boolean (true if growth has plateaued / veils are opening)
- summary: one sentence."""


def _growth_indicates_harvest(trend: dict | None) -> bool:
    """Pure decision: does this growth trend mean 'harvest now'?

    Kept separate from the Claude call so the alerting path is testable without
    an API key. A slow/stalled rate OR an explicit recommend_harvest both count.
    """
    if not isinstance(trend, dict):
        return False
    if trend.get("recommend_harvest") is True:
        return True
    return str(trend.get("growth_rate", "")).lower() in _HARVEST_GROWTH_RATES


async def _claude_growth_delta(earlier: dict, later: dict, species_name: str) -> dict:
    """Ask Claude for the growth delta between two frames. Isolated for testing."""
    if not settings.claude_api_key:
        return {"error": "Claude API key not configured"}
    client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

    def _img_block(frame: dict) -> dict:
        data = base64.standard_b64encode(Path(frame["file_path"]).read_bytes()).decode("utf-8")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}

    span_hours = abs(later["timestamp"] - earlier["timestamp"]) / 3600.0
    with _ai_timing_span("pi.vision.growth", species=species_name, span_hours=round(span_hours, 1)):
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=_GROWTH_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"EARLIER photo ({species_name}):"},
                    _img_block(earlier),
                    {"type": "text",
                     "text": f"LATER photo, {span_hours:.1f}h after the earlier one:"},
                    _img_block(later),
                    {"type": "text", "text": "Compare growth. Respond with JSON only."},
                ],
            }],
        )
    return parse_claude_json(message.content[0].text)


async def evaluate_growth_trend(session_id: int | None = None,
                                node_id: str | None = None,
                                frame_window: int = 6) -> dict:
    """Compare recent frames for a fruiting session and alert if growth slowed.

    Returns a status dict. Fires `harvest_ready` (local ntfy) + a cloud
    `harvest_ready` event when the growth trend indicates the fruit is ripe.
    """
    if session_id is None:
        session_id = await get_active_session_id()
    if session_id is None:
        return {"status": "no_active_session"}

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT s.name, s.current_phase, sp.data AS profile_data "
            "FROM sessions s LEFT JOIN species_profiles sp ON s.species_profile_id = sp.id "
            "WHERE s.id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return {"status": "session_not_found"}
    session = dict(row)
    phase = session.get("current_phase", "")
    if phase not in _FRUITING_PHASES:
        # No fruit bodies yet — a growth-slowing signal would be meaningless.
        return {"status": "not_fruiting", "phase": phase}

    profile = json.loads(session["profile_data"]) if session.get("profile_data") else {}
    species_name = profile.get("common_name", "your grow")
    session_name = session.get("name", f"Session {session_id}")

    frames = await get_frames(session_id=session_id, node_id=node_id, limit=frame_window)
    if len(frames) < 2:
        return {"status": "insufficient_frames", "frame_count": len(frames)}

    # get_frames is newest-first: frames[0] is latest, frames[-1] the oldest in
    # the window. Compare across the widest available span.
    later, earlier = frames[0], frames[-1]
    trend = await _claude_growth_delta(earlier, later, species_name)
    if isinstance(trend, dict) and trend.get("error"):
        return {"status": "analysis_error", "error": trend["error"]}

    result = {
        "status": "evaluated",
        "session_id": session_id,
        "span_frames": len(frames),
        "trend": trend,
        "harvest_recommended": _growth_indicates_harvest(trend),
    }

    if result["harvest_recommended"]:
        try:
            await harvest_ready(species_name, session_name)
        except Exception as e:
            log.warning("harvest_ready alert failed: %s", e)
        try:
            from ..cloud.service import forward_event
            await forward_event("harvest_ready", {
                "node_id": node_id,
                "session_id": session_id,
                "species": species_name,
                "reason": "fruiting_slowed",
                "growth_rate": trend.get("growth_rate") if isinstance(trend, dict) else None,
            })
        except Exception as e:
            log.warning("forward_event(harvest_ready) failed: %s", e)

    return result
