import asyncio
import base64
import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path

import anthropic

from ..config import settings
from ..db import get_db
from ..notifications.service import contamination_alert, notify_warning

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
            from ..species.service import get_profile

            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (frame["session_id"],),
                )
                row = await cursor.fetchone()
            if row:
                session = dict(row)
                species_id = session.get("species_profile_id")
                # Resolve the species profile through the tolerant lookup instead
                # of a raw `JOIN ... ON s.species_profile_id = sp.id`: the UI stores
                # hyphenated ids ("blue-oyster") while species_profiles is seeded
                # with the underscored builtin ids ("blue_oyster"), so the literal
                # join missed ~63/74 species and dropped the species context from
                # auto-analysis. get_profile() absorbs the drift via
                # species_id_candidates. See app.species.profiles.
                profile = await get_profile(species_id) if species_id else None
                species_name = profile.common_name if profile else (species_id or "Unknown")
                colonization_visual = (
                    profile.colonization_visual_description if profile else "N/A"
                )
                contamination_notes = (
                    profile.contamination_risk_notes if profile else "N/A"
                )
                session_context = f"""
Session: {session.get('name', 'Unknown')}
Species: {species_name}
Current Phase: {session.get('current_phase', 'Unknown')}
Colonization Visual: {colonization_visual}
Contamination Notes: {contamination_notes}
"""

        system_prompt = f"""You are an expert mycologist analyzing a mushroom cultivation image.
Provide a structured analysis in JSON format with these fields:
- health_assessment: "healthy" | "concern" | "contaminated" | "unknown"
- confidence: 0.0-1.0
- contamination_detected: null or {{ type, confidence, description }}
- growth_stage: description of current growth stage
- growth_rate: "expanding" | "slowing" | "stalled" | "n/a" — is the fruit body still visibly growing, or has it plateaued? Cues that growth has slowed/stalled: caps flattening or upturning, veils breaking, spores dropping, no size change expected between frames at this stage. A stalled/slowing fruit is at or past its harvest window.
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

        await _maybe_harvest_alert(frame, result, species_name)

        return result

    except Exception as e:
        log.error("Claude vision analysis failed: %s", e)
        return {"error": str(e)}


_FRUITING_PHASES = {"primordia_induction", "fruiting"}
_HARVEST_READY = {"ready", "overdue"}
_GROWTH_SLOWED = {"slowing", "stalled"}


def harvest_signal(current_phase: str, recent_analyses: list[dict]) -> tuple[bool, str | None]:
    """Should we tell the operator it's time to harvest? Pure + unit-testable.

    The spec's ask: "alert when fruiting SLOWS so you know about when to harvest."
    We only judge during a fruiting phase. `recent_analyses` is oldest→newest.
    The camera can't measure growth to the millimetre, so the signal is the
    model's per-frame stage read, corroborated across frames:
      - the latest frame says the fruit is ready/overdue or its growth has
        slowed/stalled, AND
      - it isn't a one-off: the frame before it also showed a mature/slowing
        read (a plateau), so we don't fire on a single noisy assessment.
    A single frame with no history still fires on an unambiguous overdue.
    """
    if current_phase not in _FRUITING_PHASES or not recent_analyses:
        return False, None

    def _mature(a: dict) -> bool:
        return (str(a.get("harvest_readiness", "")).lower() in _HARVEST_READY
                or str(a.get("growth_rate", "")).lower() in _GROWTH_SLOWED)

    latest = recent_analyses[-1]
    if str(latest.get("harvest_readiness", "")).lower() == "overdue":
        return True, "fruit body is overdue for harvest"
    if _mature(latest):
        # Corroborate against the prior frame to avoid a one-off false positive.
        if len(recent_analyses) >= 2 and _mature(recent_analyses[-2]):
            reason = ("growth has slowed and the fruit is at its harvest window"
                      if str(latest.get("growth_rate", "")).lower() in _GROWTH_SLOWED
                      else "fruit body is ready to harvest")
            return True, reason
    return False, None


async def _maybe_harvest_alert(frame: dict, result: dict, species_name: str) -> None:
    """Fire a deduped harvest alert when fruiting has slowed / the fruit is ready."""
    if not isinstance(result, dict):
        return
    session_id = frame.get("session_id")
    if not session_id:
        return

    async with get_db() as db:
        srow = await (await db.execute(
            "SELECT current_phase FROM sessions WHERE id = ?", (session_id,)
        )).fetchone()
        if not srow:
            return
        phase = srow["current_phase"]

        # Pull the last few Claude analyses for this session (oldest→newest).
        rows = await (await db.execute(
            "SELECT analysis_claude FROM vision_frames "
            "WHERE session_id = ? AND analysis_claude IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 4",
            (session_id,),
        )).fetchall()
    recent = []
    for r in reversed(rows):
        try:
            recent.append(json.loads(r["analysis_claude"]))
        except (json.JSONDecodeError, TypeError):
            continue
    recent.append(result)  # the frame we just analysed (may not be persisted yet)

    should, reason = harvest_signal(phase, recent)
    if not should:
        return

    async with get_db() as db:
        # Dedup: at most one harvest alert per session per 12h.
        existing = await (await db.execute(
            "SELECT 1 FROM session_events WHERE session_id = ? AND type = 'harvest_ready' "
            "AND created_at > unixepoch('now') - 43200 LIMIT 1",
            (session_id,),
        )).fetchone()
        if existing:
            return
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description, data) VALUES (?, ?, ?, ?, ?)",
            (session_id, "harvest_ready", "vision", f"Harvest window: {reason}",
             json.dumps({"reason": reason, "frame_id": frame.get("id")})),
        )
        await db.commit()

    try:
        await notify_warning(
            f"Harvest window — {species_name}",
            f"Vision: {reason}. Check the chamber.",
            dedup_key=f"harvest:{session_id}",
        )
    except Exception as e:
        log.warning("harvest notify failed: %s", e)
    try:
        from ..cloud.service import forward_event
        await forward_event("harvest_ready", {
            "node_id": frame.get("node_id"),
            "session_id": session_id,
            "species": species_name,
            "reason": reason,
            "frame_id": frame.get("id"),
        })
    except Exception as e:
        log.warning("forward_event(harvest_ready) failed: %s", e)


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


# ─── Auto-analysis on camera ingest (H4-1) ─────────────────────────────
#
# The local CNN (analyze_frame_local) is a permanent stub — every ingested
# frame it scores comes back "healthy" 0.0, so auto contamination/harvest
# detection never actually fired: green mold and overdue flushes went
# unflagged unless an operator manually hit POST /frames/{id}/analyze. Rather
# than ship a local model, we run the REAL detector (analyze_frame_claude) on
# ingest — it already routes contamination (green mold/Trichoderma) and the
# harvest-window signal (fruiting start/slowing/progressing, full colonization)
# through the persisted-alert + ntfy + cloud forward_event plumbing.
#
# Anthropic calls cost money, so ingest analysis is cost-gated:
#   - only when a Claude key is present. On the Pi, AI is BYOK — the operator's
#     own key IS the premium/BYOK gate (the Pi has no tier concept of its own);
#   - only for frames tied to an active grow session (nothing to monitor
#     between grows), and
#   - at most once per session per _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS, so a
#     camera streaming a frame every few seconds can't run up a bill.
_AUTO_ANALYSIS_MIN_INTERVAL_SECONDS = 15 * 60  # tunable cadence, per session
_last_auto_analysis: dict[int, float] = {}
# Strong refs to in-flight background tasks so the event loop can't GC them
# mid-run (per asyncio.create_task docs). Cleared via the done-callback.
_auto_analysis_tasks: set[asyncio.Task] = set()


def _claim_auto_analysis_slot(session_id: int, now: float | None = None) -> bool:
    """Atomically claim this session's throttle slot; True iff outside the window.

    Check-and-record with no ``await`` in between, so under the single-threaded
    event loop two frames arriving back-to-back can't both claim the slot. The
    attempt time is recorded (not the success time), so a failed/slow analysis
    still counts against the budget — the throttle strictly bounds API calls.
    """
    now = time.time() if now is None else now
    last = _last_auto_analysis.get(session_id, 0.0)
    if now - last < _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS:
        return False
    _last_auto_analysis[session_id] = now
    return True


async def _run_auto_analysis(frame: dict) -> None:
    """Run the real Claude detector for an ingested frame and persist the result.

    analyze_frame_claude fires the contamination + harvest alert/forward
    plumbing itself; here we only persist the analysis blob so the frame row
    carries it and the harvest-corroboration query (which reads analysis_claude
    across recent frames) can see this frame next time.
    """
    try:
        result = await analyze_frame_claude(frame)
    except Exception as e:  # a background task must never die silently
        log.warning("auto vision analysis failed for frame %s: %s", frame.get("id"), e)
        return
    if isinstance(result, dict) and "error" not in result:
        try:
            await update_analysis_claude(frame["id"], result)
        except Exception as e:
            log.warning("persisting auto vision analysis for frame %s failed: %s",
                        frame.get("id"), e)


async def maybe_schedule_auto_analysis(
    frame_id: int,
    session_id: int | None,
    node_id: str,
    file_path: str,
) -> asyncio.Task | None:
    """Kick the real Claude detector for a freshly-ingested frame, cost-gated.

    Returns the scheduled task (so callers/tests can await it) or None when
    gating declines: no active session, no Claude key (free / no BYOK), or
    still inside the per-session throttle window. Non-blocking — the analysis
    runs in the background so the ingest response returns immediately.
    """
    if session_id is None:
        return None
    # BYOK gate — the Pi's AI paygate. No key ⇒ don't even schedule (calling
    # analyze_frame_claude would just return an error and waste a task).
    if not settings.claude_api_key:
        return None
    if not _claim_auto_analysis_slot(session_id):
        return None

    frame = {
        "id": frame_id,
        "session_id": session_id,
        "node_id": node_id,
        "file_path": file_path,
    }
    task = asyncio.create_task(_run_auto_analysis(frame))
    _auto_analysis_tasks.add(task)
    task.add_done_callback(_auto_analysis_tasks.discard)
    return task
