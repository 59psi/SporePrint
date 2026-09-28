"""Notification service using self-hosted ntfy.

Three tiers:
- CRITICAL (immediate; identical pages collapse for 15 min): contamination,
  temp/CO2 safety, node offline
- WARNING (5min deduped): out-of-range, etiolation, safety cutoffs
- INFO (batched hourly): phase reminders, harvest readiness, daily summary
"""

import logging
import time

import httpx

from ..config import settings

log = logging.getLogger(__name__)

# Dedup tracking: dedup_key -> time of the last successful publish.
_last_sent: dict[str, float] = {}

# Identical CRITICAL pages are collapsed for this long. The first page is still
# immediate; the window only stops a persisting condition (an emergency the
# automation engine re-detects on every telemetry frame, a forecast re-checked
# every poll) from paging priority-5 every minute until the topic gets muted.
CRITICAL_DEDUP_SECONDS = 900

_NTFY_PRIORITY = {
    "critical": 5,
    "warning": 4,
    "info": 3,
    "default": 3,
}


async def notify(
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
    dedup_key: str | None = None,
    dedup_seconds: int = 300,
) -> bool:
    """Send a notification via ntfy. Returns True when the publish succeeded.

    Publishes through ntfy's JSON API (POST to the server root, topic in the
    body) rather than the header API: httpx encodes header values as ASCII, so
    a `Title:` header containing an em-dash or a degree sign raised before any
    connection was made and the alert was silently dropped. JSON bodies are
    UTF-8, so every title/message survives intact.
    """
    if not settings.ntfy_url:
        return False

    now = time.time()
    previous: float | None = None
    if dedup_key:
        previous = _last_sent.get(dedup_key)
        if previous is not None and now - previous < dedup_seconds:
            return False
        # Claim the slot before awaiting the POST so a concurrent identical
        # alert can't double-send; released below if the publish fails, so a
        # transient ntfy outage doesn't swallow the retry for a whole window.
        _last_sent[dedup_key] = now

    payload: dict = {
        "topic": settings.ntfy_topic,
        "title": title,
        "message": message,
        "priority": _NTFY_PRIORITY.get(priority, 3),
    }
    if tags:
        payload["tags"] = list(tags)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.ntfy_url.rstrip("/") + "/", json=payload, timeout=5,
            )
            response.raise_for_status()
    except Exception as e:
        log.error("Notification failed: %s", e)
        if dedup_key:
            if previous is None:
                _last_sent.pop(dedup_key, None)
            else:
                _last_sent[dedup_key] = previous
        return False

    log.info("Notification sent: [%s] %s", priority, title)
    return True


async def notify_critical(
    title: str,
    message: str,
    tags: list[str] | None = None,
    dedup_key: str | None = None,
    dedup_seconds: int = CRITICAL_DEDUP_SECONDS,
):
    """CRITICAL tier: immediate, but identical pages collapse for a short window.

    Callers should pass a stable `dedup_key` when the title carries changing
    values (a live reading, "in 5h"); otherwise the title itself is the key.
    """
    await notify(
        title, message, priority="critical", tags=tags or ["warning"],
        dedup_key=dedup_key or f"critical:{title}", dedup_seconds=dedup_seconds,
    )


async def notify_warning(
    title: str,
    message: str,
    dedup_key: str | None = None,
    dedup_seconds: int = 300,
):
    await notify(title, message, priority="warning", dedup_key=dedup_key,
                 dedup_seconds=dedup_seconds, tags=["mushroom"])


async def notify_info(title: str, message: str, dedup_key: str | None = None):
    await notify(title, message, priority="info", dedup_key=dedup_key, dedup_seconds=3600, tags=["seedling"])


# Convenience wrappers for common events

async def contamination_alert(
    species: str, contam_type: str, confidence: float, dedup_key: str | None = None,
):
    await notify_critical(
        f"CONTAMINATION DETECTED — {species}",
        f"{contam_type} detected with {confidence:.0%} confidence. Inspect immediately!",
        tags=["warning", "biohazard"],
        dedup_key=dedup_key or f"contam:{species}:{contam_type}",
    )


async def temperature_alert(temp_f: float, direction: str):
    await notify_critical(
        f"Temperature {'HIGH' if direction == 'high' else 'LOW'}: {temp_f:.1f}°F",
        f"Temperature is critically {direction}. Check environment immediately.",
        tags=["thermometer"],
        dedup_key=f"temperature:{direction}",
    )


async def co2_alert(co2_ppm: int):
    await notify_critical(
        f"CO2 CRITICAL: {co2_ppm} ppm",
        "CO2 levels dangerously high. Check ventilation.",
        tags=["cloud"],
        dedup_key="co2:critical",
    )


async def node_offline(node_id: str):
    # CRITICAL tier per spec: an offline relay may leave actuators stuck, an
    # offline climate node leaves temperature/CO2 unmonitored.
    await notify_critical(
        f"Node offline: {node_id}",
        f"Hardware node {node_id} has gone offline.",
        tags=["warning", "electric_plug"],
        dedup_key=f"offline:{node_id}",
    )


async def harvest_ready(
    species: str, session_name: str, *, reason: str | None = None, dedup_key: str | None = None,
):
    """INFO: vision analysis says the session's fruit is at its harvest window.

    ``reason`` (the vision read, e.g. "growth has slowed …") is appended to the
    message; ``dedup_key`` defaults to one per session name.
    """
    message = f"Session '{session_name}' appears ready for harvest based on vision analysis."
    if reason:
        message += f" Vision: {reason}."
    await notify_info(
        f"Harvest ready — {species}",
        message,
        dedup_key=dedup_key or f"harvest:{session_name}",
    )


async def phase_reminder(session_name: str, phase: str, days_in_phase: int, expected_max: int):
    await notify_info(
        f"Phase check — {session_name}",
        f"Day {days_in_phase}/{expected_max} of {phase.replace('_', ' ')}. Consider advancing if ready.",
        dedup_key=f"phase:{session_name}:{phase}",
    )


async def pink_oyster_harvest():
    """Pink oyster specific: cannot be refrigerated."""
    await notify_critical(
        "PINK OYSTER — Process Immediately!",
        "Pink oyster harvest detected. CANNOT be refrigerated. Process/cook within hours.",
        tags=["warning", "mushroom"],
    )
