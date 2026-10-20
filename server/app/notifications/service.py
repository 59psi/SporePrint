"""Notification service using self-hosted ntfy.

Three tiers:
- CRITICAL (immediate; identical pages collapse for 15 min): contamination,
  temp/CO2 safety, node offline
- WARNING (5min deduped): out-of-range, etiolation, safety cutoffs
- INFO (each message at most once an hour, keyed by dedup key or title; sent
  immediately, never batched): phase reminders, harvest readiness, browning and
  drying complete
"""

import logging
import time

import httpx

from ..config import settings
from ..http_tls import tls_context

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
        # The shared TLS context: a client of its own would load the CA
        # bundle on the event loop for every page.
        async with httpx.AsyncClient(verify=tls_context()) as client:
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
    """WARNING tier: deduplicated for 5 min, keyed by `dedup_key` or the title."""
    await notify(title, message, priority="warning", dedup_key=dedup_key or f"warning:{title}",
                 dedup_seconds=dedup_seconds, tags=["mushroom"])


async def notify_info(title: str, message: str, dedup_key: str | None = None):
    """INFO tier: each message at most once an hour, keyed by `dedup_key` or the title."""
    await notify(title, message, priority="info", dedup_key=dedup_key or f"info:{title}",
                 dedup_seconds=3600, tags=["seedling"])


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


async def co2_alert(
    co2_ppm: int,
    node_id: str,
    *,
    dedup_key: str | None = None,
    life_safety: bool = False,
) -> bool:
    """CRITICAL CO2 page naming its node. True when it was published.

    Collapsed per node (``dedup_key``, else one key per ``node_id``), never
    under a shared key: one shared key let a CO2 emergency on one node
    silence every other node's page, the life-safety one included, for as
    long as the first kept re-paging. ``life_safety`` marks a level
    dangerous to people, not just to the grow.
    """
    message = (
        "CO2 is at a level dangerous to people. Ventilate the room before going in."
        if life_safety else
        "CO2 levels dangerously high. Check ventilation."
    )
    return await notify(
        f"CO2 CRITICAL on {node_id}: {co2_ppm} ppm", message,
        priority="critical", tags=["cloud"],
        dedup_key=dedup_key or f"co2:critical:{node_id}",
        dedup_seconds=CRITICAL_DEDUP_SECONDS,
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


async def phase_reminder(
    session_id: int, session_name: str, phase: str, days_in_phase: int, expected_max: int,
):
    """INFO: a session has overrun its phase. Deduplicated per session, not
    per name: sessions are named after their species, so a second grow of
    the same species lost its reminder every day."""
    await notify_info(
        f"Phase check — {session_name}",
        f"Day {days_in_phase}/{expected_max} of {phase.replace('_', ' ')}. Consider advancing if ready.",
        dedup_key=f"phase:{session_id}:{phase}",
    )


async def harvest_notice(species_name: str, notice: str, dedup_key: str | None = None):
    """CRITICAL: a harvest that must be handled at once — the species
    profile's harvest_notice (pink oyster cannot be refrigerated; shaggy mane
    turns to ink within hours)."""
    await notify_critical(
        f"{species_name.upper()} — Process Immediately!",
        notice,
        tags=["warning", "mushroom"],
        dedup_key=dedup_key,
    )
