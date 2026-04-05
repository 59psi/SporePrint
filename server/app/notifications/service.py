"""Notification service using self-hosted ntfy.

Three tiers:
- CRITICAL (immediate): contamination, temp/CO2 safety, node offline
- WARNING (5min deduped): out-of-range, etiolation, safety cutoffs
- INFO (batched hourly): phase reminders, harvest readiness, daily summary
"""

import logging
import time

import httpx

from ..config import settings

log = logging.getLogger(__name__)

# Dedup tracking
_last_sent: dict[str, float] = {}


async def notify(
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
    dedup_key: str | None = None,
    dedup_seconds: int = 300,
):
    """Send a notification via ntfy."""
    if not settings.ntfy_url:
        return

    # Dedup check
    if dedup_key:
        last = _last_sent.get(dedup_key, 0)
        if time.time() - last < dedup_seconds:
            return
        _last_sent[dedup_key] = time.time()

    ntfy_priority = {
        "critical": "5",
        "warning": "4",
        "info": "3",
        "default": "3",
    }.get(priority, "3")

    url = f"{settings.ntfy_url}/{settings.ntfy_topic}"
    headers = {
        "Title": title,
        "Priority": ntfy_priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, content=message, headers=headers, timeout=5)
        log.info("Notification sent: [%s] %s", priority, title)
    except Exception as e:
        log.error("Notification failed: %s", e)


async def notify_critical(title: str, message: str, tags: list[str] | None = None):
    await notify(title, message, priority="critical", tags=tags or ["warning"])


async def notify_warning(title: str, message: str, dedup_key: str | None = None):
    await notify(title, message, priority="warning", dedup_key=dedup_key, dedup_seconds=300, tags=["mushroom"])


async def notify_info(title: str, message: str, dedup_key: str | None = None):
    await notify(title, message, priority="info", dedup_key=dedup_key, dedup_seconds=3600, tags=["seedling"])


# Convenience wrappers for common events

async def contamination_alert(species: str, contam_type: str, confidence: float):
    await notify_critical(
        f"CONTAMINATION DETECTED — {species}",
        f"{contam_type} detected with {confidence:.0%} confidence. Inspect immediately!",
        tags=["warning", "biohazard"],
    )


async def temperature_alert(temp_f: float, direction: str):
    await notify_critical(
        f"Temperature {'HIGH' if direction == 'high' else 'LOW'}: {temp_f:.1f}°F",
        f"Temperature is critically {direction}. Check environment immediately.",
        tags=["thermometer"],
    )


async def co2_alert(co2_ppm: int):
    await notify_critical(
        f"CO2 CRITICAL: {co2_ppm} ppm",
        "CO2 levels dangerously high. Check ventilation.",
        tags=["cloud"],
    )


async def node_offline(node_id: str):
    await notify_warning(
        f"Node offline: {node_id}",
        f"Hardware node {node_id} has gone offline.",
        dedup_key=f"offline:{node_id}",
    )


async def harvest_ready(species: str, session_name: str):
    await notify_info(
        f"Harvest ready — {species}",
        f"Session '{session_name}' appears ready for harvest based on vision analysis.",
        dedup_key=f"harvest:{session_name}",
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
