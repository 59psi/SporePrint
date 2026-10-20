import asyncio
import base64
import json
import logging
import math
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import anthropic

from ..config import settings
from ..contamination.service import as_confidence, record_event
from ..db import get_db
from ..node_clock import MAX_FUTURE_SKEW_SECONDS, SYNCED_TS_MIN
from ..notifications.service import contamination_alert, harvest_ready, notify_info, notify_warning
from ..species.models import COLONIZATION_PHASES, FRUITING_PHASES, GrowPhase, SpeciesProfile
from ..species.service import get_profile

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
    """Parse a JSON object out of a Claude response. Never raises.

    Tries, in order: the whole text, the first fenced block (```json or ```),
    then the span between the first '{' and the last '}' (prose-wrapped JSON).
    Anything that doesn't yield a JSON *object* — including a response
    truncated at max_tokens mid-fence — degrades to {"raw_response": text}, so
    callers take their documented fallback path instead of a 500.
    """
    if not isinstance(text, str):
        return {"raw_response": str(text)}

    candidates = [text]
    if "```" in text:
        after = text.split("```json", 1)[1] if "```json" in text else text.split("```", 1)[1]
        candidates.append(after.split("```", 1)[0])
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except ValueError:  # JSONDecodeError is a ValueError subclass
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"raw_response": text}


# Output ceiling for the non-streaming Claude calls. Current models think by
# default and thinking tokens count against max_tokens, so the old 1000-2048
# budgets truncated the JSON answer. Only tokens actually generated are billed;
# 16K stays under the SDK's non-streaming limit.
CLAUDE_MAX_TOKENS = 16_000


def claude_response_text(message) -> str:
    """Joined text of a Messages API response's text blocks. Never raises.

    `content[0]` is not necessarily text: models that think by default put a
    `thinking` block first, and a refusal can carry no text at all. Blocks with
    no string `type` but a string `text` count as text.
    """
    parts = []
    for block in getattr(message, "content", None) or ():
        text = getattr(block, "text", None)
        block_type = getattr(block, "type", None)
        if isinstance(text, str) and (block_type == "text" or not isinstance(block_type, str)):
            parts.append(text)
    return "".join(parts)


def claude_stop_reason(message) -> str | None:
    """The response's stop_reason ("end_turn", "max_tokens", "refusal", ...)."""
    reason = getattr(message, "stop_reason", None)
    return reason if isinstance(reason, str) else None


# Image types the Claude Messages API accepts, keyed by stored-file extension.
_MEDIA_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
EXT_BY_MEDIA = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def sniff_image_media_type(data: bytes) -> str | None:
    """Identify JPEG/PNG/WebP/GIF from magic bytes; None for anything else.

    The bytes are the authority — a Content-Type header or file suffix can lie
    (and early frames were stored as .jpg whatever their real type). The
    Messages API rejects a request whose declared media_type doesn't match the
    image, and only accepts these four types (so HEIC etc. sniff to None).
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


# ─── Frame ingest helpers (timestamp + storage name) ────────────────────
#
# Contract with the cam firmware: X-Timestamp carries Unix-epoch seconds only
# when the cam is NTP-synced. A missing value, or one below 1e9 (the uptime
# counter older firmware sends when unsynced), is stamped with arrival time.
# The bounds are the shared node clock contract (app/node_clock.py).
_EPOCH_SYNCED_MIN = SYNCED_TS_MIN
# A synced clock far ahead of the Pi is as wrong as an unsynced one: it would
# sort as the newest frame forever and break the harvest-corroboration query.
_MAX_FUTURE_SKEW_SECONDS = MAX_FUTURE_SKEW_SECONDS


def resolve_frame_timestamp(raw: str | None, now: float | None = None) -> float:
    """Frame timestamp from the X-Timestamp header; arrival time unless synced.

    A missing, unparseable, non-finite, pre-epoch-sync (< 1e9) or far-future
    value is not a capture time the Pi can trust, so the frame is stamped with
    its arrival time — never refused: the camera can't fix its clock, and a
    400 here only threw its frames away.
    """
    now = time.time() if now is None else now
    try:
        ts = float(raw) if raw else now
    except ValueError:
        return now
    if not math.isfinite(ts) or ts < _EPOCH_SYNCED_MIN or ts > now + _MAX_FUTURE_SKEW_SECONDS:
        return now
    return ts


def frame_storage_name(node_id: str, ts: float, media_type: str) -> str:
    """Unique on-disk name for a frame: node + second + random suffix.

    `{node}_{int(ts)}.jpg` collided whenever two frames shared a second
    (uptime values recur after every reboot), silently overwriting an older
    frame's image while its DB row still pointed at the path.
    """
    ext = EXT_BY_MEDIA.get(media_type, ".jpg")
    return f"{node_id}_{int(ts)}_{uuid.uuid4().hex[:12]}{ext}"


class FrameStorageError(Exception):
    """A frame could not be written under the storage directory."""


class InvalidFramePathError(FrameStorageError):
    """The frame's file name would resolve outside the storage directory."""


def write_frame_file(storage_dir: str, node_id: str, ts: float, media_type: str,
                     content: bytes) -> Path:
    """Write a frame's bytes to a new file under ``storage_dir``; its path.

    Blocking file I/O (up to the 20 MB upload cap), so ingest runs it in a
    worker thread. The file is opened exclusively, so an existing frame is
    never overwritten: a name collision draws a new random suffix. Raises
    InvalidFramePathError when the name would resolve outside the storage
    dir, FrameStorageError when no unique name is found.
    """
    storage = Path(storage_dir).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        file_path = (storage / frame_storage_name(node_id, ts, media_type)).resolve()
        if not file_path.is_relative_to(storage):
            raise InvalidFramePathError("Invalid frame path")
        try:
            with file_path.open("xb") as fh:  # exclusive: never overwrite a frame
                fh.write(content)
            return file_path
        except FileExistsError:
            continue
    raise FrameStorageError("Could not allocate a unique frame filename")


async def analyze_frame_local(file_path: Path) -> dict | None:
    """Run local CNN inference on a frame.

    Returns the classification result, or None while no model is available.
    No local model is built yet (docs/feature-status.md), so this returns
    None and ingest stores nothing in analysis_local: a placeholder result
    on every frame was a fake "healthy" read plus a second write per frame.
    Claude auto-analysis is the automatic detector.
    """
    return None


def _load_image_for_claude(file_path: Path) -> tuple[str, str]:
    """(media type, base64 data) of a stored frame, for a Messages API image block.

    Blocking (a read and a base64 encode of up to the 20 MB upload cap), so
    analyze_frame_claude runs it in a worker thread. The bytes decide the
    media type; the suffix only covers a file that sniffs as none of the four.
    """
    raw_image = file_path.read_bytes()
    media_type = (sniff_image_media_type(raw_image)
                  or _MEDIA_BY_SUFFIX.get(file_path.suffix.lower(), "image/jpeg"))
    return media_type, base64.standard_b64encode(raw_image).decode("utf-8")


@dataclass(frozen=True)
class _FrameGrow:
    """The grow session a frame belongs to, read once per analysis: the
    prompt's context and every alert the reply raises use the same row."""
    session: dict
    profile: SpeciesProfile | None
    species_name: str


async def _load_frame_grow(session_id: int | None) -> _FrameGrow | None:
    """The session row and species profile a frame's analysis runs under."""
    if not session_id:
        return None
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )).fetchone()
    if not row:
        return None
    session = dict(row)
    species_id = session.get("species_profile_id")
    # Resolve the species profile through the tolerant lookup instead of a raw
    # `JOIN ... ON s.species_profile_id = sp.id`: the UI stores hyphenated ids
    # ("blue-oyster") while species_profiles is seeded with the underscored
    # builtin ids ("blue_oyster"), so the literal join missed ~63/74 species
    # and dropped the species context from auto-analysis. get_profile()
    # absorbs the drift via species_id_candidates. See app.species.profiles.
    profile = await get_profile(species_id) if species_id else None
    species_name = profile.common_name if profile else (species_id or "Unknown")
    return _FrameGrow(session=session, profile=profile, species_name=species_name)


async def analyze_frame_claude(frame: dict) -> dict | None:
    """Send frame to Claude Vision API for deep analysis.

    Only the Claude call and its parsing can turn the result into an
    {"error": ...}. The alerts the reply raises run after it, each on its own
    guard (_route_vision_signals): a failing alert (a database lock held past
    busy_timeout, say) used to replace the paid analysis with an error, which
    callers never store — and the auto path then could not retry the frame
    for a whole cadence window.
    """
    if not settings.claude_api_key:
        return {"error": "Claude API key not configured"}

    file_path = Path(frame["file_path"])
    grow = None

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

        media_type, image_data = await asyncio.to_thread(_load_image_for_claude, file_path)

        grow = await _load_frame_grow(frame.get("session_id"))
        species_name = grow.species_name if grow is not None else "Unknown"
        session_context = ""
        if grow is not None:
            session, profile = grow.session, grow.profile
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
{browning_guidance(profile, session.get('current_phase'))}"""

        camera_context = ""
        if frame.get("camera_sensor"):
            # OV3660 frames are noticeably more saturated than OV2640 ones —
            # colour cues (green trich, orange cordyceps) read differently.
            camera_context = f"Camera sensor: {str(frame['camera_sensor']).upper()} (ESP32-CAM)\n"

        system_prompt = f"""You are an expert mycologist analyzing a mushroom cultivation image.
Provide a structured analysis in JSON format with these fields:
- health_assessment: "healthy" | "concern" | "contaminated" | "unknown"
- confidence: 0.0-1.0
- contamination_detected: null or {{ type, confidence, description }}
- growth_stage: description of current growth stage
- growth_rate: "expanding" | "slowing" | "stalled" | "n/a" — is the fruit body still visibly growing, or has it plateaued? Cues that growth has slowed/stalled: caps flattening or upturning, veils breaking, spores dropping, no size change expected between frames at this stage. A stalled/slowing fruit is at or past its harvest window.
- colonization_percent: 0-100 or null — for a colonizing culture (grain/agar/substrate, no fruit bodies yet), the estimated percentage of the visible surface run through with white mycelium. 100 means fully colonized and ready to fruit. null when this isn't a colonization image (e.g. fruit bodies present).
- surface: "bag" | "jar" | "agar" | "n/a" — the container/medium shown (grow bag, grain jar, or agar/petri plate); "n/a" if none applies.
- morphology_notes: observations about mycelium/fruit body morphology
- harvest_readiness: "not_ready" | "approaching" | "ready" | "overdue" | "n/a"
- recommendations: list of actionable recommendations
- summary: 2-3 sentence natural language summary

{session_context}{camera_context}"""

        # v3.3.5 — wrap in the Pi-side AI tracer so an operator can see
        # latency + success rate in journalctl without adding Sentry.
        image_bytes_len = len(image_data)
        with _ai_timing_span(
            "pi.vision.claude",
            species=species_name,
            image_b64_bytes=image_bytes_len,
        ):
            message = await client.messages.create(
                model=settings.claude_model,
                max_tokens=CLAUDE_MAX_TOKENS,
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
                                "text": "Analyze this mushroom cultivation image. Respond with JSON only.",
                            },
                        ],
                    }
                ],
                system=system_prompt,
            )

        stop_reason = claude_stop_reason(message)
        if stop_reason == "refusal":
            log.warning("Claude declined to analyze frame %s (refusal)", frame.get("id"))
            return {"error": "Claude declined to analyze this frame (refusal)"}
        text = claude_response_text(message)
        result = parse_claude_json(text)
        if stop_reason == "max_tokens":
            # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure — logs an identifier/path/field names only, never a secret value
            log.warning("Claude vision response truncated at max_tokens (frame %s)", frame.get("id"))
            if "raw_response" in result:
                # An error result is never persisted over the frame's last good analysis.
                return {"error": "Claude response was cut off at max_tokens", "raw_response": text}
        if "raw_response" in result:
            # A complete reply with no JSON object in it (prose about a dark or
            # empty frame, say) is no analysis either: as an error it is never
            # persisted over the frame's last good analysis, where it would drop
            # health_assessment and let retention prune a flagged frame.
            return {"error": "Claude returned no JSON analysis", "raw_response": text}

    except Exception as e:
        log.error("Claude vision analysis failed: %s", e)
        return {"error": str(e)}

    await _route_vision_signals(frame, result, grow)
    return result


async def _route_vision_signals(frame: dict, result: dict, grow: _FrameGrow | None) -> None:
    """Raise the alerts a parsed analysis calls for: contamination, then the
    harvest window, full colonization and finished browning. Each runs on its
    own guard, so one failing neither skips the others nor costs the analysis."""
    tier, contam_type, confidence = contamination_signal(result)
    if tier:
        try:
            await _handle_contamination(
                frame, tier, contam_type, confidence,
                grow.species_name if grow is not None else "Unknown",
                grow.session.get("chamber_id") if grow is not None else None,
            )
        except Exception as e:
            log.warning("Vision contamination alert for frame %s failed: %s", frame.get("id"), e)
    if grow is None:
        return
    for check in (_maybe_harvest_alert, _maybe_colonization_alert, _maybe_browning_alert):
        try:
            await check(frame, result, grow)
        except Exception as e:
            log.warning("%s for frame %s failed: %s",
                        getattr(check, "__name__", "vision alert"), frame.get("id"), e)


# Claude's per-detection confidence at/above which a vision contamination read
# pages CRITICAL, is forwarded to the cloud and is logged to contamination_events.
_CONTAM_ALERT_MIN_CONFIDENCE = 0.6
# Borderline reads (at/above this, below the alert bar) get one deduped WARNING
# so a plausible early detection isn't silently dropped.
_CONTAM_WARN_MIN_CONFIDENCE = 0.3
# First words of a `contamination_detected` type that mean "nothing found":
# "none", but also "None detected", "No contamination", "not present",
# "N/A". Whole words only, so a real type that merely begins with the same
# letters ("nocardia") still counts.
_NO_CONTAMINATION_WORDS = frozenset({
    "none", "null", "n/a", "na", "no", "not", "nothing", "false", "negative", "clean",
    "healthy",
})
# What separates the words of a type ("none_detected", "no-contamination").
_TYPE_WORD_SPLIT = re.compile(r"[\s_,.;:!?()\[\]-]+")
_SIGNAL_TIER_RANK = {None: 0, "warning": 1, "critical": 2}
# The same contamination (session + type) is paged/logged at most once per window.
_CONTAM_DEDUP_SECONDS = 12 * 3600


def _means_no_contamination(contam_type: str) -> bool:
    """A `contamination_detected` type that says nothing was found."""
    words = [w for w in _TYPE_WORD_SPLIT.split(contam_type.lower()) if w]
    return not words or words[0] in _NO_CONTAMINATION_WORDS


def _detection_signal(contam: dict, result: dict) -> tuple[str | None, str, float]:
    """(tier, type, confidence) of one `contamination_detected` entry."""
    health = str(result.get("health_assessment") or "").strip().lower()
    contam_type = str(contam.get("type") or "unknown").strip()
    if _means_no_contamination(contam_type):
        return None, contam_type, 0.0
    confidence = as_confidence(contam.get("confidence"))
    if confidence is None and health == "contaminated":
        confidence = as_confidence(result.get("confidence"))
    confidence = confidence or 0.0
    if confidence >= _CONTAM_ALERT_MIN_CONFIDENCE:
        # A detection inside a read Claude calls healthy overall is a possible
        # early spot: worth the deduped WARNING, not a CRITICAL page.
        tier = "warning" if health == "healthy" else "critical"
    elif confidence >= _CONTAM_WARN_MIN_CONFIDENCE:
        tier = "warning"
    else:
        tier = None
    return tier, contam_type, confidence


def contamination_signal(result) -> tuple[str | None, str, float]:
    """Classify a Claude vision result's contamination read. Pure + testable.

    Returns (tier, type, confidence) where tier is "critical", "warning" or
    None. Any object in `contamination_detected` used to page CRITICAL —
    including {type: "none", confidence: 0} — with no threshold at all.

    `contamination_detected` may be one object, a list of them (the
    strongest entry counts: tier first, then confidence) or a bare type
    string. A type whose first word says nothing was found ("None detected",
    "No contamination") is no detection; a confident detection in a read
    whose health_assessment is "healthy" is downgraded to a warning; and a
    read Claude calls "contaminated" without naming what counts as an
    unnamed detection at the read's own confidence.
    """
    if not isinstance(result, dict):
        return None, "", 0.0
    contam = result.get("contamination_detected")
    if isinstance(contam, dict):
        entries = [contam]
    elif isinstance(contam, list):
        entries = [c for c in contam if isinstance(c, dict)]
    elif isinstance(contam, str):
        entries = [{"type": contam}]
    else:
        entries = []
    if not entries:
        if str(result.get("health_assessment") or "").strip().lower() != "contaminated":
            return None, "", 0.0
        entries = [{}]  # contaminated, nothing named: type "unknown"
    signals = [_detection_signal(entry, result) for entry in entries]
    return max(signals, key=lambda s: (_SIGNAL_TIER_RANK[s[0]], s[2]))


async def _handle_contamination(
    frame: dict,
    tier: str,
    contam_type: str,
    confidence: float,
    species_name: str,
    chamber_id: int | None,
) -> None:
    """Route a vision contamination read: log to history, page, forward to cloud.

    A confident detection is written to contamination_events (source='vision',
    linked to the frame) so the Contamination page, RCA flow and chamber
    contamination rates see auto-detected contamination too — then paged
    CRITICAL and forwarded. It's deduped per session + type via that same
    table, so an unresolved contamination re-seen on every analysis doesn't
    re-page. Borderline reads only get a deduped WARNING. A dedup lookup that
    fails (a locked database) does not swallow the detection: it is still
    recorded if it can be and paged (the notifier dedups the page itself).
    """
    session_id = frame.get("session_id")
    scope = session_id if session_id is not None else frame.get("node_id")

    if tier == "warning":
        try:
            await notify_warning(
                f"Possible contamination — {species_name}",
                f"Vision flagged possible {contam_type} ({confidence:.0%} confidence). "
                f"Inspect the chamber.",
                dedup_key=f"contam-warn:{scope}:{contam_type.lower()}",
                dedup_seconds=_CONTAM_DEDUP_SECONDS,
            )
        except Exception as e:
            log.warning("possible-contamination notify failed: %s", e)
        return

    try:
        async with get_db() as db:
            existing = await (await db.execute(
                "SELECT 1 FROM contamination_events WHERE source = 'vision' "
                "AND session_id IS ? AND lower(contamination_type) = ? AND detected_at > ? LIMIT 1",
                (session_id, contam_type.lower(), time.time() - _CONTAM_DEDUP_SECONDS),
            )).fetchone()
    except Exception as e:
        log.warning("Vision contamination dedup lookup failed, alerting anyway: %s", e)
        existing = None
    if existing:
        return

    recorded = None
    try:
        recorded = await record_event(
            source="vision",
            session_id=session_id,
            chamber_id=chamber_id,
            contamination_type=contam_type,
            confidence=confidence,
            frame_id=frame.get("id"),
        )
    except Exception as e:
        log.warning("Failed to persist vision contamination event: %s", e)

    try:
        await contamination_alert(
            species=species_name,
            contam_type=contam_type,
            confidence=confidence,
            dedup_key=f"contam:{scope}:{contam_type.lower()}",
        )
    except Exception as e:
        log.warning("contamination_alert failed: %s", e)
    # Also forward to cloud so premium mobile subscribers get the push.
    await _forward_to_cloud("contamination_alert", {
        "node_id": frame.get("node_id"),
        # Names the recorded event: the cloud stores it from the event
        # sync (app.cloud.session_sync), so the alert must not add a copy.
        "pi_event_id": recorded["id"] if recorded else None,
        "session_id": session_id,
        "species": species_name,
        "contamination_type": contam_type,
        "confidence": confidence,
        "frame_id": frame.get("id"),
    })


async def _forward_to_cloud(event_type: str, payload: dict) -> None:
    """cloud.service.forward_event, never raising: the cloud link is optional."""
    try:
        # Imported here: app.cloud.service imports this module through its own
        # imports, so a module-level import would be circular.
        from ..cloud.service import forward_event
        await forward_event(event_type, payload)
    except Exception as e:
        log.warning("forward_event(%s) failed: %s", event_type, e)


# A vision milestone (harvest window, colonization or browning complete) is
# logged, notified and forwarded at most once per session and kind per window.
_MILESTONE_DEDUP_SECONDS = 12 * 3600


async def _record_vision_milestone(
    session_id: int,
    event_type: str,
    description: str,
    data: dict,
    notify: Callable[[], Awaitable[object]],
    forward_type: str,
    forward_payload: dict,
) -> bool:
    """Log a vision milestone on its session, then notify and forward it.

    Deduped on session_events itself (one per session and event type per
    _MILESTONE_DEDUP_SECONDS), checked and written in one transaction.
    `notify` sends the notification; a failed notify or forward is logged,
    never raised. False when an earlier event of the kind deduped this one.
    """
    async with get_db() as db:
        existing = await (await db.execute(
            "SELECT 1 FROM session_events WHERE session_id = ? AND type = ? "
            "AND timestamp > unixepoch('now') - ? LIMIT 1",
            (session_id, event_type, _MILESTONE_DEDUP_SECONDS),
        )).fetchone()
        if existing:
            return False
        await db.execute(
            "INSERT INTO session_events (session_id, type, source, description, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, event_type, "vision", description, json.dumps(data)),
        )
        await db.commit()
    try:
        await notify()
    except Exception as e:
        log.warning("%s notify failed: %s", event_type, e)
    await _forward_to_cloud(forward_type, forward_payload)
    return True


_FRUITING_PHASES = FRUITING_PHASES
_HARVEST_READY = {"ready", "overdue"}
_GROWTH_SLOWED = {"slowing", "stalled"}

# Shiitake browning (CLAUDE.md §4b: "vision should track browning"). The block's
# brown, popcorned skin is the stage maturing — the generic prompt would read a
# brown-blistered block as contamination. The model reports browning_percent;
# at this share of the visible surface the block is browned and owes its
# cold-water soak.
_BROWNING_COMPLETE_PERCENT = 90.0


def browning_guidance(profile, current_phase: str | None) -> str:
    """Extra prompt lines while a session is browning ("" otherwise), so every
    other species/phase prompt is unchanged. Pure + testable."""
    if current_phase != GrowPhase.BROWNING.value or profile is None:
        return ""
    params = profile.phases.get(GrowPhase.BROWNING)
    if params is None:
        return ""
    return (
        f"Phase Expectations (browning): {params.notes}\n"
        "Browning is NORMAL for this species: a brown, leathery outer skin with popcorn-like "
        "blisters (and brown liquid beading on it) is the block maturing — do NOT report it as "
        "contamination. Contamination in this phase looks different: green (Trichoderma) or "
        "other off-colour mold, most often where the surface stays wet.\n"
        "Also include browning_percent: 0-100 — the share of the visible block surface that "
        f"has formed the brown skin ({_BROWNING_COMPLETE_PERCENT:.0f}+ = evenly brown, ready "
        "for the cold-water soak).\n"
    )


def browning_signal(current_phase: str, browning_percent) -> tuple[bool, str | None]:
    """Is the browning block done? Pure + testable; mirrors colonization_signal.

    Only judged in the browning phase, on the model's per-frame
    ``browning_percent`` read. Advancing (after the cold-water soak) is the
    operator's call — this only tells them.
    """
    if current_phase != GrowPhase.BROWNING.value:
        return False, None
    try:
        pct = float(browning_percent)
    except (TypeError, ValueError):
        return False, None
    if pct >= _BROWNING_COMPLETE_PERCENT:
        return True, f"block is {pct:.0f}% browned — browning looks complete"
    return False, None

# Phases where the culture is still running (species.models, as sessions
# reads them). Full colonization is the "ready to fruit" milestone; only
# meaningful before the bag/jar/plate is opened to fruit.
_COLONIZATION_PHASES = COLONIZATION_PHASES
# The visible surface must be essentially fully run before we page the operator.
_COLONIZATION_COMPLETE_PERCENT = 95.0


def colonization_signal(current_phase: str, colonization_percent, *,
                        ready_to: str = "fruit") -> tuple[bool, str | None]:
    """Should we tell the operator the culture is fully colonized? Pure + testable.

    The spec's ask: surface the "ready to fruit" milestone the vision path never
    raised. We only judge during a colonization phase (agar / LC / grain /
    substrate) — once fruit bodies are present the fruiting-side signals take
    over. The camera can't measure coverage to the percent, so the signal is the
    model's per-frame ``colonization_percent`` read: at or above the completion
    threshold, the medium is fully run and ready to move to fruiting conditions.
    Advancing the phase is a separate product decision — this only alerts.
    ``ready_to`` names the next stage: "brown" for a species that browns
    before it can fruit (shiitake).
    """
    if current_phase not in _COLONIZATION_PHASES:
        return False, None
    try:
        pct = float(colonization_percent)
    except (TypeError, ValueError):
        return False, None
    if pct >= _COLONIZATION_COMPLETE_PERCENT:
        return True, f"substrate is {pct:.0f}% colonized — ready to {ready_to}"
    return False, None


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


async def _harvest_history(frame: dict, session_id: int) -> list[dict] | None:
    """The camera's earlier Claude reads in this session, oldest→newest, that
    `frame`'s read is judged against; None when a newer frame of the same
    camera is already analysed (this read is not the latest one).

    Only frames before this one count, by (timestamp, id): a re-analysis of a
    frame used to find its own stored read as "the frame before it", and a
    re-read old frame was taken as the newest read, so one image could make
    the two-frame plateau. One camera's reads only: the plateau is the same
    view twice, and another camera that cannot see the fruit (a top-down
    colonization view) would never corroborate it.
    """
    frame_id = frame.get("id")
    async with get_db() as db:
        own = await (await db.execute(
            "SELECT node_id, timestamp FROM vision_frames WHERE id = ?", (frame_id,)
        )).fetchone()
        params = {
            "session_id": session_id,
            "node_id": own["node_id"] if own else frame.get("node_id"),
            "frame_id": frame_id,
            "ts": own["timestamp"] if own else time.time(),
        }
        newer = await (await db.execute(
            "SELECT 1 FROM vision_frames WHERE session_id = :session_id "
            "AND node_id IS :node_id AND id IS NOT :frame_id AND analysis_claude IS NOT NULL "
            "AND (timestamp > :ts OR (timestamp = :ts AND id > COALESCE(:frame_id, 0))) LIMIT 1",
            params,
        )).fetchone()
        if newer:
            return None
        rows = await (await db.execute(
            "SELECT analysis_claude FROM vision_frames WHERE session_id = :session_id "
            "AND node_id IS :node_id AND id IS NOT :frame_id AND analysis_claude IS NOT NULL "
            "AND (timestamp < :ts OR (timestamp = :ts AND id < COALESCE(:frame_id, 0))) "
            "ORDER BY timestamp DESC, id DESC LIMIT 3",
            params,
        )).fetchall()
    history = []
    for r in reversed(rows):
        try:
            analysis = json.loads(r["analysis_claude"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(analysis, dict):
            history.append(analysis)
    return history


async def _maybe_harvest_alert(frame: dict, result: dict, grow: _FrameGrow) -> None:
    """Fire a deduped harvest alert when fruiting has slowed / the fruit is ready."""
    session_id = grow.session["id"]
    phase = grow.session["current_phase"]
    if phase not in _FRUITING_PHASES:
        return
    history = await _harvest_history(frame, session_id)
    if history is None:
        return
    should, reason = harvest_signal(phase, [*history, result])
    if not should:
        return
    await _record_vision_milestone(
        session_id, "harvest_ready", f"Harvest window: {reason}",
        {"reason": reason, "frame_id": frame.get("id")},
        # INFO tier per spec §6 ("harvest readiness"); the session_events row
        # already limits it to one per session per 12 h.
        lambda: harvest_ready(grow.species_name, grow.session["name"], reason=reason,
                              dedup_key=f"harvest:{session_id}"),
        "harvest_ready",
        {
            "node_id": frame.get("node_id"),
            "session_id": session_id,
            "species": grow.species_name,
            "reason": reason,
            "frame_id": frame.get("id"),
        },
    )


async def _maybe_colonization_alert(frame: dict, result: dict, grow: _FrameGrow) -> None:
    """Fire a deduped colonization-complete alert when the culture is fully run.

    Gated on the session's phase, one alert per session per 12 h
    (_record_vision_milestone), then notify + forward to the cloud.
    """
    session_id = grow.session["id"]
    phase = grow.session["current_phase"]
    # A species that browns before it can fruit (shiitake) moves to browning next.
    browns_next = grow.profile is not None and GrowPhase.BROWNING in grow.profile.phases
    should, reason = colonization_signal(phase, result.get("colonization_percent"),
                                         ready_to="brown" if browns_next else "fruit")
    if not should:
        return
    await _record_vision_milestone(
        session_id, "colonization_complete", f"Colonization complete: {reason}",
        {"reason": reason,
         "colonization_percent": result.get("colonization_percent"),
         "surface": result.get("surface"),
         "frame_id": frame.get("id")},
        lambda: notify_warning(
            f"Colonization complete — {grow.species_name}",
            f"Vision: {reason}. Ready to move to {'browning' if browns_next else 'fruiting'}.",
            dedup_key=f"colonization:{session_id}",
        ),
        "colonization_complete",
        {
            "node_id": frame.get("node_id"),
            "session_id": session_id,
            "species": grow.species_name,
            "reason": reason,
            "colonization_percent": result.get("colonization_percent"),
            "surface": result.get("surface"),
            "frame_id": frame.get("id"),
        },
    )


async def _maybe_browning_alert(frame: dict, result: dict, grow: _FrameGrow) -> None:
    """Fire a deduped browning-complete alert when a browning block is done.

    Gated on the browning phase, one alert per session per 12 h
    (_record_vision_milestone). The INFO notification carries the phase's exit
    step — shiitake's cold-water soak — since that is what the operator does
    next; the cloud gets it as a phase_reminder (a type it already pushes).
    """
    session_id = grow.session["id"]
    phase = grow.session["current_phase"]
    should, reason = browning_signal(phase, result.get("browning_percent"))
    if not should:
        return
    step = grow.profile.phase_exit_reminder(phase) if grow.profile is not None else None
    await _record_vision_milestone(
        session_id, "browning_complete", f"Browning complete: {reason}",
        {"reason": reason,
         "browning_percent": result.get("browning_percent"),
         "frame_id": frame.get("id")},
        lambda: notify_info(
            f"Browning complete — {grow.species_name}",
            f"Vision: {reason}. " + (f"Next: {step}" if step else "Ready to move on to pinning."),
            dedup_key=f"browning:{session_id}",
        ),
        "phase_reminder",
        {
            "node_id": frame.get("node_id"),
            "session_id": session_id,
            "species": grow.species_name,
            "phase": phase,
            "reason": reason,
            "reminder": step,
            "browning_percent": result.get("browning_percent"),
            "frame_id": frame.get("id"),
        },
    )


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
    """One vision_frames row, its analysis fields decoded like get_frames'."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM vision_frames WHERE id = ?", (frame_id,))
        row = await cursor.fetchone()
        return _deserialize_frame(row) if row else None


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
# The local CNN (analyze_frame_local) is not built — it scores no frame, so
# without this auto contamination/harvest detection never fired: green mold
# and overdue flushes went
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
#   - at most once per camera of a session per
#     _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS, so a camera streaming a frame every
#     few seconds can't run up a bill.
# The default is the spec's 6h cadence (CLAUDE.md §6 "Layer 2 — every 6h +
# on-demand"); at 15 min every capture was analysed, ~24x the specified spend.
# `settings.vision_auto_interval_min`, when the config defines it, overrides it.
# The window is per camera, not per session: with one slot per session the
# cameras of a chamber (front and top-down) raced for it, and whichever
# camera's frame landed first after each window took every slot, so the other
# view could go unread indefinitely. Spend is one call per camera per window.
# A phase transition (the spec's other Layer-2 trigger) bypasses the window
# once per camera, so the first frame of a new phase is read straight away.
_AUTO_ANALYSIS_MIN_INTERVAL_SECONDS = 6 * 3600
# Keyed by (session id, camera node id).
_last_auto_analysis: dict[tuple[int, str], float] = {}
_last_auto_phase: dict[tuple[int, str], str] = {}
# Strong refs to in-flight background tasks so the event loop can't GC them
# mid-run (per asyncio.create_task docs). Cleared via the done-callback.
_auto_analysis_tasks: set[asyncio.Task] = set()


def _auto_analysis_interval_seconds() -> float:
    minutes = getattr(settings, "vision_auto_interval_min", None)
    try:
        if minutes is not None and float(minutes) > 0:
            return float(minutes) * 60
    except (TypeError, ValueError):
        pass
    return _AUTO_ANALYSIS_MIN_INTERVAL_SECONDS


def _claim_auto_analysis_slot(
    session_id: int, node_id: str, now: float | None = None, phase: str | None = None,
) -> bool:
    """Atomically claim this camera's throttle slot in the session; True iff
    outside the window or the session's phase changed since this camera's
    last auto analysis.

    Check-and-record with no ``await`` in between, so under the single-threaded
    event loop two frames arriving back-to-back can't both claim the slot. The
    attempt time is recorded (not the success time), so a failed/slow analysis
    still counts against the budget — the throttle strictly bounds API calls.
    """
    now = time.time() if now is None else now
    key = (session_id, node_id)
    last = _last_auto_analysis.get(key, 0.0)
    seen_phase = _last_auto_phase.get(key)
    phase_changed = phase is not None and seen_phase is not None and phase != seen_phase
    if not phase_changed and now - last < _auto_analysis_interval_seconds():
        return False
    _last_auto_analysis[key] = now
    if phase is not None:
        _last_auto_phase[key] = phase
    return True


async def _session_phase(session_id: int) -> str | None:
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT current_phase FROM sessions WHERE id = ?", (session_id,)
        )).fetchone()
    return row["current_phase"] if row else None


async def _run_auto_analysis(frame: dict) -> None:
    """Run the real Claude detector for an ingested frame and persist the result.

    analyze_frame_claude fires the contamination + harvest alert/forward
    plumbing itself; here we only persist the analysis blob so the frame row
    carries it and the harvest-corroboration query (which reads analysis_claude
    across the camera's recent frames) can see this frame next time.
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
    camera_sensor: str | None = None,
) -> asyncio.Task | None:
    """Kick the real Claude detector for a freshly-ingested frame, cost-gated.

    Returns the scheduled task (so callers/tests can await it) or None when
    gating declines: no active session, no Claude key (free / no BYOK), or
    this camera still inside its throttle window. Non-blocking — the analysis
    runs in the background so the ingest response returns immediately.
    """
    if session_id is None:
        return None
    # BYOK gate — the Pi's AI paygate. No key ⇒ don't even schedule (calling
    # analyze_frame_claude would just return an error and waste a task).
    if not settings.claude_api_key:
        return None
    if not _claim_auto_analysis_slot(session_id, node_id,
                                     phase=await _session_phase(session_id)):
        return None

    frame = {
        "id": frame_id,
        "session_id": session_id,
        "node_id": node_id,
        "file_path": file_path,
        "camera_sensor": camera_sensor,
    }
    task = asyncio.create_task(_run_auto_analysis(frame))
    _auto_analysis_tasks.add(task)
    task.add_done_callback(_auto_analysis_tasks.discard)
    return task


# ─── Frame retention ────────────────────────────────────────────────────
#
# Each camera writes ~96 UXGA frames/day onto the same volume as the SQLite
# DB, and nothing ever deleted them. Frames younger than
# VISION_FULL_RETENTION_DAYS are kept in full; older whole days are thinned to
# the last frame per node per day, plus every frame worth keeping: a
# non-healthy / contamination Claude read, an active-learning label, or a
# reference from a contamination event, session note or harvest. The pass is
# idempotent and piggy-backs on ingest (at most once per interval) — frames
# only accumulate while a camera is posting.
#
# A frame's age is the LATER of its capture timestamp and its arrival time
# (created_at). Before the ingest fix, an unsynced cam's uptime X-Timestamp
# (e.g. 900) was stored verbatim, so `timestamp` alone would date a frame
# ingested minutes ago to 1970 and prune it.
VISION_FULL_RETENTION_DAYS = 30
_VISION_PRUNE_INTERVAL_SECONDS = 24 * 3600
# Rows examined per batch. The first pass on an existing install can face
# months of frames; batching bounds memory (analysis blobs) and keeps each
# write transaction short.
_VISION_PRUNE_BATCH = 500
_last_vision_prune: float = 0.0
_vision_prune_tasks: set[asyncio.Task] = set()

# Age expression: MAX(timestamp, COALESCE(created_at, timestamp)).
# The last frame of each expired (node, UTC day) — computed once per pass.
_PRUNE_KEEPERS_SQL = """
    SELECT MAX(id) AS id FROM vision_frames
     WHERE MAX(timestamp, COALESCE(created_at, timestamp)) < :cutoff
     GROUP BY node_id,
              CAST(MAX(timestamp, COALESCE(created_at, timestamp)) / 86400 AS INT)
"""
# One page of expired frames, walked by rowid.
_PRUNE_BATCH_SQL = """
    SELECT id, file_path, analysis_local, analysis_claude
      FROM vision_frames
     WHERE id > :after_id
       AND MAX(timestamp, COALESCE(created_at, timestamp)) < :cutoff
     ORDER BY id
     LIMIT :batch
"""


def _frame_is_notable(row) -> bool:
    """Keep frames with a non-healthy Claude read or an operator label."""
    try:
        local = json.loads(row["analysis_local"]) if row["analysis_local"] else {}
        claude = json.loads(row["analysis_claude"]) if row["analysis_claude"] else {}
    except (TypeError, ValueError):
        return True  # can't tell — keep it
    if isinstance(local, dict) and (local.get("user_label") is not None
                                    or "user_confirmed" in local):
        return True
    if isinstance(claude, dict):
        if str(claude.get("health_assessment", "")).lower() in ("concern", "contaminated"):
            return True
        if contamination_signal(claude)[0] is not None:
            return True
    return False


def _partition_prunable(
    rows: list[dict], keep_ids: set[int], storage: Path,
) -> tuple[list[tuple[int, Path]], int]:
    """Worker-thread half of a batch: JSON checks + path resolution.

    Returns ([(frame id, resolved file path)] safe to delete, number of
    expired frames kept because their file is outside the storage dir). Those
    are kept rather than row-deleted: dropping only the row would orphan an
    image no later pass could find, and their files are never touched.
    """
    doomed: list[tuple[int, Path]] = []
    outside = 0
    for r in rows:
        if r["id"] in keep_ids or _frame_is_notable(r):
            continue
        try:
            path = Path(r["file_path"]).resolve()
        except (OSError, RuntimeError):
            outside += 1
            continue
        if not path.is_relative_to(storage):
            outside += 1
            continue
        doomed.append((r["id"], path))
    return doomed, outside


def _unlink_frame_files(paths: list[Path]) -> int:
    """Delete frame files (runs in a worker thread). Returns bytes freed."""
    freed = 0
    for path in paths:
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
        except FileNotFoundError:
            continue
        except OSError as e:
            log.warning("Vision retention: could not remove %s: %s", path, e)
    return freed


async def prune_vision_frames(now: float | None = None) -> dict:
    """Thin vision frames older than the full-retention window. Idempotent.

    Filesystem work (resolving paths, stat/unlink) and the per-row JSON checks
    run in a worker thread so a large backlog can't stall the event loop.
    """
    now = time.time() if now is None else now
    # Whole UTC days only, so each day's keeper (its highest id) is stable
    # across runs instead of shifting as the cutoff crosses the day.
    cutoff = now - VISION_FULL_RETENTION_DAYS * 86400
    cutoff -= cutoff % 86400
    storage = await asyncio.to_thread(Path(settings.vision_storage).resolve)

    frames_deleted = 0
    bytes_freed = 0
    kept_outside = 0
    # One connection for the whole pass, committed per batch so a long first
    # pass never holds a write transaction across the whole backlog.
    async with get_db() as db:
        # Never pruned: each expired day's keeper, and any frame referenced by
        # a contamination event, a session note or a harvest.
        keep_ids: set[int] = {
            r["id"] for r in await (await db.execute(
                _PRUNE_KEEPERS_SQL, {"cutoff": cutoff},
            )).fetchall()
        }
        for sql in ("SELECT frame_id FROM contamination_events WHERE frame_id IS NOT NULL",
                    "SELECT image_id FROM session_notes WHERE image_id IS NOT NULL"):
            keep_ids.update(r[0] for r in await (await db.execute(sql)).fetchall())
        harvest_rows = await (await db.execute(
            "SELECT image_ids FROM harvests WHERE image_ids IS NOT NULL"
        )).fetchall()
        for h in harvest_rows:
            try:
                ids = json.loads(h["image_ids"])
            except (TypeError, ValueError):
                continue
            if isinstance(ids, list):
                keep_ids.update(i for i in ids if isinstance(i, int))

        after_id = 0
        while True:
            rows = [dict(r) for r in await (await db.execute(
                _PRUNE_BATCH_SQL,
                {"cutoff": cutoff, "after_id": after_id, "batch": _VISION_PRUNE_BATCH},
            )).fetchall()]
            if not rows:
                break
            after_id = rows[-1]["id"]
            doomed, outside = await asyncio.to_thread(
                _partition_prunable, rows, keep_ids, storage,
            )
            kept_outside += outside
            if not doomed:
                continue
            await db.executemany(
                "DELETE FROM vision_frames WHERE id = ?", [(fid,) for fid, _ in doomed]
            )
            await db.commit()
            # Rows first, files second: a failed unlink leaves an orphan file,
            # never a row pointing at a missing image.
            bytes_freed += await asyncio.to_thread(
                _unlink_frame_files, [path for _, path in doomed],
            )
            frames_deleted += len(doomed)

    if frames_deleted:
        log.info("Vision retention: pruned %d frames, freed %.1f MB",
                 frames_deleted, bytes_freed / 1024 / 1024)
    if kept_outside:
        log.warning(
            "Vision retention: kept %d expired frames whose files are outside %s "
            "(storage moved?); remove them manually if no longer needed",
            kept_outside, storage,
        )
    return {
        "frames_deleted": frames_deleted,
        "bytes_freed": bytes_freed,
        "frames_kept_outside_storage": kept_outside,
    }


async def _run_vision_prune() -> None:
    try:
        await prune_vision_frames()
    except Exception as e:  # a background task must never die silently
        log.warning("Vision retention pass failed: %s", e)


async def maybe_schedule_vision_prune(now: float | None = None) -> asyncio.Task | None:
    """Kick a background retention pass at most once per interval (from ingest)."""
    global _last_vision_prune
    now = time.time() if now is None else now
    if now - _last_vision_prune < _VISION_PRUNE_INTERVAL_SECONDS:
        return None
    _last_vision_prune = now
    task = asyncio.create_task(_run_vision_prune())
    _vision_prune_tasks.add(task)
    task.add_done_callback(_vision_prune_tasks.discard)
    return task
